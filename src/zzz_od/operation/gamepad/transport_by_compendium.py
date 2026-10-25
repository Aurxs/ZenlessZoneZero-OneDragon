"""快捷手册的原生手柄传送，只支持已验证的基础材料入口。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from zzz_od.operation.gamepad.focus import (
    find_yellow_frames,
    has_filled_highlight,
    text_inside_frame,
)
from zzz_od.operation.zzz_operation import ZOperation

if TYPE_CHECKING:
    from cv2.typing import MatLike

    from one_dragon.base.geometry.rectangle import Rect
    from one_dragon.base.matcher.match_result import MatchResultList
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class GamepadTransportByCompendium(ZOperation):
    """逐帧确认焦点后导航，不使用坐标点击或桌面输入。"""

    TABS: tuple[str, ...] = ('目标', '日常', '训练', '作战', '战术')
    CATEGORIES: tuple[str, ...] = (
        '特训目标', '实战模拟室', '区域巡防', '专业挑战室', '恶名狩猎'
    )

    def __init__(
        self,
        ctx: ZContext,
        tab_name: str,
        category_name: str,
        mission_type_name: str | None = None,
    ) -> None:
        """保留原传送操作的参数，由调用方选择平台实现。"""
        super().__init__(ctx, op_name='手柄快捷手册传送', timeout_seconds=60)
        self.tab_name: str = tab_name
        self.category_name: str = category_name
        self.mission_type_name: str | None = mission_type_name
        self._opened: bool = False
        self._entered_list: bool = False
        self._requested_teleport: bool = False
        self._confirmed_teleport: bool = False

    def handle_init(self) -> None:
        """重复执行前清除一次性按键记录。"""
        self._opened = False
        self._entered_list = False
        self._requested_teleport = False
        self._confirmed_teleport = False

    def _read_area(
        self, screen_name: str, area_name: str
    ) -> tuple[MatLike, dict[str, MatchResultList]] | None:
        """从平台画面区域裁图并识别，缺少配置时不发送按键。"""
        area = self.ctx.screen_loader.get_area(screen_name, area_name)
        if area is None or self.last_screenshot is None:
            return None
        rect = area.rect
        image = self.last_screenshot[rect.y1:rect.y2, rect.x1:rect.x2]
        if not image.size:
            return None
        return image, self.ctx.ocr.crop_and_run_ocr(self.last_screenshot, rect)

    @staticmethod
    def _text_rect(results: dict[str, MatchResultList], target: str) -> Rect | None:
        """忽略空格与问号，保留完整目标文字匹配。"""
        for text, matches in results.items():
            normalized = text.replace(' ', '').replace('？', '').replace('?', '')
            if target in normalized and matches.max is not None:
                return matches.max.rect
        return None

    def _selected(
        self, area_name: str, names: tuple[str, ...], color: Literal['yellow', 'blue']
    ) -> str | None:
        """用文字及其周围的填充颜色确定当前项目。"""
        area = self._read_area('快捷手册', area_name)
        if area is None:
            return None
        image, results = area
        selected: list[str] = []
        for name in names:
            rect = self._text_rect(results, name)
            if rect is not None and has_filled_highlight(image, rect, color):
                selected.append(name)
        return selected[0] if len(selected) == 1 else None

    def _basic_material_focused(self) -> bool:
        """基础材料文字必须处于右列表的整行边框内。"""
        area = self._read_area('快捷手册', '手柄-副本列表')
        if area is None:
            return False
        image, results = area
        rect = self._text_rect(results, '基础材料')
        return rect is not None and text_inside_frame(rect, find_yellow_frames(image))

    def _teleport_dialog(self) -> bool:
        """确认当前弹窗确实询问传送。"""
        area = self._read_area('菜单', '手柄-确认弹窗')
        return area is not None and self._text_rect(area[1], '是否立即传送') is not None

    @operation_node(name='检查目标', is_start_node=True)
    def check_target(self) -> OperationRoundResult:
        """未验证的分类明确停止，不代替用户改成基础材料。"""
        if (self.tab_name, self.category_name, self.mission_type_name) != (
            '训练', '实战模拟室', '基础材料'
        ):
            return self.round_fail('手柄快捷手册暂仅支持训练/实战模拟室/基础材料')
        return self.round_success()

    @node_from(from_name='检查目标')
    @operation_node(name='打开快捷手册', node_max_retry_times=5, timeout_seconds=8)
    def open_compendium(self) -> OperationRoundResult:
        """仅在大世界证据命中时使用快捷手册组合键。"""
        if self.last_screenshot is None:
            return self.round_retry('截图无效', wait=1)
        if self._selected('手柄-顶部标签', self.TABS, 'yellow') is not None:
            return self.round_success()
        if not self._opened and self.round_by_find_area(
            self.last_screenshot, '大世界-普通', '快捷手册'
        ).is_success:
            if self.ctx.controller.click(gamepad_key='compendium'):
                self._opened = True
        return self.round_retry('等待手柄快捷手册', wait=1)

    @node_from(from_name='打开快捷手册')
    @operation_node(name='选择训练', node_max_retry_times=6, timeout_seconds=10)
    def choose_training(self) -> OperationRoundResult:
        """按已确认的固定标签顺序，每轮只移动一个标签。"""
        selected = self._selected('手柄-顶部标签', self.TABS, 'yellow')
        if selected == '训练':
            return self.round_success()
        if selected is not None:
            key = 'right_shoulder' if self.TABS.index(selected) < 2 else 'left_shoulder'
            self.ctx.controller.btn_tap(key)
        return self.round_retry('等待训练标签高亮', wait=0.8)

    @node_from(from_name='选择训练')
    @operation_node(name='选择实战模拟室', node_max_retry_times=6, timeout_seconds=10)
    def choose_simulation(self) -> OperationRoundResult:
        """按已确认的分类顺序移动，未知焦点不猜方向。"""
        selected = self._selected('手柄-分类列表', self.CATEGORIES, 'blue')
        if selected == '实战模拟室':
            return self.round_success()
        if selected is not None:
            key = 'dpad_down' if self.CATEGORIES.index(selected) < 1 else 'dpad_up'
            self.ctx.controller.btn_tap(key)
        return self.round_retry('等待实战模拟室分类高亮', wait=0.8)

    @node_from(from_name='选择实战模拟室')
    @operation_node(name='选择基础材料', node_max_retry_times=5, timeout_seconds=8)
    def choose_basic_material(self) -> OperationRoundResult:
        """先确认左分类和目标文字，再单次进入右列表。"""
        if self._basic_material_focused():
            return self.round_success()
        area = self._read_area('快捷手册', '手柄-副本列表')
        if area is None:
            return self.round_retry('副本列表区域未配置或截图无效', wait=0.8)
        if find_yellow_frames(area[0]):
            return self.round_fail('右列表焦点不是基础材料')
        if (
            not self._entered_list
            and self._text_rect(area[1], '基础材料') is not None
            and self._selected('手柄-分类列表', self.CATEGORIES, 'blue') == '实战模拟室'
        ):
            self.ctx.controller.btn_tap('south')
            self._entered_list = True
        return self.round_retry('等待基础材料整行焦点', wait=0.8)

    @node_from(from_name='选择基础材料')
    @operation_node(name='请求传送', node_max_retry_times=5, timeout_seconds=8)
    def request_teleport(self) -> OperationRoundResult:
        """只有基础材料有整行焦点时才打开确认弹窗。"""
        if self._teleport_dialog():
            return self.round_success()
        if not self._requested_teleport and self._basic_material_focused():
            self.ctx.controller.btn_tap('south')
            self._requested_teleport = True
        return self.round_retry('等待传送弹窗', wait=0.8)

    @node_from(from_name='请求传送')
    @operation_node(name='确认传送', node_max_retry_times=5, timeout_seconds=8)
    def confirm_teleport(self) -> OperationRoundResult:
        """弹窗文字与确认高亮同时命中后只按一次 A。"""
        if self._confirmed_teleport:
            return self.round_success()
        area = self._read_area('菜单', '手柄-确认按钮')
        if self._teleport_dialog() and area is not None:
            image, results = area
            rect = self._text_rect(results, '确认')
            if rect is not None and has_filled_highlight(image, rect, 'yellow'):
                self.ctx.controller.btn_tap('south')
                self._confirmed_teleport = True
                return self.round_success(wait=1)
        return self.round_retry('等待传送确认按钮高亮', wait=0.8)

    @node_from(from_name='确认传送')
    @operation_node(name='等待模拟室入口', node_max_retry_times=15, timeout_seconds=20)
    def wait_for_simulation(self) -> OperationRoundResult:
        """挑战等级与下一步同时出现才算抵达，不把加载空白当成功。"""
        if self.last_screenshot is None:
            return self.round_retry('截图无效', wait=1)
        level = self.round_by_find_area(
            self.last_screenshot, '实战模拟室', '手柄-挑战等级'
        )
        next_step = self.round_by_find_area(
            self.last_screenshot, '实战模拟室', '手柄-下一步'
        )
        if level.is_success and next_step.is_success:
            return self.round_success('已抵达实战模拟室基础材料')
        return self.round_retry('等待实战模拟室入口', wait=1)
