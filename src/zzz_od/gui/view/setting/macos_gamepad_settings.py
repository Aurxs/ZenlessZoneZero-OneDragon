"""Mac 手柄安装与显式连接控件；页面打开时只读本地状态。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from qfluentwidgets import FluentIcon

from one_dragon.base.controller.macos.ojd_gamepad_client import OjdGamepadClient
from one_dragon.base.controller.macos.ojd_service import install_ojd
from one_dragon.base.operation.context_notify_event import ContextNotifyEvent
from one_dragon.utils.log_utils import log
from one_dragon_qt.widgets.setting_card.push_setting_card import PushSettingCard
from one_dragon_qt.widgets.setting_card.switch_setting_card import SwitchSettingCard
from one_dragon_qt.widgets.setting_card.text_setting_card import TextSettingCard

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtWidgets import QWidget
    from qfluentwidgets import SettingCardGroup

    from zzz_od.context.zzz_context import ZContext

# 无父对象的工作线程保持到 finished，防止关闭页面时销毁运行中的 QThread。
_WORKERS: set[ServiceWorker] = set()


class ServiceWorker(QThread):
    """在后台进行有界进程调用，不阻塞界面处理系统授权弹窗。"""

    result_ready = Signal(str, object)

    def __init__(self, action: Callable[[], tuple[str, str | None]]) -> None:
        """接收已经确定的操作，不在工作线程访问 Qt 控件。"""
        super().__init__()
        self.action: Callable[[], tuple[str, str | None]] = action

    def run(self) -> None:
        """操作错误转成界面诊断；不吞掉日志。"""
        try:
            message, path = self.action()
        except Exception as error:
            log.error('Mac 手柄服务操作失败', exc_info=True)
            message, path = str(error), None
        self.result_ready.emit(message, path)


class MacGamepadSettings(QObject):
    """沿用实例配置；不自建额外游戏手柄，连接由控制器持有。"""

    def __init__(self, ctx: ZContext, group: SettingCardGroup, parent: QWidget) -> None:
        """安装普通 Fluent 设置卡，不启动设备或服务。"""
        super().__init__(parent)
        self.ctx: ZContext = ctx
        self.worker: ServiceWorker | None = None
        self.path: TextSettingCard = TextSettingCard(
            icon=FluentIcon.FOLDER, title='手柄组件路径',
            content='一键配置后自动填写，通常无需修改',
        )
        self.path.value_changed.connect(self._config_changed)
        self.auto_start: SwitchSettingCard = SwitchSettingCard(
            icon=FluentIcon.PLAY, title='自动启动手柄服务',
            content='开始任务时自动启动所需组件，无需另外打开 OJD',
        )
        self.auto_start.value_changed.connect(self._config_changed)
        self.install: PushSettingCard = PushSettingCard(
            icon=FluentIcon.DOWNLOAD, title='安装 / 检查 OJD 官方组件', text='一键配置',
            content='约 29 MB，保留作者签名；首次系统权限需手动确认，不安装 USB 驱动扩展',
        )
        self.install.clicked.connect(self._install)
        self.inspect: PushSettingCard = PushSettingCard(
            icon=FluentIcon.INFO, title='服务与权限诊断', text='检查', content='尚未检查；检查不会创建设备',
        )
        self.inspect.clicked.connect(self._inspect)
        self.connect: PushSettingCard = PushSettingCard(
            icon=FluentIcon.PLAY, title='手柄状态', text='连接手柄',
            content='未连接；连接后不会自动操作游戏',
        )
        self.connect.clicked.connect(self._connect)
        self.stop: PushSettingCard = PushSettingCard(
            icon=FluentIcon.CLOSE, title='停止与释放', text='断开', content='释放本实例输入，取消已有保持动作',
        )
        self.stop.clicked.connect(self._stop)
        self.cards: list[QWidget] = [self.install, self.auto_start, self.path, self.inspect, self.connect, self.stop]
        for card in self.cards:
            group.addSettingCard(card)
        self.timer: QTimer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._refresh_connection)
        self.timer.start()

    def reload(self) -> None:
        """读取实例配置，初始化控件时不触发连接操作。"""
        config = self.ctx.macos_config
        self.path.init_with_adapter(config.get_prop_adapter('ojd_cli_path'))
        self.auto_start.init_with_adapter(config.get_prop_adapter('ojd_auto_start'))

    def _config_changed(self, value: str | bool) -> None:
        """只重建输入控制器，保留已经完成的应用初始化。"""
        if not self.ctx.run_context.is_context_stop:
            self.ctx.run_context.stop_running()
        if self.ctx.controller is not None:
            self.ctx.controller.cleanup_after_app_shutdown()
            self.ctx.controller = None
        if self.ctx.ready_for_application:
            self.ctx.init_controller()
        event = ContextNotifyEvent.info('手柄配置已保存', '下次连接使用新配置')
        self.ctx.dispatch_event(ContextNotifyEvent.EVENT_ID, event)

    def _run(self, action: Callable[[], tuple[str, str | None]]) -> None:
        """串行处理按钮操作，运行期间禁止修改本页配置。"""
        if self.worker is not None:
            return
        self.parent().setEnabled(False)
        self.inspect.setContent('正在处理，请等待；系统授权弹窗需要本人确认')
        worker = ServiceWorker(action)
        self.worker = worker
        _WORKERS.add(worker)
        worker.result_ready.connect(self._result)
        worker.finished.connect(self._finished)
        worker.finished.connect(lambda: _WORKERS.discard(worker))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _result(self, message: str, path: str | None) -> None:
        """主线程保存安装结果；一次配置后即可按需后台启动。"""
        if path is not None:
            if not self.ctx.run_context.is_context_stop:
                self.inspect.setContent('官方组件已安装；请停止任务后再次点击一键配置，应用连接参数')
                return
            self.ctx.macos_config.ojd_cli_path = path
            self.ctx.macos_config.ojd_auto_start = True
            self._config_changed(path)
            self.reload()
        self.inspect.setContent(message)

    def _finished(self) -> None:
        """恢复控件，后续连接仍由用户或任务显式触发。"""
        self.worker = None
        self.parent().setEnabled(True)
        self._refresh_connection()

    def _require_stopped(self) -> bool:
        """连接变更不得与正在运行的任务竞争。"""
        if self.ctx.run_context.is_context_stop:
            return True
        self.inspect.setContent('请先停止当前任务，再安装或更改手柄连接')
        return False

    def _install(self) -> None:
        """显式按钮触发固定官方组件安装，不在打开页面时下载。"""
        if self._require_stopped():
            self._run(lambda: ('官方组件校验通过，已配置按需启动；首次使用请确认系统输入权限', str(install_ojd())))

    def _inspect(self) -> None:
        """只读检查 OJD，不干扰正在运行的手柄。"""
        client = OjdGamepadClient(self.ctx.macos_config.ojd_cli_path)

        def action() -> tuple[str, None]:
            status = client.inspect()
            running = status['service'].get('state') == 'Running'
            permissions = status.get('permissions', {})
            read = '已允许' if permissions.get('inputRead') == 'Granted' else '待授权'
            inject = '已允许' if permissions.get('inputInject') == 'Granted' else '待授权'
            message = f'服务：{"运行中" if running else "未运行"}；输入监控：{read}；输入控制：{inject}'
            return message, None

        self._run(action)

    def _connect(self) -> None:
        """使用实例控制器的同一手柄，只连接并暂停在中立状态。"""
        if not self._require_stopped():
            return
        try:
            self.ctx.init_controller()
        except Exception as error:
            log.error('Mac 手柄控制器构造失败', exc_info=True)
            self.inspect.setContent(str(error))
            return
        gamepad = self.ctx.controller.gamepad

        def action() -> tuple[str, None]:
            try:
                gamepad.connect()
                gamepad.suspend()
            except Exception:
                gamepad.close()
                raise
            return '手柄已连接，可以点击“准备游戏”进入游戏', None

        self._run(action)

    def _stop(self) -> None:
        """任务停止后关闭同一个输入，不停止全局 OJD 或其他设备。"""
        if not self._require_stopped() or self.ctx.controller is None:
            return
        controller = self.ctx.controller

        def action() -> tuple[str, None]:
            controller.cleanup_after_app_shutdown()
            return '本实例手柄已归零并释放', None

        self._run(action)

    def _refresh_connection(self) -> None:
        """定时只读进程存活与最近错误，不发状态帧或启动进程。"""
        if self.worker is not None:
            return
        controller = self.ctx.controller
        gamepad = getattr(controller, 'gamepad', None)
        connected = gamepad is not None and gamepad.is_connected is True
        self.connect.button.setText('已连接' if connected else '连接手柄')
        self.connect.button.setEnabled(not connected)
        self.connect.setContent('已连接，可以开始准备游戏' if connected else '未连接；连接后不会自动操作游戏')
        if gamepad is not None and isinstance(gamepad.last_error, str) and gamepad.last_error:
            self.inspect.setContent(gamepad.last_error)
