from __future__ import annotations

from typing import TYPE_CHECKING

from one_dragon.base.operation.operation import Operation
from zzz_od.operation.enter_game.game_session_entry import create_game_session_entry

if TYPE_CHECKING:
    from collections.abc import Callable

    from one_dragon.base.operation.operation_base import OperationResult
    from zzz_od.context.zzz_context import ZContext


class ZOperation(Operation):

    def __init__(self, ctx: ZContext,
                 node_max_retry_times: int = 3,
                 op_name: str = '',
                 timeout_seconds: float = -1,
                 op_callback: Callable[[OperationResult], None] | None = None,
                 need_check_game_win: bool = True
                 ) -> None:
        """复用对应平台的游戏会话入口。"""
        self.ctx: ZContext = ctx
        op_to_enter_game = create_game_session_entry(ctx)
        Operation.__init__(self,
                           ctx=ctx,
                           node_max_retry_times=node_max_retry_times,
                           op_name=op_name,
                           timeout_seconds=timeout_seconds,
                           op_callback=op_callback,
                           need_check_game_win=need_check_game_win,
                           op_to_enter_game=op_to_enter_game)
