"""Mac 编队扫描仅暂存预览，由原页面确认后更新当前账户。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zzz_od.config.team_config import PredefinedTeamInfo
    from zzz_od.context.zzz_context import ZContext


def team_signature(teams: list[PredefinedTeamInfo]) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """队名、成员或策略任一改变，都要求重新扫描后再确认。"""
    return tuple((team.name, team.auto_battle, tuple(team.agent_id_list)) for team in teams)


@dataclass(frozen=True)
class MacTeamRecognition:
    """成员不足三人时保留整组原成员，避免错位覆盖。"""

    team_idx: int
    name: str | None
    agent_ids: tuple[str, ...]


@dataclass(frozen=True)
class MacPredefinedTeamPreview:
    instance_idx: int
    baseline: tuple[tuple[str, str, tuple[str, ...]], ...]
    teams: tuple[MacTeamRecognition, ...]
    screenshots: tuple[str, ...]

    def apply(self, ctx: ZContext) -> int:
        """仅在调用方得到用户确认后写一次；账户或配置变化时拒绝旧结果。"""
        if not ctx.run_context.is_context_stop:
            raise ValueError('请先停止任务再确认编队')
        if ctx.current_instance_idx != self.instance_idx or team_signature(ctx.team_config.team_list) != self.baseline:
            raise ValueError('账户或编队配置已变化，请重新识别后确认')
        current = ctx.team_config.team_list
        raw = deepcopy(ctx.team_config.get('team_list', []))
        output = []
        changed = 0
        by_idx = {team.team_idx: team for team in self.teams}
        for team in current:
            data = raw[team.idx] if team.idx < len(raw) else {
                'name': team.name, 'auto_battle': team.auto_battle,
                'agent_id_list': list(team.agent_id_list),
            }
            recognition = by_idx.get(team.idx)
            if recognition is not None:
                if recognition.name:
                    data['name'] = recognition.name
                if len(recognition.agent_ids) == 3:
                    data['agent_id_list'] = list(recognition.agent_ids)
            if data.get('name') != team.name or data.get('agent_id_list') != team.agent_id_list:
                changed += 1
            output.append(data)
        if changed:
            ctx.team_config.update('team_list', output)
        return changed
