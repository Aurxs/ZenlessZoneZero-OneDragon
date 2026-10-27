import sys

from PySide6.QtCore import Signal
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon,
    LineEdit,
    MessageBox,
    MessageBoxBase,
    SubtitleLabel,
    TextEdit,
)

from one_dragon.base.config.config_item import ConfigItem
from one_dragon.utils.i18_utils import gt
from one_dragon_qt.utils.layout_utils import Margins
from one_dragon_qt.view.app_run_interface import SplitAppRunInterface
from one_dragon_qt.widgets.column import Column
from one_dragon_qt.widgets.combo_box import ComboBox
from one_dragon_qt.widgets.editable_combo_box import EditableComboBox
from one_dragon_qt.widgets.setting_card.push_setting_card import PushSettingCard
from one_dragon_qt.widgets.setting_card.setting_card_base import SettingCardBase
from zzz_od.application.battle_assistant.auto_battle_config import (
    get_auto_battle_op_config_list,
)
from zzz_od.application.game_config_checker.predefined_team_checker import (
    predefined_team_checker_const,
)
from zzz_od.config.team_config import PredefinedTeamInfo
from zzz_od.context.zzz_context import ZContext
from zzz_od.game_data.agent import AgentEnum
from zzz_od.macos.predefined_team_preview import MacPredefinedTeamPreview


class TeamRecognitionPreviewDialog(MessageBoxBase):
    """完整列出二十队提议，取消时不写任何配置。"""

    def __init__(self, preview: MacPredefinedTeamPreview, parent: QWidget) -> None:
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel('预备编队识别预览'))
        names = {item.value.agent_id: item.value.agent_name for item in AgentEnum}
        lines = ['确认后仅更新已识别队名和完整三人成员；战斗策略和未识别成员保留。', '']
        for item in preview.teams:
            old_name, strategy, old_ids = preview.baseline[item.team_idx]
            new_name = item.name or f'{old_name}（未识别，保留）'
            old_members = '、'.join(names.get(value, value) for value in old_ids)
            new_members = '、'.join(names.get(value, value) for value in item.agent_ids) if len(item.agent_ids) == 3 else f'{old_members}（识别不完整，保留）'
            lines.extend([f'{item.team_idx + 1}. {old_name} → {new_name}', f'   {old_members} → {new_members}', f'   战斗配置：{strategy}（保留）', ''])
        viewer = TextEdit()
        viewer.setReadOnly(True)
        viewer.setPlainText('\n'.join(lines))
        viewer.setMinimumSize(680, 400)
        self.viewLayout.addWidget(viewer)
        self.yesButton.setText('确认写入')
        self.cancelButton.setText('取消')


class TeamNameValidator(QValidator):
    """限制编队名称：中文最多 7 个 / 英文最多 14 个（混合按宽度计）"""

    MAX_WIDTH = 14

    def validate(self, input_str: str, pos: int) -> tuple[QValidator.State, str, int]:
        input_width = sum(2 if ord(c) > 127 else 1 for c in input_str)
        if input_width <= self.MAX_WIDTH:
            return QValidator.State.Acceptable, input_str, pos
        return QValidator.State.Invalid, input_str, pos


