"""复用原应用组，在任务失败后恢复主界面再继续。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from one_dragon.base.operation.application.group_application import GroupApplication
from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from zzz_od.operation.gamepad.back_to_normal_world import GamepadBackToNormalWorld

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_round_result import OperationRoundResult


class GamepadGroupApplication(GroupApplication):
    """保留原任务顺序、跳过逻辑及失败记录，只增加失败恢复。"""

    @node_from(from_name='获取应用组配置')
    @node_from(from_name='执行应用')
    @operation_node(name='执行应用', screenshot_before_round=False)
    def run_app(self) -> OperationRoundResult:
        """超时或失败后先返回；手动停止、暂停均不发送恢复输入。"""
        fail_count = len(self._fail_app_idx_list)
        result = super().run_app()
        if len(self._fail_app_idx_list) == fail_count:
            return result
        if not self.ctx.run_context.is_context_running:
            return self.round_fail('任务运行已停止或暂停，未执行失败恢复')
        recovery = GamepadBackToNormalWorld(self.ctx).execute()
        if not recovery.success:
            return self.round_fail(f'任务失败后返回主界面失败：{recovery.status}', data=recovery.data)
        return result
