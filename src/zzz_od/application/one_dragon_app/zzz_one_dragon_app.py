from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from one_dragon.base.operation.application import application_const
from one_dragon.base.operation.one_dragon_app import OneDragonApp
from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from zzz_od.application.zzz_application import ZApplication
from zzz_od.macos.application_capabilities import (
    get_macos_one_dragon_unavailable_reason,
)
from zzz_od.operation.enter_game.game_session_entry import (
    create_account_switch_entry,
    create_game_session_entry,
)

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_base import OperationResult
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class ZOneDragonApp(OneDragonApp, ZApplication):

    """一条龙:按已启用顺序串跑各 app 的完整循环。会触发所有已启用玩法的副作用(含消耗体力/周限等)。"""

    def __init__(self, ctx: ZContext) -> None:
        """按平台构造会话入口，不提前加载未支持的登录操作。"""
        op_to_enter_game = create_game_session_entry(ctx)
        op_to_switch_account = create_account_switch_entry(ctx)

        ZApplication.__init__(
            self,
            ctx=ctx,
            app_id=application_const.ONE_DRAGON_APP_ID,
            op_to_enter_game=op_to_enter_game,
        )
        OneDragonApp.__init__(
            self,
            ctx=ctx,
            op_to_enter_game=op_to_enter_game,
            op_to_switch_account=op_to_switch_account,
        )

    def execute(self) -> OperationResult:
        """Mac 仅执行当前实例的已适配任务，保留原应用组与排序。"""
        unavailable_reason = get_macos_one_dragon_unavailable_reason(self.ctx)
        if unavailable_reason is not None:
            return self.op_fail(unavailable_reason)
        if sys.platform == 'darwin':
            return ZApplication.execute(self)
        return OneDragonApp.execute(self)

    @node_from(from_name='运行应用组')
    @operation_node(name='切换实例配置', screenshot_before_round=False)
    def switch_instance(self) -> OperationRoundResult:
        """Mac 当前实例执行后不重建采集；Windows 沿用原切换逻辑。"""
        if sys.platform == 'darwin':
            return self.round_success()
        return OneDragonApp.switch_instance(self)


def __debug():
    from zzz_od.context.zzz_context import ZContext

    ctx = ZContext()
    ctx.init()
    ctx.run_context.start_running()
    app = ZOneDragonApp(ctx)
    app.execute()

if __name__ == '__main__':
    __debug()
