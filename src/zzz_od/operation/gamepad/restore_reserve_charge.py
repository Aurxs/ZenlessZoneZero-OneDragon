"""原体力计划的最小储蓄补充；确认前落盘，结果不明不重领。"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from one_dragon.utils import os_utils
from zzz_od.operation.gamepad.area_patrol import GamepadChargeBackToWorld
from zzz_od.operation.gamepad.configure_cards import GamepadConfigureCards
from zzz_od.operation.gamepad.reserve_charge import (
    ChargeResourceSnapshot,
    ReserveChargeBudget,
    remaining_plan_energy,
)
from zzz_od.operation.gamepad.rewards import _GamepadRewardOperation
from zzz_od.operation.gamepad.simulation_preset import read_preset_charge
from zzz_od.operation.gamepad.transport import find_yellow_focus_frames
from zzz_od.operation.gamepad.transport_by_compendium import (
    GamepadTransportByCompendium,
)

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.application.charge_plan.charge_plan_config import (
        ChargePlanConfig,
        ChargePlanItem,
    )
    from zzz_od.context.zzz_context import ZContext


def reserve_budget(config: ChargePlanConfig) -> ReserveChargeBudget:
    """显式日历日和正额度缺一不可，默认仍不支持自动补电。"""
    allowed = date.fromisoformat(config.get('macos_reserve_date', ''))
    maximum = config.get('macos_reserve_limit', 0)
    if type(maximum) is not int or not 0 < maximum <= 320:
        raise ValueError('Mac储蓄恢复需要1至320的单日明确额度')
    budget = ReserveChargeBudget(allowed, maximum, config.restore_charge)
    budget._check_date(datetime.now(ZoneInfo('Asia/Shanghai')))
    if config.loop or config.double_reward:
        raise ValueError('储蓄恢复不支持循环或双倍计划')
    remaining_plan_energy(config.plan_list)
    if any(
        p.run_times < p.plan_times and p.category_name != '区域巡防'
        for p in config.plan_list
    ):
        raise ValueError('当前储蓄路径仅支持已完成五卡后的普通巡防余项')
    verification_plan(config)
    return budget


def verification_plan(config: ChargePlanConfig) -> ChargePlanItem:
    """只复用已完成的五卡基础材料预设做只读核账，不增加挑战次数。"""
    for plan in config.plan_list:
        if (
            plan.category_name == '实战模拟室'
            and plan.mission_type_name == '基础材料'
            and plan.card_num == '5'
            and plan.run_times == plan.plan_times
        ):
            return plan
    raise ValueError('储蓄恢复需已有已完成五卡基础材料预设用于只读核账')


class GamepadRestoreReserveCharge(_GamepadRewardOperation):
    """巡防不足时最小补到六十，再用已完成百电预设打开余额页核账。"""

    def __init__(self, ctx: ZContext, config: ChargePlanConfig) -> None:
        super().__init__(ctx, '手柄最小储蓄补电', timeout_seconds=240)
        self.config: ChargePlanConfig = config
        self.budget: ReserveChargeBudget = reserve_budget(config)
        self.journal: Path = (
            Path(os_utils.get_work_dir())
            / '.debug'
            / 'macos'
            / f'reserve_{ctx.current_instance_idx}_{self.budget.allowed_date.isoformat()}.json'
        )
        self._opened: bool = False
        self._source_sent: bool = False
        self._confirm_sent: bool = False
        self._reward_sent: bool = False
        self._initial_energy: int | None = None
        self._after_energy: int | None = None
        self._regen_deadline: float = 0
        self._before: ChargeResourceSnapshot | None = None
        self._after: ChargeResourceSnapshot | None = None
        self._amount: int = 0

    def _area(self, name: str) -> tuple | None:
        return self._read_area('恢复电量', name)

    def _texts(self, name: str) -> set[str]:
        area = self._area(name)
        return (
            {unicodedata.normalize('NFKC', text).replace(' ', '') for text in area[1]}
            if area
            else set()
        )

    def _main(self) -> bool:
        return '恢复电量' in self._texts('手柄-恢复标题')

    def _snapshot(self, energy: int) -> ChargeResourceSnapshot | None:
        """来源名、独立余额和唯一储蓄焦点必须同时成立。"""
        area = self._area('手柄-恢复来源')
        if area is None:
            return None
        image, words = area
        names = ('储蓄电量', '以太电池', '菲林')
        positions: dict[str, float] = {}
        numbers: list[tuple[float, int]] = []
        for text, matches in words.items():
            text = unicodedata.normalize('NFKC', text).replace(' ', '')
            if matches.max is None:
                continue
            if text in names:
                positions[text] = matches.max.center.x
            elif text.isdecimal():
                numbers.append((matches.max.center.x, int(text)))
        if set(positions) != set(names) or len(numbers) != 3:
            return None
        frames = find_yellow_focus_frames(image, 90, 160, 90, 160)
        if len(frames) != 1 or abs(frames[0].center.x - positions[names[0]]) > 35:
            return None
        values = []
        for name in names:
            nearby = [value for x, value in numbers if abs(x - positions[name]) < 35]
            if len(nearby) != 1:
                return None
            values.append(nearby[0])
        return ChargeResourceSnapshot(energy, *values)

    def _save_journal(self, state: str) -> None:
        """先保存意图再发确认；未核账回执阻止新进程重新领取。"""
        data = {
            'state': state,
            'time': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
            'before': asdict(self._before) if self._before else None,
            'after': asdict(self._after) if self._after else None,
            'amount': self._amount,
            'restored_total': self.budget.restored,
            'evidence_paths': self.evidence_paths,
        }
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.journal.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        temporary.replace(self.journal)

    @operation_node(name='打开不足电量来源', is_start_node=True, node_max_retry_times=8)
    def open_source(self) -> OperationRoundResult:
        """仅从已核对的六十电巡防详情进入；已有未核账记录不操作。"""
        if self.journal.exists() and not self._opened:
            saved = json.loads(self.journal.read_text())
            if saved.get('state') != 'verified':
                return self.round_fail(f'已有储蓄领取待核账，禁止重领：{self.journal}')
            self.budget.restored = saved['restored_total']
        if self._main() and self._opened:
            return self.round_success()
        if self._opened:
            return self.round_retry('等待储蓄来源页', wait=0.8)
        charge = read_preset_charge(self.ctx, self.last_screenshot)
        if charge is None or charge[1] != 60 or charge[0] >= 60:
            return self.round_fail('未确认六十电巡防不足，未打开补电')
        self._initial_energy = charge[0]
        self._save_evidence('reserve_preset_before')
        self.ctx.controller.btn_tap('start')
        self._opened = True
        return self.round_retry('等待储蓄来源页', wait=0.8)

    @node_from(from_name='打开不足电量来源')
    @operation_node(name='核对储蓄来源', node_max_retry_times=6)
    def choose_source(self) -> OperationRoundResult:
        if self._source_sent:
            return self.round_success()
        if not self._main() or self._initial_energy is None:
            return self.round_fail('储蓄来源页不明确')
        self._before = self._snapshot(self._initial_energy)
        if self._before is None or '取出等量储备电量' not in self._texts(
            '手柄-恢复说明'
        ):
            return self.round_retry('等待来源名称、焦点和三项余额', wait=0.8)
        # 当前实拍为一点粒度、上限240；最终数量页仍独立核对。
        transfer = self.budget.prepare(
            self._before,
            60,
            remaining_plan_energy(self.config.plan_list),
            1,
            240,
            datetime.now(ZoneInfo('Asia/Shanghai')),
        )
        if transfer is None:
            return self.round_fail('储蓄余额或授权额度不足，未领取')
        timers = [
            re.search(r'电量恢复(\d+)分(\d+)秒', text)
            for text in self._texts('手柄-恢复倒计时')
        ]
        seconds = [int(m[1]) * 60 + int(m[2]) for m in timers if m]
        if len(seconds) != 1 or seconds[0] <= 20:
            return self.round_fail('自然恢复时刻接近或倒计时不明，未领取储蓄')
        self._regen_deadline = time.monotonic() + seconds[0]
        self._amount = transfer.amount
        self._save_evidence('reserve_source_before')
        self.ctx.controller.btn_tap('south')
        self._source_sent = True
        return self.round_success(wait=0.8)

    @node_from(from_name='核对储蓄来源')
    @operation_node(name='确认最小兑换量', node_max_retry_times=8)
    def confirm_quantity(self) -> OperationRoundResult:
        if self._confirm_sent:
            return self.round_success()
        source = self._texts('手柄-快捷来源')
        quantities = self._texts('手柄-兑换数值')
        if (
            '快捷使用' not in self._texts('手柄-快捷标题')
            or self._before is None
            or not any(
                re.fullmatch(rf'储蓄电量[×xX]{self._before.reserve}', text)
                for text in source
            )
            or quantities != {str(self._amount)}
        ):
            return self.round_retry('等待准确储蓄来源和最小差额，未确认', wait=0.8)
        limits = self._texts('手柄-兑换最小') | self._texts('手柄-兑换最大')
        if limits != {'1', '240'} or not any(
            '确认' in text for text in self._texts('手柄-兑换确认')
        ):
            return self.round_fail('兑换范围或确认按钮不明确')
        if time.monotonic() + 10 >= self._regen_deadline:
            return self.round_fail('自然恢复即将改变差额，未确认储蓄')
        self.budget.check_confirmation(
            '储蓄电量',
            self._amount,
            self._before,
            datetime.now(ZoneInfo('Asia/Shanghai')),
        )
        if not self._save_evidence('reserve_quantity_before_confirm'):
            return self.round_fail('补电确认前截图保存失败，未使用资源')
        self._save_journal('confirmation_issued')
        self._confirm_sent = True
        self.ctx.controller.btn_tap('south')
        return self.round_success(wait=1)

    @node_from(from_name='确认最小兑换量')
    @operation_node(name='确认储蓄获得', node_max_retry_times=10)
    def confirm_obtained(self) -> OperationRoundResult:
        if self._known_reward_visible():
            self._save_evidence('reserve_obtained')
            if not self._reward_sent:
                self.ctx.controller.btn_tap('south')
                self._reward_sent = True
            return self.round_retry('等待电量获得后返回巡防', wait=0.8)
        charge = read_preset_charge(self.ctx, self.last_screenshot)
        if self._reward_sent and charge is not None and charge[1] == 60:
            if self._before is None or charge[0] != self._before.energy + self._amount:
                return self.round_fail('补电增量不明确，保留待核账，不再次领取')
            self._after_energy = charge[0]
            self._save_evidence('reserve_preset_after')
            return self.round_success()
        return self.round_retry('等待本次储蓄获得及返回证据，未重发确认', wait=0.8)

    @node_from(from_name='确认储蓄获得')
    @operation_node(
        name='进入只读余额核账', screenshot_before_round=False, timeout_seconds=120
    )
    def open_verification(self) -> OperationRoundResult:
        """六十电已足够不能再开不足页；复用已完成百电预设，只看余额不出战。"""
        target = verification_plan(self.config)
        operations = (
            GamepadChargeBackToWorld(self.ctx, '区域巡防'),
            GamepadTransportByCompendium(self.ctx, '训练', '实战模拟室', '基础材料'),
            GamepadConfigureCards(self.ctx, 5, target.mission_name, '基础材料'),
        )
        for op in operations:
            result = op.execute()
            if not result.success:
                return self.round_by_op_result(result)
        _, self.last_screenshot = self.ctx.controller.screenshot()
        charge = read_preset_charge(self.ctx, self.last_screenshot)
        if (
            charge is None
            or self._after_energy is None
            or charge[1] != 100
            or not self._after_energy <= charge[0] <= self._after_energy + 1
            or charge[0] >= 100
        ):
            return self.round_fail('核账预设或电量变化，保留待核账，未出战')
        self.ctx.controller.btn_tap('start')
        return self.round_success(wait=0.8)

    @node_from(from_name='进入只读余额核账')
    @operation_node(name='核对储蓄扣减', node_max_retry_times=8)
    def verify_resources(self) -> OperationRoundResult:
        if not self._main() or self._after_energy is None:
            return self.round_retry('等待只读余额页', wait=0.8)
        self._after = self._snapshot(self._after_energy)
        if self._after is None:
            return self.round_retry('等待独立储蓄、电池及菲林余额', wait=0.8)
        try:
            self.budget.record_result(self._after)
        except ValueError as error:
            return self.round_fail(str(error))
        self._save_evidence('reserve_balances_after')
        self._save_journal('verified')
        self.ctx.controller.btn_tap('east')
        return self.round_success(wait=0.8)

    @node_from(from_name='核对储蓄扣减')
    @operation_node(
        name='核账后返回', screenshot_before_round=False, timeout_seconds=90
    )
    def back(self) -> OperationRoundResult:
        result = GamepadChargeBackToWorld(self.ctx, '实战模拟室').execute()
        if not result.success:
            return self.round_by_op_result(result)
        return self.round_success(
            '储蓄恢复已对账',
            data={
                'amount': self._amount,
                'before': asdict(self._before),
                'after': asdict(self._after),
                'journal': str(self.journal),
            },
        )
