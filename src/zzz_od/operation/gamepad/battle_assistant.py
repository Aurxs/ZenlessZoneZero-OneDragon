"""原独立战斗助手的 Mac 会话准备与输入释放。"""

from __future__ import annotations

import time
from threading import RLock
from typing import TYPE_CHECKING

from one_dragon.base.operation.application_base import Application
from one_dragon.base.operation.operation_node import operation_node
from zzz_od.controller.macos_battle_input_guard import MacBattleHudGuard
from zzz_od.macos.application_capabilities import get_macos_app_unavailable_reason
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation
from zzz_od.operation.gamepad.lost_void import GamepadLostVoidExit

if TYPE_CHECKING:
    from cv2.typing import MatLike

    from one_dragon.base.operation.operation_base import OperationResult
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.application.zzz_application import ZApplication
    from zzz_od.context.zzz_context import ZContext


def is_native_battle(ctx: ZContext, image: MatLike | None) -> bool:
    """普攻按钮及固定位置的手柄 A 提示共同确认原生手柄战斗。"""
    if image is None or not ctx.auto_battle_context.is_normal_attack_btn_available(image):
        return False
    area = ctx.screen_loader.get_area('战斗画面', '手柄-闪避键提示')
    if area is None:
        return False
    matches = ctx.tm.crop_and_match_template(image, area.rect, area.template_sub_dir, area.template_id,
                                              threshold=area.template_match_threshold)
    return matches.max is not None


def is_native_battle_menu(ctx: ZContext, image: MatLike | None) -> bool:
    """复用战况底部快捷栏及 A/B 提示，确认手柄菜单。"""
    area = ctx.screen_loader.get_area('迷失之地-大世界', '手柄-战况返回')
    if image is None or area is None:
        return False
    pieces = {text.replace(' ', '').upper() for text in ctx.ocr.crop_and_run_ocr(image, area.rect)}
    words = ''.join(pieces)
    if not all(word in words for word in ('重新开始', '退出战斗', '返回')):
        return False
    return any(text in ('A', 'A选择') for text in pieces) and any(text in ('B', 'B返回') for text in pieces)


class GamepadBattleAssistantEntry(GamepadOperation):
    """已在原生手柄战斗时直接确认，其余情况复用原准备流程。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='准备 Mac 独立战斗助手', timeout_seconds=180)

    @operation_node(name='确认助手输入模式', is_start_node=True, node_max_retry_times=6)
    def prepare(self) -> OperationRoundResult:
        """战斗中只确认手柄布局，世界和启动页仍走既有模式切换。"""
        if is_native_battle(self.ctx, self.last_screenshot):
            return self.round_success('已确认原生手柄战斗')
        if is_native_battle_menu(self.ctx, self.last_screenshot):
            return self.round_success('已确认手柄战况菜单，等待战斗')
        if self.last_screenshot is not None and self.ctx.auto_battle_context.is_normal_attack_btn_available(self.last_screenshot):
            return self.round_retry('等待明确的手柄战斗提示', wait=0.5)
        if self.node_retry_times < 2 and not self.round_by_find_area(
            self.last_screenshot, '大世界-普通', '快捷手册',
        ).is_success:
            return self.round_retry('等待战斗或启动画面稳定', wait=0.5)
        return self.round_by_op_result(self.ctx.macos_session_preparation.prepare())


class GamepadResumeBattle(GamepadOperation):
    """从已确认的手柄战况菜单返回战斗，不处理退出或重开。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄返回当前战斗', timeout_seconds=10)
        self._sent: bool = False

    @operation_node(name='返回当前战斗', is_start_node=True, node_max_retry_times=6)
    def resume(self) -> OperationRoundResult:
        """B 仅发一次，必须看到原生战斗 HUD 才完成。"""
        if is_native_battle(self.ctx, self.last_screenshot):
            return self.round_success('已返回原生手柄战斗')
        if is_native_battle_menu(self.ctx, self.last_screenshot):
            if not self._sent:
                self.ctx.controller.btn_tap('east')
                self._sent = True
            return self.round_retry('等待返回战斗', wait=0.5)
        return self.round_retry('等待已确认的战况或战斗画面', wait=0.5)


