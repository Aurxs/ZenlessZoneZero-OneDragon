from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from one_dragon.base.operation.application_base import Application
from zzz_od.macos.application_capabilities import get_macos_app_unavailable_reason
from zzz_od.operation.enter_game.game_session_entry import (
    create_game_session_entry,
    prepare_game_window_for_resume,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from one_dragon.base.operation.application_run_record import AppRunRecord
    from one_dragon.base.operation.operation import Operation
    from one_dragon.base.operation.operation_base import OperationResult
    from zzz_od.context.zzz_context import ZContext


class ZApplication(Application):

    def __init__(self, ctx: ZContext, app_id: str,
                 node_max_retry_times: int = 1,
                 op_name: str | None = None,
                 timeout_seconds: float = -1,
                 op_callback: Callable[[OperationResult], None] | None = None,
                 need_check_game_win: bool = True,
                 op_to_enter_game: Operation | None = None,
                 run_record: AppRunRecord | None = None,
                 ) -> None:
        """按平台提供默认入口，同时保留调用方指定的入口。"""
        self.ctx: ZContext = ctx
        if op_to_enter_game is None:
            op_to_enter_game = create_game_session_entry(ctx)
        Application.__init__(
            self,
            ctx=ctx,
            app_id=app_id,
            node_max_retry_times=node_max_retry_times,
            op_name=op_name,
            timeout_seconds=timeout_seconds,
            op_callback=op_callback,
            need_check_game_win=need_check_game_win,
            op_to_enter_game=op_to_enter_game,
            run_record=run_record,
        )

    def execute(self) -> OperationResult:
        """Mac 在原应用执行前核对适配范围并统一准备游戏会话。"""
        unavailable_reason = get_macos_app_unavailable_reason(self.app_id)
        if unavailable_reason is not None:
            return self.op_fail(unavailable_reason)
        if sys.platform == 'darwin':
            result = self.ctx.macos_session_preparation.prepare()
            if not result.success:
                return result
        return Application.execute(self)

    def handle_resume(self) -> None:
        """恢复框架执行，Mac 不请求激活游戏窗口。"""
        prepare_game_window_for_resume(self.ctx)
        Application.handle_resume(self)
