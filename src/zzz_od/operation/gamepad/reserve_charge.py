"""储蓄电量的额度与结果核对；不发送输入，也不解除未迁移界面的拦截。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar
from zoneinfo import ZoneInfo

from zzz_od.application.charge_plan.charge_plan_config import RestoreChargeEnum

if TYPE_CHECKING:
    from collections.abc import Sequence

    from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem


def _nonnegative(value: int, label: str) -> None:
    """未知读数不能按零处理，布尔值也不能作为OCR数量。"""
    if type(value) is not int or value < 0:
        raise ValueError(f'{label}必须为已核实的非负整数')


def remaining_plan_energy(plans: Sequence[ChargePlanItem]) -> int:
    """只计算明确卡数的模拟室和普通巡防；跳过标记不能抹掉剩余计划。"""
    total = 0
    for plan in plans:
        _nonnegative(plan.run_times, '已完成次数')
        _nonnegative(plan.plan_times, '计划次数')
        if plan.plan_times == 0 or plan.run_times > plan.plan_times:
            raise ValueError('计划次数无效，不能据此领取储蓄电量')
        if plan.category_name == '实战模拟室' and plan.card_num in ('1', '2', '3', '4', '5'):
            cost = int(plan.card_num) * 20
        elif plan.category_name == '区域巡防' and not plan.is_agent_plan:
            cost = 60
        else:
            raise ValueError('储蓄额度需要明确卡数的模拟室或普通区域巡防计划')
        total += (plan.plan_times - plan.run_times) * cost
    return total


@dataclass(frozen=True)
class ChargeResourceSnapshot:
    """确认前后须独立读回资源，不能把缺失的读数补零。"""

    energy: int
    reserve: int
    ether_batteries: int
    premium_currency: int

    def __post_init__(self) -> None:
        for label, value in (
            ('当前电量', self.energy), ('储蓄余额', self.reserve),
            ('以太电池', self.ether_batteries), ('付费货币', self.premium_currency),
        ):
            _nonnegative(value, label)


@dataclass(frozen=True)
class ReserveTransfer:
    """单次最小补充意图；结果不明时必须保留，不能重新领取。"""

    before: ChargeResourceSnapshot
    amount: int


class ReserveChargeBudget:
    """单次运行的储蓄额度；有效日使用北京时间日历日，不使用游戏刷新日。"""

    SOURCE: ClassVar[str] = '储蓄电量'

    def __init__(self, allowed_date: date, maximum_reserve: int, setting: str) -> None:
        if type(allowed_date) is not date:
            raise ValueError('必须指定允许使用储蓄的日历日')
        _nonnegative(maximum_reserve, '储蓄额度')
        if setting != RestoreChargeEnum.BACKUP_ONLY.value.value:
            raise ValueError('仅允许使用储蓄电量，不能使用电池、混合来源或付费货币')
        self.allowed_date: date = allowed_date
        self.maximum_reserve: int = maximum_reserve
        self.restored: int = 0
        self.pending: ReserveTransfer | None = None
        self._confirmation_issued: bool = False

    def _check_date(self, now: datetime) -> None:
        """每次准备和最终确认都检查期限，午夜不能沿用上一日授权。"""
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError('领取时间必须包含时区')
        if now.astimezone(ZoneInfo('Asia/Shanghai')).date() != self.allowed_date:
            raise ValueError('已超出允许使用储蓄电量的北京时间日期')

    def prepare(
        self, before: ChargeResourceSnapshot, required: int, remaining_energy: int,
        increment: int, maximum_exchange: int, now: datetime,
    ) -> ReserveTransfer | None:
        """只补下一场差额，按已读领取粒度向上取整，不能超剩余总差额。"""
        self._check_date(now)
        if self.pending is not None:
            raise ValueError('已有领取意图尚未核对，禁止再次领取')
        for label, value in (
            ('本场消耗', required), ('剩余计划电量', remaining_energy),
            ('领取粒度', increment), ('界面单次上限', maximum_exchange),
        ):
            _nonnegative(value, label)
        if required == 0 or increment == 0 or maximum_exchange == 0:
            raise ValueError('本场消耗、领取粒度和单次上限必须大于零')
        if remaining_energy < required:
            raise ValueError('剩余计划额度不足以覆盖本场，禁止补电')
        shortage = max(0, required - before.energy)
        if shortage == 0:
            return None
        amount = ((shortage + increment - 1) // increment) * increment
        limit = min(
            before.reserve, maximum_exchange, remaining_energy - before.energy,
            self.maximum_reserve - self.restored,
        )
        if amount > limit:
            # 不领取无助于完成下一场的部分电量，也不突破计划凑整。
            return None
        self.pending = ReserveTransfer(before, amount)
        self._confirmation_issued = False
        return self.pending

    def check_confirmation(
        self, source: str, amount: int, current: ChargeResourceSnapshot, now: datetime,
    ) -> None:
        """核对后仅发放一次确认机会，调用方须在输入前调用，结果不明不重发。"""
        self._check_date(now)
        _nonnegative(amount, '确认数量')
        if self._confirmation_issued:
            raise ValueError('已经允许过一次确认，结果核实前禁止重发')
        if (self.pending is None or source != self.SOURCE
                or amount != self.pending.amount or current != self.pending.before):
            raise ValueError('领取来源、数量或余额与已核实意图不一致，未允许确认')
        self._confirmation_issued = True

    def record_result(self, after: ChargeResourceSnapshot) -> int:
        """电量增量与储蓄扣减须完全对账，电池和付费货币须未变。"""
        if self.pending is None:
            raise ValueError('没有待核对的储蓄领取，禁止重复记账')
        if not self._confirmation_issued:
            raise ValueError('尚未核对确认条件，不能记为已领取')
        before, amount = self.pending.before, self.pending.amount
        if (after.energy != before.energy + amount or after.reserve != before.reserve - amount
                or after.ether_batteries != before.ether_batteries
                or after.premium_currency != before.premium_currency):
            # 未知结果保留pending，调用方只能复核，不能重发输入。
            raise ValueError('领取结果未能对账，保留待核对状态，禁止再次领取')
        self.restored += amount
        self.pending = None
        self._confirmation_issued = False
        return amount
