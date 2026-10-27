"""游戏设置中的 Mac 运行参数，沿用当前账户的配置。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject
from qfluentwidgets import FluentIcon

from one_dragon.base.config.game_account_config import GamePlatformEnum
from one_dragon.base.operation.context_notify_event import ContextNotifyEvent
from one_dragon_qt.widgets.setting_card.combo_box_setting_card import (
    ComboBoxSettingCard,
)
from one_dragon_qt.widgets.setting_card.spin_box_setting_card import SpinBoxSettingCard
from one_dragon_qt.widgets.setting_card.switch_setting_card import SwitchSettingCard
from one_dragon_qt.widgets.setting_card.text_setting_card import TextSettingCard

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget
    from qfluentwidgets import SettingCardGroup

    from zzz_od.context.zzz_context import ZContext


class MacRuntimeSettings(QObject):
    """只迁移界面位置，不改变配置路径、默认值或连接生命周期。"""

    def __init__(self, ctx: ZContext, group: SettingCardGroup, parent: QWidget) -> None:
        """创建当前账户的运行设置，不连接设备。"""
        super().__init__(parent)
        self.ctx: ZContext = ctx
        self.platform_opt: ComboBoxSettingCard = ComboBoxSettingCard(
            icon=FluentIcon.APPLICATION, title='游戏平台', options_enum=GamePlatformEnum,
            content='在此选择 macOS PlayCover；修改后重新启动一条龙',
        )
        self.platform_opt.value_changed.connect(self._on_mac_platform_changed)
        group.addSettingCard(self.platform_opt)
        self.macos_bundle_opt: TextSettingCard = TextSettingCard(
            icon=FluentIcon.GAME, title='游戏应用标识',
            content='国服为 com.miHoYo.Nap，用于绑定游戏窗口',
        )
        self.macos_bundle_opt.value_changed.connect(self._on_mac_config_changed)
        group.addSettingCard(self.macos_bundle_opt)
        self.macos_app_path_opt: TextSettingCard = TextSettingCard(
            icon=FluentIcon.FOLDER, title='PlayCover 游戏路径',
            content='完整 .app 路径；留空按应用标识使用 PlayCover 默认安装目录',
        )
        self.macos_app_path_opt.value_changed.connect(self._on_mac_config_changed)
        group.addSettingCard(self.macos_app_path_opt)
        self.macos_launch_timeout_opt: SpinBoxSettingCard = SpinBoxSettingCard(
            icon=FluentIcon.HISTORY, title='启动窗口等待（秒）', minimum=1, maximum=120,
            content='未运行时先连接中立手柄再启动，默认等待45秒；已有进程不会重启',
        )
        self.macos_launch_timeout_opt.value_changed.connect(self._on_mac_config_changed)
        group.addSettingCard(self.macos_launch_timeout_opt)
        self.macos_auto_top_inset_opt: SwitchSettingCard = SwitchSettingCard(
            icon=FluentIcon.PHOTO, title='自动适配游戏窗口',
            content='默认开启；按16:9和窗口底边自动忽略标题栏，放大缩小后自动适配',
        )
        self.macos_auto_top_inset_opt.value_changed.connect(self._on_auto_top_inset_changed)
        group.addSettingCard(self.macos_auto_top_inset_opt)
        self.macos_top_inset_opt: SpinBoxSettingCard = SpinBoxSettingCard(
            icon=FluentIcon.PHOTO, title='截图顶部裁剪（旧像素配置）', minimum=0, maximum=256,
            content='关闭自动适配且逻辑点高度为0时使用；保留已有像素设置',
        )
        self.macos_top_inset_opt.value_changed.connect(self._on_mac_config_changed)
        group.addSettingCard(self.macos_top_inset_opt)
        self.macos_top_inset_points_opt: SpinBoxSettingCard = SpinBoxSettingCard(
            icon=FluentIcon.PHOTO,title='标题栏高度（逻辑点）',minimum=0,maximum=256,
            content='关闭自动适配后使用；非0时按每帧缩放换算，优先于旧像素配置',
        )
        self.macos_top_inset_points_opt.value_changed.connect(self._on_mac_config_changed)
        group.addSettingCard(self.macos_top_inset_points_opt)
        self.macos_menu_interval_opt: SpinBoxSettingCard = SpinBoxSettingCard(
            icon=FluentIcon.HISTORY, title='界面操作间隔（毫秒）', minimum=0, maximum=2000,
            content='默认 500 毫秒（0.5 秒），每个手柄界面步骤至少等待此时长；不影响战斗策略',
        )
        group.addSettingCard(self.macos_menu_interval_opt)

    def reload(self) -> None:
        """每次打开页面重新绑定当前账户，初始化不触发保存。"""
        self.platform_opt.init_with_adapter(self.ctx.game_account_config.get_prop_adapter('platform'))
        self.macos_menu_interval_opt.init_with_adapter(
            self.ctx.macos_config.get_prop_adapter('menu_action_interval_ms'),
        )
        self.macos_bundle_opt.init_with_adapter(self.ctx.macos_config.get_prop_adapter('bundle_id'))
        self.macos_app_path_opt.init_with_adapter(self.ctx.macos_config.get_prop_adapter('app_path'))
        self.macos_launch_timeout_opt.init_with_adapter(
            self.ctx.macos_config.get_prop_adapter('launch_timeout_seconds'),
        )
        self.macos_top_inset_opt.init_with_adapter(
            self.ctx.macos_config.get_prop_adapter('capture_top_inset_pixels'),
        )
        self.macos_top_inset_points_opt.init_with_adapter(
            self.ctx.macos_config.get_prop_adapter('capture_top_inset_points'),
        )
        self.macos_auto_top_inset_opt.init_with_adapter(
            self.ctx.macos_config.get_prop_adapter('capture_auto_top_inset'),
        )
        self._update_manual_inset_enabled(self.ctx.macos_config.capture_auto_top_inset)

    def _update_manual_inset_enabled(self, auto: bool) -> None:
        """自动模式保留原值，只禁用手动控件。"""
        self.macos_top_inset_opt.setEnabled(not auto)
        self.macos_top_inset_points_opt.setEnabled(not auto)

    def _on_auto_top_inset_changed(self, value: bool) -> None:
        """切换裁剪方式后更新控件并停止旧连接。"""
        self._update_manual_inset_enabled(value)
        self._on_mac_config_changed(value)

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

