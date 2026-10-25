from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon, SettingCardGroup

from one_dragon.base.config.game_account_config import GamePlatformEnum
from one_dragon.base.operation.context_notify_event import ContextNotifyEvent
from one_dragon_qt.view.setting.setting_instance_interface import (
    SettingInstanceInterface,
)
from one_dragon_qt.widgets.setting_card.combo_box_setting_card import (
    ComboBoxSettingCard,
)
from one_dragon_qt.widgets.setting_card.help_card import HelpCard
from one_dragon_qt.widgets.setting_card.spin_box_setting_card import SpinBoxSettingCard
from one_dragon_qt.widgets.setting_card.text_setting_card import TextSettingCard

if TYPE_CHECKING:
    from zzz_od.context.zzz_context import ZContext


class ZSettingInstanceInterface(SettingInstanceInterface):
    """复用账户管理，在 Mac 上显式配置 PlayCover 与手柄连接。"""

    def __init__(self, ctx: ZContext, parent: QWidget | None = None) -> None:
        """保留当前实例，不在启动时自动改写 PC 平台配置。"""
        self.ctx: ZContext = ctx
        self.platform_opt: ComboBoxSettingCard | None = None
        self.macos_bundle_opt: TextSettingCard | None = None
        self.macos_app_path_opt: TextSettingCard | None = None
        self.macos_launch_timeout_opt: SpinBoxSettingCard | None = None
        self.macos_ojd_opt: TextSettingCard | None = None
        self.macos_top_inset_opt: SpinBoxSettingCard | None = None
        super().__init__(ctx=ctx, parent=parent)

    def _get_instanceSettings_group(self) -> QWidget:
        """保留 Windows 页面，在 Mac 增加实例级连接配置。"""
        group: SettingCardGroup = super()._get_instanceSettings_group()
        if sys.platform != 'darwin':
            return group

        self.platform_opt = ComboBoxSettingCard(
            icon=FluentIcon.APPLICATION, title='游戏平台', options_enum=GamePlatformEnum,
            content='在此选择 macOS PlayCover；修改后重新启动一条龙',
        )
        self.platform_opt.value_changed.connect(self._on_mac_platform_changed)
        group.addSettingCard(self.platform_opt)
        self.macos_bundle_opt = TextSettingCard(
            icon=FluentIcon.GAME, title='游戏应用标识',
            content='国服为 com.miHoYo.Nap，用于绑定游戏窗口',
        )
        self.macos_bundle_opt.value_changed.connect(self._on_mac_config_changed)
        group.addSettingCard(self.macos_bundle_opt)
        self.macos_app_path_opt = TextSettingCard(
            icon=FluentIcon.FOLDER, title='PlayCover 游戏路径',
            content='完整 .app 路径；留空按应用标识使用 PlayCover 默认安装目录',
        )
        self.macos_app_path_opt.value_changed.connect(self._on_mac_config_changed)
        group.addSettingCard(self.macos_app_path_opt)
        self.macos_launch_timeout_opt = SpinBoxSettingCard(
            icon=FluentIcon.HISTORY, title='启动窗口等待（秒）', minimum=1, maximum=120,
            content='未运行时先连接中立手柄再启动，默认等待45秒；已有进程不会重启',
        )
        self.macos_launch_timeout_opt.value_changed.connect(self._on_mac_config_changed)
        group.addSettingCard(self.macos_launch_timeout_opt)
        self.macos_ojd_opt = TextSettingCard(
            icon=FluentIcon.FOLDER, title='OJD 命令路径',
            content='填写 ojd 或其完整路径，命令名必须为 ojd',
        )
        self.macos_ojd_opt.value_changed.connect(self._on_mac_config_changed)
        group.addSettingCard(self.macos_ojd_opt)
        self.macos_top_inset_opt = SpinBoxSettingCard(
            icon=FluentIcon.PHOTO, title='截图顶部裁剪', minimum=0, maximum=256,
            content='填已确认的标题栏像素高度；无标题栏填 0，剩余游戏内容须为 16:9',
        )
        self.macos_top_inset_opt.value_changed.connect(self._on_mac_config_changed)
        group.addSettingCard(self.macos_top_inset_opt)
        group.addSettingCard(HelpCard(
            title='Mac 当前支持范围',
            content='准备游戏会按需启动已安装的客户端；凭据或验证码需要人工处理，完整每日流程仍在适配。',
        ))
        return group

    def init_game_account_config(self) -> None:
        """切换实例时同步控件，读取配置不会改写平台。"""
        super().init_game_account_config()
        if self.platform_opt is None:
            return
        self.platform_opt.init_with_adapter(self.ctx.game_account_config.get_prop_adapter('platform'))
        self.macos_bundle_opt.init_with_adapter(self.ctx.macos_config.get_prop_adapter('bundle_id'))
        self.macos_app_path_opt.init_with_adapter(self.ctx.macos_config.get_prop_adapter('app_path'))
        self.macos_launch_timeout_opt.init_with_adapter(
            self.ctx.macos_config.get_prop_adapter('launch_timeout_seconds'),
        )
        self.macos_ojd_opt.init_with_adapter(self.ctx.macos_config.get_prop_adapter('ojd_cli_path'))
        self.macos_top_inset_opt.init_with_adapter(
            self.ctx.macos_config.get_prop_adapter('capture_top_inset_pixels'),
        )
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
        for control in (
            self.game_path_opt, self.custom_win_title_opt, self.game_region_opt,
            self.game_account_opt, self.game_password_opt, self.help_bilibili_opt,
            self.bilibili_account_name, self.force_login_opt,
        ):
            control.hide()

    def _on_mac_platform_changed(self, index: int, value: str) -> None:
        """平台选择已由适配器保存，终止旧连接并等待重新启动。"""
        self._on_mac_config_changed(value)

    def _on_mac_config_changed(self, value: str | int) -> None:
        """保存连接参数后停止旧任务，防止使用旧窗口或旧手柄配置。"""
        if not self.ctx.run_context.is_context_stop:
            self.ctx.run_context.stop_running()
        self.ctx.ready_for_application = False
        self.ctx.initialization_error = '连接配置已修改，请重新启动一条龙'
        if self.ctx.controller is not None:
            self.ctx.controller.cleanup_after_app_shutdown()
            self.ctx.controller = None
        event = ContextNotifyEvent.info('配置已保存', self.ctx.initialization_error)
        self.ctx.dispatch_event(ContextNotifyEvent.EVENT_ID, event)