class GamepadExitBattle(GamepadLostVoidExit):
    """复用既有退出确认流程，兼容恶名入口与结果页。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx)
        self.op_name = '手柄退出当前战斗'

    @operation_node(name='退出当前挑战', is_start_node=True, node_max_retry_times=15)
    def leave(self) -> OperationRoundResult:
        """普通挑战返回自己的入口，不写迷失或恶名任务计数。"""
        from zzz_od.operation.gamepad.notorious_hunt import GamepadHuntResultExit

        if self.round_by_find_area(self.last_screenshot, '战斗画面', '手柄-挑战结果').is_success:
            return self.round_by_op_result(GamepadHuntResultExit(self.ctx).execute())
        words = self.ctx.ocr.run_ocr(self.last_screenshot) if self.last_screenshot is not None else {}
        text = ''.join(words).replace(' ', '')
        if '挑战等级' in text and '深度追猎' in text:
            return self.round_success('已退出当前战斗')
        return super().leave()


def execute_macos_battle_assistant(application: ZApplication) -> OperationResult:
    """保留原应用生命周期，不要求用户先退出已确认的手柄战斗。"""
    reason = get_macos_app_unavailable_reason(application.app_id)
    if reason is not None:
        return application.op_fail(reason)
    result = GamepadBattleAssistantEntry(application.ctx).execute()
    return Application.execute(application) if result.success else result


class MacBattleAssistantSession:
    """等待战斗时保持中立；暂停、结束和未知画面均停止策略。"""

    def __init__(self, ctx: ZContext, auto_ultimate_enabled: bool | None = None) -> None:
        self.ctx: ZContext = ctx
        self.auto_ultimate_enabled: bool | None = auto_ultimate_enabled
        self._scope: bool = False
        self._active: bool = False
        self._started: bool = False
        self._waiting: bool = False
        self._closed: bool = False
        self._next_probe: float = 0
        self._lock: RLock = RLock()

    def _activate(self, resume: bool) -> None:
        """策略恢复后保留原独立助手的终结技开关。"""
        battle = self.ctx.auto_battle_context
        if resume:
            battle.resume_auto_battle()
        else:
            battle.start_auto_battle()
        if self.auto_ultimate_enabled is not None:
            battle.auto_ultimate_enabled = self.auto_ultimate_enabled
        self._active = True
        self._started = True
        self._waiting = False

    def update(self, image: MatLike | None) -> bool:
        """仅战斗输入限制放行后，原应用才继续发布识别状态。"""
        with self._lock:
            return self._update(image)

    def _update(self, image: MatLike | None) -> bool:
        """暂停回调和识别循环共用会话锁，避免重复建立输入范围。"""
        if self._closed or self.ctx.run_context.is_context_running is False:
            return False
        if not self._scope:
            ready = (
                image is not None and MacBattleHudGuard(self.ctx.auto_battle_context)(image)
                if self._started else is_native_battle(self.ctx, image)
            )
            if not ready:
                if not self._waiting:
                    self.ctx.controller.pause_input()
                    self._waiting = True
                return False
            self.ctx.controller.resume_input()
            self.ctx.controller.begin_battle_input_scope(MacBattleHudGuard(self.ctx.auto_battle_context))
            self._scope = True
            self._activate(self._started)
            return True
        if self.ctx.controller.battle_input_blocked:
            if self._active:
                self.ctx.auto_battle_context.stop_auto_battle()
                self._active = False
            now = time.monotonic()
            if now < self._next_probe:
                return False
            self._next_probe = now + 0.25
            if not self.ctx.controller.refresh_battle_input_scope():
                return False
            self._activate(True)
        return self._active

    def pause(self) -> None:
        """暂停先停止策略并结束限制，让运行上下文能在菜单中恢复等待。"""
        with self._lock:
            self._release()

    def _release(self) -> None:
        """调用方持有会话锁，停止与状态更新不可交错。"""
        try:
            self.ctx.auto_battle_context.stop_auto_battle()
        finally:
            if self._scope:
                self.ctx.controller.end_battle_input_scope()
                self._scope = False
            else:
                self.ctx.controller.pause_input()
            self._active = False
            self._waiting = False
            self._next_probe = 0

    def close(self) -> None:
        """停止和异常清理可重复调用，不留下按住状态。"""
        with self._lock:
            if not self._closed:
                try:
                    self._release()
                finally:
                    self._closed = True
