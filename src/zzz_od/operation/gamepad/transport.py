"""按地图区域与底部传送点焦点执行原生手柄传送。"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import cv2
import numpy as np

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from zzz_od.operation.gamepad.focus import has_filled_highlight, highlight_mask
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation

if TYPE_CHECKING:
    from cv2.typing import MatLike

    from one_dragon.base.matcher.match_result import MatchResultList
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


def find_yellow_focus_frames(
    image: MatLike,
    min_width: int,
    max_width: int,
    min_height: int,
    max_height: int,
) -> list[Rect]:
    """检查大卡片或小传送点的四边，排除黄色图案和按钮圆标。"""
    mask = highlight_mask(image, 'yellow')
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    frames: list[Rect] = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if not (min_width <= width <= max_width and min_height <= height <= max_height):
            continue
        crop = mask[y:y + height, x:x + width]
        edges = (crop[:8], crop[-8:], crop[:, :8], crop[:, -8:])
        if all(np.count_nonzero(edge) / edge.size >= 0.4 for edge in edges):
            frames.append(Rect(x, y, x + width, y + height))
    return frames


class GamepadTransport(GamepadOperation):
    """一次只移动一个焦点；未知页、目标不可见或无边框时不猜方向。"""

    SUPPORTED_TARGETS: ClassVar[set[tuple[str, str]]] = {
        ('澄辉坪', '阿朔'),
        ('澄辉坪', '汀曼咖啡'),
        ('澄辉坪', '录像店营业点'),
    }

    def __init__(self, ctx: ZContext, area_name: str, tp_name: str) -> None:
        """保留原地图传送的区域和传送点参数。"""
        super().__init__(ctx, op_name=f'手柄传送 {area_name} {tp_name}', timeout_seconds=90)
        self.area_name: str = area_name
        self.tp_name: str = tp_name
        self._opened: bool = False
        self._entered_points: bool = False
        self._returned_to_regions: bool = False
        self._requested_teleport: bool = False
        self._confirmed_teleport: bool = False
        self._last_move: tuple[str, int, int, int, int] | None = None

    def handle_init(self) -> None:
        """重新执行时清除一次性确认和焦点移动记录。"""
        self._opened = False
        self._entered_points = False
        self._returned_to_regions = False
        self._requested_teleport = False
        self._confirmed_teleport = False
        self._last_move = None

    def _read_area(
        self, area_name: str,
    ) -> tuple[MatLike, dict[str, MatchResultList]] | None:
        """只读取 iOS 地图区域；缺少配置或截图时不发送输入。"""
        area = self.ctx.screen_loader.get_area('地图', area_name)
        if area is None or self.last_screenshot is None:
            return None
        rect = area.rect
        image = self.last_screenshot[rect.y1:rect.y2, rect.x1:rect.x2]
        if not image.size:
            return None
        return image, self.ctx.ocr.crop_and_run_ocr(self.last_screenshot, rect)

    @staticmethod
    def _text_rects(results: dict[str, MatchResultList], target: str) -> list[Rect]:
        """要求完整名称，防止把营业点当成区域名或匹配其他地点。"""
        return [
            matches.max.rect for text, matches in results.items()
            if text.replace(' ', '').replace('？', '').replace('?', '') == target
            and matches.max is not None
        ]

    def _focus(self, point: bool) -> tuple[Rect, dict[str, MatchResultList]] | None:
        """大区域框与小传送点框分别识别，不能把同时高亮当作同一层。"""
        area = self._read_area('手柄-传送点卡片' if point else '手柄-区域卡片')
        if area is None:
            return None
        frames = find_yellow_focus_frames(
            area[0], 250 if point else 550, 330 if point else 700,
            115 if point else 230, 145 if point else 300,
        )
        return (frames[0], area[1]) if len(frames) == 1 else None

    @staticmethod
    def _contains(frame: Rect, text: Rect) -> bool:
        """文字中心落在完整焦点框内才视为选中。"""
        return frame.x1 < text.center.x < frame.x2 and frame.y1 < text.center.y < frame.y2

    def _move_toward(self, frame: Rect, target: Rect, point: bool) -> None:
        """按当前框与目标文字所在行列移动，同一焦点未变化时不连发。"""
        if not point and target.center.y < frame.y1:
            key = 'dpad_up'
        elif not point and target.center.y > frame.y2:
            key = 'dpad_down'
        else:
            key = 'dpad_left' if target.center.x < frame.x1 else 'dpad_right'
        signature = (key, frame.x1, frame.y1, frame.x2, frame.y2)
        if signature != self._last_move:
            self.ctx.controller.btn_tap(key)
            self._last_move = signature

    def _teleport_dialog(self) -> bool:
        """仅识别地图传送确认主句，不能把其他确认弹窗当成传送。"""
        area = self._read_area('手柄-传送确认主句')
        return area is not None and bool(self._text_rects(area[1], '是否传送至该地点'))

    @operation_node(name='检查手柄传送目标', is_start_node=True, screenshot_before_round=False)
    def check_target(self) -> OperationRoundResult:
        """仅接入当前已建档区域中的三个日常目标。"""
        if (self.area_name, self.tp_name) not in self.SUPPORTED_TARGETS:
            return self.round_fail(f'Mac 地图传送尚未支持 {self.area_name}/{self.tp_name}')
        return self.round_success()

    @node_from(from_name='检查手柄传送目标')
    @operation_node(name='打开手柄地图', node_max_retry_times=8, timeout_seconds=12)
    def open_map(self) -> OperationRoundResult:
        """在已知大世界打开地图，也允许从已打开的区域卡片开始。"""
        if self._teleport_dialog():
            return self.round_fail('当前已有传送弹窗，无法确认待传送目标')
        if self._focus(False) is not None:
            return self.round_success()
        if not self._opened and self.last_screenshot is not None and self.round_by_find_area(
            self.last_screenshot, '大世界-普通', '快捷手册'
        ).is_success:
            self.ctx.controller.click(gamepad_key='map')
            self._opened = True
        return self.round_retry('等待手柄地图区域焦点', wait=0.8)

    @node_from(from_name='打开手柄地图')
    @operation_node(name='选择手柄地图区域', node_max_retry_times=12, timeout_seconds=18)
    def choose_area(self) -> OperationRoundResult:
        """读取当前页目标名称与真实焦点，目标不可见时不翻页。"""
        if self._teleport_dialog():
            return self.round_fail('区域选择期间出现未请求的传送弹窗')
        focused = self._focus(False)
        if focused is None:
            return self.round_retry('地图区域焦点缺失', wait=0.8)
        frame, results = focused
        targets = self._text_rects(results, self.area_name)
        if not targets:
            return self.round_fail(f'当前地图页看不到区域 {self.area_name}，未执行翻页')
        target_focused = any(self._contains(frame, target) for target in targets)
        point_focused = self._focus(True) is not None
        if point_focused:
            if target_focused:
                return self.round_success()
            if not self._returned_to_regions:
                self.ctx.controller.btn_tap('east')
                self._returned_to_regions = True
            return self.round_retry('等待返回区域焦点', wait=0.8)
        if target_focused:
            if not self._entered_points:
                self.ctx.controller.btn_tap('south')
                self._entered_points = True
            return self.round_retry('等待传送点焦点', wait=0.8)
        self._move_toward(frame, targets[-1], False)
        return self.round_retry('等待目标区域焦点', wait=0.8)

    @node_from(from_name='选择手柄地图区域')
    @operation_node(name='选择手柄传送点', node_max_retry_times=12, timeout_seconds=18)
    def choose_point(self) -> OperationRoundResult:
        """只在底部传送点有焦点时导航，不把区域大框当成传送点。"""
        focused = self._focus(True)
        if focused is None:
            return self.round_retry('地图传送点焦点缺失', wait=0.8)
        frame, results = focused
        targets = self._text_rects(results, self.tp_name)
        if not targets:
            return self.round_fail(f'当前地图页看不到传送点 {self.tp_name}，未执行翻页')
        if any(self._contains(frame, target) for target in targets):
            return self.round_success()
        self._move_toward(frame, targets[0], True)
        return self.round_retry('等待目标传送点焦点', wait=0.8)

    @node_from(from_name='选择手柄传送点')
    @operation_node(name='请求手柄地图传送', node_max_retry_times=6, timeout_seconds=10)
    def request_teleport(self) -> OperationRoundResult:
        """目标小框确认后只按一次 A，随后等专属传送弹窗。"""
        if self._teleport_dialog():
            return self.round_success()
        focused = self._focus(True)
        if not self._requested_teleport and focused is not None and any(
            self._contains(focused[0], target)
            for target in self._text_rects(focused[1], self.tp_name)
        ):
            self.ctx.controller.btn_tap('south')
            self._requested_teleport = True
        return self.round_retry('等待地图传送确认弹窗', wait=0.8)

    @node_from(from_name='请求手柄地图传送')
    @operation_node(name='确认手柄地图传送', node_max_retry_times=6, timeout_seconds=10)
    def confirm_teleport(self) -> OperationRoundResult:
        """传送主句与确认按钮黄填充同时命中后只按一次 A。"""
        if self._confirmed_teleport:
            return self.round_success()
        area = self._read_area('手柄-传送确认按钮')
        if self._teleport_dialog() and area is not None:
            if any(has_filled_highlight(area[0], rect, 'yellow')
                   for rect in self._text_rects(area[1], '确认')):
                self.ctx.controller.btn_tap('south')
                self._confirmed_teleport = True
                return self.round_success(wait=1)
        return self.round_retry('等待地图确认按钮高亮', wait=0.8)

    @node_from(from_name='确认手柄地图传送')
    @operation_node(name='等待手柄传送落地', node_max_retry_times=30, timeout_seconds=40)
    def wait_for_world(self) -> OperationRoundResult:
        """确认大世界后结束，黑屏、加载和残留地图均不算到达。"""
        if self.last_screenshot is not None and self.round_by_find_area(
            self.last_screenshot, '大世界-普通', '快捷手册'
        ).is_success:
            return self.round_success(f'已传送至 {self.area_name}/{self.tp_name}')
        return self.round_retry('等待地图传送落地', wait=1)
