"""手动控制只允许设置页固定入口调用。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from one_dragon.base.operation.application.application_factory import ApplicationFactory
from zzz_od.application.manual_gamepad import manual_gamepad_const
from zzz_od.application.manual_gamepad.manual_gamepad_app import ManualGamepadApp

if TYPE_CHECKING:
    from zzz_od.context.zzz_context import ZContext


class ManualGamepadFactory(ApplicationFactory):
    """无独立配置和运行记录，映射继续使用原账户游戏设置。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(manual_gamepad_const)
        self.ctx: ZContext = ctx

    def create_application(self, instance_idx: int, group_id: str) -> ManualGamepadApp:
        """由原工厂管理器创建同一上下文的手动应用。"""
        return ManualGamepadApp(self.ctx)
