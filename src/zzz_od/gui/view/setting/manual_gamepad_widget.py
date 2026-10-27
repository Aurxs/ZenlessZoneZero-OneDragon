"""鼠标可操作的虚拟手柄；只在用户启用手动会话时发送输入。"""

from __future__ import annotations

import math
from functools import partial
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel, CardWidget, PushButton, SubtitleLabel, isDarkTheme

from zzz_od.config.game_config import GamepadActionEnum
from zzz_od.gui.view.setting.xbox_gamepad_surface import XboxGamepadSurface

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtGui import QHideEvent, QMouseEvent, QPaintEvent

    from zzz_od.context.zzz_context import ZContext
    from zzz_od.macos.manual_gamepad import ManualGamepadSession


class GamepadStick(QWidget):
    """拖动位置转换为单位圆内的摇杆值，松开或隐藏立即归零。"""

    changed = Signal(float, float)
    stick_clicked = Signal(bool)

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title: str = title
        self.value: QPointF = QPointF()
        self.held: bool = False
        self.click_held: bool = False
        self.resize(102, 102)
        self.setAccessibleName(title)
        self.setToolTip(f'{title}：左键拖动方向，右键按下摇杆；松开归零')

    def paintEvent(self, event: QPaintEvent) -> None:
        """使用当前主题文字色和强调色绘制摇杆，不加载图片资源。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark = isDarkTheme()
        center = QPointF(self.width() / 2, self.height() / 2)
        radius = min(self.width(), self.height()) * 0.45
        painter.setPen(QPen(QColor('#484b51' if dark else '#8a94a2'), 2))
        painter.setBrush(QColor('#17191d' if dark else '#aeb5bf'))
        painter.drawEllipse(center, radius, radius)
        knob = center + self.value * radius * 0.35
        active = self.held or self.click_held
        painter.setPen(QPen(QColor('#6aaaff' if active else '#606369'), 2))
        painter.setBrush(QColor('#3487f3' if active else ('#51545a' if dark else '#7e8a9a')))
        painter.drawEllipse(knob, radius * 0.74, radius * 0.74)
        painter.setPen(QPen(QColor('#71acfa' if active else '#5d6066'), 1))
        painter.drawEllipse(knob, radius * 0.64, radius * 0.64)

    def _move(self, point: QPointF) -> None:
        """按圆形边界限制幅度，正 Y 向下，与兼容层保持一致。"""
        center = QPointF(self.width() / 2, self.height() / 2)
        value = (point - center) / (min(self.width(), self.height()) * 0.45)
        length = math.hypot(value.x(), value.y())
        if length > 1:
            value /= length
        self.value = value
        self.changed.emit(value.x(), value.y())
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """左键拖动方向，右键按下摇杆的 L3/R3。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.held = True
            self._move(event.position())
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self.click_held = True
            self.stick_clicked.emit(True)
            self.update()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """鼠标按住时更新摇杆。"""
        if self.held:
            self._move(event.position())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """松开后不保留任何摇杆方向。"""
        self.reset()

    def reset(self) -> None:
        """同时清除控件状态与输出，允许失焦/隐藏统一调用。"""
        self.held = False
        if self.click_held:
            self.click_held = False
            self.stick_clicked.emit(False)
        self.value = QPointF()
        self.changed.emit(0.0, 0.0)
        self.update()

    def hideEvent(self, event: QHideEvent) -> None:
        self.reset()
        super().hideEvent(event)


