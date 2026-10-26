"""读取模拟室双倍活动，生成仅本次运行使用的原格式计划。"""

from __future__ import annotations

import re
import uuid
from dataclasses import replace
from typing import TYPE_CHECKING

from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from zzz_od.operation.gamepad.agent_training import (
    GamepadCloseTrainingHandbook,
    GamepadOpenTrainingTarget,
)
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation

if TYPE_CHECKING:
    from one_dragon.base.matcher.match_result import MatchResultList
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem
    from zzz_od.context.zzz_context import ZContext


def read_double_reward_count(words: dict[str, MatchResultList]) -> int:
    """次数必须属于双倍提示同一行，不能误用资源栏或其他进度数字。"""
    labels = [(text, match) for text, matches in words.items()
              if '怪物卡' in text and '双倍' in text for match in matches]
    if not labels:
        if any('双倍' in text for text in words):
            raise ValueError('双倍提示格式尚未确认')
        return 0
    counts: set[int] = set()
    for label, anchor in labels:
        for text, matches in words.items():
            compact = text.replace(' ', '').replace('／', '/')
            count = re.search(r'(?<!\d)([0-5])/5(?!\d)', compact)
            if count is None:
                continue
            if text == label or any(abs(match.center.y - anchor.center.y) < 35
                                    and -30 < match.center.x - anchor.right_bottom.x < 350 for match in matches):
                counts.add(int(count[1]))
    if len(counts) != 1:
        raise ValueError('双倍剩余次数无法唯一确认')
    return counts.pop()


def make_double_reward_plan(source: ChargePlanItem, remaining: int, current_charge: int) -> ChargePlanItem | None:
    """沿用原双倍配置，按可用电量取最多五卡，临时ID与计数不写回配置。"""
    if not 0 <= remaining <= 5 or current_charge < 0:
        raise ValueError('双倍次数或当前电量无效')
    if source.category_name != '实战模拟室' or source.is_agent_plan:
        raise ValueError('双倍临时计划只支持普通模拟室材料')
    cards = min(remaining, current_charge // 20)
    if cards == 0:
        return None
    return replace(source, card_num=str(cards), run_times=0, plan_times=1,
                   skipped=False, plan_id=str(uuid.uuid4()))


class GamepadCheckDoubleReward(GamepadOperation):
    """读取活动后返回大世界，不编辑原计划、不消耗电量。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄检查模拟室双倍活动', timeout_seconds=80)
        self._remaining: int = 0
        self._charge: int | None = None
        self._absent_frames: int = 0

    def handle_init(self) -> None:
        self._remaining = 0
        self._charge = None
        self._absent_frames = 0

    @operation_node(name='打开双倍活动分类', is_start_node=True, screenshot_before_round=False)
    def open_category(self) -> OperationRoundResult:
        return self.round_by_op_result(GamepadOpenTrainingTarget(self.ctx, '实战模拟室').execute())

    @node_from(from_name='打开双倍活动分类')
    @operation_node(name='读取双倍剩余次数', node_max_retry_times=5)
    def inspect(self) -> OperationRoundResult:
        """要求分类列表加载完整；无活动需连续两帧确认。"""
        if self.last_screenshot is None:
            return self.round_retry('等待活动截图', wait=0.8)
        words = self.ctx.ocr.run_ocr(self.last_screenshot)
        compact = {text.replace(' ', '') for text in words}
        if not {'基础材料', '代理人晋升'} <= compact:
            return self.round_retry('等待模拟室列表加载', wait=0.8)
        try:
            self._remaining = read_double_reward_count(words)
        except ValueError as error:
            return self.round_retry(str(error), wait=0.8)
        if self._remaining == 0:
            self._absent_frames += 1
            if self._absent_frames < 2:
                return self.round_retry('复核无可用双倍次数', wait=0.8)
        else:
            charges = {int(match[1]) for text in compact if (match := re.fullmatch(r'(\d{1,4})/240', text))}
            if len(charges) != 1:
                return self.round_retry('未确认双倍卡数所需当前电量', wait=0.8)
            self._charge = charges.pop()
        self.save_screenshot(prefix='macos_double_reward_check')
        return self.round_success()

    @node_from(from_name='读取双倍剩余次数')
    @operation_node(name='退出活动手册', screenshot_before_round=False)
    def close(self) -> OperationRoundResult:
        result = GamepadCloseTrainingHandbook(self.ctx).execute()
        if not result.success:
            return self.round_by_op_result(result)
        return self.round_success('双倍活动检查完成', data={
            'remaining': self._remaining, 'current_charge': self._charge,
        })
