# macOS 原生手柄方案调研

核实日期：2026-10-25。用途：为 [macOS 迁移方案](macos_migration.md) 选择第一轮输入验证对象。

本次只读取 GitHub 元数据、源码、发布说明与官方文档，没有安装驱动、运行发布包或操作游戏。下文的“支持”须区分源码能力、维护者报告与本项目实机验证；目前没有候选通过本项目的 PlayCover《绝区零》验证。

## 1. 选择结论

优先验证 **OpenJoystickDriver（OJD）0.6.0-alpha.1** 的 `GameControllerCompatible` 输出。它已有无需实体手柄的脚本输入接口，当前源码提供 Apple GameController 兼容的 Xbox 身份，最贴近“原生手柄界面、不抢键鼠”的目标。

相关输出在 2026-10-23 才加入并修正，仍是 alpha 功能。第一轮只验证固定发布版本，不把“项目很新”当作稳定性的证明，也不自动跟随它的主分支升级。

备选为 **LizardByte/libvirtualhid**：有官方提供的已签名 broker（负责创建虚拟设备的本机服务），但需要机器许可证，且 broker 并非 MIT 许可。可作为独立候选验证，不在本次下载、购买或集成。

WaveBird、Steam Controller Bridge 和 Satellite 主要提供实现参考。旧的 foohid、内核扩展教程不作为首版依据。

用户已验证蓝牙手柄以 Xbox 兼容方式操作游戏，推测为 Xbox 360 协议。该信息记录为 **Xbox 兼容输入已验证，具体设备协议待确认**。后续记录设备型号、VID/PID、GameController 识别结果和实际按键；游戏显示 Xbox 图标不能单独证明使用 Xbox 360 协议。

## 2. 近期项目对比

日期取实际提交或 release，不用 GitHub `updated_at` 代替代码维护时间。系统要求来自各项目，不能视为本项目已覆盖的系统范围。

