from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from one_dragon_qt.view.setting.setting_custom_interface import SettingCustomInterface
from one_dragon_qt.view.setting.setting_env_interface import SettingEnvInterface
from one_dragon_qt.view.setting.setting_push_interface import SettingPushInterface
from one_dragon_qt.widgets.pivot_navi_interface import PivotNavigatorInterface
from zzz_od.gui.view.setting.setting_game_interface import SettingGameInterface

if TYPE_CHECKING:
    from zzz_od.context.zzz_context import ZContext


class AppSettingInterface(PivotNavigatorInterface):

    def __init__(self, ctx: ZContext, parent: QWidget | None = None) -> None:
        self.ctx: ZContext = ctx
        PivotNavigatorInterface.__init__(self, object_name='app_setting_interface', parent=parent,
                                         nav_text_cn='设置', nav_icon=FluentIcon.SETTING)

    def create_sub_interface(self) -> None:
        """
        创建下面的子页面
        :return:
        """
        self.add_sub_interface(SettingGameInterface(ctx=self.ctx))
        if sys.platform == 'darwin':
            from zzz_od.gui.view.setting.setting_gamepad_interface import (
                SettingGamepadInterface,
            )

            self.add_sub_interface(SettingGamepadInterface(ctx=self.ctx))
        if sys.platform == 'win32':
            from zzz_od.gui.view.setting.setting_overlay_interface import (
                SettingOverlayInterface,
            )

            self.add_sub_interface(SettingOverlayInterface(ctx=self.ctx))
        self.add_sub_interface(SettingEnvInterface(ctx=self.ctx))
        self.add_sub_interface(SettingPushInterface(ctx=self.ctx))
        self.add_sub_interface(SettingCustomInterface(ctx=self.ctx))
