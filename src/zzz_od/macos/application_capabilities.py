"""统一说明 Mac 应用适配范围，保留原有任务与配置。"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from one_dragon.base.config.one_dragon_config import AfterDoneOpEnum, InstanceRun
from one_dragon.base.operation.application import application_const
from zzz_od.application.charge_plan import charge_plan_const
from zzz_od.application.city_fund import city_fund_const
from zzz_od.application.coffee import coffee_app_const
from zzz_od.application.engagement_reward import engagement_reward_const
from zzz_od.application.random_play import random_play_const

if TYPE_CHECKING:
    from zzz_od.context.zzz_context import ZContext


MACOS_CHARGE_PLAN_LIMITS: str = (
    'Mac 支持实战模拟室基础、晋升、音擎改装、技能材料，默认等级、默认五卡或1至5张卡片、当前编队或前六个预备编队；'
    '每场核对实际消耗20至100电量，不自动补电量'
)
MACOS_APP_SUMMARY: str = (
    'Mac 已支持阿朔占卜、录像店、汀曼咖啡、体力计划、活跃度奖励、丽都周纪和丽都城募；'
    '恶名狩猎已支持库萨里库，其他任务以卡片上的适配提示为准'
)
MACOS_SUPPORTED_APP_IDS: frozenset[str] = frozenset({
    application_const.ONE_DRAGON_APP_ID,
    charge_plan_const.APP_ID,
    random_play_const.APP_ID,
    coffee_app_const.APP_ID,
    city_fund_const.APP_ID,
    engagement_reward_const.APP_ID,
    'daily_signin',
    'ridu_weekly',
    'notorious_hunt',
})


def get_macos_app_limits(app_id: str) -> str:
    """让每个任务显示自身范围，避免商店按钮误显示战斗限制。"""
    return {
        'daily_signin': 'Mac 支持阿朔占卜；刮刮卡和吼吼饼铺尚未适配',
        'notorious_hunt': 'Mac 已验证库萨里库免费挑战、GUI 难度与编队、周期领奖；其他 Boss 和深度追猎尚未开放',
        'ridu_weekly': 'Mac 支持领取已完成九宫格积分与积分特赏，不代做周任务',
        charge_plan_const.APP_ID: MACOS_CHARGE_PLAN_LIMITS,
        random_play_const.APP_ID: 'Mac 支持澄辉坪营业点、随机或已选宣传员和推荐上架；指定人物移焦尚未支持',
        coffee_app_const.APP_ID: 'Mac 已验证澄辉坪汀曼特调与今日已喝；其他入口和额外咖啡尚未实测',
        engagement_reward_const.APP_ID: 'Mac 支持活跃度领奖、满档判断及已领取跳过',
        city_fund_const.APP_ID: 'Mac 支持现有成长任务与等级奖励领取，不购买等级或升级计划',
    }.get(app_id, MACOS_APP_SUMMARY)


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
