"""限制单场 Mac 自动战斗输入，战斗标识消失后要求业务显式恢复。"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from one_dragon.utils import cv2_utils

if TYPE_CHECKING:
    from cv2.typing import MatLike

    from one_dragon.base.controller.macos.sck_frame_converter import CapturedFrame
    from zzz_od.auto_battle.auto_battle_context import AutoBattleContext


class MacBattleHudGuard:
    """只接受普通攻击按钮或明确的连携角色头像，不接受结算画面。"""

    def __init__(self, battle: AutoBattleContext) -> None:
        """复用已经初始化的战斗区域与现有头像模板。"""
        self.battle: AutoBattleContext = battle

    def __call__(self, image: MatLike) -> bool:
        """判断当前帧是否允许战斗动作；未知画面直接拒绝。"""
        if image.shape != (1080, 1920, 3):
            return False
        if self.battle.is_normal_attack_btn_available(image):
            return True
        agents = self.battle.agent_context.get_possible_agent_list()
        if not agents:
            return False
        for area in (self.battle.area_chain_1, self.battle.area_chain_2):
            part = cv2_utils.crop_image_only(image, area.rect)
            if self.battle._match_chain_agent_in(part, agents) is not None:
                return True
        return False


class MacBattleInputScope:
    """对每个新采集帧只检查一次，首次不通过后保持阻断直到显式复核。"""

    def __init__(self, hud_check: Callable[[MatLike], bool]) -> None:
        """创建独立场次，不沿用上一场的帧或放行状态。"""
        self._hud_check: Callable[[MatLike], bool] = hud_check
        self._lock: threading.Lock = threading.Lock()
        self._last_sequence: int | None = None
        self._blocked: bool = False

    @property
    def blocked(self) -> bool:
        """返回本场是否已发现战斗标识消失。"""
        with self._lock:
            return self._blocked

    def allows(self, frame: CapturedFrame) -> bool:
        """校验最新帧；异常同样锁存阻断，不能继续重放动作。"""
        with self._lock:
            if self._blocked:
                return False
            if frame.sequence != self._last_sequence:
                self._blocked = True
                if self._hud_check(frame.image):
                    self._blocked = False
                self._last_sequence = frame.sequence
            return not self._blocked

    def refresh(self, frame: CapturedFrame) -> bool:
        """由已停止策略的业务流程复核过场后的 HUD，结算帧始终不放行。"""
        with self._lock:
            self._blocked = True
            if self._hud_check(frame.image):
                self._blocked = False
            self._last_sequence = frame.sequence
            return not self._blocked