class TeamSettingCard(SettingCardBase):
    changed = Signal(PredefinedTeamInfo)

    def __init__(self, only_agents: bool = False):
        SettingCardBase.__init__(
            self, icon=FluentIcon.PEOPLE, title='',
            margins=Margins(16, 0, 0, 16),
        )
        self.team_info: PredefinedTeamInfo | None = None
        self.only_agents: bool = only_agents

        self.titleLabel.hide()
        self.contentLabel.hide()

        # 两行内容布局
        v_layout = QVBoxLayout()
        v_layout.setSpacing(8)
        self.hBoxLayout.addLayout(v_layout)

        # 第一行：编队名称 + 战斗策略
        if only_agents:
            self.name_input = None
            self.auto_battle_btn = None
        else:
            self.setFixedHeight(96)

            row1 = QHBoxLayout()
            row1.setSpacing(10)
            self.name_input = LineEdit()
            self.name_input.setValidator(TeamNameValidator(self.name_input))
            self.name_input.textChanged.connect(self.on_name_changed)
            self.name_input.setFixedWidth(130)
            row1.addWidget(self.name_input)
            row1.addSpacing(13)

            auto_battle_label = CaptionLabel(gt('战斗配置'))
            row1.addWidget(auto_battle_label)

            self.auto_battle_btn = ComboBox()
            self.auto_battle_btn.currentIndexChanged.connect(self.on_auto_battle_changed)
            row1.addWidget(self.auto_battle_btn, stretch=1)
            row1.addSpacing(16)
            v_layout.addLayout(row1)

        # 第二行：三个代理人
        row2 = QHBoxLayout()
        row2.setSpacing(10)
        self.agent_1_btn = EditableComboBox()
        self.agent_1_btn.currentIndexChanged.connect(self.on_agent_1_changed)
        self.agent_1_btn.setFixedWidth(130)
        row2.addWidget(self.agent_1_btn)
        self.agent_2_btn = EditableComboBox()
        self.agent_2_btn.currentIndexChanged.connect(self.on_agent_2_changed)
        self.agent_2_btn.setFixedWidth(130)
        row2.addWidget(self.agent_2_btn)
        self.agent_3_btn = EditableComboBox()
        self.agent_3_btn.currentIndexChanged.connect(self.on_agent_3_changed)
        self.agent_3_btn.setFixedWidth(130)
        row2.addWidget(self.agent_3_btn)
        row2.addSpacing(16)
        v_layout.addLayout(row2)

    def init_setting_card(self, auto_battle_list: list[ConfigItem], team: PredefinedTeamInfo) -> None:
        self.team_info = team

        if not self.only_agents:
            self.name_input.blockSignals(True)
            self.name_input.setText(self.team_info.name)
            self.name_input.blockSignals(False)

            self.auto_battle_btn.set_items(auto_battle_list, team.auto_battle)

        agent_opts = ([ConfigItem(label='代理人', value='unknown')]
                      + [ConfigItem(label=i.value.agent_name, value=i.value.agent_id) for i in AgentEnum])

        self.agent_1_btn.set_items(agent_opts, team.agent_id_list[0])
        self.agent_2_btn.set_items(agent_opts, team.agent_id_list[1])
        self.agent_3_btn.set_items(agent_opts, team.agent_id_list[2])

    def setEnabled(self, enabled: bool):
        if not self.only_agents:
            self.name_input.setEnabled(enabled)
            self.auto_battle_btn.setEnabled(enabled)

        self.agent_1_btn.setEnabled(enabled)
        self.agent_2_btn.setEnabled(enabled)
        self.agent_3_btn.setEnabled(enabled)

    def setDisabled(self, disabled: bool):
        self.setEnabled(not disabled)

    def on_name_changed(self, value: str) -> None:
        if self.team_info is None:
            return

        self.team_info.name = value
        self.changed.emit(self.team_info)

    def on_auto_battle_changed(self, idx: int) -> None:
        if self.team_info is None:
            return

        self.team_info.auto_battle = self.auto_battle_btn.itemData(idx)
        self.changed.emit(self.team_info)

    def on_agent_1_changed(self, idx: int) -> None:
        if self.team_info is None:
            return

        self.team_info.agent_id_list[0] = self.agent_1_btn.itemData(idx)
        self.changed.emit(self.team_info)

    def on_agent_2_changed(self, idx: int) -> None:
        if self.team_info is None:
            return

        self.team_info.agent_id_list[1] = self.agent_2_btn.itemData(idx)
        self.changed.emit(self.team_info)

    def on_agent_3_changed(self, idx: int) -> None:
        if self.team_info is None:
            return

        self.team_info.agent_id_list[2] = self.agent_3_btn.itemData(idx)
        self.changed.emit(self.team_info)


