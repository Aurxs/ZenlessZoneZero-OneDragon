"""统一说明 Mac 应用适配范围，保留原有任务与配置。"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from one_dragon.base.config.one_dragon_config import AfterDoneOpEnum, InstanceRun
from one_dragon.base.operation.application import application_const
from zzz_od.application.charge_plan import charge_plan_const
from zzz_od.application.coffee import coffee_app_const
from zzz_od.application.random_play import random_play_const

if TYPE_CHECKING:
    from zzz_od.context.zzz_context import ZContext


MACOS_CHARGE_PLAN_LIMITS: str = (
    'Mac 目前仅支持基础材料调查专项、默认等级、默认或五张卡片、当前编队；'
    '每场实际消耗100电量，不自动补电量'
)
MACOS_SUPPORTED_APP_IDS: frozenset[str] = frozenset({
    application_const.ONE_DRAGON_APP_ID,
    charge_plan_const.APP_ID,
    random_play_const.APP_ID,
    coffee_app_const.APP_ID,
})


def get_macos_app_unavailable_reason(app_id: str) -> str | None:
    """只限制 Mac 运行，不更改应用注册、顺序与启用状态。"""
    if sys.platform != 'darwin' or app_id in MACOS_SUPPORTED_APP_IDS:
        return None
    return 'Mac暂未适配，此应用仍可查看和配置'


def get_macos_one_dragon_unavailable_reason(ctx: ZContext) -> str | None:
    """运行前检查当前实例与启用任务，不静默跳过用户配置。"""
    if sys.platform != 'darwin':
        return None
    config = ctx.one_dragon_config
    if config.instance_run == InstanceRun.ALL.value.value:
        instances = config.instance_list_in_od
        if len(instances) > 1 or (
            instances and instances[0].idx != ctx.current_instance_idx
        ):
            return 'Mac 多账号运行暂未适配，请将运行实例设为「仅运行当前」'
    if config.after_done != AfterDoneOpEnum.NONE.value.value:
        return 'Mac 的结束后操作暂未适配，请将「结束后」设为「无」'

    group = ctx.app_group_manager.get_one_dragon_group_config(ctx.current_instance_idx)
    unsupported = [
        item.app_name or item.app_id
        for item in group.app_list
        if item.enabled and get_macos_app_unavailable_reason(item.app_id) is not None
    ]
    if unsupported:
        return f'Mac暂未适配已启用的任务：{"、".join(unsupported)}。请关闭这些任务后再开始'
    return None
