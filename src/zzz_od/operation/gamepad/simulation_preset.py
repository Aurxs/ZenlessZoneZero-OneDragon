"""基础材料专项的识别、选择与实际电量读取。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import cv2

from one_dragon.base.operation.operation_node import operation_node
from zzz_od.operation.gamepad.focus import highlight_mask
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation

if TYPE_CHECKING:
    from cv2.typing import MatLike

    from one_dragon.base.matcher.match_result import MatchResultList
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext

BASIC_MISSIONS: tuple[str, ...] = ('调查专项', '音擎专项', '赏金专项', '镀剂专项')


def read_preset_area(
    ctx: ZContext, screen: MatLike | None, area_name: str,
) -> tuple[MatLike, dict[str, MatchResultList]] | None:
    """读取平台模拟室区域，缺少截图或配置时不产生输入。"""
    area = ctx.screen_loader.get_area('实战模拟室', area_name)
    if area is None or screen is None:
        return None
    rect = area.rect
    image = screen[rect.y1:rect.y2, rect.x1:rect.x2]
    if not image.size:
        return None
    return image, ctx.ocr.crop_and_run_ocr(screen, rect)


def read_preset_charge(ctx: ZContext, screen: MatLike | None) -> tuple[int, int] | None:
    """读取实际电量与所需消耗，不用卡片预估代替画面。"""
    area = read_preset_area(ctx, screen, '手柄-电量')
    if area is None:
        return None
    values: set[tuple[int, int]] = set()
    for text in area[1]:
        match = re.fullmatch(r'\s*(\d{1,4})\s*/\s*(\d{1,3})\s*', text)
        if match is not None:
            values.add((int(match[1]), int(match[2])))
    return next(iter(values)) if len(values) == 1 else None


def selected_preset(ctx: ZContext, screen: MatLike | None) -> str | None:
    """一次 OCR 找到完整黄框中的唯一专项，忽略角落 NEW 标记。"""
    area = read_preset_area(ctx, screen, '手柄-预设列表')
    if area is None:
        return None
    image, results = area
    contours, _ = cv2.findContours(
        highlight_mask(image, 'yellow'), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
    )
    selected: set[str] = set()
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if width < 200 or height < 100 or cv2.contourArea(contour) / (width * height) < 0.75:
            continue
        for text, matches in results.items():
            name = text.replace(' ', '')
            target = matches.max
            if name not in BASIC_MISSIONS or target is None:
                continue
            if x < target.x < target.x + target.w < x + width and y < target.y < target.y + target.h < y + height:
                selected.add(name)
    return next(iter(selected)) if len(selected) == 1 else None


def preset_focused(ctx: ZContext, screen: MatLike | None, mission_name: str) -> bool:
    """材料名称与当前唯一焦点必须一致。"""
    return selected_preset(ctx, screen) == mission_name


class GamepadChooseSimulationPreset(GamepadOperation):
    """从当前专项焦点移到配置目标，每次移动后确认新帧。"""

    def __init__(self, ctx: ZContext, mission_name: str) -> None:
        super().__init__(ctx, op_name=f'手柄选择{mission_name}', timeout_seconds=30)
        self.mission_name: str = mission_name
        self._last_focus: str | None = None
        self._unchanged_rounds: int = 0
        self._moves: int = 0
        self._menu_back_sent: bool = False

    def handle_init(self) -> None:
        """每次运行重新识别起点。"""
        self._last_focus = None
        self._unchanged_rounds = 0
        self._moves = 0
        self._menu_back_sent = False

    @operation_node(name='选择材料专项', is_start_node=True, node_max_retry_times=12)
    def choose(self) -> OperationRoundResult:
        """目标和唯一整卡焦点都已确认才移动，未知状态不猜方向。"""
        if self.mission_name not in BASIC_MISSIONS:
            return self.round_fail(f'尚未支持专项：{self.mission_name}')
        menu = read_preset_area(self.ctx, self.last_screenshot, '手柄-预设操作菜单')
        if menu is not None and all(
            name in {text.replace(' ', '') for text in menu[1]}
            for name in ('开始战斗', '编辑', '重命名')
        ):
            if not self._menu_back_sent:
                self.ctx.controller.btn_tap('east')
                self._menu_back_sent = True
            return self.round_retry('关闭旧方案菜单后重新核对材料', wait=0.8)
        if self.last_screenshot is None or not all(
            self.round_by_find_area(self.last_screenshot, '实战模拟室', area).is_success
            for area in ('手柄-挑战等级', '手柄-下一步')
        ):
            return self.round_retry('等待基础材料方案页', wait=0.8)
        current = selected_preset(self.ctx, self.last_screenshot)
        if current is None:
            return self.round_retry('未识别唯一专项焦点，未发送按键', wait=0.8)
        if current == self.mission_name:
            self.save_screenshot(prefix='macos_material_selected')
            return self.round_success(f'已选中{current}')
        if current == self._last_focus:
            self._unchanged_rounds += 1
            if self._unchanged_rounds >= 3:
                self.save_screenshot(prefix='macos_material_focus_unchanged')
                return self.round_fail('专项焦点未按预期移动')
            return self.round_retry('等待专项焦点更新', wait=0.8)
        if self._moves >= len(BASIC_MISSIONS) - 1:
            return self.round_fail('专项切换超过预期步数')
        self._last_focus = current
        self._unchanged_rounds = 0
        self._moves += 1
        direction = 'dpad_right' if BASIC_MISSIONS.index(current) < BASIC_MISSIONS.index(self.mission_name) else 'dpad_left'
        self.ctx.controller.btn_tap(direction)
        return self.round_retry('等待目标专项焦点', wait=0.8)
