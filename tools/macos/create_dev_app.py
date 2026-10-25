"""为本地源码 GUI 生成有明确 Bundle ID 的开发 .app，不复制依赖或自动启动。"""

from __future__ import annotations

import argparse
import json
import plistlib
import subprocess
import sys
from pathlib import Path

DEFAULT_BUNDLE_ID: str = 'io.onedragon.zzz.macos.dev'
EXECUTABLE_NAME: str = 'OneDragonDev'


def launcher_source(repo_root: Path) -> str:
    """用 C 字符串转义固定路径，原生进程内运行现有 Python 以保留应用身份。"""
    repo = json.dumps(str(repo_root), ensure_ascii=False)
    python = json.dumps(str(repo_root / '.venv' / 'bin' / 'python'), ensure_ascii=False)
    source = json.dumps(str(repo_root / 'src'), ensure_ascii=False)
    log = json.dumps(str(repo_root / '.debug' / 'macos' / 'dev-app.log'), ensure_ascii=False)
    return f'''#import <Foundation/Foundation.h>
#include <Python.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main(int argc, char **argv) {{
    @autoreleasepool {{
        if (chdir({repo}) != 0) {{ perror("OneDragon chdir"); return 1; }}
        if (freopen({log}, "a", stdout) == NULL) return 1;
        if (freopen({log}, "a", stderr) == NULL) return 1;
        setvbuf(stdout, NULL, _IONBF, 0);
        setvbuf(stderr, NULL, _IONBF, 0);
        setenv("PYTHONPATH", {source}, 1);
        setenv("PYTHONUNBUFFERED", "1", 1);
        setenv("QT_QPA_PLATFORM", "cocoa", 1);
        unsetenv("PYTHONHOME");
        unsetenv("__PYVENV_LAUNCHER__");
        fprintf(stderr, "OneDragon development app: %s\\n",
            [[[NSBundle mainBundle] bundleIdentifier] UTF8String]);
        [[NSProcessInfo processInfo] setProcessName:@"OneDragonDev"];

        PyConfig config;
        PyConfig_InitPythonConfig(&config);
        config.parse_argv = 0;
        PyStatus status = PyConfig_SetBytesString(&config, &config.program_name, {python});
        if (!PyStatus_Exception(status))
            status = PyConfig_SetBytesString(&config, &config.executable, {python});
        if (!PyStatus_Exception(status))
            status = PyConfig_SetString(&config, &config.run_module, L"zzz_od.macos.main");
        if (!PyStatus_Exception(status)) status = Py_InitializeFromConfig(&config);
        PyConfig_Clear(&config);
        if (PyStatus_Exception(status)) Py_ExitStatusException(status);
        return Py_RunMain();
    }}
}}
'''


def create_dev_app(repo_root: Path, output: Path | None = None) -> Path:
    """使用当前仓库虚拟环境的头文件和动态库编译小型开发启动器。"""
    repo_root = repo_root.resolve(strict=True)
    python = repo_root / '.venv' / 'bin' / 'python'
    if not python.is_file() or not (repo_root / 'src' / 'zzz_od' / 'macos' / 'main.py').is_file():
        raise ValueError('请指定已创建 .venv 且含 Mac 源码入口的仓库目录')
    query = (
        'import json,sysconfig; print(json.dumps({'
        '"include":sysconfig.get_config_var("INCLUDEPY"),'
        '"libdir":sysconfig.get_config_var("LIBDIR"),'
        '"library":sysconfig.get_config_var("LDLIBRARY")}))'
    )
    result = subprocess.run([str(python), '-c', query], check=True, capture_output=True, text=True)
    build = json.loads(result.stdout)
    include = Path(build['include'])
    library = Path(build['libdir']) / build['library']
    if not (include / 'Python.h').is_file() or not library.is_file() or library.suffix != '.dylib':
        raise ValueError('当前虚拟环境的 Python 缺少嵌入式启动所需的 Python.h 或动态库')

    bundle = (output or repo_root / '.debug' / 'macos' / 'OneDragonDev.app').absolute()
    contents = bundle / 'Contents'
    executable = contents / 'MacOS' / EXECUTABLE_NAME
    executable.parent.mkdir(parents=True, exist_ok=True)
    (contents / 'Resources').mkdir(exist_ok=True)
    (repo_root / '.debug' / 'macos').mkdir(parents=True, exist_ok=True)
    source = contents / 'Resources' / 'launcher.m'
    source.write_text(launcher_source(repo_root), encoding='utf-8')
    subprocess.run([
        'xcrun', 'clang', '-fobjc-arc', '-I', str(include), str(source), str(library),
        '-framework', 'Foundation', '-Xlinker', '-rpath', '-Xlinker', str(library.parent),
        '-o', str(executable),
    ], check=True)
    executable.chmod(0o755)
    with (contents / 'Info.plist').open('wb') as stream:
        plistlib.dump({
            'CFBundleIdentifier': DEFAULT_BUNDLE_ID,
            'CFBundleExecutable': EXECUTABLE_NAME,
            'CFBundleName': EXECUTABLE_NAME,
            'CFBundleDisplayName': 'OneDragon Dev',
            'CFBundlePackageType': 'APPL',
            'CFBundleInfoDictionaryVersion': '6.0',
            'CFBundleVersion': '1',
            'CFBundleShortVersionString': '0.1',
            'LSMinimumSystemVersion': '12.3',
            'NSHighResolutionCapable': True,
            'LSMultipleInstancesProhibited': True,
        }, stream)
    (contents / 'PkgInfo').write_bytes(b'APPL????')
    return bundle


def main() -> int:
    """只生成开发应用，启动与真实 GUI 检查由调用者明确执行。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('开发 .app 包装器仅支持在 macOS 上生成')
    print(create_dev_app(args.repo, args.output))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
