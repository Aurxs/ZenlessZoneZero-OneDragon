# macOS 开发与联调工具

手柄探测工具独立于一条龙运行环境，不导入 `ZContext`，也不发送桌面键鼠事件。它们用于区分服务可用、GameController 识别和游戏响应；不能代替完整游戏流程测试。阶段及验收条件见 [macOS 迁移方案](../../docs/develop/zzz/macos_migration.md)，固定版本依据见 [手柄调研](../../docs/develop/zzz/macos_gamepad_research.md)。

## 生成本地 GUI 开发应用

`uv run --no-sync python tools/macos/create_dev_app.py` 只生成 `.debug/macos/OneDragonDev.app`，不会自动启动。它使用固定的当前仓库目录、`src` 搜索路径与 `.venv` Python，在原生可执行文件内部运行现有 GUI；Bundle ID 为 `io.onedragon.zzz.macos.dev`，便于系统和开发工具识别窗口。生成需要 Xcode Command Line Tools，日志写入 `.debug/macos/dev-app.log`。

这是本机开发入口，不复制依赖、不安装到系统，也不作为发行包。移动仓库、更换虚拟环境或 Python 后应重新生成；程序界面与技术栈保持原样。

## 运行一次实战模拟室

当前实例须已选择 Mac 平台并准备好 OCR、闪光模型和 OJD，游戏位于当前桌面且已进入手柄大世界。本入口使用项目的截图、识别、Operation 与自动战斗策略，不依赖 Computer Use。自动切换手柄模式尚待接入。

```shell
PYTHONPATH=src uv run --no-sync python tools/macos/run_combat_simulation.py
```

默认只运行「基础材料 → 调查专项」一次，沿用当前队伍、默认等级及已选中的五卡预设，核对画面消耗为 100 电量，不足则停止。胜利后按 B 完成，逐步返回大世界。`--prepare-only` 只到出战准备页；`--entry simulation` 从已有的预设或出战页开始。可用 `--auto-battle` 指定已有策略，策略必须关闭尚未校准的自动转向；本机默认使用已配置的 `Mac全配队通用`。

2026-10-25 已完成当前桌面的一次完整实机运行，程序返回 `success: true`、`completed_battles: 1`，并确认回到大世界。战斗输入保护及限制见[手柄实战模拟室设计](../../docs/develop/zzz/application/macos_combat_simulation.md)。跨桌面采集、启动时自动切换输入模式及 GUI 一条龙接入仍按[实施进度](../../docs/develop/zzz/macos_migration_progress.md)推进。

## 只读观察 GameController

需要本机 Xcode 或 Command Line Tools，以及支持 GameController 的 macOS。编译产物和缓存放在忽略目录 `.debug/`：

```shell
mkdir -p .debug/macos/swift-module-cache
xcrun swiftc -module-cache-path .debug/macos/swift-module-cache tools/macos/gamecontroller_probe.swift -o .debug/macos/gamecontroller_probe -framework GameController -framework AppKit
.debug/macos/gamecontroller_probe --duration 15 > .debug/macos/gamecontroller.jsonl
```

