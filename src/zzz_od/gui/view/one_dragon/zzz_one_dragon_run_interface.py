from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from qfluentwidgets import BodyLabel, FluentIcon, PushButton

from one_dragon.utils.log_utils import log
from one_dragon_qt.view.one_dragon.one_dragon_run_interface import OneDragonRunInterface
from zzz_od.macos.application_capabilities import (
    MACOS_CHARGE_PLAN_LIMITS,
    get_macos_app_unavailable_reason,
    get_macos_one_dragon_unavailable_reason,
)

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from one_dragon.base.operation.application.application_group_config import (
        ApplicationGroupConfigItem,
    )
    from one_dragon.base.operation.context_event_bus import ContextEventItem
    from zzz_od.context.zzz_context import ZContext
    from zzz_od.gui.view.one_dragon.macos_game_preparation_runner import (
        MacGamePreparationRunner,
    )


class ZOneDragonRunInterface(OneDragonRunInterface):

    def __init__(self, ctx: ZContext, parent: QWidget | None = None) -> None:
        self.ctx: ZContext = ctx
        OneDragonRunInterface.__init__(
            self,
            ctx=ctx,
            parent=parent,
            help_url='https://one-dragon.com/zzz/zh/feat/feat_one_dragon/onedragon.html',
        )
        self._macos_preparation_runner: MacGamePreparationRunner | None = None

    def get_widget_at_top(self) -> QWidget:
        """在原运行设置中补充 Mac 范围与不消耗电量的准备按钮。"""
        top = super().get_widget_at_top()
        if sys.platform != 'darwin':
            return top
        self.macos_status_label: BodyLabel = BodyLabel(
            f'{MACOS_CHARGE_PLAN_LIMITS}。其他任务标记为「Mac暂未适配」；'
            '准备游戏会按需启动游戏、进入已保存账号并确认手柄模式。'
            '触屏模式下会短暂置前游戏并使用鼠标，切手柄后恢复。',
        )
        self.macos_status_label.setWordWrap(True)
        top.layout().addWidget(self.macos_status_label)
        self.macos_prepare_btn: PushButton = PushButton(
            text='准备游戏（启动并切换手柄）', icon=FluentIcon.GAME,
        )
        self.macos_prepare_btn.setToolTip(
            '游戏未运行时自动启动，进入已保存账号并确认手柄大世界。'
            '不执行任务、不消耗电量；需要重新登录时会停止提示。'
            '触屏模式下会短暂置前游戏并使用鼠标，切手柄后恢复。'
        )
        self.macos_prepare_btn.clicked.connect(self._on_prepare_game_clicked)
        top.layout().addWidget(self.macos_prepare_btn)
        return top

    def _init_app_list(self) -> None:
        super()._init_app_list()
        self._apply_macos_availability()

    def _apply_macos_availability(self) -> None:
        """保留任务顺序与设置，只标明适配范围并限制运行按钮。"""
        if sys.platform != 'darwin':
            return
        for card in self.app_run_list._app_cards:
            reason = get_macos_app_unavailable_reason(card.app.app_id)
            card.run_btn.setEnabled(reason is None)
            card.run_btn.setToolTip(reason or MACOS_CHARGE_PLAN_LIMITS)
            card.content_widget.titleLabel.setEnabled(reason is None)
            if reason is not None:
                card.content_widget.setTitle(f'{card.app.app_name} · Mac暂未适配')
                card.content_widget.setContent(reason)
            # 保留原启用值；已启用的未适配任务允许用户主动关闭。
            card.switch_btn.setEnabled(reason is None or card.app.enabled)
            card.switch_btn.setToolTip(
                f'{reason}；可关闭已有启用项' if reason is not None else MACOS_CHARGE_PLAN_LIMITS,
            )

    def on_context_state_changed(self) -> None:
        super().on_context_state_changed()
        self._apply_macos_availability()
        if sys.platform == 'darwin' and hasattr(self, 'macos_prepare_btn'):
            preparing = (
                self._macos_preparation_runner is not None
                and self._macos_preparation_runner.isRunning()
            )
            self.macos_prepare_btn.setEnabled(self.ctx.run_context.is_context_stop and not preparing)
            if preparing:
                self.start_btn.setEnabled(False)

    def _on_app_state_changed(self, event: ContextEventItem) -> None:
        super()._on_app_state_changed(event)
        self._apply_macos_availability()

    def on_app_switch_run(self, app_id: str, value: bool) -> None:
        super().on_app_switch_run(app_id, value)
        self._apply_macos_availability()

    def run_app(self) -> None:
        """启动前列出不支持的启用任务，不改写用户列表。"""
        reason = get_macos_one_dragon_unavailable_reason(self.ctx)
        if reason is not None:
            log.error(reason)
            if hasattr(self, 'macos_status_label'):
                self.macos_status_label.setText(reason)
            return
        if self._macos_preparation_runner is not None and self._macos_preparation_runner.isRunning():
            log.error('请等待游戏准备结束')
            return
        super().run_app()

    def run_app_by_item(self, app: ApplicationGroupConfigItem) -> None:
        reason = get_macos_app_unavailable_reason(app.app_id)
        if reason is not None:
            log.error(reason)
            return
        super().run_app_by_item(app)

    def _on_prepare_game_clicked(self) -> None:
        """准备操作使用独立工作线程，不注册成一条龙任务。"""
        if not self.ctx.run_context.is_context_stop or self.app_runner.isRunning():
            return
        if self._macos_preparation_runner is not None and self._macos_preparation_runner.isRunning():
            return
        from zzz_od.gui.view.one_dragon.macos_game_preparation_runner import (
            MacGamePreparationRunner,
        )

        runner = MacGamePreparationRunner(self.ctx)
        self._macos_preparation_runner = runner
        runner.state_changed.connect(self.on_context_state_changed)
        runner.finished.connect(self._on_prepare_game_finished)
        self.macos_status_label.setText('正在检查游戏输入模式；此操作不消耗电量')
        self.macos_prepare_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.log_card.start()
        runner.start()

    def _on_prepare_game_finished(self) -> None:
        self.on_context_state_changed()
        runner = self._macos_preparation_runner
        if runner is not None and runner.result is not None:
            self.macos_status_label.setText(runner.result.status or '游戏准备已结束')
