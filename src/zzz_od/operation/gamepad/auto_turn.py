"""Mac 周期转向只在镜头参数有效时启用，不改写保存的策略。"""

from __future__ import annotations

from math import isfinite
from typing import TYPE_CHECKING

from one_dragon.utils.log_utils import log

if TYPE_CHECKING:
    from zzz_od.context.zzz_context import ZContext


def get_auto_turn_interval(ctx: ZContext, configured_interval: float) -> float:
    """缺少镜头参数时关闭本次周期转向，普通战斗与自动锁定照常执行。"""
    if configured_interval <= 0:
        return configured_interval
    speed = ctx.macos_config.turn_distance_per_second
    if isfinite(speed) and speed > 0:
        return configured_interval
    log.info('Mac 镜头尚未校准，本次自动战斗关闭自动转向，攻击和自动锁定照常执行')
    return 0
