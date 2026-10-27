from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from one_dragon.base.operation.operation_round_result import OperationRoundResult
from zzz_od.application.battle_assistant.auto_battle.auto_battle_app import (
    AutoBattleApp,
)
from zzz_od.application.battle_assistant.battle_assistant_input_mode import (
    apply_battle_assistant_input_mode,
)
from zzz_od.application.battle_assistant.dodge_assitant import dodge_assistant_const
from zzz_od.application.zzz_application import ZApplication
from zzz_od.context.zzz_context import ZContext

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_base import OperationResult
    from zzz_od.operation.gamepad.battle_assistant import MacBattleAssistantSession


class DodgeAssistantApp(ZApplication):

    """闪避助手:辅助工具,战斗中自动闪避。非玩法、无独立消耗。"""

    def __init__(self, ctx: ZContext):
        """
        识别后进行闪避
        """
        ZApplication.__init__(
            self,
            ctx=ctx,
            app_id=dodge_assistant_const.APP_ID,
            op_name=dodge_assistant_const.APP_NAME,
        )
        self._mac_session: MacBattleAssistantSession | None = None

    def execute(self) -> OperationResult:
        """Mac 复用原启动准备，已经在手柄战斗时直接确认。"""
        if sys.platform == 'darwin':
            from zzz_od.operation.gamepad.battle_assistant import (
                execute_macos_battle_assistant,
            )

            return execute_macos_battle_assistant(self)
        return super().execute()

    def handle_init(self) -> None:
        """
        执行前的初始化 由子类实现
        注意初始化要全面 方便一个指令重复使用
        """
        if sys.platform == 'darwin':
            from zzz_od.operation.gamepad.battle_assistant import (
                MacBattleAssistantSession,
            )

            self._mac_session = MacBattleAssistantSession(self.ctx)

    @operation_node(name='手柄检测', is_start_node=True)
    def check_gamepad(self) -> OperationRoundResult:
        """
        检测手柄
        :return:
        """
        success, status = apply_battle_assistant_input_mode(self.ctx)
        return self.round_success(status=status) if success else self.round_fail(status=status)

    @node_from(from_name='手柄检测')
    @operation_node(name='加载自动战斗指令')
    def load_op(self) -> OperationRoundResult:
        """
        加载战斗指令
        :return:
        """
        try:
            self.ctx.auto_battle_context.init_auto_op(
                sub_dir='dodge',
                op_name=self.ctx.battle_assistant_config.dodge_assistant_config
            )
        except Exception as e:
            return self.round_fail(status=f'加载指令失败: {e}')

        self.ctx.dispatch_event(
            AutoBattleApp.EVENT_OP_LOADED,
            self.ctx.auto_battle_context.auto_op
        )
        if self._mac_session is not None:
            self._mac_session.update(self.last_screenshot)
        else:
            self.ctx.auto_battle_context.start_auto_battle()

        return self.round_success()

    @node_from(from_name='加载自动战斗指令')
    @operation_node(name='闪避判断', mute=True)
    def check_dodge(self) -> OperationRoundResult:
        """
        识别当前画面 并进行点击
        :return:
        """
        if self._mac_session is None or self._mac_session.update(self.last_screenshot):
            self.ctx.auto_battle_context.check_battle_state(self.last_screenshot, self.last_screenshot_time)

        return self.round_wait(wait_round_time=self.ctx.battle_assistant_config.screenshot_interval)

    def handle_pause(self, e=None):
        if self._mac_session is not None:
            self._mac_session.pause()
        else:
            self.ctx.auto_battle_context.stop_auto_battle()

    def handle_resume(self, e=None):
        if self.current_node.node is not None and self.current_node.node.cn == '闪避判断':
            if self._mac_session is not None:
                self._mac_session.update(self.ctx.controller.get_screenshot())
            else:
                self.ctx.auto_battle_context.resume_auto_battle()

    def after_operation_done(self, result: OperationResult) -> None:
        """闪避助手同样保证异常和停止都释放输入并执行原应用收尾。"""
        try:
            if self._mac_session is not None:
                self._mac_session.close()
            else:
                self.ctx.auto_battle_context.stop_auto_battle()
        finally:
            ZApplication.after_operation_done(self, result)
