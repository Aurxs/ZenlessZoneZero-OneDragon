"""Mac 手柄邮箱的进入和安全识别。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from zzz_od.operation.gamepad.focus import has_filled_highlight, highlight_mask
from zzz_od.operation.gamepad.rewards import _GamepadRewardOperation

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class GamepadOpenMailbox(_GamepadRewardOperation):
    """只打开已识别的邮箱；不发送领取、删除或其他页面按键。"""

    MENU_ITEMS: tuple[str, ...] = (
        '更多', '勘域编队', '邮件', '设置', '公告', '成就',
        '绳网', '仓库', '代理人', '商城', '丽都城募', '调频',
    )

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄打开邮箱', timeout_seconds=45)
        self._menu_opened: bool = False
        self._entered: bool = False

    def handle_init(self) -> None:
        self.evidence_paths.clear()
        self._menu_opened = False
        self._entered = False

    def _mailbox_visible(self) -> bool:
        """同时匹配邮箱标题和操作栏，不能把菜单中的“邮件”当邮箱。"""
        return all(
            part is not None and any(''.join(text.split()) == target for text in part[1])
            for part, target in (
                (self._read_area('邮件', '标题-邮件'), '邮件'),
                (self._read_area('邮件', '手柄-全部领取提示'), '全部领取'),
            )
        )

    @operation_node(name='打开邮件', is_start_node=True, node_max_retry_times=28, timeout_seconds=40)
    def open_mail(self) -> OperationRoundResult:
        """每帧只向目标移一格；只有目标为唯一确认焦点才进入。"""
        if self._mailbox_visible():
            return self.round_success('已打开邮件')
        if self._known_reward_visible():
            return self.round_fail('已有奖励弹窗，未操作邮件')
        if self._entered:
            return self.round_retry('等待邮件加载', wait=0.8)
        area = self._read_area('菜单', '手柄-底部应用')
        if area is not None:
            image, results = area
            rects = {
                name: self._text_rect(results, name)
                for name in self.MENU_ITEMS
            }
            target = rects['邮件']
            if target is not None and rects['仓库'] is not None and rects['设置'] is not None:
                selected = [
                    (name, rect) for name, rect in rects.items()
                    if rect is not None and has_filled_highlight(image, rect, 'yellow')
                ]
                if len(selected) != 1:
                    return self.round_retry('等待唯一菜单焦点，未发送输入', wait=0.8)
                name, current = selected[0]
                if name == '邮件':
                    self.ctx.controller.btn_tap('south')
                    self._entered = True
                else:
                    self.ctx.controller.btn_tap(
                        'dpad_right' if current.center.x < target.center.x else 'dpad_left',
                    )
                return self.round_retry('等待邮件焦点或页面切换', wait=0.7)
        if self.last_screenshot is not None and self.round_by_find_area(
            self.last_screenshot, '大世界-普通', '快捷手册',
        ).is_success:
            if not self._menu_opened:
                self.ctx.controller.click(gamepad_key='menu')
                self._menu_opened = True
            return self.round_retry('等待游戏菜单', wait=0.8)
        return self.round_retry('等待受支持的已知页面，未发送输入', wait=0.8)


class GamepadClaimMailbox(GamepadOpenMailbox):
    """仅处理手动明确请求的全部附件，不删邮件、不打开单封或附件链接。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx)
        self.op_name = '手柄领取邮件附件'
        self.timeout_seconds = 95
        self._claim_sent: bool = False
        self._confirmation_sent: bool = False
        self._mail_back_sent: bool = False
        self._menu_back_sent: bool = False
        self._claim_status: str = ''

    def handle_init(self) -> None:
        super().handle_init()
        self._claim_sent = False
        self._confirmation_sent = False
        self._mail_back_sent = False
        self._menu_back_sent = False
        self._claim_status = ''

    def _claim_prompt(self) -> tuple[bool, bool]:
        """独立核对 X 的位置和文字启用颜色，不把 A 单封领取当全部领取。"""
        area = self._read_area('邮件', '手柄-全部领取提示')
        if area is None:
            return False, False
        image, results = area
        labels = [
            item for text, matches in results.items()
            if ''.join(text.split()) == '全部领取' for item in matches
        ]
        keys = [
            item for text, matches in results.items()
            if text.strip().upper() == 'X' for item in matches
        ]
        if len(labels) != 1 or len(keys) != 1:
            return False, False
        label, key = labels[0], keys[0]
        if not 0 <= label.rect.x1 - key.rect.x2 <= 80 or abs(label.center.y - key.center.y) > 20:
            return False, False
        rect = label.rect
        crop = image[rect.y1:rect.y2, rect.x1:rect.x2]
        if not crop.size:
            return False, False
        mask = highlight_mask(crop, 'yellow')
        return True, bool(np.count_nonzero(mask) / mask.size >= 0.15)

    @node_from(from_name='打开邮件')
    @operation_node(name='核对并领取邮件', node_max_retry_times=6, timeout_seconds=12)
    def claim_mail(self) -> OperationRoundResult:
        """没有稳定识别到正确页面及启用提示时不发送输入。"""
        if not self._mailbox_visible() or self._known_reward_visible():
            return self.round_retry('等待可验证的邮箱页面，未发领取输入', wait=0.8)
        known, enabled = self._claim_prompt()
        if not known:
            return self.round_retry('未识别邮件 X 全部领取提示', wait=0.8)
        if not enabled:
            self._claim_status = '未见启用的全部领取提示，未领取'
            return self.round_success('未执行领取')
        if not self._claim_sent:
            if not self._save_evidence('mail_before_claim'):
                return self.round_fail('无法保存邮件领取前证据，未执行领取')
            self._claim_sent = True
            self.ctx.controller.btn_tap('west')
        return self.round_success(wait=0.8)

    @node_from(from_name='核对并领取邮件')
    @operation_node(name='确认邮件领取结果', node_max_retry_times=8, timeout_seconds=13)
    def confirm_mail(self) -> OperationRoundResult:
        """只确认由本次 X 触发的已知获得弹窗；未知结果不重发 X。"""
        if not self._claim_sent:
            return self.round_success()
        if self._known_reward_visible():
            if not self._confirmation_sent:
                if not self._save_evidence('mail_claim_reward'):
                    return self.round_fail('邮件结果截图未保存，未确认弹窗')
                self._confirmation_sent = True
                self.ctx.controller.btn_tap('south')
            return self.round_retry('等待邮件奖励弹窗关闭', wait=0.8)
        if self._confirmation_sent and self._mailbox_visible():
            self._claim_status = '已核对邮件附件领取结果'
            return self.round_success()
        if self.node_retry_times >= 7:
            return self._pending_evidence('mail_unknown_result', '邮件领取结果未能确认，不重复领取')
        return self.round_retry('等待可确认的邮件奖励结果，不重复领取', wait=0.8)

    @node_from(from_name='确认邮件领取结果')
    @operation_node(name='邮件返回大世界', node_max_retry_times=10, timeout_seconds=16)
    def back_to_world(self) -> OperationRoundResult:
        """仅从确认的邮箱及菜单各返回一次，未知弹窗或页面不输入。"""
        if self._known_reward_visible():
            return self.round_retry('邮件奖励弹窗尚未关闭', wait=0.8)
        if self.last_screenshot is not None and self.round_by_find_area(
            self.last_screenshot, '大世界-普通', '快捷手册',
        ).is_success:
            return self.round_success(self._claim_status)
        if self._mailbox_visible():
            if not self._mail_back_sent:
                self._mail_back_sent = True
                self.ctx.controller.btn_tap('east')
        elif all(self._has_text('菜单', '手柄-底部应用', item) for item in ('邮件', '仓库', '设置')):
            if not self._menu_back_sent:
                self._menu_back_sent = True
                self.ctx.controller.btn_tap('east')
        return self.round_retry('等待从邮件返回大世界', wait=0.8)
