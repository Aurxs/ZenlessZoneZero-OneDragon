"""藏品页采用手柄页签，分类提取继续使用原动态优先级流程。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from zzz_od.application.hollow_zero.lost_void.operation.update_priority_operation import (
    UpdatePriorityOperation,
)
from zzz_od.operation.gamepad.focus import has_filled_highlight
from zzz_od.operation.gamepad.gamepad_operation import GamepadMenuDelayMixin
from zzz_od.operation.gamepad.transport_by_compendium import (
    GamepadTransportByCompendium,
)

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class GamepadLostVoidUpdatePriority(GamepadMenuDelayMixin, UpdatePriorityOperation):
    """只替换进入和返回菜单，不复制原等级与武备分类决策。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx)
        self.navigation: GamepadTransportByCompendium = GamepadTransportByCompendium(ctx, '作战', '周期征讨')
        self._opened: bool = False
        self._closed: bool = False

    @operation_node(name='进入藏品页面', is_start_node=True, node_max_retry_times=8)
    def enter_collections(self) -> OperationRoundResult:
        """按完整页签填充识别肩键方向，只从已确认局内打开一次。"""
        if self.last_screenshot is None:
            return self.round_retry('等待藏品菜单截图', wait=1)
        nav = self.navigation
        nav.last_screenshot = self.last_screenshot
        tabs = nav._read_area('迷失之地-藏品面板', '手柄-页签')
        if tabs:
            current = [name for name in ('地图', '藏品', '属性') if (rect := nav._text_rect(tabs[1], name)) is not None
                       and has_filled_highlight(tabs[0], rect, 'yellow')]
            if current == ['藏品']:
                return self.round_success('已进入藏品页', wait=1)
            if len(current) == 1:
                self.ctx.controller.btn_tap('right_shoulder' if current[0] == '地图' else 'left_shoulder')
                return self.round_retry('等待藏品页签', wait=1)
        if not self._opened and self.ctx.lost_void.in_normal_world(self.last_screenshot):
            self.ctx.controller.click(gamepad_key='minimap')
            self._opened = True
        return self.round_retry('等待局内菜单', wait=1)

    @node_from(from_name='识别并存储优先级')
    @operation_node(name='关闭菜单', node_max_retry_times=8)
    def close_menu(self) -> OperationRoundResult:
        """关闭后必须重新确认局内 HUD。"""
        if self.last_screenshot is None:
            return self.round_retry('等待返回截图', wait=1)
        if self.ctx.lost_void.in_normal_world(self.last_screenshot):
            self.ctx.lost_void.priority_updated = True
            return self.round_success('动态优先级已更新')
        nav = self.navigation
        nav.last_screenshot = self.last_screenshot
        tabs = nav._read_area('迷失之地-藏品面板', '手柄-页签')
        if tabs and all(nav._text_rect(tabs[1], name) is not None for name in ('地图', '藏品', '属性')) and not self._closed:
            self.ctx.controller.btn_tap('east')
            self._closed = True
        return self.round_retry('等待藏品菜单关闭', wait=1)
