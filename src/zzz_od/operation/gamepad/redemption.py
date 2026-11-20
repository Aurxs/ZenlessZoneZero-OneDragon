"""Mac 手柄兑换入口；焦点不能确认时不继续按键。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, ClassVar

from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from one_dragon.base.operation.operation_round_result import (
    OperationRoundResult,
    OperationRoundResultEnum,
)
from zzz_od.macos.redemption_catalog import normalize_code
from zzz_od.macos.redemption_pasteboard import temporary_redemption_pasteboard
from zzz_od.operation.gamepad.focus import has_filled_highlight
from zzz_od.operation.gamepad.rewards import _GamepadRewardOperation
from zzz_od.operation.gamepad.rewards_city_fund import GamepadCityFund
from zzz_od.operation.gamepad.transport import find_yellow_focus_frames

if TYPE_CHECKING:
    from zzz_od.application.redemption_code.redemption_code_run_record import (
        RedemptionCodeRunRecord,
    )
    from zzz_od.context.zzz_context import ZContext


class GamepadOpenRedemption(_GamepadRewardOperation):
    """仅通过大世界、主菜单及更多功能的已知焦点进入兑换页。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄打开兑换码', timeout_seconds=76)
        self._opened_menu: bool = False
        self._opened_more: bool = False
        self._opened_dialog: bool = False

    def handle_init(self) -> None:
        self.evidence_paths.clear()
        self._opened_menu = False
        self._opened_more = False
        self._opened_dialog = False

    def _exact_text(self, screen: str, area: str, value: str) -> bool:
        found = self._read_area(screen, area)
        return found is not None and any(''.join(text.split()) == value for text in found[1])

    def _dialog_visible(self) -> bool:
        return (
            self._exact_text('菜单', '手柄-兑换码标题', '兑换码')
            and self._exact_text('菜单', '兑换码兑换', '兑换')
        )

    @operation_node(name='进入兑换码页面', is_start_node=True, node_max_retry_times=32)
    def open_redemption(self) -> OperationRoundResult:
        """只有完整目标文字落在唯一彩框中才按 A。"""
        if self._dialog_visible():
            return self.round_success('已进入兑换码页面')
        if self._opened_dialog:
            return self.round_retry('等待兑换码页面，未发送输入', wait=0.7)
        if self._exact_text('菜单-更多功能', '标题-更多功能', '更多功能'):
            grid = self._read_area('菜单-更多功能', '手柄-功能网格')
            if grid is None:
                return self.round_retry('兑换码网格未知，未发送输入', wait=0.8)
            image, words = grid
            target = self._text_rect(words, '兑换码')
            frames = find_yellow_focus_frames(image, 130, 188, 140, 205, min_edge_presence=0.6)
            if target is None or len(frames) != 1:
                return self.round_retry('等待唯一功能焦点，未发送输入', wait=0.8)
            focus = frames[0]
            if focus.x1 <= target.center.x <= focus.x2 and focus.y1 <= target.center.y <= focus.y2:
                self.ctx.controller.btn_tap('south')
                self._opened_dialog = True
            elif target.center.y > focus.y2:
                self.ctx.controller.btn_tap('dpad_down')
            elif target.center.y < focus.y1:
                self.ctx.controller.btn_tap('dpad_up')
            else:
                self.ctx.controller.btn_tap('dpad_right' if target.center.x > focus.center.x else 'dpad_left')
            return self.round_retry('等待更多功能焦点或页面切换', wait=0.8)
        if self._opened_more:
            return self.round_retry('等待更多功能页面，未发送输入', wait=0.7)
        menu = self._read_area('菜单', '手柄-底部应用')
        if menu is not None:
            image, words = menu
            target = self._text_rect(words, '更多')
            if target is not None and all(self._text_rect(words, item) is not None for item in ('邮件', '仓库', '设置')):
                focused = [
                    (name, rect) for name in GamepadCityFund.MENU_ITEMS
                    if (rect := self._text_rect(words, name)) is not None
                    and has_filled_highlight(image, rect, 'yellow')
                ]
                if len(focused) != 1:
                    return self.round_retry('等待唯一主菜单焦点，未发送输入', wait=0.8)
                name, current = focused[0]
                if name == '更多':
                    self.ctx.controller.btn_tap('south')
                    self._opened_more = True
                else:
                    self.ctx.controller.btn_tap('dpad_right' if current.center.x < target.center.x else 'dpad_left')
                return self.round_retry('等待主菜单焦点或页面切换', wait=0.8)
        if self.last_screenshot is not None and self.round_by_find_area(
            self.last_screenshot, '大世界-普通', '快捷手册',
        ).is_success and not self._opened_menu:
            self.ctx.controller.click(gamepad_key='menu')
            self._opened_menu = True
        return self.round_retry('等待大世界或主菜单，未发送确认', wait=0.8)


