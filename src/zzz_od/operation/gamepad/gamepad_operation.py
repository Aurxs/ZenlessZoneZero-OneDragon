"""手柄界面操作的公共等待，不改变底层输入与战斗策略时序。"""

from __future__ import annotations

import sys
import time
from typing import ClassVar

from zzz_od.operation.zzz_operation import ZOperation


class GamepadMenuDelayMixin:
    """每个界面步骤结束后至少等待用户配置的间隔。"""

    realtime_nodes: ClassVar[frozenset[str]] = frozenset()

    def _after_round_wait(
        self, wait: float | None = None, wait_round_time: float | None = None,
    ) -> None:
        """保留原来更长的动画等待，实时战斗节点沿用原时序。"""
        if sys.platform != 'darwin':
            return super()._after_round_wait(wait, wait_round_time)
        node = self._current_node
        if node is not None and node.cn in self.realtime_nodes:
            return super()._after_round_wait(wait, wait_round_time)
        interval = self.ctx.macos_config.menu_action_interval_ms / 1000
        requested = wait if wait is not None and wait > 0 else (
            max(0, wait_round_time - (time.time() - self.round_start_time))
            if wait_round_time is not None and wait_round_time > 0 else 0
        )
        super()._after_round_wait(max(interval, requested))


class GamepadOperation(GamepadMenuDelayMixin, ZOperation):
    """手柄界面操作沿用原 Operation，仅统一步骤后的等待。"""
