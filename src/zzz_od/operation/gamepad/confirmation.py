"""已知流程中的单按钮确认，不读取弹窗祝词或替代未知确认判断。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from one_dragon.base.operation.operation import Operation
    from one_dragon.base.operation.operation_round_result import OperationRoundResult


def confirm_expected_single_dialog(operation: Operation) -> OperationRoundResult:
    """调用方已明确正在等待结果确认时，匹配居中按钮及 A 提示后确认一次。"""
    if operation.node_clicked:
        return operation.round_success()
    if operation.last_screenshot is None or not all(
        operation.round_by_find_area(operation.last_screenshot, '画面-通用', name).is_success
        for name in ('手柄-单按钮确认', '手柄-单按钮选择')
    ):
        return operation.round_retry('等待预期的单按钮确认弹窗', wait=0.5)
    operation.save_screenshot(prefix='macos_expected_single_confirm')
    operation.node_clicked = True
    operation.ctx.controller.btn_tap('south')
    return operation.round_success(wait=1)
