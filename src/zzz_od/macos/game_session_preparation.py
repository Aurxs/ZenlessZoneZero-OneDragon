"""同一次 Mac 运行只准备一次游戏，重连后重新确认画面。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from one_dragon.base.operation.operation_base import OperationResult
from zzz_od.operation.enter_game.game_session_entry import create_game_session_entry

if TYPE_CHECKING:
    from zzz_od.context.zzz_context import ZContext


class MacGameSessionPreparation:
    """以兼容层每次初始化的代数区分会话，不复用上次运行的准备结果。"""

    def __init__(self, ctx: ZContext) -> None:
        self.ctx: ZContext = ctx
        self._prepared_key: tuple[object, int] | None = None

    def prepare(self) -> OperationResult:
        """必须在运行中确认输入模式；失败或停止不缓存成功。"""
        if self.ctx.run_context.is_context_stop:
            return OperationResult(False, status='当前已停止，未执行游戏准备')
        controller = self.ctx.controller
        generation = getattr(controller, 'run_generation', None)
        key = (controller, generation) if isinstance(generation, int) else None
        if key is not None and key == self._prepared_key and self.ctx.is_game_window_ready:
            return OperationResult(True, status='本次运行已确认手柄大世界')

        self._prepared_key = None
        result = create_game_session_entry(self.ctx).execute()
        if result.success and not self.ctx.run_context.is_context_stop:
            self._prepared_key = key
        return result
