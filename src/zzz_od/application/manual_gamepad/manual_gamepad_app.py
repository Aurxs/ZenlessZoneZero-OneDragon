"""设置页专用手动控制，沿用原运行状态互斥，不加入一条龙任务列表。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from one_dragon.base.operation.application_base import Application
from one_dragon.base.operation.operation_node import operation_node
from zzz_od.macos.manual_gamepad import APP_ID

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_base import OperationResult
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class ManualGamepadApp(Application):
    """不导航游戏，允许用户从当前手柄画面接管。"""

    def __init__(self, ctx: ZContext) -> None:
        self.ctx: ZContext = ctx
        super().__init__(ctx, APP_ID, op_name='手动手柄', need_check_game_win=False)

    @operation_node(name='等待手动控制', is_start_node=True, screenshot_before_round=False, mute=True)
    def wait_for_input(self) -> OperationRoundResult:
        """页面取消请求后结束；启动过程收到离页事件也不会发出游戏动作。"""
        if not self.ctx.manual_gamepad.requested.is_set():
            return self.round_success('手动控制已结束')
        self.ctx.manual_gamepad.ready.set()
        return self.round_wait(wait=0.1)

    def after_operation_done(self, result: OperationResult) -> None:
        """收尾前归零，防止页面或任务切换后遗留保持输入。"""
        try:
            self.ctx.manual_gamepad.ready.clear()
            self.ctx.manual_gamepad.requested.clear()
            self.ctx.manual_gamepad.release_all()
        finally:
            super().after_operation_done(result)
