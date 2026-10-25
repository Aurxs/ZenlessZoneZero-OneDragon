"""在公共画面之上加载平台差异，编辑时只保存平台文件。"""

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from one_dragon.base.screen.screen_info import ScreenInfo
from one_dragon.base.screen.screen_loader import ScreenContext
from one_dragon.utils import os_utils, yaml_utils


class ProfileScreenContext(ScreenContext):
    """按画面 ID 和区域名称保存差异，未修改的字段继续继承公共资源。"""

    def __init__(self, resource_profile: str = 'ios_gamepad', defer_missing_screens: bool = False) -> None:
        """选择已知平台；上下文加载插件期间可以暂缓检查缺失画面。"""
        if resource_profile != 'ios_gamepad':
            raise ValueError(f'不支持的画面资源配置: {resource_profile}')
        super().__init__()
        self.resource_profile: str = resource_profile
        self._defer_missing_screens: bool = defer_missing_screens
        self._base_screen_data: dict[str, dict[str, Any]] = {}
        self._patches: dict[str, dict[str, Any]] = {}
        self._loaded_screen_names: dict[str, str] = {}

    @property
    def patch_dir(self) -> Path:
        """返回平台独立的画面差异目录。"""
        return Path(os_utils.get_work_dir()) / 'assets' / 'game_data' / 'platform' / self.resource_profile / 'screen_patches'

    def reload(self, from_memory: bool = False, from_separated_files: bool = False) -> None:
        """先按原规则加载公共画面，再应用平台差异并重建索引。"""
        super().reload(from_memory=from_memory, from_separated_files=from_separated_files)
        if from_memory:
            return
        self.exit_scope()
        self.last_screen_name = None
        self.current_screen_name = None
        self._base_screen_data = {
            screen_id: deepcopy(screen.to_dict()) for screen_id, screen in self._id_2_screen.items()
        }
        self._patches.clear()
        if self.patch_dir.is_dir():
            for path in sorted(self.patch_dir.glob('*.yml')):
                with path.open(encoding='utf-8') as file:
                    patch = yaml_utils.safe_load(file)
                if not isinstance(patch, dict) or patch.get('screen_id') != path.stem:
                    raise ValueError(f'平台画面差异的 screen_id 与文件名不一致: {path}')
                self._patches[path.stem] = patch
        self.apply_profile_patches(require_all=not self._defer_missing_screens)

    def load_extra_screen_dir(self, dir_path: str, default_app_id: str = '') -> None:
        """保留插件原数据，插件加载后重新叠加平台差异。"""
        previous_ids = set(self._id_2_screen)
        super().load_extra_screen_dir(dir_path, default_app_id)
        added_ids = self._id_2_screen.keys() - previous_ids
        if not added_ids:
            return
        for screen_id in added_ids:
            self._base_screen_data[screen_id] = deepcopy(self._id_2_screen[screen_id].to_dict())
        self.apply_profile_patches(require_all=not self._defer_missing_screens)

    def apply_profile_patches(self, require_all: bool = True) -> None:
        """应用差异；全部插件加载完成后必须检查每个目标画面存在。"""
        screens = {screen_id: deepcopy(data) for screen_id, data in self._base_screen_data.items()}
        for screen_id, patch in self._patches.items():
            if 'screen' in patch:
                if self._defer_missing_screens and not require_all:
                    continue
                if screen_id in screens:
                    raise ValueError(f'平台新增画面与公共画面 ID 冲突: {screen_id}')
                data = deepcopy(patch['screen'])
                if not isinstance(data, dict) or data.get('screen_id') != screen_id or not data.get('screen_name'):
                    raise ValueError(f'平台新增画面缺少完整元数据: {screen_id}')
                screens[screen_id] = data
                continue
            if screen_id not in screens:
                if require_all:
                    raise ValueError(f'平台差异找不到公共画面: {screen_id}')
                continue
            data = screens[screen_id]
            self._apply_fields(data, patch.get('screen_fields', {}), {'pc_alt', 'app_id'})
            areas = {area['area_name']: area for area in data['area_list']}
            for area_name in patch.get('deleted_areas', []):
                if area_name not in areas:
                    raise ValueError(f'平台差异找不到待删除区域: {screen_id}.{area_name}')
                del areas[area_name]
            for area_name, fields in patch.get('area_patches', {}).items():
                if area_name not in areas:
                    raise ValueError(f'平台差异找不到区域: {screen_id}.{area_name}')
                self._apply_fields(areas[area_name], fields, {
                    'area_type', 'pc_rect', 'text', 'lcs_percent', 'template_sub_dir',
                    'template_id', 'template_match_threshold', 'color_range', 'id_mark',
                    'goto_list', 'gamepad_key',
                })
            for area in patch.get('added_areas', []):
                if not {'area_name', 'area_type', 'pc_rect'} <= area.keys():
                    raise ValueError(f'平台新增区域缺少完整元数据: {screen_id}')
                if area['area_name'] in areas:
                    raise ValueError(f'平台新增区域与公共区域冲突: {screen_id}.{area["area_name"]}')
                areas[area['area_name']] = deepcopy(area)
            data['area_list'] = list(areas.values())
        loaded_screens = {screen_id: ScreenInfo(data) for screen_id, data in screens.items()}
        names = [screen.screen_name for screen in loaded_screens.values()]
        if len(names) != len(set(names)):
            raise ValueError('平台新增画面与已有画面名称冲突')
        self._id_2_screen = loaded_screens
        self._loaded_screen_names = {screen_id: screen.screen_name for screen_id, screen in loaded_screens.items()}
        super().reload(from_memory=True)

    @staticmethod
    def _apply_fields(data: dict[str, Any], fields: dict[str, Any], allowed: set[str]) -> None:
        """叠加已知字段，空值表示清除原有可选字段。"""
        if not isinstance(fields, dict) or fields.keys() - allowed:
            raise ValueError(f'平台画面差异含不支持的字段: {fields}')
        for key, value in fields.items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = deepcopy(value)

    @staticmethod
    def _field_diff(base: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        """只保存值发生变化的字段，缺失字段保存为空值。"""
        return {key: deepcopy(data.get(key)) for key in base.keys() | data.keys() if base.get(key) != data.get(key)}

    def _write_screen_patch(self, screen_info: ScreenInfo) -> None:
        """比较公共数据并写入单个差异文件，禁止修改公共资源。"""
        screen_id = screen_info.screen_id
        if not screen_id or screen_id in {'.', '..'} or '/' in screen_id or '\\' in screen_id:
            raise ValueError(f'无效的画面 ID: {screen_id}')
        if screen_info.old_screen_id and screen_info.old_screen_id != screen_id:
            raise ValueError('平台画面暂不支持修改画面 ID')
        previous_name = self._loaded_screen_names.get(screen_id)
        if previous_name is not None and previous_name != screen_info.screen_name:
            raise ValueError('平台画面暂不支持修改画面名称')
        if not screen_info.screen_name or any(
            name == screen_info.screen_name and loaded_id != screen_id
            for loaded_id, name in self._loaded_screen_names.items()
        ):
            raise ValueError('画面名称不能为空或与已有画面冲突')

        data = screen_info.to_dict()
        base = self._base_screen_data.get(screen_id)
        patch: dict[str, Any] = {'screen_id': screen_id}
        if base is None:
            patch['screen'] = data
        else:
            fields = self._field_diff(
                {key: value for key, value in base.items() if key not in {'screen_id', 'screen_name', 'area_list'}},
                {key: value for key, value in data.items() if key not in {'screen_id', 'screen_name', 'area_list'}},
            )
            if fields:
                patch['screen_fields'] = fields
            base_areas = {area['area_name']: area for area in base['area_list']}
            areas = {area['area_name']: area for area in data['area_list']}
            if len(areas) != len(data['area_list']):
                raise ValueError('同一画面不能包含重名区域')
            area_patches = {
                name: diff for name, area in areas.items()
                if name in base_areas and (diff := self._field_diff(base_areas[name], area))
            }
            if area_patches:
                patch['area_patches'] = area_patches
            added = [area for name, area in areas.items() if name not in base_areas]
            if added:
                patch['added_areas'] = added
            deleted = [name for name in base_areas if name not in areas]
            if deleted:
                patch['deleted_areas'] = deleted
        path = self.patch_dir / f'{screen_id}.yml'
        if len(patch) > 1:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('w', encoding='utf-8') as file:
                yaml.safe_dump(patch, file, allow_unicode=True, sort_keys=False)
            self._patches[screen_id] = patch
        else:
            path.unlink(missing_ok=True)
            self._patches.pop(screen_id, None)
        screen_info.old_screen_id = screen_id
        self._id_2_screen[screen_id] = screen_info
        self._loaded_screen_names[screen_id] = screen_info.screen_name

    def save_screen(self, screen_info: ScreenInfo) -> None:
        """MCP 和管理界面共用入口，只写平台差异并更新内存索引。"""
        self._write_screen_patch(screen_info)
        self.reload(from_memory=True)

    def save(self, screen_id: str | None = None, reload_after_save: bool = True) -> None:
        """兼容批量保存入口，同样只写平台差异。"""
        screens = list(self._id_2_screen.values()) if screen_id is None else [self._id_2_screen[screen_id]]
        for screen in screens:
            self._write_screen_patch(screen)
        if reload_after_save:
            self.reload(from_memory=True)

    def delete_screen(self, screen_id: str, save: bool = True) -> None:
        """首批不支持整画面删除，避免误删公共资源。"""
        raise ValueError('平台画面暂不支持整画面删除，请按区域删除')
