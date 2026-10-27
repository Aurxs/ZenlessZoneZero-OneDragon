"""参考实物比例绘制 Xbox 手柄，控件与外壳一同缩放。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget
from qfluentwidgets import PushButton, isDarkTheme

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtGui import QPaintEvent, QResizeEvent


class XboxGamepadSurface(QWidget):
    """半实心外壳、圆形凹槽和一体十字键，输入仍由页面按钮处理。"""

    def __init__(
        self, left_stick: QWidget, right_stick: QWidget,
        create_button: Callable[[str, str], PushButton], parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setMinimumWidth(540)
        self.setFixedHeight(430)
        self.setAccessibleName('Xbox 手柄正面')
        self.placements: list[tuple[QWidget, QRectF, str, bool]] = []
        self._place(left_stick, (135, 165, 90, 90))
        self._place(right_stick, (315, 253, 90, 90))
        for label, key, rect, kind in (
            ('LT', 'xbox_lt', (194, 39, 32, 55), 'trigger'),
            ('LB', 'xbox_lb', (185, 101, 50, 21), 'shoulder'),
            ('RT', 'xbox_rt', (374, 39, 32, 55), 'trigger'),
            ('RB', 'xbox_rb', (365, 101, 50, 21), 'shoulder'),
            ('Y', 'xbox_y', (406, 173, 28, 28), 'face'),
            ('X', 'xbox_x', (383, 196, 28, 28), 'face'),
            ('B', 'xbox_b', (429, 196, 28, 28), 'face'),
            ('A', 'xbox_a', (406, 219, 28, 28), 'face'),
            ('▣', 'xbox_back', (254, 200, 20, 20), 'small'),
            ('↥', 'capture', (290, 200, 20, 20), 'small'),
            ('☰', 'xbox_start', (326, 200, 20, 20), 'small'),
            ('⌂', 'xbox_guide', (284, 153, 32, 32), 'home'),
        ):
            button = create_button(label, key)
            descriptions = {
                'xbox_back': '视图 / BACK', 'xbox_start': '菜单 / START',
                'xbox_guide': 'Xbox / GUIDE', 'capture': '分享 / CAPTURE',
            }
            if key in descriptions:
                button.setToolTip(descriptions[key])
                button.setAccessibleName(descriptions[key])
            self._place(button, rect, kind, circle=kind in ('face', 'small', 'home'))
        for label, key, rect in (
            ('↑', 'xbox_dpad_up', (231, 266, 18, 23)),
            ('←', 'xbox_dpad_left', (208, 289, 23, 18)),
            ('→', 'xbox_dpad_right', (249, 289, 23, 18)),
            ('↓', 'xbox_dpad_down', (231, 307, 18, 23)),
        ):
            button = create_button(label, key)
            button.setText('')
            button.setToolTip(f'十字键 {label}')
            self._place(button, rect, 'dpad')

    def _place(
        self, widget: QWidget, rect: tuple[int, int, int, int],
        kind: str = 'stick', circle: bool = False,
    ) -> None:
        """保存设计坐标，命中区域与矢量图共用变换。"""
        widget.setParent(self)
        self.placements.append((widget, QRectF(*rect), kind, circle))

    def _transform(self) -> tuple[float, QPointF]:
        scale = min(self.width() / 600, self.height() / 480)
        return scale, QPointF((self.width() - 600 * scale) / 2, (self.height() - 480 * scale) / 2)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """缩放真实按钮，并让按下高亮覆盖实际按钮轮廓。"""
        scale, offset = self._transform()
        for widget, rect, kind, circle in self.placements:
            widget.setGeometry(QRectF(offset + rect.topLeft() * scale, rect.size() * scale).toRect())
            if not isinstance(widget, PushButton):
                continue
            radius = min(widget.width(), widget.height()) // 2 if circle else (13 if kind == 'trigger' else 6)
            background = '#48494d' if isDarkTheme() else '#9198a2'
            border = '#626367' if isDarkTheme() else '#7c8692'
            if kind == 'dpad':
                background, border, radius = 'transparent', 'transparent', 0
            if kind == 'home':
                background = 'transparent'
            size = 10 if kind == 'shoulder' else (12 if kind == 'small' else 13)
            widget.setStyleSheet(
                f'PushButton {{border: 1px solid {border}; border-radius: {radius}px; '
                f'background: {background}; color: #e7e7e8; font-size: {size}px; font-weight: 600;}}'
                'PushButton:hover {background: #5b6069;}'
                'PushButton:pressed {background: #3487f3; border-color: #69aaff; color: white;}'
                'PushButton:disabled {color: #92959b;}',
            )
        super().resizeEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        """外形和布局按用户参考图绘制，凹槽与握柄分缝保持低对比。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale, offset = self._transform()
        painter.translate(offset)
        painter.scale(scale, scale)
        dark = isDarkTheme()
        body = QPainterPath(QPointF(195, 135))
        body.lineTo(405, 135)
        body.cubicTo(455, 135, 480, 165, 497, 215)
        body.cubicTo(525, 293, 545, 374, 540, 410)
        body.cubicTo(538, 440, 525, 454, 500, 454)
        body.cubicTo(482, 454, 467, 439, 449, 416)
        body.lineTo(400, 374)
        body.cubicTo(390, 364, 380, 360, 365, 360)
        body.lineTo(235, 360)
        body.cubicTo(220, 360, 210, 364, 200, 374)
        body.lineTo(151, 416)
        body.cubicTo(133, 439, 118, 454, 100, 454)
        body.cubicTo(75, 454, 62, 440, 60, 410)
        body.cubicTo(55, 374, 75, 293, 103, 215)
        body.cubicTo(120, 165, 145, 135, 195, 135)
        body.closeSubpath()
        painter.setPen(QPen(QColor('#4d5056' if dark else '#9ea6b1'), 2.8))
        painter.setBrush(QColor('#292b30' if dark else '#d7dbe1'))
        painter.drawPath(body)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor('#41454b' if dark else '#aab2bc'), 1.8))
        painter.drawLine(QPointF(86, 274), QPointF(193, 381))
        painter.drawLine(QPointF(514, 274), QPointF(407, 381))
        painter.setBrush(QColor('#191b1f' if dark else '#aeb5be'))
        for point, radius in ((QPointF(240, 298), 43), (QPointF(420, 210), 43)):
            painter.drawEllipse(point, radius, radius)
        cross = QPainterPath()
        cross.setFillRule(Qt.FillRule.WindingFill)
        cross.addRect(QRectF(231, 266, 18, 64))
        cross.addRect(QRectF(208, 289, 64, 18))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#505258' if dark else '#727e8d'))
        painter.drawPath(cross.simplified())
