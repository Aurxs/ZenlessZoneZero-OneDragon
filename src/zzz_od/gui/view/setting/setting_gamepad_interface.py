"""Mac 手柄设置二级页，复用原账户映射和服务设置卡。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon, SettingCardGroup

from one_dragon.base.controller.gamepad_button import XboxButtonEnum
from one_dragon_qt.widgets.column import Column
from one_dragon_qt.widgets.setting_card.combo_box_setting_card import (
    ComboBoxSettingCard,
)
from one_dragon_qt.widgets.setting_card.expand_setting_card_group import (
    ExpandSettingCardGroup,
)
from one_dragon_qt.widgets.setting_card.gamepad_action_key_card import (
    GamepadActionKeyCard,
)
from one_dragon_qt.widgets.setting_card.spin_box_setting_card import (
    DoubleSpinBoxSettingCard,
)
from one_dragon_qt.widgets.vertical_scroll_interface import VerticalScrollInterface
from zzz_od.config.game_config import GameKeyAction, GamepadActionEnum
from zzz_od.gui.view.setting.macos_gamepad_settings import MacGamepadSettings
from zzz_od.gui.view.setting.manual_gamepad_widget import ManualGamepadWidget

if TYPE_CHECKING:
    from zzz_od.context.zzz_context import ZContext


class SettingGamepadInterface(VerticalScrollInterface):
    """手动控制在上方，映射及服务配置按当前账户保存。"""

    def __init__(self, ctx: ZContext, parent: QWidget | None = None) -> None:
        self.ctx: ZContext = ctx
        super().__init__(None, 'setting_gamepad_interface', '手柄', parent=parent)

    def get_content_widget(self) -> QWidget:
        """构造页面不会连接游戏或创建设备。"""
        content = Column()
        self.manual: ManualGamepadWidget = ManualGamepadWidget(self.ctx, self)
        content.add_widget(self.manual)
        self.mapping_group: ExpandSettingCardGroup = ExpandSettingCardGroup(
            FluentIcon.GAME, '动作按键映射（当前账户）',
            '修改一条龙发出的 Xbox 按键，请与游戏内设置一致；下次连接生效。上方 A/B/X/Y 始终代表物理按钮。',
        )
        self.press_time: DoubleSpinBoxSettingCard = DoubleSpinBoxSettingCard(
            FluentIcon.GAME, '单次按键持续时间（秒）', minimum=0.01, maximum=1, step=0.01,
        )
        self.press_time.value_changed.connect(self._mapping_changed)
        self.mapping_group.addSettingCard(self.press_time)
        self.key_cards: dict[str, ComboBoxSettingCard] = {}
        for action in GameKeyAction:
            card = ComboBoxSettingCard(FluentIcon.GAME, action.value.ui_text, options_enum=XboxButtonEnum)
            card.value_changed.connect(self._mapping_changed)
            self.key_cards[action.value.value] = card
            self.mapping_group.addSettingCard(card)
        content.add_widget(self.mapping_group)
        self.action_group: ExpandSettingCardGroup = ExpandSettingCardGroup(
            FluentIcon.GAME, '界面快捷键', '菜单、地图和快捷手册的单键或组合键。',
        )
        self.action_cards: dict[str, GamepadActionKeyCard] = {}
        for action in GamepadActionEnum:
            card = GamepadActionKeyCard(FluentIcon.GAME, action.value.ui_text, XboxButtonEnum, XboxButtonEnum)
            card.value_changed.connect(self._mapping_changed)
            self.action_cards[action.value.value] = card
            self.action_group.addSettingCard(card)
        content.add_widget(self.action_group)
        self.service_group: SettingCardGroup = SettingCardGroup('手柄服务')
        self.macos_gamepad_settings: MacGamepadSettings = MacGamepadSettings(self.ctx, self.service_group, self)
        content.add_widget(self.service_group)
        content.add_stretch(1)
        self.timer: QTimer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._refresh_editable)
        self.timer.start()
        return content

    def on_interface_shown(self) -> None:
        """沿用适配器的连接清理，重复打开或切换账户不会重复保存。"""
        super().on_interface_shown()
        self.macos_gamepad_settings.reload()
        config = self.ctx.game_config
        self.press_time.init_with_adapter(config.get_prop_adapter('xbox_key_press_time'))
        for name, card in self.key_cards.items():
            card.init_with_adapter(config.get_prop_adapter(f'xbox_key_{name}'))
        for name, card in self.action_cards.items():
            card.init_with_adapter(config.get_prop_adapter(f'xbox_action_{name}'))
        self._refresh_editable()

    def on_interface_hidden(self) -> None:
        """页面导航先释放，不等待下一次计时器。"""
        if self._init:
            self.manual.release_all()
            self.ctx.manual_gamepad.stop()
        super().on_interface_hidden()

    def _refresh_editable(self) -> None:
        """操作期间锁住映射，避免组合键按下和释放读取不同的配置。"""
        editable = self.ctx.run_context.is_context_stop and not self.ctx.manual_gamepad.pending.is_set()
        for group in (self.mapping_group, self.action_group, self.service_group):
            group.setEnabled(editable)

    def _mapping_changed(self, value: object) -> None:
        """复用服务设置的控制器重建路径，让缓存动作映射随修改更新。"""
        self.macos_gamepad_settings._config_changed('mapping')