默认只初始化 Foundation。需要排查运行方式的差异时，可另跑 `.debug/macos/gamecontroller_probe --appkit --duration 15`：它创建 [`NSApplication.shared`](https://developer.apple.com/documentation/appkit/nsapplication/shared) 以连接窗口服务，并设为 [`.prohibited`](https://developer.apple.com/documentation/appkit/nsapplication/activationpolicy-swift.enum/prohibited)，禁止窗口和激活；仍使用同一个主 RunLoop，不调用包含激活处理的 `finishLaunching`/`run`。`started.runtime` 明确记录 `foundation` 或 `appkit`，两种模式均只读，不能把 AppKit 初始化模式视为完整 `.app` 生命周期测试。

若当前进程无法设置禁止激活策略，`--appkit` 会报错并在监听前退出，不能把这次运行记为“枚举 0 台”。本机直接从终端执行曾返回无效策略值 `-1`；应另用包含 `LSBackgroundOnly=1` 的 `.app` 包核实启动方式，该配置与禁止激活策略对应。不通过改成允许激活、调用激活方法或创建窗口来绕过。

默认观察 15 秒，`--duration` 必须大于 0 且不超过 300 秒。观察器先注册连接/断开通知，再枚举已有设备，按对象身份去重编号。它只为本进程开启后台监听，不激活或切换前台应用，不修改 PlayTools 或游戏设置。超时、Ctrl+C、SIGTERM 都会移除通知、恢复回调与后台监听，然后输出 `summary`。

每台支持 `extendedGamepad` 的设备都会记录初始状态、变化状态和退出状态：按钮的 `value`/`pressed`、左右摇杆和方向键的完整 x/y。不存在的可选标准按钮为 `null`；设备附加按钮使用 Apple 暴露的名称。这里记录 Apple 原始坐标，不能直接假定与 OJD 的 Y 方向相同。观察器没有设定玩家编号、震动、设备发现或任何输出操作。

输出为 JSONL，包含 UTC 墙钟 `time` 和单调计时 `elapsed_seconds`。`controllers_seen: 0` 表示本进程未观察到设备，不能说明 HID 设备一定不存在。观察器收到后台输入只证明该观察器可读，游戏失焦后是否收到输入仍需单独验证。

## 查询固定版本 OJD

Python 工具仅使用标准库。先按发行包说明人工安装并检查 **OJD 0.6.0-alpha.1** 的签名和授权；工具不会下载、安装或自动启动 OJD 服务。

通过 OJD 的命令行工具安装入口创建官方 `/usr/local/bin/ojd` 符号链接，然后把该链接传给 `--ojd`；也可人工创建名为 `ojd` 的链接。发行包内的 `OpenJoystickDriver.app/Contents/MacOS/OpenJoystickDriver` 同时承载 GUI 和 CLI，[入口源码](https://github.com/xsyetopz/OpenJoystickDriver/blob/3552be925d7dacef3fd895ac0c6cbf39e9d3cd70/Sources/OpenJoystickDriver/main.swift#L11) 仅在 `argv[0]` 的文件名为 `ojd` 时运行 CLI。工具保留链接的绝对路径，不解析成 app 主程序路径；文件名不是 `ojd` 的入口会被拒绝，以免误开 GUI。

```shell
python3 tools/macos/gamepad_probe.py --ojd /usr/local/bin/ojd > .debug/macos/ojd-status.jsonl
```

不指定 `--action` 时，只执行 `--version` 和 `--json --no-input --no-color --timeout 2 status`。它解析 `service.state`，服务为 `Stopped` 时即使 OJD 退出码是 0，也会明确记录 `running: false`。只读查询本身成功时工具可以退出 0；这不代表设备创建或输入验证通过。显式动作则要求 CLI 和正在运行的服务均为固定版本，服务停止时拒绝执行。

## 显式发送有限动作

只有 `--action neutral/tap/stick/combo` 会运行 feed 并创建独立虚拟手柄。执行前把游戏置于适合观察的画面，关闭其他会消费手柄输入的游戏，再分别记录前台和失焦结果。工具不会切换前台；需要时用 `--delay 5` 留出手动切换时间。

```shell
# 只创建并保持中立状态，配合 GameController 观察器确认枚举。
python3 tools/macos/gamepad_probe.py --ojd /实际路径/ojd --action neutral --duration 1

# South 对应 Xbox A；按 0.1 秒后释放，改 duration 可测长按。
python3 tools/macos/gamepad_probe.py --ojd /实际路径/ojd --action tap --button South --duration 0.1

# 左摇杆向右半幅，保持 1 秒后归零；OJD 的正 Y 向下。
python3 tools/macos/gamepad_probe.py --ojd /实际路径/ojd --action stick --x 0.5 --y 0 --duration 1

# 同时保持摇杆和两个按钮，5 秒后开始，持续 1 秒。
python3 tools/macos/gamepad_probe.py --ojd /实际路径/ojd --action combo --button South --button RightShoulder --x 0.5 --duration 1 --delay 5
```

`--duration` 默认 1 秒，最小 0.008 秒；只有 `neutral` 最多 600 秒，便于观察设备，其他动作仍最多 10 秒。`--delay` 为 0 到 30 秒。`--stick right` 选择右摇杆。`--button` 可重复指定；tap/combo 默认 South。所有动作从中立状态开始，每约 50 毫秒写一次完整状态，包含按钮、方向键、两根摇杆及两个扳机，不使用几秒长的队列帧。正常完成、中断或错误时都尝试写中立帧，然后关闭 stdin，等待 CLI 排空队列并关闭 feed；超时会终止 CLI。日志区分中立帧写入成功与实际释放观察，断线后的释放结果必须由观察器确认。

固定命令为 `ojd --json --no-input --no-color --timeout 2 virtual feed --as game-controller-compatible`。stdin 每行仅为 `VirtualFeedFrame`，不写 socket 专用的 `endpointKeepAlive`。OJD CLI 自己每 0.5 秒进行空 exchange，服务闲置超时为 2 秒。EOF 后 CLI 等待已排队帧执行，再关闭 feed。

**CLI 的 JSON 输出只有震动反馈，没有 ready/accepted 回执。** `feed_process_started` 和 `frame_written` 只说明进程启动、帧写入管道，不能证明虚拟设备创建成功或输入被接受。即使工具退出 0，`device_created`、`accepted`、`release_observed` 仍记为 `unverified`。必须同时检查观察器和游戏画面，分别确认枚举、按钮/摇杆数值、原生手柄界面、失焦响应和停止释放。

两个工具均输出 UTC 墙钟及单调耗时，便于把人工画面记录与日志对齐。工具不采集窗口画面，不判断窗口遮挡后是否继续渲染，也不证明用户同时使用键鼠时游戏仍接收输入；这些检查按迁移方案另记实机结果。


## 当前证据与适用范围

本机 Safari 和游戏均已识别 OJD 虚拟手柄；此前原始持久 CLI 的 East 100ms 返回菜单，游戏后台 South 100ms 进入登录奖励页。该结果证明基础输入链路，不代表战斗、持续后台渲染或完整任务通过。命令行 GameController 观察器曾枚举为 0，不能覆盖实际应用的阳性结果，不再为此扩展排查。

项目现已新增 `GamepadInput`、`OjdGamepadClient`、窗口采集和 `ZMacController`，探测脚本仍保持独立。显式顶部裁剪默认 0，本机确认 56px，账户页可配置；每帧按当前宽高裁顶部并检查 16:9，不要求固定窗口尺寸。Mac GUI 源码入口为 `PYTHONPATH=src uv run --no-sync python -m zzz_od.macos.main`；须先在账户页显式选择 Mac 平台并准备模型。开发阶段、聚焦测试及真实采集结果以[实施进度](../../docs/develop/zzz/macos_migration_progress.md)为准。