class GamepadRedeemCode(GamepadOpenRedemption):
    """确认空白输入、精确码、唯一兑换焦点及独立回执；不操作邮件。"""

    realtime_nodes: ClassVar[frozenset[str]] = frozenset({'等待兑换回执'})
    RECEIPTS: ClassVar[dict[str, str]] = {
        '兑换成功': '兑换成功',
        '兑换码已使用': '兑换码已使用',
        '该兑换码已使用': '兑换码已使用',
        '兑换码无效': '兑换码无效',
        '兑换码已过期': '兑换码已过期',
        '该兑换码已过期': '兑换码已过期',
    }

    def __init__(self, ctx: ZContext, code: str, record: RedemptionCodeRunRecord) -> None:
        super().__init__(ctx)
        self.op_name = '手柄兑换一枚兑换码'
        self.code: str = normalize_code(code)
        self.record: RedemptionCodeRunRecord = record
        self._paste_started: bool = False
        self._paste_sent: bool = False
        self._move_sent: bool = False
        self._submit_sent: bool = False
        self._receipt_frame_time: float = 0
        self._receipt_deadline: float = 0

    def handle_init(self) -> None:
        super().handle_init()
        self._paste_started = False
        self._paste_sent = False
        self._move_sent = False
        self._submit_sent = False
        self._receipt_frame_time = 0
        self._receipt_deadline = 0

    def _field_is(self, value: str) -> bool:
        """只接受独立输入框中唯一的完整 OCR 文字，不放宽相似字符。"""
        area = self._read_area('菜单', '手柄-兑换码字段')
        return area is not None and {''.join(text.split()) for text in area[1]} == {value}

    def _field_focused(self) -> bool:
        area = self._read_area('菜单', '手柄-兑换码字段焦点')
        return area is not None and len(find_yellow_focus_frames(
            area[0], 500, 550, 67, 89, min_edge_presence=0.54,
        )) == 1

    def _redeem_focused(self) -> bool:
        area = self._read_area('菜单', '手柄-兑换按钮焦点')
        if area is None:
            return False
        image, words = area
        label = self._text_rect(words, '兑换')
        return self._exact_text('菜单', '兑换码兑换', '兑换') and label is not None and (
            has_filled_highlight(image, label, 'yellow')
            or len(find_yellow_focus_frames(image, 235, 285, 47, 70, min_edge_presence=0.53)) == 1
        )

    def _known_receipt(self) -> str | None:
        """只能用已提交后的确定文字作回执，不以表单仍然可见充当成功。"""
        statuses: set[str] = set()
        for name in ('手柄-兑换顶部结果', '手柄-兑换结果'):
            area = self._read_area('菜单', name)
            if area is not None:
                statuses.update(
                    self.RECEIPTS[exact] for word in area[1]
                    if (exact := ''.join(word.split()).rstrip('！!。')) in self.RECEIPTS
                )
        return next(iter(statuses)) if len(statuses) == 1 else None

    @node_from(from_name='进入兑换码页面')
    @operation_node(name='填写并兑换', node_max_retry_times=15, timeout_seconds=32)
    def redeem_once(self) -> OperationRoundResult:
        """未知状态停在现场；只有一次 Y、一次方向键和一次 A。"""
        if self._submit_sent:
            return self.round_fail('已尝试提交，禁止再次发送兑换输入')
        if self.record.macos_code_attempted(self.code):
            return self.round_fail('该码已记为已使用，或先前提交结果未能确认；未再次提交')
        if not self._dialog_visible() or self._known_receipt() is not None:
            return self.round_retry('兑换表单不明确，未发送输入', wait=0.6)
        if not self._paste_sent:
            if self._paste_started:
                return self.round_fail('原生粘贴曾中断，未提交、不重试')
            if not (self._field_is('请输入兑换码') and self._field_focused()
                    and not self._redeem_focused()
                    and self._exact_text('菜单', '手柄-兑换粘贴提示', 'Y')
                    and self._exact_text('菜单', '手柄-兑换粘贴提示', '粘贴')):
                return self.round_retry('未找到空输入框及手柄粘贴提示，未发送输入', wait=0.65)
            self._paste_started = True
            try:
                with temporary_redemption_pasteboard(self.code):
                    self.ctx.controller.btn_tap('north')
                    time.sleep(0.8)
            except RuntimeError as error:
                return self.round_fail(f'无法安全完成原生粘贴，未提交：{error}')
            except Exception:
                return self.round_fail('原生粘贴不可用，未提交、不重试')
            self._paste_sent = True
            return self.round_retry('等待识别粘贴后的准确兑换码', wait=0.65)
        if not self._field_is(self.code):
            return self.round_retry('输入框未辨认到指定的完整兑换码，不提交', wait=0.65)
        input_focused = self._field_focused()
        redeem_focused = self._redeem_focused()
        if input_focused and not redeem_focused and not self._move_sent:
            self._move_sent = True
            self.ctx.controller.btn_tap('dpad_down')
            return self.round_retry('等待确定唯一兑换按钮焦点', wait=0.7)
        if not input_focused and redeem_focused:
            if not self._save_evidence('redeem_verified_before_submit'):
                return self.round_fail('无法保存已核对兑换码和焦点的本地证据，未提交')
            if not self.record.begin_macos_attempt(self.code):
                return self.round_fail('该账号有该兑换码的提交记录，未再次提交')
            self._submit_sent = True
            self._receipt_frame_time = self.last_screenshot_time
            self._receipt_deadline = time.monotonic() + 10
            try:
                self.ctx.controller.btn_tap('south')
            except RuntimeError:
                return self._pending_evidence('redeem_receipt_unknown', '兑换输入发送状态不明，不会重试')
            # 这一步已完成唯一一次输入，下一节点只读取；不等待菜单节拍而错过短回执。
            return OperationRoundResult(OperationRoundResultEnum.SUCCESS, '已尝试一次兑换，不重复发送')
        return self.round_retry('兑换按钮不是唯一焦点，不提交', wait=0.65)

    @node_from(from_name='填写并兑换')
    @operation_node(name='等待兑换回执', timeout_seconds=14, mute=True)
    def wait_for_receipt(self) -> OperationRoundResult:
        """快速读取提交后的新帧，冲突或未知回执不算成功。"""
        if not self._submit_sent:
            return self.round_fail('未提交兑换码')
        if self.last_screenshot is not None and self.last_screenshot_time > self._receipt_frame_time:
            self._receipt_frame_time = self.last_screenshot_time
            status = self._known_receipt()
            if status is not None:
                self._save_evidence('redeem_result')
                if status in ('兑换成功', '兑换码已使用'):
                    self.record.add_used_code(self.code)
                if status == '兑换成功':
                    return self.round_success(status)
                return self.round_fail(status)
        if time.monotonic() >= self._receipt_deadline:
            return self._pending_evidence(
                'redeem_receipt_unknown', '已尝试提交一次，未识别到可信回执；请手动查看兑换奖励邮件，不会重试',
            )
        return self.round_wait('只读等待兑换回执', wait=0.15)
