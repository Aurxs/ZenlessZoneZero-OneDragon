"""复用公共会话入口，让原一条龙页面可单独检查游戏准备。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal

from one_dragon.base.operation.application.application_run_context import (
    ApplicationRunContextStateEventEnum,
)
from one_dragon.base.operation.operation_base import OperationResult
from one_dragon.utils.log_utils import log

if TYPE_CHECKING:
    from one_dragon.base.operation.context_event_bus import ContextEventItem
    from zzz_od.context.zzz_context import ZContext


class MacGamePreparationRunner(QThread):
    """只检查和切换模式，结束后释放运行状态，不执行任务列表。"""

    state_changed = Signal()

    def __init__(self, ctx: ZContext) -> None:
        super().__init__()
        self.ctx: ZContext = ctx
        self.result: OperationResult | None = None

    def _on_state_changed(self, event: ContextEventItem) -> None:
        """将运行状态通知转到 Qt 主线程。"""
        self.state_changed.emit()

    def run(self) -> None:
        """保留 Qt 主线程事件循环，只在工作线程执行准备操作。"""
        self.result = None
        if not self.ctx.ready_for_application:
            self.result = OperationResult(
                False, status=self.ctx.initialization_error or '初始化尚未完成，请稍后再试',
            )
            log.error(self.result.status)
            return
        bus = self.ctx.run_context.event_bus
        for event in (
            ApplicationRunContextStateEventEnum.START,
            ApplicationRunContextStateEventEnum.PAUSE,
            ApplicationRunContextStateEventEnum.RESUME,
            ApplicationRunContextStateEventEnum.STOP,
        ):
            bus.listen_event(event, self._on_state_changed)
        started = False
        try:
            started = self.ctx.run_context.start_running()
            if not started:
                self.result = OperationResult(False, status='游戏准备未开始，请查看初始化日志')
                return
            self.result = self.ctx.macos_session_preparation.prepare()
            if self.result.success:
                log.info('游戏准备完成：%s', self.result.status)
            else:
                log.error('游戏准备失败：%s', self.result.status)
        except Exception as error:
            self.result = OperationResult(False, status=f'游戏准备失败：{error}')
            log.error(self.result.status, exc_info=True)
        finally:
            if started:
                self.ctx.run_context.stop_running()
            bus.unlisten_all_event(self)
