import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIconBase, PushButton, SettingCard

from one_dragon.utils.i18_utils import gt
from one_dragon_qt.utils.layout_utils import IconSize, Margins
from one_dragon_qt.widgets.adapter_init_mixin import AdapterInitMixin
from one_dragon_qt.widgets.setting_card.setting_card_base import SettingCardBase

if TYPE_CHECKING:
    from one_dragon.base.controller.pc_button.pc_button_listener import PcButtonListener


class KeyEventWorker(QObject):

    key_pressed = Signal(str)

    def on_key_press(self, key: str) -> None:
        """
        按键后触发 发送信号
        :param key:
        :return:
        """
        self.key_pressed.emit(key)


class KeySettingCard(SettingCardBase, AdapterInitMixin):

    value_changed = Signal(str)

    def __init__(self,
                 icon: str | QIcon | FluentIconBase, title: str, content: str | None = None,
                 icon_size: IconSize = IconSize(16, 16),
                 margins: Margins = Margins(16, 16, 0, 16),
                 parent: QWidget | None = None) -> None:

        SettingCardBase.__init__(
            self,
            icon=icon,
            title=title,
            content=content,
            icon_size=icon_size,
            margins=margins,
            parent=parent
        )
        AdapterInitMixin.__init__(self)

        # 初始化 PushButton
        self.value: str = ''
        self.btn: PushButton = PushButton(text='', parent=self)
        self.btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn.clicked.connect(self._on_btn_clicked)
        if sys.platform != 'win32':
            self.btn.setEnabled(False)
            self.btn.setToolTip(gt('当前平台暂不支持键盘录制'))

        # 初始化监听器和键盘事件工作者
        self.button_listener: PcButtonListener | None = None  # 按键监听
        self.key_worker: KeyEventWorker = KeyEventWorker()
        self.key_worker.key_pressed.connect(self._on_key_signal)

        # 布局处理
        self.hBoxLayout.addWidget(self.btn, 1, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def _on_btn_clicked(self) -> None:
        """
        点击按钮后 开始监听按键事件
        :return:
        """
        if sys.platform != 'win32':
            return

        if self.button_listener is None:
            from one_dragon.base.controller.pc_button.pc_button_listener import (
                PcButtonListener,
            )

            self.button_listener = PcButtonListener(
                self._on_key_press, listen_keyboard=True, listen_mouse=True
            )
            self.btn.setText(gt('请按键'))
            self.button_listener.start()
        else:
            self._stop_listener()
            self.btn.setText(self.value.upper())

    def _on_key_press(self, key: str) -> None:
        """
        按键时触发
        :param key:
        :return:
        """
        self._stop_listener()
        self.key_worker.on_key_press(key)

    def _on_key_signal(self, key: str) -> None:
        """
        :param key:
        :return:
        """
        self.setValue(key)

        if self.adapter is not None:
            self.adapter.set_value(key)

    def setContent(self, content: str) -> None:
        """
        更新左侧详细文本
        :param content: 文本 中文
        :return:
        """
        SettingCard.setContent(self, gt(content))

    def setValue(self, value: str, emit_signal: bool = True) -> None:
        """
        设置值
        :param value:
        :param emit_signal: 是否发送信号
        :return:
        """
        self.value = value
        self.btn.setText(value.upper())
        if emit_signal:
            self.value_changed.emit(value)

    def _stop_listener(self) -> None:
        """
        停止键盘鼠标的监听
        :return:
        """
        if self.button_listener is not None:
            self.button_listener.stop()
            self.button_listener = None

    def default_adapter_value(self) -> str:
        return ""