| 项目 | 核实的近期版本或提交 | 脚本输入 | 系统与许可 | 本次结论 |
|---|---|---|---|---|
| [OpenJoystickDriver](https://github.com/xsyetopz/OpenJoystickDriver/releases/tag/0.6.0-alpha.1) | 2026-10-23，`3552be9`，0.6.0-alpha.1 | CLI JSONL、Unix socket、WebSocket | macOS 12+；MIT；源码工具链 Swift 6.4 | 首选验证；原生 GameController 输出刚加入，需核验发行包签名及游戏行为 |
| [libvirtualhid](https://github.com/LizardByte/libvirtualhid/releases/tag/v2026.1022.2339.24) | 发布 2026-10-23，`45c9b4d`；Mac broker 有 2026-09 的实际功能提交 | C++ library 经本机 broker 发送状态 | 有 universal Mac 发布包；library 为 MIT，broker 为 LB-SAL；需要机器许可证 | 第二候选；未确认 PlayCover 兼容性、最低可用系统和本机许可条件 |
| [WaveBird](https://github.com/murphyjt/wavebird/releases/tag/v0.9.0) | 2026-08-31，`b04a072`，v0.9.0 | 未找到公开 feed/IPC；输入来自实体 Switch 2 手柄 | 工程最低 macOS 15；Swift 6.2；MIT | CoreHID 输出代码可参考；不是现成自动化输入服务 |
| [Steam Controller Bridge](https://github.com/tkubicz/steam-controller-bridge/releases/tag/v1.10.0) | release 2026-08-27；主分支 2026-08-28，`5490822` | 独立 JSONL helper、模拟器与重放 | macOS 13+；Rust；MIT | 协议设计可参考；普通系统保护下的虚拟后端授权尚未解决 |
| [Satellite](https://github.com/TinkerNorth/satellite/releases/tag/2.1.6) | release 2026-10-18；主分支 2026-10-19，`d3ac0fc` | HTTPS 会话与 UDP 输入 | macOS 10.15+；C++17；LGPL-3.0-or-later | Mac 发布物仍为 unsigned stub，不能作为可用接收器安装 |

另外检查了两个 2026 年项目：

- [runzerobass/SteamControllerBridgeMac](https://github.com/runzerobass/SteamControllerBridgeMac/blob/5c7e0733e9a9de5911d451c6942618e624c0fc7b/README.md)，实际最新提交 2026-06-12。README 明确其输出面向 SDL，GameController 消费方看不到该虚拟手柄，不选作 PlayCover 后端。
- [rowizcode/Mac-GamingStream-RemoteDesktop](https://github.com/rowizcode/Mac-GamingStream-RemoteDesktop/blob/3e57ab43dcb60d6f1926ab4c2bf72a989134931d/README.md)，实际最新提交 2026-08-13。当前公开构建的虚拟手柄路径要求改变 AMFI/启动保护，不能作为面向普通用户的默认依赖。本次不执行其安装脚本或系统配置命令。

## 3. OJD 的具体接入依据

已追踪的源码链路：

`Python → CLI 或本机 socket → VirtualFeedRegistry → GameControllerCompatible → IOHIDUserDevice`

这里创建的是独立虚拟手柄，不要求读取、占用或修改用户的蓝牙手柄。

### 3.1 已证实的代码能力

- [`VirtualFeedCommand`](https://github.com/xsyetopz/OpenJoystickDriver/blob/3552be925d7dacef3fd895ac0c6cbf39e9d3cd70/Sources/OpenJoystickDriverCLI/Commands/Virtual/VirtualFeedCommand.swift) 的 `--as` 接受 `VirtualHIDProfileID`，向服务打开独立 feed。
- [`VirtualFeedRegistry.open`](https://github.com/xsyetopz/OpenJoystickDriver/blob/3552be925d7dacef3fd895ac0c6cbf39e9d3cd70/Sources/OpenJoystickDriverService/Runtime/VirtualFeedRegistry.swift) 接受 `GameControllerCompatible`，无需实体输入设备。
- [`GameControllerCompatible` 设备描述](https://github.com/xsyetopz/OpenJoystickDriver/blob/3552be925d7dacef3fd895ac0c6cbf39e9d3cd70/Resources/VirtualDevices/virtual-device.game-controller-compatible.json) 使用 Xbox Series Bluetooth 报告格式，VID/PID 为 `045E:0B13`。不要换成默认 SDL 身份，也不要因为用户猜测 Xbox 360 就强制使用 360 输出。
- [`EndpointServer+Handshake`](https://github.com/xsyetopz/OpenJoystickDriver/blob/3552be925d7dacef3fd895ac0c6cbf39e9d3cd70/Sources/OpenJoystickDriverService/Runtime/Endpoint/EndpointServer%2BHandshake.swift) 同样接受三种输出身份。SDK 文档仍称 feed 只接受 Generic / SDLCompatible，落后于这份源码。
- [`IOHIDVirtualDevicePublisher`](https://github.com/xsyetopz/OpenJoystickDriver/blob/3552be925d7dacef3fd895ac0c6cbf39e9d3cd70/Sources/OpenJoystickDriverMacOSPlatform/Output/IOHIDVirtualDevicePublisher.swift) 检查受限的 `com.apple.developer.hid.virtual.device` 授权后创建虚拟设备。

真正引入目标功能的是 [2026-10-23 新增 GameController 输出](https://github.com/xsyetopz/OpenJoystickDriver/commit/262754b4b4fa2c5247e02b14030a5bd2147dd20b) 和 [同日修正报告位布局](https://github.com/xsyetopz/OpenJoystickDriver/commit/a57dc560a2f1c1f870bbbd9c8d2ec7f00c9d1181)，不是依赖机器人更新。

### 3.2 第一轮接口选择

先用一个持续运行的 CLI 子进程验证，候选命令为 `ojd --json virtual feed --as game-controller-compatible`。正式接入再使用同版本的本机 Unix socket 接口，避免每个按键启动一次进程。具体 socket 地址和握手字段以安装版本为准，不从文档猜测或硬编码到业务层。

正式 socket 接入还需启用 OJD endpoint，并为客户端授予 `Control` 权限。普通源码 Python 不能假定拥有签名身份授权，应采用本机 token grant，按服务 challenge 完成认证。凭据存本机凭据存储，不写入 YAML、日志或仓库；未授权或授权撤销时停止。仅知道 socket 路径不等于有控制权限，依据同版本 `EndpointServer+Handshake` 实现。

[`VirtualFeedFrame`](https://github.com/xsyetopz/OpenJoystickDriver/blob/3552be925d7dacef3fd895ac0c6cbf39e9d3cd70/Sources/OpenJoystickDriverKit/ApplicationService/Payloads/VirtualFeedPayloads.swift) 使用完整状态：省略的控制为中立，摇杆范围为 -1 到 1、Y 向下，扳机为 0 到 1。Python 必须维护整个按键与摇杆状态后发送，不能把“按下 A”和“左摇杆偏转”当成互不关联的增量报文，否则会意外释放另一项。

服务存在帧时长、心跳和断开清理机制。接入前实测最短有效按键、持续按住、同时移动攻击、更新顺序及断连归零。长时间保持应使用短周期完整状态刷新，不把几秒长的阻塞动作排入发送队列，确保停止能及时生效。

### 3.3 不能提前宣布通过的事项

- [维护者兼容记录](https://github.com/xsyetopz/OpenJoystickDriver/blob/3552be925d7dacef3fd895ac0c6cbf39e9d3cd70/wiki/Playing-Games.md) 报告 GameController 消费方可读取该输出，但没有本项目的 macOS 26.7 / PlayCover /《绝区零》结果。
- [匹配测试](https://github.com/xsyetopz/OpenJoystickDriver/blob/3552be925d7dacef3fd895ac0c6cbf39e9d3cd70/Tests/OpenJoystickDriverMacOSPlatformTests/GameControllerPersonalityMatchTests.swift) 涉及系统 `GCIOMatchVirtual` 规则，未来系统更新仍可能影响识别。
- [签名说明](https://github.com/xsyetopz/OpenJoystickDriver/blob/3552be925d7dacef3fd895ac0c6cbf39e9d3cd70/docs/development/signing.md) 要求 Apple 授权。源码 MIT 不代表自己重编译的服务能继承作者的受限权限；先核验原发行包签名、entitlement 和正常系统保护下的创建设备结果。
- 系统虚拟手柄可能被其他手柄应用接收。不抢键鼠不等于手柄事件只发给目标游戏。首版明确不能同时运行另一个消费手柄的游戏；是否需要进一步定向隔离由实测决定。

## 4. 备选方案的使用边界

### libvirtualhid

[Mac 使用文档](https://github.com/LizardByte/libvirtualhid/blob/45c9b4db05779d18224a751e33cb8dfea78201bb/docs/macos-gamepad.md) 描述：安装已签名、公证且持有虚拟 HID 授权的 broker，C++ library 经服务创建手柄。安装需要管理员授权和设备控制权限，手柄创建需要机器许可证。

官方文档还区分年付与终身许可的离线行为；年付许可重启后需要联网验证。这会影响无人值守运行，必须在决定采用时再核对当前条款和行为。[许可分工](https://github.com/LizardByte/libvirtualhid/blob/45c9b4db05779d18224a751e33cb8dfea78201bb/LICENSES/license-map.md) 明确 library 为 MIT、Mac broker 为 LB-SAL，不能把整个产品当作 MIT 组件复制进项目。

若选择该路线，优先作为独立安装的服务，通过小型 C++ 适配器接 Python；不把串流、键鼠注入或其完整 GUI 引入一条龙。仍须实测 GameController 和 PlayCover，而不是只检查 HID 枚举。

### WaveBird

[`VirtualHIDDevice`](https://github.com/murphyjt/wavebird/blob/b04a072f1b17df58965efb14a066873a0b48da2a/WaveBird/HID/VirtualHIDDevice.swift) 和 [`HIDOutputSession`](https://github.com/murphyjt/wavebird/blob/b04a072f1b17df58965efb14a066873a0b48da2a/WaveBird/HID/HIDOutputProfile.swift) 已分离状态编码与设备输出，适合参考。其签名、公证发布包仍是实体手柄桥接器；新增脚本接口后需要自己的构建与签名路径，不能直接沿用发行包权限。

### Steam Controller Bridge 与 Satellite

- Steam Controller Bridge 的 [JSONL 协议](https://github.com/tkubicz/steam-controller-bridge/blob/5490822fbd95a9713858805815f0f77252f3995a/docs/VIRTUAL_HID_IPC.md) 值得参考；[验证矩阵](https://github.com/tkubicz/steam-controller-bridge/blob/5490822fbd95a9713858805815f0f77252f3995a/docs/VIRTUAL_HID_FEASIBILITY.md) 明确区分降低保护的 VM 成功与正常保护构建未完成，不能混为同一结果。
- Satellite 的 [Mac DS4 实现](https://github.com/TinkerNorth/satellite/blob/d3ac0fcdcfe1b4a62ff2215c9a0e3c80218eaf6c/src/platform/macos/mac_hid_gamepad_adapter.cpp) 和 [输入协议](https://github.com/TinkerNorth/satellite/blob/d3ac0fcdcfe1b4a62ff2215c9a0e3c80218eaf6c/docs/contract.md) 可参考；其 [Mac CI](https://github.com/TinkerNorth/satellite/blob/d3ac0fcdcfe1b4a62ff2215c9a0e3c80218eaf6c/.github/workflows/macos-ci.yml) 仍生成不能创建虚拟手柄的 unsigned stub。

## 5. PlayCover 与 Apple 官方边界

[PlayTools `ControllerFocus.m`](https://github.com/PlayCover/PlayTools/blob/fbc88801b63c791e4ef597a2746676c69864ccc6/PlayTools/Utils/ControllerFocus.m) 设置 `GCController.shouldMonitorBackgroundEvents = YES`。这支持优先验证后台手柄输入，但必须确认本机 PlayTools 版本以及游戏失焦后的行为。

[Apple 工程师答复](https://developer.apple.com/forums/thread/812774) 提醒：虚拟 HID 有可能被 GameController 忽略，系统不承诺所有伪装设备可用。该答复与近期项目的具体兼容实现并不矛盾；应通过当前系统和目标游戏验证，不能据此宣布永远不可行，也不能根据一个项目 README 宣布已经解决。

[GCVirtualController](https://developer.apple.com/documentation/gamecontroller/adding-virtual-controls-to-games-that-support-game-controllers-in-ios) 是游戏内虚拟控件能力，不是另一进程向目标游戏注入手柄输入的通用接口。首选外部服务验证通过前，不修改 PlayTools，也不引入触屏映射。

## 6. 验证记录必须区分的结果

依次记录：发行包可运行 → HID 设备存在 → GameController 能枚举并读取数值 → 游戏进入原生手柄界面 → 按钮及摇杆正确 → 游戏失焦后继续响应 → 用户同时使用键鼠不受影响。

记录 macOS、PlayCover、PlayTools、游戏与手柄服务版本，以及固定提交/发布包、签名核验结果、按键延迟、失焦状态、停止释放结果。任何一级失败都不能用前一级通过来替代。完整任务还需通过菜单导航和后台截图验证，详见迁移方案。
