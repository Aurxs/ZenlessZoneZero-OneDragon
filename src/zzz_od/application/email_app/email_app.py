from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from one_dragon.base.operation.operation_notify import NotifyTiming, node_notify
from one_dragon.base.operation.operation_round_result import OperationRoundResult
from zzz_od.application.email_app import email_app_const
from zzz_od.application.zzz_application import ZApplication
from zzz_od.context.zzz_context import ZContext
from zzz_od.operation.back_to_normal_world import BackToNormalWorld

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_base import OperationResult


class EmailApp(ZApplication):

    """邮件:自动领取游戏内未读邮件奖励(菲林/材料)。无消耗。"""

    def __init__(self, ctx: ZContext) -> None:
        """
        每天自动接收邮件奖励
        """
        ZApplication.__init__(
            self,
            ctx=ctx,
            app_id=email_app_const.APP_ID,
            op_name=email_app_const.APP_NAME,
        )

    def handle_init(self) -> None:
        """
        执行前的初始化 由子类实现
        注意初始化要全面 方便一个指令重复使用
        """
        pass

    def execute(self) -> OperationResult:
        """Mac 邮件必须整次运行明确授权，不从整组或未确认的 GUI 启动。"""
        if sys.platform == 'darwin' and not getattr(self.ctx, 'macos_claim_all_mail', False):
            return self.op_fail('Mac 邮件仅限 CLI 手动使用 --app email --claim-all')
        return super().execute()

    @operation_node(name='选择邮件输入方式', is_start_node=True)
    def choose_input_mode(self) -> OperationRoundResult:
        return self.round_success('Mac手柄邮件' if sys.platform == 'darwin' else '原邮件流程')

    @node_from(from_name='选择邮件输入方式', status='Mac手柄邮件')
    @operation_node(name='手柄领取邮件附件', timeout_seconds=100)
    def run_gamepad_mail(self) -> OperationRoundResult:
        from zzz_od.operation.gamepad.mailbox import GamepadClaimMailbox

        return self.round_by_op_result(GamepadClaimMailbox(self.ctx).execute())

    @node_from(from_name='选择邮件输入方式', status='原邮件流程')
    @operation_node(name='打开邮件')
    def goto_email(self) -> OperationRoundResult:
        return self.round_by_goto_screen(screen_name='邮件')

    @node_from(from_name='打开邮件')
    @node_notify(when=NotifyTiming.CURRENT_SUCCESS)
    @operation_node(name='全部领取')
    def click_get_all(self) -> OperationRoundResult:
        """
        邮件画面 点击全部领取
        就算时灰色的也能识别到
        :return:
        """
        return self.round_by_find_and_click_area(self.last_screenshot, '邮件', '全部领取', success_wait=1, retry_wait=1)

    @node_from(from_name='全部领取')
    @operation_node(name='确认')
    def click_confirm(self) -> OperationRoundResult:
        """
        邮件画面 领取后点击确认
        :return:
        """
        target_word_list = [
            '确认',  # 正常领取的情况
            '确定',  # 某种物品爆满了
        ]
        return self.round_by_ocr_and_click_by_priority(
            target_cn_list=target_word_list,
            success_wait=1,
            retry_wait=1,
        )

    @node_from(from_name='确认')  # 确认之后返回
    @node_from(from_name='确认', success=False)  # 没有确认 其实就是没有东西能领取 也返回
    @node_from(from_name='全部领取', success=False)  # 没找到全部领取的话 也返回
    @operation_node(name='返回菜单')
    def back_to_menu(self) -> OperationRoundResult:
        """
        返回菜单
        领取后的确认按钮可以不按 直接点击外层也可以返回
        :return:
        """
        return self.round_by_find_and_click_area(self.last_screenshot, '菜单', '返回', success_wait=1, retry_wait=1)

    @node_from(from_name='返回菜单')
    @node_from(from_name='返回菜单', success=False)
    @operation_node(name='返回大世界')
    def back_to_world(self) -> OperationRoundResult:
        op = BackToNormalWorld(self.ctx)
        return self.round_by_op_result(op.execute())
