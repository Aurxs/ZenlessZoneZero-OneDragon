from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget

from one_dragon_qt.view.setting.setting_instance_interface import (
    SettingInstanceInterface,
)

if TYPE_CHECKING:
    from zzz_od.context.zzz_context import ZContext


class ZSettingInstanceInterface(SettingInstanceInterface):
    """Mac 多账户页保留账户管理，运行参数统一放到游戏设置。"""

    def __init__(self, ctx: ZContext, parent: QWidget | None = None) -> None:
        """沿用原账户列表和切换逻辑。"""
        self.ctx: ZContext = ctx
        self._account_settings_group: QWidget | None = None
        super().__init__(ctx=ctx, parent=parent)

    def _get_instanceSettings_group(self) -> QWidget:
        """Windows 保留原设置组，Mac 隐藏没有适用控件的空分组。"""
        self._account_settings_group = super()._get_instanceSettings_group()
        if sys.platform == 'darwin':
            self._account_settings_group.hide()
        return self._account_settings_group

    def init_game_account_config(self) -> None:
        """切换账户后仍不显示 Windows 专用配置。"""
        super().init_game_account_config()
        self._hide_windows_settings()

    def _update_developer_visibility(self) -> None:
        """开发者模式也不显示 Mac 无法使用的 Windows 窗口配置。"""
        super()._update_developer_visibility()
        self._hide_windows_settings()

    def set_ui_of_game_region(self, value: str) -> None:
        """保留区服显示逻辑，但 Mac 暂不提供自动登录配置。"""
        super().set_ui_of_game_region(value)
        self._hide_windows_settings()

    def _hide_windows_settings(self) -> None:
        """隐藏当前不适用的路径、窗口标题和登录控件。"""
        if sys.platform != 'darwin':
            return
        if self._account_settings_group is not None:
            self._account_settings_group.hide()
        for control in (
            self.game_path_opt, self.custom_win_title_opt, self.game_region_opt,
            self.game_account_opt, self.game_password_opt, self.help_bilibili_opt,
            self.bilibili_account_name, self.force_login_opt,
        ):
            control.hide()