class ManualGamepadWidget(CardWidget):
    """连接按钮、物理手柄按钮和原配置快捷键。"""

    def __init__(self, ctx: ZContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx: ZContext = ctx
        self.session: ManualGamepadSession = ctx.manual_gamepad
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        layout.addWidget(SubtitleLabel('手动控制'))
        description = BodyLabel(
            '启用后按住按钮或拖动摇杆操作游戏。请先用“一条龙 → 准备游戏”切到手柄模式；'
            '启用不改变当前游戏页面。自动任务运行时不可接管。',
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        row = QHBoxLayout()
        self.toggle: PushButton = PushButton('启用手动控制')
        self.toggle.clicked.connect(self._toggle)
        self.release: PushButton = PushButton('释放全部')
        self.release.clicked.connect(self.release_all)
        self.status: BodyLabel = BodyLabel('未启用手动控制')
        self.status.setWordWrap(True)
        row.addWidget(self.toggle)
        row.addWidget(self.release)
        row.addWidget(self.status, 1)
        layout.addLayout(row)
        self.controls: QWidget = QWidget(self)
        controls_layout = QVBoxLayout(self.controls)
        self.buttons: dict[str, PushButton] = {}
        self.left_stick: GamepadStick = GamepadStick('左摇杆 · 移动')
        self.right_stick: GamepadStick = GamepadStick('右摇杆 · 镜头')
        self.left_stick.changed.connect(partial(self._stick, 'left'))
        self.right_stick.changed.connect(partial(self._stick, 'right'))
        self.left_stick.stick_clicked.connect(partial(self._input, self.session.set_button, 'xbox_l_thumb'))
        self.right_stick.stick_clicked.connect(partial(self._input, self.session.set_button, 'xbox_r_thumb'))
        self.surface: XboxGamepadSurface = XboxGamepadSurface(self.left_stick, self.right_stick, self._button)
        controls_layout.addWidget(self.surface)
        hint = BodyLabel('左键拖动摇杆 · 右键摇杆按下 L3 / R3 · 其他按钮按住操作，松开释放')
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        controls_layout.addWidget(hint)
        shortcuts = QHBoxLayout()
        for action in GamepadActionEnum:
            name = action.value.value
            button = PushButton(action.value.ui_text)
            button.pressed.connect(partial(self._action, name, True))
            button.released.connect(partial(self._action, name, False))
            shortcuts.addWidget(button)
        controls_layout.addLayout(shortcuts)
        layout.addWidget(self.controls)
        self.controls.setEnabled(False)
        self.timer: QTimer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        QApplication.instance().applicationStateChanged.connect(self._application_state)

    def _button(self, label: str, key: str) -> PushButton:
        """按钮的按下/释放直接对应物理手柄，不使用自动重复或锁定保持。"""
        button = PushButton(label)
        button.setAccessibleName(f'手柄 {label}')
        button.pressed.connect(partial(self._input, self.session.set_button, key, True))
        button.released.connect(partial(self._input, self.session.set_button, key, False))
        self.buttons[key] = button
        return button

    def _input(self, callback: Callable, *args: object) -> None:
        """传输或采集失败时结束手动会话，并将原因留在页面。"""
        try:
            callback(*args)
        except Exception as error:
            self.session.stop()
            self.session.last_status = str(error)
        self.refresh()

    def _stick(self, side: str, x: float, y: float) -> None:
        self._input(self.session.set_stick, side, x, y)

    def _action(self, action: str, pressed: bool) -> None:
        self._input(self.session.set_action, action, pressed)

    def _toggle(self) -> None:
        """启动请求和停止都由当前上下文处理，不创建独立输入进程。"""
        if self.session.requested.is_set():
            self.session.stop()
        else:
            self._input(self.session.start)
        self.refresh()

    def release_all(self) -> None:
        """包括失焦时的统一归零；控件不保留旧的拖动状态。"""
        self.left_stick.reset()
        self.right_stick.reset()
        for button in self.buttons.values():
            button.setDown(False)
        self._input(self.session.release_all)

    def refresh(self) -> None:
        """只查询运行状态，不自动恢复、重连或发手柄按键。"""
        requested = self.session.requested.is_set()
        active = self.session.active
        self.controls.setEnabled(active)
        self.release.setEnabled(active)
        self.toggle.setText('结束手动控制' if requested else '启用手动控制')
        self.toggle.setEnabled(requested or (
            self.ctx.run_context.is_context_stop and not self.session.pending.is_set()
        ))
        self.status.setText('手动控制中 · 自动任务暂不可用' if active else self.session.last_status)

    def _application_state(self, state: Qt.ApplicationState) -> None:
        """切到游戏或其他应用时松开保持输入，不让旧按钮粘住。"""
        if state != Qt.ApplicationState.ApplicationActive:
            self.release_all()

    def hideEvent(self, event: QHideEvent) -> None:
        """离开设置页或关闭窗口时撤回请求并释放输入。"""
        self.release_all()
        self.session.stop()
        super().hideEvent(event)
