"""路径迭换沿用原操作的直接返回行为，不消耗导航次数或定位卡。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from one_dragon.base.operation.operation_node import operation_node
from zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_route_change import (
    LostVoidRouteChange,
)
from zzz_od.operation.gamepad.gamepad_operation import GamepadMenuDelayMixin

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class GamepadLostVoidRouteChange(GamepadMenuDelayMixin,LostVoidRouteChange):
    """只在路径迭换双锚点匹配后返回一次，等待实际局内画面。"""

    def __init__(self,ctx: ZContext) -> None:
        super().__init__(ctx)
        self._sent: bool=False

    @operation_node(name='返回',is_start_node=True,node_max_retry_times=8)
    def back_to_world(self) -> OperationRoundResult:
        if self.last_screenshot is None:
            return self.round_retry('等待路径迭换截图',wait=1)
        if self.ctx.lost_void.in_normal_world(self.last_screenshot):
            return self.round_success('路径迭换已返回')
        current=self.check_and_update_current_screen(self.last_screenshot,screen_name_list=['迷失之地-路径迭换'])
        if current is not None and not self._sent:
            self.ctx.controller.btn_tap('east')
            self._sent=True
        return self.round_retry('等待路径迭换关闭',wait=1)
