from __future__ import annotations

import sys
from functools import cached_property
from typing import TYPE_CHECKING

from one_dragon.base.operation.one_dragon_context import OneDragonContext

if TYPE_CHECKING:
    from zzz_od.config.macos_config import MacOsConfig
    from zzz_od.macos.game_session_preparation import MacGameSessionPreparation
    from zzz_od.macos.manual_gamepad import ManualGamepadSession
    from zzz_od.macos.predefined_team_preview import MacPredefinedTeamPreview


class ZContext(OneDragonContext):

    def __init__(self,):

        OneDragonContext.__init__(self)
        self.macos_predefined_team_preview: MacPredefinedTeamPreview | None = None

        if sys.platform == 'darwin':
            from one_dragon.base.screen.profile_screen_context import (
                ProfileScreenContext,
            )
            self.screen_loader = ProfileScreenContext(
                self.macos_config.resource_profile, defer_missing_screens=True,
            )

        # 后续所有用到自动战斗的 都统一设置到这个里面
        from zzz_od.auto_battle.auto_battle_context import AutoBattleContext
        self.auto_battle_context: AutoBattleContext = AutoBattleContext(self)

    def init(self) -> None:
        """Mac 先要求明确的平台配置，再开始模型下载与服务初始化。"""
        from one_dragon.base.config.game_account_config import GamePlatformEnum

        if (sys.platform == 'darwin'
                and self.game_account_config.platform != GamePlatformEnum.MACOS_PLAYCOVER.value.value):
            self.ready_for_application = False
            self.initialization_error = '请在账户管理中将游戏平台设为 macOS PlayCover，然后重新启动一条龙'
            return
        super().init()

    def get_application_unavailable_reason(self, app_id: str) -> str | None:
        """为运行界面提供平台限制，不改变页面、任务注册或配置。"""
        from zzz_od.macos.application_capabilities import (
            get_macos_app_unavailable_reason,
        )

        return get_macos_app_unavailable_reason(app_id)

    #------------------- 需要懒加载的都使用 @cached_property -------------------#

    #------------------- 以下是 游戏/脚本级别的 -------------------#

    @cached_property
    def model_config(self):
        from zzz_od.config.model_config import ModelConfig
        return ModelConfig(self.repo_config)

    @cached_property
    def map_service(self):
        from zzz_od.game_data.map_area import MapAreaService
        return MapAreaService()

    @cached_property
    def compendium_service(self):
        from zzz_od.game_data.compendium import CompendiumService
        return CompendiumService()

    @cached_property
    def world_patrol_service(self):
        from zzz_od.application.world_patrol.world_patrol_service import (
            WorldPatrolService,
        )
        return WorldPatrolService(self)

    @cached_property
    def telemetry(self):
        from zzz_od.telemetry.telemetry_manager import TelemetryManager
        return TelemetryManager(self)

    @cached_property
    def lost_void(self):
        from zzz_od.application.hollow_zero.lost_void.context.lost_void_context import (
            LostVoidContext,
        )
        return LostVoidContext(self)

    @cached_property
    def withered_domain(self):
        from zzz_od.application.hollow_zero.withered_domain.withered_domain_context import (
            WitheredDomainContext,
        )
        return WitheredDomainContext(self)

    #------------------- 以下是 账号实例级别的 需要在 reload_instance_config 中刷新 -------------------#

    @cached_property
    def game_config(self):
        from zzz_od.config.game_config import GameConfig
        return GameConfig(self.current_instance_idx)

    @cached_property
    def macos_config(self) -> MacOsConfig:
        """按账号实例读取 Mac 采集和手柄连接配置。"""
        from zzz_od.config.macos_config import MacOsConfig
        return MacOsConfig(self.current_instance_idx)

    @cached_property
    def macos_session_preparation(self) -> MacGameSessionPreparation:
        """复用同一次运行的模式确认，停止后再次开始必须重新准备。"""
        from zzz_od.macos.game_session_preparation import MacGameSessionPreparation

        return MacGameSessionPreparation(self)

    @cached_property
    def manual_gamepad(self) -> ManualGamepadSession:
        """手动控制与自动应用共用一个运行上下文和控制器。"""
        from zzz_od.macos.manual_gamepad import ManualGamepadSession

        return ManualGamepadSession(self)

    @cached_property
    def team_config(self):
        from zzz_od.config.team_config import TeamConfig
        return TeamConfig(self.current_instance_idx)

    @cached_property
    def battle_assistant_config(self):
        from zzz_od.application.battle_assistant.battle_assistant_config import (
            BattleAssistantConfig,
        )
        return BattleAssistantConfig(self.current_instance_idx)

    def reload_instance_config(self) -> None:
        """刷新实例配置；Mac 控制器先释放输入，再重新构造绑定服务。"""
        self.macos_predefined_team_preview = None
        if 'manual_gamepad' in self.__dict__:
            self.manual_gamepad.stop()
        rebuild_macos_controller = sys.platform == 'darwin' and self.controller is not None
        if rebuild_macos_controller:
            if not self.run_context.is_context_stop:
                self.run_context.stop_running()
            self.controller.cleanup_after_app_shutdown()
            self.controller = None

        OneDragonContext.reload_instance_config(self)

        to_clear_props = [
            'game_config',
            'macos_config',
            'team_config',
            'battle_assistant_config',
        ]
        for prop in to_clear_props:
            if prop in self.__dict__:
                del self.__dict__[prop]

        if sys.platform == 'darwin':
            from one_dragon.base.screen.profile_screen_context import (
                ProfileScreenContext,
            )

            self.screen_loader = ProfileScreenContext(
                self.macos_config.resource_profile, defer_missing_screens=True,
            )
            self.screen_loader.reload()
            self._load_plugin_screens()

        if rebuild_macos_controller:
            self.init_controller()

    def _load_plugin_screens(self) -> None:
        """插件加载完成后应用 Mac 差异，并更新依赖画面的缓存。"""
        super()._load_plugin_screens()
        if sys.platform == 'darwin':
            self.screen_loader.apply_profile_patches()
            self.template_loader.template.clear()
            self.__dict__.pop('cv_service', None)
            self.auto_battle_context.init_screen_area()

    def _get_win_title(self) -> str:
        """获取当前配置对应的窗口标题"""
        if self.game_account_config.use_custom_win_title:
            return self.game_account_config.custom_win_title
        from one_dragon.base.config.game_account_config import GameRegionEnum
        if self.game_account_config.game_region == GameRegionEnum.CN.value.value \
                or self.game_account_config.game_region == GameRegionEnum.CNB.value.value:
            return '绝区零'
        else:
            return 'ZenlessZoneZero'

    def on_switch_instance(self) -> None:
        """
        切换实例后更新 controller 的窗口标题和账号配置
        """
        if sys.platform == 'darwin':
            self.init_controller()
            return

        from zzz_od.controller.zzz_pc_controller import ZPcController

        controller = self.controller
        if not isinstance(controller, ZPcController):
            return

        new_win_title = self._get_win_title()
        controller.set_window_title(new_win_title)
        controller.sync_game_config(self.game_config)

    def init_controller(self) -> None:
        """按系统和显式客户端配置创建控制器，不自动改写原 PC 配置。"""
        from one_dragon.base.config.game_account_config import GamePlatformEnum
        if sys.platform == 'darwin':
            if self.game_account_config.platform != GamePlatformEnum.MACOS_PLAYCOVER.value.value:
                raise RuntimeError('当前账号仍使用 PC 平台，请先将 platform 设置为 macos_playcover')
            from zzz_od.controller.zzz_macos_controller import ZMacController

            if (isinstance(self.controller, ZMacController)
                    and self.controller.game_config is self.game_config
                    and self.controller.macos_config is self.macos_config):
                return
            if self.controller is not None:
                self.controller.cleanup_after_app_shutdown()
            self.controller = ZMacController(
                game_config=self.game_config,
                macos_config=self.macos_config,
                standard_width=self.project_config.screen_standard_width,
                standard_height=self.project_config.screen_standard_height,
            )
            return

        if self.game_account_config.platform == GamePlatformEnum.MACOS_PLAYCOVER.value.value:
            raise RuntimeError('macos_playcover 平台只能在 macOS 上运行')
        if self.game_account_config.platform == GamePlatformEnum.PC.value.value:
            if self.controller is not None:
                self.controller.cleanup_after_app_shutdown()
            from zzz_od.controller.zzz_pc_controller import ZPcController
            self.controller: ZPcController = ZPcController(
                game_config=self.game_config,
                screenshot_method=self.env_config.screenshot_method,
                standard_width=self.project_config.screen_standard_width,
                standard_height=self.project_config.screen_standard_height
            )
            # 初始化窗口标题
            self.controller.set_window_title(self._get_win_title())

    def init_for_application(self) -> None:
        self.map_service.reload()  # 传送需要用的数据
        self.compendium_service.reload()  # 快捷手册
        self.auto_battle_context.init_screen_area()  # 自动战斗相关的区域 依赖 ScreenLoader

    def init_others(self) -> None:
        self.telemetry.initialize()  # 遥测

    def after_app_shutdown(self) -> None:
        """
        App关闭后进行的操作 关闭一切可能资源操作
        """
        if 'manual_gamepad' in self.__dict__:
            self.manual_gamepad.stop()
        if hasattr(self, 'telemetry') and self.telemetry:
            self.telemetry.shutdown()

        # 上层清理依赖框架服务(如 StateRecordService)，必须先于框架清理
        self.withered_domain.after_app_shutdown()
        self.auto_battle_context.after_app_shutdown()

        from zzz_od.auto_battle.auto_battle_operator import AutoBattleOperator
        AutoBattleOperator.after_app_shutdown()

        OneDragonContext.after_app_shutdown(self)
