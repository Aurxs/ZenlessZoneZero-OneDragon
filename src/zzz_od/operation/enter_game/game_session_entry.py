"""集中选择游戏会话入口，避免 Mac 加载 Windows 登录和窗口依赖。"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from one_dragon.base.operation.operation import Operation
    from zzz_od.context.zzz_context import ZContext


def create_game_session_entry(ctx: ZContext) -> Operation:
    """Mac 自动准备手柄会话，Windows 保留原自动启动和登录流程。"""
    if sys.platform == 'darwin':
        from zzz_od.operation.enter_game.mac_bootstrap_game_session import (
            MacBootstrapGameSession,
        )

        return MacBootstrapGameSession(ctx)

    from zzz_od.operation.enter_game.open_and_enter_game import OpenAndEnterGame

    return OpenAndEnterGame(ctx)


def create_account_switch_entry(ctx: ZContext) -> Operation | None:
    """Mac 尚未实现切换账号，Windows 延迟构造原切换操作。"""
    if sys.platform == 'darwin':
        return None

    from zzz_od.operation.enter_game.switch_account import SwitchAccount

    return SwitchAccount(ctx)


def prepare_game_window_for_resume(ctx: ZContext) -> None:
    """Windows 恢复时激活游戏，Mac 保持后台窗口状态。"""
    if sys.platform != 'darwin':
        ctx.controller.active_window()
