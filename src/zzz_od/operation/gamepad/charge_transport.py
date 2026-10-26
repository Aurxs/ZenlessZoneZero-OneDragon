"""按原体力副本数据导航快捷手册的分类和目标。"""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING

from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from zzz_od.game_data.compendium import CompendiumService
from zzz_od.operation.gamepad.focus import (
    find_yellow_frames,
    has_filled_highlight,
    text_inside_frame,
)
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation
from zzz_od.operation.gamepad.transport_by_compendium import (
    GamepadTransportByCompendium,
)

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


@cache
def charge_mission_names(category_name: str) -> tuple[str, ...]:
    """原副本数据中的普通目标，特训计划单独接入。"""
    service = CompendiumService()
    service.reload()
    category = service.get_category_data('训练', category_name)
    return tuple(item.mission_type_name for item in category.mission_type_list if not item.is_agent_plan) if category else ()


class GamepadChargeTransport(GamepadOperation):
    """逐帧确认目标文字与焦点，传送后只检查入口、不出战。"""

    def __init__(self, ctx: ZContext, category_name: str, mission_type_name: str) -> None:
        super().__init__(ctx, op_name=f'手柄传送{category_name} {mission_type_name}', timeout_seconds=180)
        self.category_name: str = category_name
        self.target: str = mission_type_name
        self.navigation: GamepadTransportByCompendium = GamepadTransportByCompendium(ctx, '训练', category_name, mission_type_name)
        self._names: tuple[str, ...] = ()
        self._entered: bool = False
        self._requested: bool = False
        self._last_selected: str | None = None
        self._unchanged: int = 0
        self._scan_down: bool | None = None
        self._scan_reversed: bool = False

    def handle_init(self) -> None:
        """每次从当前画面重新确认，不复用上一次的焦点。"""
        self.navigation.handle_init()
        self._entered = False
        self._requested = False
        self._last_selected = None
        self._unchanged = 0
        self._scan_down = None
        self._scan_reversed = False

    @operation_node(name='检查副本目标', is_start_node=True, screenshot_before_round=False)
    def check_target(self) -> OperationRoundResult:
        """普通副本从原数据取名，特训目标另行适配。"""
        if self.category_name not in ('区域巡防',):
            return self.round_fail(f'尚未开放手册分类：{self.category_name}')
        self._names = charge_mission_names(self.category_name)
        if self.target not in self._names:
            return self.round_fail(f'副本不在原数据中：{self.category_name}/{self.target}')
        return self.round_success()

    @node_from(from_name='检查副本目标')
    @operation_node(name='打开快捷手册', node_max_retry_times=6)
    def open_handbook(self) -> OperationRoundResult:
        """复用原手柄大世界入口。"""
        self.navigation.last_screenshot = self.last_screenshot
        return self.navigation.open_compendium()

    @node_from(from_name='打开快捷手册')
    @operation_node(name='选择训练标签', node_max_retry_times=6)
    def choose_training(self) -> OperationRoundResult:
        """复用训练标签的颜色与文字识别。"""
        self.navigation.last_screenshot = self.last_screenshot
        return self.navigation.choose_training()

    @node_from(from_name='选择训练标签')
    @operation_node(name='选择副本分类', node_max_retry_times=8)
    def choose_category(self) -> OperationRoundResult:
        """按已建档左栏分类顺序移动，未知焦点不操作。"""
        nav = self.navigation
        nav.last_screenshot = self.last_screenshot
        current = nav._selected('手柄-分类列表', nav.CATEGORIES, 'blue')
        if current == self.category_name:
            return self.round_success()
        if current is not None:
            self.ctx.controller.btn_tap('dpad_down' if nav.CATEGORIES.index(current) < nav.CATEGORIES.index(self.category_name) else 'dpad_up')
        return self.round_retry('等待副本分类高亮', wait=0.7)

    @node_from(from_name='选择副本分类')
    @operation_node(name='选择计划副本', node_max_retry_times=70, timeout_seconds=130)
    def choose_target(self) -> OperationRoundResult:
        """整行黄框或对应前往按钮必须属于目标，滚动始终依据当前项。"""
        nav = self.navigation
        nav.last_screenshot = self.last_screenshot
        if nav._teleport_dialog():
            return self.round_success() if self._requested else self.round_fail('传送弹窗来源未确认')
        area = nav._read_area('快捷手册', '手柄-副本列表')
        if area is None:
            return self.round_retry('等待副本列表', wait=0.7)
        image, words = area
        frames = find_yellow_frames(image)
        buttons = [match.rect for text, matches in words.items() if text.replace(' ', '') == '前往'
                   for match in matches if has_filled_highlight(image, match.rect, 'yellow')]
        visible = {name: rect for name in self._names if (rect := nav._text_rect(words, name)) is not None}
        selected: list[str] = []
        for name, rect in visible.items():
            if text_inside_frame(rect, frames) or (
                len(buttons) == 1 and 0 < buttons[0].center.y - rect.center.y < 170
            ):
                selected.append(name)
        if len(selected) == 1:
            current = selected[0]
            if current == self.target:
                if not self._requested:
                    self.save_screenshot(prefix='macos_charge_handbook_target')
                    self.ctx.controller.btn_tap('south')
                    self._requested = True
                return self.round_retry('等待目标传送弹窗', wait=0.8)
            if current == self._last_selected:
                self._unchanged += 1
                if self._unchanged >= 3:
                    if self._scan_reversed:
                        self.save_screenshot(prefix='macos_charge_handbook_stuck')
                        return self.round_fail(f'已遍历列表，目标不可达：{self.target}')
                    self._scan_reversed = True
                    self._scan_down = not self._scan_down
                    self._unchanged = 0
                    self.ctx.controller.btn_tap('dpad_down' if self._scan_down else 'dpad_up')
                    return self.round_retry('边界焦点未移动，反向查找一次', wait=0.7)
                return self.round_retry('等待列表移动', wait=0.7)
            self._last_selected = current
            self._unchanged = 0
            if self.target in visible:
                down = visible[current].center.y < visible[self.target].center.y
            else:
                # 推荐目标可能置顶，方向只在第一次决定，不能每行重新推断而振荡。
                if self._scan_down is None:
                    ranks = [self._names.index(name) for name in sorted(visible, key=lambda name: visible[name].center.y)]
                    ascending = len(ranks) > 1 and all(a < b for a, b in zip(ranks, ranks[1:], strict=False))
                    descending = len(ranks) > 1 and all(a > b for a, b in zip(ranks, ranks[1:], strict=False))
                    self._scan_down = (self._names.index(current) < self._names.index(self.target)) == ascending if ascending or descending else True
                down = self._scan_down
            self.ctx.controller.btn_tap('dpad_down' if down else 'dpad_up')
            return self.round_retry('等待计划目标进入焦点', wait=0.7)
        if not frames and not buttons and not self._entered:
            if nav._selected('手柄-分类列表', nav.CATEGORIES, 'blue') == self.category_name:
                self.ctx.controller.btn_tap('south')
                self._entered = True
        if self.node_retry_times >= 30:
            self.save_screenshot(prefix='macos_charge_target_missing')
        return self.round_retry('目标或焦点尚不明确，未发送确认', wait=0.7)

    @node_from(from_name='选择计划副本')
    @operation_node(name='确认目标传送', node_max_retry_times=5)
    def confirm_teleport(self) -> OperationRoundResult:
        """复用已有传送确认。"""
        self.navigation.last_screenshot = self.last_screenshot
        return self.navigation.confirm_teleport()

    @node_from(from_name='确认目标传送')
    @operation_node(name='等待副本准备', node_max_retry_times=20, timeout_seconds=30)
    def wait_entry(self) -> OperationRoundResult:
        """落地后保留真实画面，后续单场再次核对目标与电量。"""
        if self.last_screenshot is not None and all(
            self.round_by_find_area(self.last_screenshot, self.category_name, name).is_success
            for name in ('手柄-挑战等级', '手柄-下一步')
        ):
            self.save_screenshot(prefix='macos_charge_entry')
            return self.round_success(f'已抵达{self.category_name}准备页')
        if self.node_retry_times >= 15:
            self.save_screenshot(prefix='macos_charge_entry_pending')
        return self.round_retry('等待副本准备页', wait=1)
