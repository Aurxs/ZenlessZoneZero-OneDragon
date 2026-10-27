"""设置页的手动手柄会话，复用原应用调度和当前控制器。"""

from __future__ import annotations

from threading import Event
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from concurrent.futures import Future

    from one_dragon.base.controller.gamepad_input import GamepadSide
    from one_dragon.base.operation.application.application_run_context import (
        ApplicationRunResult,
    )
    from zzz_od.context.zzz_context import ZContext

APP_ID: str = 'manual_gamepad'


class ManualGamepadSession:
    """只有设置页显式请求且原调度持有手动应用时，才允许发送输入。"""

    def __init__(self, ctx: ZContext) -> None:
        self.ctx: ZContext = ctx
        self.requested: Event = Event()
        self.ready: Event = Event()
        self.pending: Event = Event()
        self.last_status: str = '未启用手动控制'

    @property
    def active(self) -> bool:
        """暂停、停止、切换应用或页面撤回请求后立即禁止新输入。"""
        return (
            self.requested.is_set() and self.ready.is_set()
            and self.ctx.run_context.is_context_running
            and self.ctx.run_context.current_app_id == APP_ID
        )

    def start(self) -> None:
        """使用原单工作线程申请运行；不创建第二个手柄或切换当前画面。"""
        if not self.ctx.ready_for_application:
            raise RuntimeError(self.ctx.initialization_error or '请等待一条龙初始化完成')
        if self.pending.is_set() or not self.ctx.run_context.is_context_stop:
            raise RuntimeError('请先停止当前任务，再启用手动控制')
        self.ready.clear()
        self.last_status = '正在连接手柄与游戏画面…'
        self.requested.set()
        self.pending.set()
        try:
            started = self.ctx.run_context.run_application_async(
                APP_ID, self.ctx.current_instance_idx, 'one_dragon', on_done=self._finished,
            )
        except Exception:
            self.requested.clear()
            self.pending.clear()
            raise
        if not started:
            self.requested.clear()
            self.pending.clear()
            raise RuntimeError('手动控制未开始')

    def _finished(self, future: Future[ApplicationRunResult]) -> None:
        """初始化失败或异常也撤销请求，页面不会永久停在连接状态。"""
        try:
            result = future.result()
            self.last_status = (
                '手动控制已结束' if result.finish_reason in ('COMPLETED', 'STOPPED')
                else '手动控制未能启动或已异常停止，请查看运行日志'
            )
        except Exception as error:
            self.last_status = f'手动控制失败：{error}'
        finally:
            self.ready.clear()
            self.requested.clear()
            self.pending.clear()

    def stop(self) -> None:
        """撤回未启动请求或停止本页应用，不停止其他自动任务。"""
        self.requested.clear()
        self.ready.clear()
        if self.pending.is_set():
            self.last_status = '正在结束手动控制…'
        if self.ctx.run_context.current_app_id == APP_ID:
            self.ctx.run_context.stop_running()

    def release_all(self) -> None:
        """只清空本页持有的输入，保留手动会话。"""
        if self.ctx.run_context.current_app_id == APP_ID and self.ctx.controller is not None:
            self.ctx.controller.reset_input()

    def set_button(self, key: str, pressed: bool) -> None:
        """保持/松开物理按键；不绕过兼容层的新帧和暂停保护。"""
        if not self.active:
            return
        if pressed:
            self.ctx.controller.btn_press(key)
        else:
            self.ctx.controller.btn_release(key)

    def set_stick(self, side: GamepadSide, x: float, y: float) -> None:
        """更新单根摇杆，其他按键状态保持不变。"""
        if self.active:
            self.ctx.controller.set_gamepad_stick(side, x, y)

    def set_action(self, action: str, pressed: bool) -> None:
        """界面快捷键从当前账户读取，按下与释放使用同一页锁定的配置。"""
        keys = self.ctx.game_config.get_gamepad_action_keys('xbox').get(action, [])
        for key in keys if pressed else reversed(keys):
            self.set_button(key, pressed)
