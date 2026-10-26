"""复用已有计划配置，串行运行 Mac 手柄体力副本。"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from zzz_od.application.charge_plan.charge_plan_config import (
    CardNumEnum,
    RestoreChargeEnum,
)
from zzz_od.operation.gamepad.agent_training import (
    GamepadCloseTrainingHandbook,
    GamepadResolveTrainingTarget,
    resolve_training_plan,
)
from zzz_od.operation.gamepad.area_patrol import (
    GamepadAreaPatrol,
    GamepadChargeBackToWorld,
)
from zzz_od.operation.gamepad.charge_transport import (
    GamepadChargeTransport,
    charge_mission_names,
)
from zzz_od.operation.gamepad.combat_simulation import GamepadCombatSimulation
from zzz_od.operation.gamepad.configure_cards import GamepadConfigureCards
from zzz_od.operation.gamepad.deep_hunt import GamepadDeepHunt, GamepadEnableDeepHunt
from zzz_od.operation.gamepad.double_reward import (
    GamepadCheckDoubleReward,
    make_double_reward_plan,
)
from zzz_od.operation.gamepad.ether_battery import GamepadSynthesizeEtherBattery
from zzz_od.operation.gamepad.expert_challenge import (
    GamepadDisableBurnout,
    GamepadExpertChallenge,
)
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation
from zzz_od.operation.gamepad.notorious_hunt import GamepadHuntBackToWorld
from zzz_od.operation.gamepad.simulation_preset import (
    SIMULATION_TYPES,
    simulation_targets,
)
from zzz_od.operation.gamepad.transport_by_compendium import (
    GamepadTransportByCompendium,
)

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.application.charge_plan.charge_plan_config import (
        ChargePlanConfig,
        ChargePlanItem,
    )
    from zzz_od.application.charge_plan.charge_plan_run_record import (
        ChargePlanRunRecord,
    )
    from zzz_od.context.zzz_context import ZContext


def validate_macos_charge_plan(config: ChargePlanConfig) -> str | None:
    """检查所有保存的计划，不把未支持的任务替换成调查专项。"""
    if config.restore_charge != RestoreChargeEnum.NONE.value.value:
        return 'Mac 体力计划尚不支持恢复电量，请将恢复电量设置为不使用'
    plans = list(config.plan_list)
    if config.double_reward:
        try:
            plans.append(make_double_reward_plan(config.combat_simulation_double_reward_config, 1, 20))
        except ValueError as error:
            return str(error)
    supported: dict[str, tuple[str | int, ...]] = {
        'tab_name': ('训练',),
        'category_name': ('实战模拟室', '区域巡防', '专业挑战室', '恶名狩猎'),
        'mission_type_name': SIMULATION_TYPES,
        'level': ('默认等级',),
        'card_num': (CardNumEnum.DEFAULT.value.value, '1', '2', '3', '4', '5'),
        'predefined_team_idx': tuple(range(-1, 20)),
    }
    labels: dict[str, str] = {
        'tab_name': '标签页',
        'category_name': '副本分类',
        'mission_type_name': '副本类型',
        'mission_name': '副本',
        'level': '等级',
        'card_num': '卡片数量',
        'predefined_team_idx': '预备编队',
    }
    for index, plan in enumerate(plans, start=1):
        if plan.category_name == '合成电池':
            if plan.tab_name != '训练' or plan.mission_type_name or plan.mission_name:
                return f'Mac体力计划第{index}项合成电池须为空副本目标'
            if plan.plan_times <= 0 or plan.run_times < 0:
                return f'Mac体力计划第{index}项合成次数无效'
            continue
        for field, values in supported.items():
            if plan.category_name in ('区域巡防', '专业挑战室', '恶名狩猎') and field in ('mission_type_name', 'card_num'):
                continue
            value = getattr(plan, field)
            if value not in values:
                return (
                    f'Mac 体力计划第 {index} 项的{labels[field]}“{value}”尚未支持；'
                    '目前仅支持训练/实战模拟室/基础/晋升/音擎改装/技能材料、默认等级、'
                    '默认保留已保存数量、1至5张卡片，或区域巡防/专业挑战室普通副本；当前编队或二十个预备编队'
                )
        if plan.category_name in ('区域巡防', '专业挑战室', '恶名狩猎') and not plan.is_agent_plan and plan.mission_type_name not in charge_mission_names(plan.category_name):
            return f'Mac 体力计划第 {index} 项的副本“{plan.category_name}/{plan.mission_type_name}”不在原数据中'
        if plan.category_name == '实战模拟室' and plan.mission_name not in simulation_targets().get(plan.mission_type_name, ()):
            return f'Mac 体力计划第 {index} 项的专项“{plan.mission_type_name}/{plan.mission_name}”不在原副本数据中'
        if plan.category_name == '恶名狩猎' and plan.notorious_hunt_buff_num not in (1, 2, 3):
            return f'Mac 体力计划第 {index} 项的鸣徽选项须为1至3'
        if plan.plan_times <= 0 or plan.run_times < 0:
            return f'Mac 体力计划第 {index} 项的计划次数必须大于零，已运行次数不能为负'
    return None


class GamepadChargePlan(GamepadOperation):
    """每场配置后核对实际所需电量，胜利次数沿用原配置保存。"""

    STATUS_FINISHED: ClassVar[str] = '体力计划结束'
    STATUS_TRY_NEXT_PLAN: ClassVar[str] = '继续后续可执行计划'
    STATUS_CHARGE_NOT_ENOUGH: ClassVar[str] = GamepadCombatSimulation.STATUS_CHARGE_NOT_ENOUGH

    def __init__(
        self,
        ctx: ZContext,
        config: ChargePlanConfig,
        run_record: ChargePlanRunRecord,
    ) -> None:
        """只接入当前应用使用的配置，不创建另一份 Mac 计划。"""
        super().__init__(ctx, op_name='Mac 手柄体力计划')
        self.config: ChargePlanConfig = config
        self.run_record: ChargePlanRunRecord = run_record
        self.current_plan: ChargePlanItem | None = None
        self.current_charge: int | None = None
        self.completed_battles: int = 0
        self._double_checked: bool = False
        self._temporary_plan: ChargePlanItem | None = None
        self._simulation: GamepadCombatSimulation | GamepadDeepHunt | None = None
        self._preset_back_sent: bool = False
        self._category_back_sent: bool = False

    def handle_init(self) -> None:
        """新一次运行清除临时状态，保留用户计划中的已运行次数。"""
        self.current_plan = None
        self.current_charge = None
        self.completed_battles = 0
        self._double_checked = False
        self._temporary_plan = None
        self._simulation = None
        self._preset_back_sent = False
        self._category_back_sent = False

    def _found(self, area_name: str) -> bool:
        """只读取实战模拟室锚点，不产生输入。"""
        screen_name = self.current_plan.category_name if self.current_plan is not None and self.current_plan.category_name in ('区域巡防', '专业挑战室', '恶名狩猎') and area_name in ('手柄-挑战等级', '手柄-下一步') else '实战模拟室'
        return self.last_screenshot is not None and self.round_by_find_area(
            self.last_screenshot, screen_name, area_name
        ).is_success

    def _summary(self, reason: str) -> OperationRoundResult:
        """区分运行结束与计划完成，电量不足不补写成功次数。"""
        return self.round_success(
            f'{reason}，本次完成 {self.completed_battles} 场',
            data={
                'completed_battles': self.completed_battles,
                'plans_finished': self.config.all_plan_finished(),
                'remaining_charge': self.current_charge,
            },
        )

    @node_from(from_name='执行电池合成')
    @node_from(from_name='检查双倍活动')
    @node_from(from_name='跳过本轮培养目标')
    @node_from(from_name='跳过未开放深度追猎')
    @node_from(from_name='执行单次挑战')
    @node_from(from_name='电量不足返回大世界', status=STATUS_TRY_NEXT_PLAN)
    @operation_node(name='选择原体力计划', is_start_node=True, screenshot_before_round=False)
    def select_plan(self) -> OperationRoundResult:
        """沿用原计划顺序和循环扣减，不为凑电量改任务。"""
        reason = validate_macos_charge_plan(self.config)
        if reason is not None:
            return self.round_fail(reason)
        if self.config.double_reward and not self._double_checked:
            return self.round_success('检查双倍活动')
        if self._temporary_plan is not None and not self._temporary_plan.skipped and self._temporary_plan.run_times < self._temporary_plan.plan_times:
            self.current_plan = self._temporary_plan
        else:
            self._temporary_plan = None
            if not self.config.plan_list:
                return self.round_success(self.STATUS_FINISHED)
            if self.config.all_plan_finished():
                if not self.config.loop:
                    return self.round_success(self.STATUS_FINISHED)
                self.config.reset_plans()
            self.current_plan = self.config.get_next_plan()
            if self.current_plan is None:
                return self.round_success(self.STATUS_FINISHED)
        self._preset_back_sent = False
        self._category_back_sent = False
        self._simulation = None
        if self.current_plan.category_name == '合成电池':
            return self.round_success('合成电池')
        if self.current_plan.is_agent_plan:
            return self.round_success('解析培养目标')
        self._create_simulation(self.current_plan)
        return self.round_success()

    @node_from(from_name='选择原体力计划', status='合成电池')
    @operation_node(name='执行电池合成', screenshot_before_round=False, timeout_seconds=180)
    def synthesize_battery(self) -> OperationRoundResult:
        """每次仅合成一枚，素材不足跳过原计划，未知失败停止。"""
        if self.current_plan is None or self.current_plan.category_name != '合成电池':
            return self.round_fail('尚未选择合成电池计划')
        previous_runs = self.current_plan.run_times
        self.current_charge = None
        self.run_record.charge_power_snapshot = [0, -1]
        result = GamepadSynthesizeEtherBattery(self.ctx, self.current_plan, self.config).execute()
        if not result.success:
            return self.round_by_op_result(result)
        if result.status == '合成素材不足':
            self.current_plan.skipped = True
            return self.round_success('合成素材不足，本轮跳过')
        if self.current_plan.run_times != previous_runs + 1:
            return self.round_fail('合成结果未确认新增一次，停止计划')
        return self.round_success('单枚电池已获得并返回')

    @node_from(from_name='选择原体力计划', status='检查双倍活动')
    @operation_node(name='检查双倍活动', screenshot_before_round=False)
    def check_double_reward(self) -> OperationRoundResult:
        """每次应用运行检查一次，临时任务只驻留内存，不插入用户计划列表。"""
        result = GamepadCheckDoubleReward(self.ctx).execute()
        if not result.success:
            return self.round_by_op_result(result)
        self._temporary_plan = None if result.data['remaining'] == 0 else make_double_reward_plan(
            self.config.combat_simulation_double_reward_config,
            result.data['remaining'], result.data['current_charge'],
        )
        self._double_checked = True
        return self.round_success('双倍活动已检查')

    def _create_simulation(self, plan: ChargePlanItem) -> None:
        """本场可以使用解析后的具体副本，配置中仍保留原培养计划。"""
        operation_class = {'区域巡防': GamepadAreaPatrol, '专业挑战室': GamepadExpertChallenge, '恶名狩猎': GamepadDeepHunt}.get(plan.category_name, GamepadCombatSimulation)
        self._simulation = operation_class(self.ctx, plan, config=self.config)

    @node_from(from_name='选择原体力计划', status='解析培养目标')
    @operation_node(name='解析本场培养目标', screenshot_before_round=False)
    def resolve_training(self) -> OperationRoundResult:
        """每场重新读取游戏标记，目标变化不会改写用户计划或累加次数。"""
        if self.current_plan is None or not self.current_plan.is_agent_plan:
            return self.round_fail('尚未选择培养计划')
        result = GamepadResolveTrainingTarget(self.ctx, self.current_plan.category_name).execute()
        if not result.success:
            return self.round_by_op_result(result)
        if result.status == GamepadResolveTrainingTarget.STATUS_NO_TARGET:
            return self.round_success(GamepadResolveTrainingTarget.STATUS_NO_TARGET)
        plan = resolve_training_plan(self.current_plan, result.data['target'])
        self._create_simulation(plan)
        return self.round_success('培养目标已落实到本场')

    @node_from(from_name='解析本场培养目标', status=GamepadResolveTrainingTarget.STATUS_NO_TARGET)
    @operation_node(name='跳过本轮培养目标', screenshot_before_round=False)
    def skip_training(self) -> OperationRoundResult:
        """未找到标记只跳过本轮，退出成功后再推进下一项，不伪造达成次数。"""
        if self.current_plan is None:
            return self.round_fail('尚未选择培养计划')
        result = GamepadCloseTrainingHandbook(self.ctx).execute()
        if not result.success:
            return self.round_by_op_result(result)
        self.current_plan.skipped = True
        return self.round_success('培养目标本轮跳过')

    @node_from(from_name='解析本场培养目标')
    @node_from(from_name='选择原体力计划')
    @operation_node(name='手柄传送至模拟室')
    def transport(self) -> OperationRoundResult:
        """共用已验证的基础材料入口，随后按计划切换实际分类和专项。"""
        if self.current_plan is None:
            return self.round_fail('尚未选择体力计划')
        if self.current_plan.category_name in ('区域巡防', '专业挑战室', '恶名狩猎'):
            if self._simulation is None:
                return self.round_fail('尚未解析本场副本')
            return self.round_by_op_result(GamepadChargeTransport(self.ctx, self.current_plan.category_name, self._simulation.plan.mission_type_name).execute())
        if self._found('手柄-挑战等级') and self._found('手柄-下一步'):
            return self.round_success('已在模拟室预设，继续核对卡片与电量')
        op = GamepadTransportByCompendium(
            self.ctx, self.current_plan.tab_name,
            self.current_plan.category_name, '基础材料',
        )
        return self.round_by_op_result(op.execute())

    @node_from(from_name='手柄传送至模拟室')
    @operation_node(name='配置本次卡片数量', screenshot_before_round=False)
    def configure_cards(self) -> OperationRoundResult:
        """先把计划数量落实到预设，不将旧预设消耗用于判断本次是否足够。"""
        if self._simulation is None or self.current_plan is None:
            return self.round_fail('尚未创建单次挑战')
        if self.current_plan.category_name == '恶名狩猎':
            return self.round_by_op_result(GamepadEnableDeepHunt(self.ctx, self._simulation.plan.mission_type_name).execute())
        if self.current_plan.category_name == '专业挑战室':
            return self.round_by_op_result(GamepadDisableBurnout(self.ctx, self._simulation.plan.mission_type_name).execute())
        if self.current_plan.category_name == '区域巡防':
            return self.round_success('当前副本无需编辑卡片')
        return self.round_by_op_result(
            GamepadConfigureCards(self.ctx, self._simulation.expected_card_count, self.current_plan.mission_name, self.current_plan.mission_type_name).execute()
        )

    @node_from(from_name='配置本次卡片数量')
    @operation_node(name='核对单次实际电量', node_max_retry_times=12, timeout_seconds=30)
    def check_charge(self) -> OperationRoundResult:
        """只读已确认预设页，不能把默认数量预估二十当作实际消耗。"""
        if self._simulation is None:
            return self.round_fail('尚未创建单次挑战')
        if not (self._found('手柄-挑战等级') and self._found('手柄-下一步')):
            return self.round_retry('等待已建档的模拟室预设页', wait=1)
        self._simulation.last_screenshot = self.last_screenshot
        if not self._simulation._preset_selected():
            return self.round_fail('当前材料专项与计划不一致，未允许出战')
        charge = self._simulation.read_charge()
        if charge is None:
            return self.round_retry('未能确认实际电量消耗', wait=1)
        current, required = charge
        if self._simulation.expected_charge is None and not self._simulation.bind_prepared_charge(required):
            return self.round_fail('默认数量的实际卡片消耗无效')
        if required != self._simulation.expected_charge:
            return self.round_fail(
                f'当前预设消耗 {required} 电量，与目标 {self._simulation.expected_charge} 不一致'
            )
        self.current_charge = current
        self.run_record.record_current_charge_power(current)
        if current < required:
            return self.round_success(self.STATUS_CHARGE_NOT_ENOUGH)
        return self.round_success()

    @node_from(from_name='核对单次实际电量')
    @operation_node(name='执行单次挑战')
    def run_battle(self) -> OperationRoundResult:
        """胜利次数由单次操作保存；失败不重复挑战或增加次数。"""
        if self._simulation is None or self.current_plan is None:
            return self.round_fail('尚未创建单次挑战')
        previous_runs = self.current_plan.run_times
        # 挑战途中可能已经扣电，失败退出也不能继续展示出战前读数。
        self.current_charge = None
        self.run_record.charge_power_snapshot = [0, -1]
        result = self._simulation.execute()
        if not result.success:
            return self.round_by_op_result(result)
        if self.current_plan.run_times != previous_runs + 1:
            return self.round_fail('单次挑战未确认新增一次胜利，已停止体力计划')
        self.completed_battles += 1
        return self.round_success()

    @node_from(from_name='核对单次实际电量', status=STATUS_CHARGE_NOT_ENOUGH)
    @node_from(from_name='执行单次挑战', success=False, status=STATUS_CHARGE_NOT_ENOUGH)
    @operation_node(name='电量不足返回大世界', node_max_retry_times=15, timeout_seconds=90)
    def return_after_shortage(self) -> OperationRoundResult:
        """电量不足时保留次数，按原跳过配置尝试后续计划，不自动补电。"""
        if self.last_screenshot is None:
            return self.round_retry('截图无效', wait=1)
        if self.round_by_find_area(
            self.last_screenshot, '大世界-普通', '快捷手册'
        ).is_success:
            if self.config.skip_plan and self.current_plan is not None and self.current_charge is not None:
                following = self.config.get_next_plan(self.current_plan)
                while following is not None:
                    required = {'区域巡防': 60, '专业挑战室': 40, '恶名狩猎': 60}.get(following.category_name)
                    if required is None:
                        required = following.estimated_charge_power
                    if self.current_charge >= required:
                        self.current_plan.skipped = True
                        return self.round_success(self.STATUS_TRY_NEXT_PLAN)
                    following.skipped = True
                    following = self.config.get_next_plan(following)
            return self._summary('电量不足，未完成计划保留')
        if self.current_plan is not None and self.current_plan.category_name in ('区域巡防', '专业挑战室', '恶名狩猎'):
            result = (GamepadHuntBackToWorld(self.ctx) if self.current_plan.category_name == '恶名狩猎' else GamepadChargeBackToWorld(self.ctx, self.current_plan.category_name)).execute()
            if not result.success:
                return self.round_by_op_result(result)
            return self.round_retry('已返回大世界，检查后续计划', wait=0.5)
        if self._found('手柄-挑战等级') and self._found('手柄-下一步'):
            if not self._preset_back_sent:
                self.ctx.controller.btn_tap('east')
                self._preset_back_sent = True
            return self.round_retry('等待材料分类页', wait=1)
        if self._found('手柄-基础材料分类') and self._found('手柄-代理人晋升分类'):
            if not self._category_back_sent:
                self.ctx.controller.btn_tap('east')
                self._category_back_sent = True
            return self.round_retry('等待大世界', wait=1)
        return self.round_retry('电量不足，等待已建档的返回画面', wait=1)

    @node_from(from_name='配置本次卡片数量', success=False, status='周期挑战有剩余次数，本次跳过深度追猎')
    @operation_node(name='跳过未开放深度追猎', screenshot_before_round=False, timeout_seconds=40)
    def skip_locked_deep_hunt(self) -> OperationRoundResult:
        """沿用原语义：免费机会尚未用尽时跳过体力目标，不代打周常。"""
        result = GamepadHuntBackToWorld(self.ctx).execute()
        if not result.success:
            return self.round_by_op_result(result)
        if self.current_plan is not None:
            self.current_plan.skipped = True
        return self.round_success()

    @node_from(from_name='选择原体力计划', status=STATUS_FINISHED)
    @operation_node(name='报告体力计划结果', screenshot_before_round=False)
    def finish(self) -> OperationRoundResult:
        """没有可执行计划时直接报告，不额外打开游戏页面。"""
        reason = (
            '体力计划已完成'
            if self.config.plan_list and self.config.all_plan_finished()
            else '没有可运行的计划'
        )
        return self._summary(reason)
