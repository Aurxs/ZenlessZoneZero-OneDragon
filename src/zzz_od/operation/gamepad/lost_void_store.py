"""手柄商店复用原商品解析和购买优先级，每笔输入核对实际余额变化。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.operation.operation_node import operation_node
from one_dragon.utils.log_utils import log
from zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_bangboo_store import (
    LostVoidBangbooStore,
)
from zzz_od.operation.gamepad.focus import has_filled_highlight
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation
from zzz_od.operation.gamepad.lost_void_common import GamepadLostVoidChooseCommon
from zzz_od.operation.gamepad.transport_by_compendium import (
    GamepadTransportByCompendium,
)

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_artifact_pos import (
        LostVoidArtifactPos,
    )
    from zzz_od.context.zzz_context import ZContext


class GamepadLostVoidStoreConfirm(GamepadOperation):
    """商店交易弹窗没有商品名，只按已发起的交易类型核对明确文案。"""

    def __init__(self, ctx: ZContext, action: str, accept: bool = True) -> None:
        if action not in ('购买', '刷新'):
            raise ValueError('未知商店交易类型')
        super().__init__(
            ctx, op_name=f'手柄迷失之地商店{action}确认', timeout_seconds=15
        )
        self.action: str = action
        self.accept: bool = accept
        self.navigation: GamepadTransportByCompendium = GamepadTransportByCompendium(
            ctx, '作战', '周期征讨'
        )
        self._sent: bool = False
        self._moved: bool = False

    def can_handle(self) -> bool:
        """只识别本类交易的明确正文，不根据背景商品或默认按钮猜测。"""
        if self.last_screenshot is None:
            return False
        self.navigation.last_screenshot = self.last_screenshot
        body = self.navigation._read_area('迷失之地-邦布商店', '手柄-购买正文')
        text = ''.join(body[1]).replace(' ', '') if body else ''
        return '是否确认购买此商品' in text if self.action == '购买' else '刷新' in text

    @operation_node(
        name='核对交易弹窗后确认', is_start_node=True, node_max_retry_times=8
    )
    def confirm(self) -> OperationRoundResult:
        if self.last_screenshot is None:
            return self.round_retry('等待商店确认截图', wait=1)
        nav = self.navigation
        nav.last_screenshot = self.last_screenshot
        known = self.can_handle()
        if self._sent:
            return (
                self.round_retry('等待商店确认弹窗关闭', wait=1)
                if known
                else self.round_success('商店确认弹窗已关闭')
            )
        confirm = nav._read_area('迷失之地-邦布商店', '按钮-购买-确认')
        prompt = nav._read_area('迷失之地-邦布商店', '手柄-商店确认提示')
        button = nav._text_rect(confirm[1], '确认') if confirm else None
        if not self.accept:
            choices = nav._read_area('迷失之地-邦布商店', '手柄-商店确认选项')
            cancel = nav._text_rect(choices[1], '取消') if choices else None
            accept = nav._text_rect(choices[1], '确认') if choices else None
            if (
                not known
                or not choices
                or cancel is None
                or accept is None
                or not prompt
                or not all(
                    nav._text_rect(prompt[1], word) is not None
                    for word in ('A', '选择')
                )
            ):
                return self.round_retry('等待完整购买取消条件', wait=1)
            if has_filled_highlight(choices[0], cancel, 'yellow'):
                self.save_screenshot(prefix='macos_lost_void_store_cancel')
                self.ctx.controller.btn_tap('south')
                self._sent = True
            elif not self._moved and has_filled_highlight(choices[0], accept, 'yellow'):
                self.ctx.controller.btn_tap('dpad_left')
                self._moved = True
            return self.round_retry('等待取消未核对的购买', wait=1)
        if (
            known
            and button
            and has_filled_highlight(confirm[0], button, 'yellow')
            and prompt
            and all(
                nav._text_rect(prompt[1], word) is not None for word in ('A', '选择')
            )
        ):
            self.save_screenshot(prefix='macos_lost_void_store_confirm')
            self.ctx.controller.btn_tap('south')
            self._sent = True
        return self.round_retry('等待明确商店交易确认', wait=1)


class GamepadLostVoidBangbooStore(GamepadOperation):
    """只有原策略放行且真实余额足够的商品才购买，不重放未响应的交易。"""

    def __init__(self, ctx: ZContext, refresh_times: int = 0) -> None:
        super().__init__(ctx, op_name='手柄迷失之地邦布商店', timeout_seconds=180)
        self.parser: LostVoidBangbooStore = LostVoidBangbooStore(ctx)
        self.parser.refresh_times = refresh_times
        self.navigation: GamepadTransportByCompendium = GamepadTransportByCompendium(
            ctx, '作战', '周期征讨'
        )
        self.common: GamepadLostVoidChooseCommon = GamepadLostVoidChooseCommon(ctx)
        self._pending: str | None = None
        self._target_name: str | None = None
        self._before_balance: int = 0
        self._cost: int = 0
        self._confirm_sent: bool = False
        self._pending_waits: int = 0
        self._leave_sent: bool = False
        self._last_unmatched_balance: int | None = None
        self._unplanned_cancel_count: int = 0
        self._empty_goods_frames: int = 0
        self._empty_goods_frame_time: float = -1

    def _balance(self) -> int | None:
        """余额栏只接受一个完整数字，不把刷新费用当成可用余额。"""
        area = self.navigation._read_area('迷失之地-邦布商店', '手柄-商店余额')
        values = (
            {
                int(text.strip())
                for text in area[1]
                if re.fullmatch(r'\d+', text.strip())
            }
            if area
            else set()
        )
        return next(iter(values)) if len(values) == 1 else None

    def _goods(self) -> tuple[list[LostVoidArtifactPos], list[LostVoidArtifactPos]]:
        """沿用原价格和名称解析，另读高亮按钮的黑字，防止漏掉当前商品。"""
        all_goods, _ = self.parser.get_artifact_pos(self.last_screenshot)
        prices = self.navigation._read_area('迷失之地-邦布商店', '区域-价格')
        price_area = self.ctx.screen_loader.get_area('迷失之地-邦布商店', '区域-价格')
        # 原白色过滤会丢失抗锯齿的末位零。价格必须来自未经颜色过滤的完整文字。
        for item in all_goods:
            item.store_price = None
        if prices and price_area:
            for text, matches in prices[1].items():
                price = self.parse_price(text)
                if price is None:
                    continue
                for match in matches:
                    rect = match.rect
                    rect.add_offset(price_area.left_top)
                    for item in all_goods:
                        item.add_price(price, rect)
        buttons = self.navigation._read_area('迷失之地-邦布商店', '区域-购买按钮')
        area = self.ctx.screen_loader.get_area('迷失之地-邦布商店', '区域-购买按钮')
        if buttons and area:
            for text, matches in buttons[1].items():
                if text.strip() != '购买':
                    continue
                for match in matches:
                    rect = match.rect
                    rect.add_offset(area.left_top)
                    for item in all_goods:
                        item.add_buy(rect)
        return sorted(all_goods, key=lambda item: item.rect.center.x), [
            item
            for item in all_goods
            if item.store_buy_rect is not None and item.store_price is not None
        ]

    def _currency_flags(self) -> tuple[bool, bool]:
        """刷新费用消失时识别商品金币及高亮背景，不用钱包图标代替支付方式。"""
        gold = self.round_by_find_area(self.last_screenshot, '迷失之地-邦布商店', '标识-金币').is_success
        blood = self.round_by_find_area(self.last_screenshot, '迷失之地-邦布商店', '标识-血量').is_success
        if not gold and not blood:
            gold = any(self.round_by_find_area(self.last_screenshot, '迷失之地-邦布商店', f'{prefix}-{idx}').is_success
                       for prefix in ('手柄-商品金币', '手柄-商品金币高亮') for idx in range(1, 5))
        return gold, blood

    @staticmethod
    def parse_price(text: str) -> int | None:
        """忽略乘号前的货币图标误读，数字不得截断或与另一组价格混合。"""
        match = re.fullmatch(r'[^0-9]*[×xX]\s*(\d+)\s*', text.strip())
        if match is not None:
            return int(match[1])
        return int(text.strip()) if re.fullmatch(r'\d+', text.strip()) else None

    def _leave(self) -> OperationRoundResult:
        """明确商店返回图标后退出一次，等待局内新帧。"""
        if not self._leave_sent:
            if not self.round_by_find_area(
                self.last_screenshot, '迷失之地-邦布商店', '按钮-返回'
            ).is_success:
                return self.round_retry('等待商店返回标识', wait=1)
            self.ctx.controller.btn_tap('east')
            self._leave_sent = True
        return self.round_retry('等待商店返回局内', wait=1)

    def _settle_pending(self, in_store: bool) -> OperationRoundResult:
        """弹窗确认只发一次；实际扣款与原费用完全一致才开始下一笔。"""
        balance = self._balance() if in_store else None
        if balance == self._before_balance - self._cost:
            if self._pending == '刷新':
                self.parser.refresh_times += 1
            else:
                self.ctx.lost_void.priority_updated = False
            self._pending = None
            self._confirm_sent = False
            self._pending_waits = 0
            return self.round_wait('商店实际扣款已核对', wait=0.6)
        if balance is not None and balance != self._before_balance:
            self._pending_waits += 1
            if balance == self._last_unmatched_balance or self._pending_waits >= 5:
                self.save_screenshot(prefix='macos_lost_void_store_balance_mismatch')
                return self.round_fail(
                    f'商店余额{self._before_balance}→{balance}与费用{self._cost}不一致，已停止'
                )
            self._last_unmatched_balance = balance
            return self.round_retry('等待商店余额数字动画稳定', wait=1)
        if not in_store and not self._confirm_sent:
            result = GamepadLostVoidStoreConfirm(self.ctx, self._pending).execute()
            if result.success:
                self._confirm_sent = True
                return self.round_retry('等待商店确认后的实际结果', wait=1)
            return self.round_by_op_result(result)
        self._pending_waits += 1
        if self._pending_waits >= 5:
            self.save_screenshot(prefix='macos_lost_void_store_pending')
            return self.round_fail('商店交易结果待确认，未重复输入')
        return self.round_retry('等待商店弹窗或实际扣款', wait=1)

    def _begin(
        self, action: str, balance: int, cost: int, name: str | None, key: str
    ) -> OperationRoundResult:
        """保存本次费用与目标后才发输入，不由按键次数推算余额。"""
        self._pending = action
        self._before_balance = balance
        self._cost = cost
        self._target_name = name
        self._confirm_sent = False
        self._pending_waits = 0
        self._last_unmatched_balance = None
        log.info('商店%s：目标=%s，实际余额=%d，费用=%d', action, name, balance, cost)
        self.save_screenshot(prefix='macos_lost_void_store_before_action')
        self.ctx.controller.btn_tap(key)
        return self.round_retry(f'等待商店{action}响应', wait=1)

    @operation_node(
        name='按原配置购买并核对', is_start_node=True, node_max_retry_times=120
    )
    def buy(self) -> OperationRoundResult:
        if self.last_screenshot is None:
            return self.round_retry('等待商店截图', wait=1)
        if self.ctx.lost_void.in_normal_world(self.last_screenshot):
            return (
                self.round_success('邦布商店已返回')
                if self._leave_sent
                else self.round_fail('商店交易未核对即离开')
            )
        self.navigation.last_screenshot = self.last_screenshot
        self.common.last_screenshot = self.last_screenshot
        in_store = (
            self.check_and_update_current_screen(
                self.last_screenshot, screen_name_list=['迷失之地-邦布商店']
            )
            is not None
        )
        if not in_store and self._pending is None:
            cancel = GamepadLostVoidStoreConfirm(self.ctx, '购买', accept=False)
            cancel.last_screenshot = self.last_screenshot
            if cancel.can_handle():
                if self._unplanned_cancel_count >= 2:
                    return self.round_fail('商店反复出现未核对的购买，已停止')
                result = cancel.execute()
                if result.success:
                    self._unplanned_cancel_count += 1
                    return self.round_wait('额外购买已取消，重新核对商店', wait=1)
                return self.round_by_op_result(result)
        if not in_store and self._pending and self.common.can_handle():
            result = GamepadLostVoidChooseCommon(self.ctx).execute()
            return (
                self.round_wait(result.status, wait=1)
                if result.success
                else self.round_by_op_result(result)
            )
        if self._pending:
            return self._settle_pending(in_store)
        if not in_store:
            return self.round_retry('等待明确邦布商店', wait=1)
        if self._leave_sent:
            return self._leave()
        config = self.ctx.lost_void.challenge_config
        gold, blood = self._currency_flags()
        if blood and not config.store_blood or gold and not config.store_gold:
            return self._leave()
        all_goods, goods = self._goods()
        if len(all_goods) < 4:
            self._empty_goods_frames = 0
            return self.round_retry('等待完整商店商品识别', wait=1)
        if all(item.store_buy_rect is None and item.store_price is None for item in all_goods):
            if self.last_screenshot_time > self._empty_goods_frame_time:
                self._empty_goods_frames += 1
                self._empty_goods_frame_time = self.last_screenshot_time
            if self._empty_goods_frames >= 2:
                self.save_screenshot(prefix='macos_lost_void_store_no_goods')
                return self._leave()
            return self.round_wait('复核本页已无可购买项', wait=0.6)
        self._empty_goods_frames = 0
        if not gold or blood:
            self.save_screenshot(prefix='macos_lost_void_store_currency_pending')
            return self.round_fail('商店货币或血量费用尚未确认，未购买')
        balance = self._balance()
        if balance is None:
            return self.round_retry('等待唯一商店余额', wait=1)
        if any(
            item.store_buy_rect is not None and item.store_price is None
            for item in all_goods
        ):
            return self.round_retry('等待可购买商品的完整价格', wait=1)
        available = [item for item in goods if item.store_price <= balance]
        if not available:
            return self._leave()
        self.parser._log_priority_rules(self.parser.refresh_times + 1)
        ordered = self.ctx.lost_void.get_artifact_by_priority(
            available,
            1,
            consider_priority_1=True,
            consider_priority_2=self.parser.refresh_times
            >= config.buy_only_priority_2 - 1,
            consider_not_in_priority=self.parser.refresh_times
            >= config.buy_only_priority_2 - 1,
            consider_priority_new=config.artifact_priority_new,
        )
        if not ordered:
            refresh = self.navigation._read_area('迷失之地-邦布商店', '手柄-商店刷新')
            text = ''.join(refresh[1]).upper().replace(' ', '') if refresh else ''
            costs = {int(value) for value in re.findall(r'[×X](\d+)', text)}
            if (
                len(costs) == 1
                and next(iter(costs)) <= balance
                and 'RS' in text
                and '刷新' in text
                and self.round_by_find_area(
                    self.last_screenshot,
                    '迷失之地-邦布商店',
                    '按钮-刷新-可用',
                ).is_success
            ):
                return self._begin(
                    '刷新', balance, next(iter(costs)), None, 'right_stick_click'
                )
            ordered = self.ctx.lost_void.get_artifact_by_priority(
                available, len(available)
            )
        if not ordered:
            return self._leave()
        target = ordered[0]
        focused = self.common._focused_candidates(all_goods)
        if len(focused) != 1:
            return self.round_retry('等待商店唯一高亮商品', wait=1)
        if focused[0].artifact.display_name != target.artifact.display_name:
            self.ctx.controller.btn_tap(
                'dpad_right'
                if target.rect.center.x > focused[0].rect.center.x
                else 'dpad_left'
            )
            return self.round_retry('等待原优先级商品进入焦点', wait=0.7)
        button_area = self.navigation._read_area('迷失之地-邦布商店', '区域-购买按钮')
        region = self.ctx.screen_loader.get_area('迷失之地-邦布商店', '区域-购买按钮')
        button = target.store_buy_rect
        local = Rect(
            button.x1 - region.rect.x1,
            button.y1 - region.rect.y1,
            button.x2 - region.rect.x1,
            button.y2 - region.rect.y1,
        )
        if (
            not button_area
            or self.navigation._text_rect(button_area[1], 'A') is None
            or not has_filled_highlight(button_area[0], local, 'yellow')
        ):
            return self.round_retry('等待商品的A购买提示与高亮按钮', wait=1)
        return self._begin(
            '购买', balance, target.store_price, target.artifact.name, 'south'
        )
