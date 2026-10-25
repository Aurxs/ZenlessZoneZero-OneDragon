from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from qfluentwidgets import FluentIcon

from one_dragon_qt.view.standalone_app_run_interface import StandaloneRunInterface
from one_dragon_qt.widgets.setting_card.help_card import HelpCard
from zzz_od.macos.application_capabilities import (
    MACOS_APP_SUMMARY,
    get_macos_app_limits,
    get_macos_app_unavailable_reason,
)

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from zzz_od.context.zzz_context import ZContext


class ZStandaloneAppRunInterface(StandaloneRunInterface):

    def __init__(self, ctx: ZContext, parent: QWidget | None = None) -> None:
        self.ctx: ZContext = ctx
        StandaloneRunInterface.__init__(
            self,
            ctx=ctx,
            object_name='standalone_app_run_interface',
            nav_text_cn='应用运行',
            nav_icon=FluentIcon.APPLICATION,
            parent=parent,
        )

    def get_widget_at_top(self) -> QWidget:
        if sys.platform == 'darwin':
            card = HelpCard(
                title='Mac 适配范围',
                content=f'{MACOS_APP_SUMMARY}。应用仍可查看和配置。',
            )
            card.setFixedHeight(100)
            card.contentLabel.setWordWrap(True)
            return card
        return HelpCard(
            url='https://one-dragon.com/zzz/zh/feat/feat_standalone_app.html',
            title='应用运行说明',
            content='从应用列表中选择单个功能模块独立运行，无需跑完整的一条龙流程',
        )

    def _refresh_app_list(self) -> None:
        super()._refresh_app_list()
        self._apply_macos_availability()
        self.on_context_state_changed()

    def _apply_macos_availability(self) -> None:
        """保留所有可选应用，仅灰显未适配说明。"""
        if sys.platform != 'darwin':
            return
        for card in self.app_list_widget._cards:
            reason = get_macos_app_unavailable_reason(card.app_id)
            card.content_widget.setContent(reason or get_macos_app_limits(card.app.app_id))
            card.content_widget.titleLabel.setEnabled(reason is None)

    def _on_app_selected(self, app_id: str) -> None:
        super()._on_app_selected(app_id)
        self.on_context_state_changed()

    def _on_add_app_clicked(self) -> None:
        super()._on_add_app_clicked()
        self._apply_macos_availability()
        self.on_context_state_changed()
