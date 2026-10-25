"""Apple Silicon 上的源码入口，复用公共 Qt 界面。"""

import platform
import sys


def main() -> None:
    """检查宿主后启动界面；平台配置由用户在账户管理中选择。"""
    if sys.platform != 'darwin' or platform.machine().lower() not in ('arm64', 'aarch64'):
        raise SystemExit('Mac 源码入口需要 Apple Silicon macOS 和原生 arm64 Python')

    from zzz_od.gui.app import main as gui_main

    gui_main()


if __name__ == '__main__':
    main()
