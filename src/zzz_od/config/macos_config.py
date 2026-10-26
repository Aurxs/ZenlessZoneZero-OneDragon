"""PlayCover 客户端的实例级配置，不保存运行时窗口或输入状态。"""

from one_dragon.base.config.yaml_config import YamlConfig


class MacOsConfig(YamlConfig):
    """保存 Mac 窗口采集、OJD 连接和独立镜头校准参数。"""

    def __init__(self, instance_idx: int) -> None:
        """读取指定实例的 Mac 配置。"""
        super().__init__('macos', instance_idx=instance_idx)

    @property
    def ojd_auto_start(self) -> bool:
        """一键配置后允许后台启动，旧配置保持原有行为。"""
        return self.get('ojd_auto_start', False)

    @ojd_auto_start.setter
    def ojd_auto_start(self, value: bool) -> None:
        """保存自动启动选择，不改变 OJD 自身的登录项。"""
        self.update('ojd_auto_start', value)

    @property
    def ojd_cli_path(self) -> str:
        """返回名为 ojd 的 CLI 入口，保留符号链接名。"""
        return self.get('ojd_cli_path', 'ojd')

    @ojd_cli_path.setter
    def ojd_cli_path(self, value: str) -> None:
        """保存 CLI 入口，不解析成 app 主程序。"""
        self.update('ojd_cli_path', value)

    @property
    def bundle_id(self) -> str:
        """返回要绑定的客户端 Bundle ID。"""
        return self.get('bundle_id', 'com.miHoYo.Nap')

    @bundle_id.setter
    def bundle_id(self, value: str) -> None:
        """保存目标客户端身份。"""
        self.update('bundle_id', value)

    @property
    def app_path(self) -> str:
        """返回可选的已安装应用路径；留空使用 PlayCover 默认应用目录。"""
        return self.get('app_path', '')

    @app_path.setter
    def app_path(self, value: str) -> None:
        """保存完整 .app 路径，启动时核对应用标识。"""
        self.update('app_path', value)

    @property
    def launch_timeout_seconds(self) -> int:
        """返回等候游戏窗口的最大秒数，不代表已进入大世界。"""
        return self.get('launch_timeout_seconds', 45)

    @launch_timeout_seconds.setter
    def launch_timeout_seconds(self, value: int) -> None:
        """保存有界的冷启动窗口等待时间。"""
        self.update('launch_timeout_seconds', value)

    @property
    def window_title(self) -> str:
        """返回可选的完整窗口标题；空值选择面积唯一最大的正常尺寸窗口。"""
        return self.get('window_title', '')

    @window_title.setter
    def window_title(self, value: str) -> None:
        """保存严格匹配的标题条件，留空时允许游戏主窗口没有标题。"""
        self.update('window_title', value)

    @property
    def resource_profile(self) -> str:
        """返回客户端资源配置名，资源覆盖由后续流程接入。"""
        return self.get('resource_profile', 'ios_gamepad')

    @resource_profile.setter
    def resource_profile(self, value: str) -> None:
        """保存客户端资源配置名。"""
        self.update('resource_profile', value)

    @property
    def capture_fps(self) -> int:
        """返回窗口采集帧率。"""
        return self.get('capture_fps', 30)

    @capture_fps.setter
    def capture_fps(self, value: int) -> None:
        """保存窗口采集帧率。"""
        self.update('capture_fps', value)

    @property
    def capture_top_inset_pixels(self) -> int:
        """返回已确认的顶部标题栏像素数；零表示采集完整窗口。"""
        return self.get('capture_top_inset_pixels', 0)

    @capture_top_inset_pixels.setter
    def capture_top_inset_pixels(self, value: int) -> None:
        """保存显式裁剪量，不把游戏画面比例错误当作标题栏。"""
        self.update('capture_top_inset_pixels', value)

    @property
    def max_frame_age_seconds(self) -> float:
        """返回允许使用的最大帧龄。"""
        return self.get('max_frame_age_seconds', 0.5)

    @max_frame_age_seconds.setter
    def max_frame_age_seconds(self, value: float) -> None:
        """保存最大帧龄，单位为秒。"""
        self.update('max_frame_age_seconds', value)

    @property
    def turn_distance_per_second(self) -> float:
        """返回满幅右摇杆每秒对应的距离；零表示尚未校准。"""
        return self.get('turn_distance_per_second', 0.0)

    @turn_distance_per_second.setter
    def turn_distance_per_second(self, value: float) -> None:
        """保存 Mac 专用距离校准，不沿用 Windows 鼠标参数。"""
        self.update('turn_distance_per_second', value)

    @property
    def turn_degrees_per_second(self) -> float:
        """返回满幅右摇杆每秒转动角度；零表示尚未校准。"""
        return self.get('turn_degrees_per_second', 0.0)

    @turn_degrees_per_second.setter
    def turn_degrees_per_second(self, value: float) -> None:
        """保存 Mac 专用角度校准。"""
        self.update('turn_degrees_per_second', value)

    @property
    def menu_action_interval_ms(self) -> int:
        """返回手柄界面步骤之间的最小等待，单位毫秒。"""
        return max(0, min(2000, int(self.get('menu_action_interval_ms', 500))))

    @menu_action_interval_ms.setter
    def menu_action_interval_ms(self, value: int) -> None:
        """保存界面操作间隔，不改变战斗中的按键节奏。"""
        if not 0 <= value <= 2000:
            raise ValueError('界面操作间隔须在 0–2000 毫秒之间')
        self.update('menu_action_interval_ms', value)