class PredefinedTeamInterface(SplitAppRunInterface):

    def __init__(self, ctx: ZContext, parent=None):
        self.preview_card: PushSettingCard | None = None
        SplitAppRunInterface.__init__(
            self,
            ctx=ctx,
            app_id=predefined_team_checker_const.APP_ID,
            object_name='predefined_team_interface',
            nav_text_cn='预备编队',
            parent=parent,
            left_stretch=0,
        )

    def get_widget_at_top(self) -> QWidget:
        top = Column()
        help_card = PushSettingCard(
            icon=FluentIcon.HELP,
            title='预备编队识别',
            text='使用说明',
        )
        help_card.clicked.connect(self._on_help_clicked)
        top.add_widget(help_card)
        if sys.platform == 'darwin':
            self.preview_card = PushSettingCard(
                icon=FluentIcon.PEOPLE, title='识别结果', text='预览并确认写入',
                content='开始后只读扫描二十队，确认前不更新配置',
            )
            self.preview_card.clicked.connect(self._on_preview_clicked)
            self.preview_card.setEnabled(False)
            top.add_widget(self.preview_card)
        return top

    def _on_preview_clicked(self) -> None:
        preview = self.ctx.macos_predefined_team_preview
        if preview is None or not self.ctx.run_context.is_context_stop:
            return
        if not TeamRecognitionPreviewDialog(preview, self.window()).exec():
            return
        try:
            count = preview.apply(self.ctx)
        except ValueError as error:
            dialog = MessageBox('编队未更新', str(error), self.window())
            dialog.cancelButton.hide()
            dialog.exec()
            return
        self.ctx.macos_predefined_team_preview = None
        self._refresh_team_cards()
        self._refresh_preview_card()
        self.preview_card.setContent(f'已确认更新 {count} 队，战斗策略保留')

    def _refresh_preview_card(self) -> None:
        if self.preview_card is None:
            return
        preview = self.ctx.macos_predefined_team_preview
        self.preview_card.setEnabled(preview is not None and self.ctx.run_context.is_context_stop)
        self.preview_card.setContent('已识别二十队，等待预览确认；尚未写入' if preview is not None else '开始后只读扫描二十队，确认前不更新配置')

    def get_left_widget(self) -> QWidget:
        left_widget = Column(margins=Margins(0, 0, 16, 0))
        self.team_opt_list: list[TeamSettingCard] = []
        team_list = self.ctx.team_config.team_list
        for _ in team_list:
            card = TeamSettingCard()
            card.changed.connect(self._on_team_info_changed)
            self.team_opt_list.append(card)
            left_widget.add_widget(card)
        left_widget.add_stretch(1)
        return left_widget

    def _on_help_clicked(self) -> None:
        content = (
            '▎编队名称\n\n'
            + ('Mac 按游戏内槽位顺序对应二十队，现有名称可以作为别名。\n'
               '预览会列出队名和成员的变更，未读全的字段保留。\n\n' if sys.platform == 'darwin'
               else '请确保编队名称与游戏内完全一致，顺序随意，\n'
               '名称不匹配会导致无法识别。\n\n'
               '不建议使用默认的数字命名编队，\n'
               'OCR 识别数字容易出错，建议使用中文名称。\n\n')
            + '▎自动识别\n\n'
            '点击「开始」后将自动打开游戏内预备编队页面，\n'
            + ('通过截图只读识别二十队，返回后点击「预览并确认写入」。\n'
               '取消不会保存，战斗策略与未识别成员保留。' if sys.platform == 'darwin'
               else '通过截图识别各编队中的代理人并填入左侧配置。')
        )
        w = MessageBox(gt('使用说明'), content, self.window())
        w.cancelButton.hide()
        w.yesButton.setText(gt('确认'))
        w.exec()

    def on_interface_shown(self) -> None:
        SplitAppRunInterface.on_interface_shown(self)
        self._refresh_preview_card()

        auto_battle_list = get_auto_battle_op_config_list('auto_battle')
        team_list = self.ctx.team_config.team_list
        for i in range(len(team_list)):
            if i >= len(self.team_opt_list):
                break
            self.team_opt_list[i].init_setting_card(auto_battle_list, team_list[i])

    def _on_team_info_changed(self, team: PredefinedTeamInfo) -> None:
        self.ctx.team_config.update_team(team)

    def on_context_state_changed(self) -> None:
        """运行状态变化时刷新编队卡片。"""
        super().on_context_state_changed()
        if self.ctx.run_context.is_context_stop:
            self._refresh_team_cards()
        self._refresh_preview_card()

    def _refresh_team_cards(self) -> None:
        """根据当前配置刷新编队卡片的代理人选项。"""
        auto_battle_list = get_auto_battle_op_config_list('auto_battle')
        team_list = self.ctx.team_config.team_list
        for i in range(min(len(team_list), len(self.team_opt_list))):
            self.team_opt_list[i].init_setting_card(auto_battle_list, team_list[i])
