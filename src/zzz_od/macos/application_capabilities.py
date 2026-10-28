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
    'Mac 支持实战模拟室基础、晋升、音擎改装、技能材料，默认等级、默认保留已保存卡数或指定1至5张、当前编队或二十个预备编队；'
    '另支持区域巡防普通驱动盘副本（60电量）、专业挑战室材料（40电量，自动关闭燃竭）；支持恶名狩猎深度追猎（60电量，免费次数用尽后）；每场核对目标与实际消耗。区域巡防培养目标已验收；合成电池已接入，正向合成待票券验证；双倍配置已接入，有活动分支待验证。模拟室培养与自动补电暂未支持'
)
MACOS_APP_SUMMARY: str = (
    'Mac 已支持阿朔占卜、录像店、汀曼咖啡、体力计划、活跃度奖励、丽都周纪和丽都城募；'
    '恶名狩猎已支持库萨里库，迷失之地支持战线肃清悬赏任务，其他任务以卡片上的适配提示为准'
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
    'mouse_sensitivity_checker',
    'lost_void',
    'auto_battle',
    'dodge_assistant',
    'suibian_temple',
    'predefined_team_checker',
    'intel_board',
})


def get_macos_app_limits(app_id: str) -> str:
    """让每个任务显示自身范围，避免商店按钮误显示战斗限制。"""
    return {
        'intel_board': 'Mac 支持恶名狩猎和专业挑战室的零电量战斗代行，不接剧情；第一队叶瞬光完整周期1000及返回已验，其他队伍沿原成员核对与战斗策略',
        'auto_battle': 'Mac 原生手柄独立助手：沿原策略等待战斗，支持暂停、恢复、停止及释放；从大世界、手柄战斗或战况菜单启动',
        'dodge_assistant': 'Mac 原生手柄闪避助手：沿原策略等待战斗，支持暂停、恢复、停止及释放；不在菜单继续输出',
        'suibian_temple': 'Mac 支持已完成自动托管的领取与续开；进行中的托管保留至完成。手动游历、饮茶仙、制造、售卖及购买尚未适配，启用时会明确停止',
        'predefined_team_checker': 'Mac 与 Windows 一致：按游戏槽位自动同步识别到的队名和成员，保留原战斗策略；没有识别到成员的卡片跳过',
        'daily_signin': 'Mac 支持阿朔占卜；刮刮卡和吼吼饼铺尚未适配',
        'mouse_sensitivity_checker': 'Mac 在迷失之地入口层用唯一交互图标双向校准右摇杆，保存到当前账户；不修改 Windows 鼠标参数',
        'lost_void': 'Mac 战线肃清悬赏任务：活性维持或0至12、原预备编队、金币商店、实际8000进度和领奖；0活性、编队1整链及领奖已验收，其他活性待实测；其他模式及血量购买尚未适配',
        'notorious_hunt': 'Mac 支持自由选择原副本数据中的Boss及原难度、鸣徽、编队；库萨里库免费周期、双子和未知无报酬已实测，按实际次数与结果更新计划',
        'ridu_weekly': 'Mac 支持领取已完成九宫格积分与积分特赏，不代做周任务',
        charge_plan_const.APP_ID: MACOS_CHARGE_PLAN_LIMITS,
        random_play_const.APP_ID: 'Mac 支持澄辉坪营业点、随机或按原候选配置定位并确认宣传员、推荐上架；指定仪玄分支已验，其他人物待实测，营业中不更换',
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
