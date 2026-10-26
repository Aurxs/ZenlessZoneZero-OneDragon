"""安装并检查官方已签名 OJD，保留原包与作者身份，不重新签名。"""

from __future__ import annotations

import hashlib
import os
import plistlib
import shlex
import subprocess
import tempfile
from pathlib import Path

from one_dragon.utils import os_utils

OJD_VERSION = '0.6.0-alpha.1'
OJD_SHA256 = 'd2b771ffe4382b7bfd218932c7003227216d334a14154e95976c4f114b1c2056'
OJD_DOWNLOAD_URL = (
    'https://github.com/xsyetopz/OpenJoystickDriver/releases/download/'
    f'{OJD_VERSION}/OpenJoystickDriver-{OJD_VERSION}-macOS.dmg'
)
OJD_APP = Path('/Applications/OpenJoystickDriver.app')
_SIGNATURE_REQUIREMENT = (
    '=anchor apple generic and identifier "com.openjoystickdriver" '
    'and certificate leaf[subject.OU] = "9PQP6CDMQT"'
)


def verify_ojd_app(app: Path) -> None:
    """同时检查版本、完整包签名、作者团队、虚拟 HID 权限及公证。"""
    info = plistlib.loads((app / 'Contents' / 'Info.plist').read_bytes())
    if info.get('CFBundleIdentifier') != 'com.openjoystickdriver' or info.get('CFBundleShortVersionString') != OJD_VERSION:
        raise ValueError(f'只支持官方 OJD {OJD_VERSION}；现有应用保留，请先自行处理版本差异')
    subprocess.run(
        ['codesign', '--verify', '--deep', '--strict', '-R', _SIGNATURE_REQUIREMENT, str(app)],
        capture_output=True, check=True, timeout=20,
    )
    result = subprocess.run(
        ['codesign', '-d', '--entitlements', '-', '--xml', str(app)],
        capture_output=True, check=True, timeout=5,
    )
    entitlements = plistlib.loads(result.stdout)
    if entitlements.get('com.apple.developer.hid.virtual.device') is not True:
        raise ValueError('官方组件缺少虚拟 HID 权限，已拒绝使用')
    subprocess.run(
        ['spctl', '--assess', '--type', 'execute', str(app)],
        capture_output=True, check=True, timeout=30,
    )


def verify_ojd_download(dmg: Path) -> None:
    """用固定官方发布哈希拒绝损坏或版本变化的安装包。"""
    with dmg.open('rb') as file:
        actual = hashlib.file_digest(file, 'sha256').hexdigest()
    if actual != OJD_SHA256:
        raise ValueError('OJD 下载校验失败，未安装或执行下载内容')


def _install_app(source: Path) -> None:
    """只在不存在同名安装时复制完整签名包；需要时由系统请求管理员授权。"""
    if OJD_APP.exists():
        raise FileExistsError('已有 OJD 安装，拒绝覆盖')
    # 先在目标卷暂存，最终 rename 保证不会暴露半复制应用。
    staging = OJD_APP.parent / '.OneDragon-OJD-install'
    if staging.exists():
        raise FileExistsError(f'发现上次未完成的安装目录：{staging}，请人工检查后再试')
    commands = [
        ['/usr/bin/ditto', str(source), str(staging / OJD_APP.name)],
        ['/bin/mv', '-n', str(staging / OJD_APP.name), str(OJD_APP.parent)],
        ['/bin/rmdir', str(staging)],
    ]
    if os.access(OJD_APP.parent, os.W_OK):
        for command in commands:
            subprocess.run(command, capture_output=True, check=True, timeout=60)
    else:
        script = ' && '.join(shlex.join(command) for command in commands)
        # AppleScript 字符串与 shell 参数分别转义；不使用密码、sudo 或用户脚本。
        literal = script.replace('\\', '\\\\').replace('"', '\\"')
        subprocess.run(
            ['osascript', '-e', f'do shell script "{literal}" with administrator privileges'],
            capture_output=True, check=True, timeout=180,
        )
    if staging.exists():
        raise FileExistsError('安装时出现同名应用，已保留原安装；暂存目录需人工检查')


def install_ojd() -> Path:
    """一键安装入口；已有合格版本直接复用，不启服务、不创建设备、不注册 USB 扩展。"""
    directory = Path(os_utils.get_work_dir()) / '.install' / 'ojd'
    directory.mkdir(parents=True, exist_ok=True)
    if not OJD_APP.exists():
        dmg = directory / f'OpenJoystickDriver-{OJD_VERSION}-macOS.dmg'
        if not dmg.exists():
            partial = dmg.with_suffix('.download')
            try:
                subprocess.run(
                    ['curl', '-fL', '--silent', '--show-error', '--retry', '2', '--max-time', '180',
                     OJD_DOWNLOAD_URL, '-o', str(partial)],
                    capture_output=True, check=True, timeout=200,
                )
                verify_ojd_download(partial)
                partial.replace(dmg)
            finally:
                partial.unlink(missing_ok=True)
        verify_ojd_download(dmg)
        with tempfile.TemporaryDirectory(prefix='onedragon-ojd-') as temporary:
            mount = Path(temporary) / 'volume'
            subprocess.run(
                ['hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint', str(mount), str(dmg)],
                capture_output=True, check=True, timeout=30,
            )
            try:
                app = mount / OJD_APP.name
                verify_ojd_app(app)
                _install_app(app)
            finally:
                subprocess.run(['hdiutil', 'detach', str(mount)], capture_output=True, check=True, timeout=30)
    verify_ojd_app(OJD_APP)
    # 不写 /usr/local/bin，项目持有自己的 ojd 链接，并保留 argv[0] 名称。
    executable = OJD_APP / 'Contents' / 'MacOS' / 'OpenJoystickDriver'
    link = directory / 'ojd'
    if link.is_symlink() and link.resolve() == executable:
        return link
    if link.exists() or link.is_symlink():
        raise FileExistsError(f'已有其他命令入口，未覆盖：{link}')
    link.symlink_to(executable)
    return link
