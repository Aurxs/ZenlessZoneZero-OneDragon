# macOS 手柄组件安装与管理

## 当前方案

项目自动安装和管理 **OJD 官方签名组件**，用户无需手动找下载地址或另外打开 OJD。它仍是第三方依赖，不称为项目自己实现的原生虚拟 HID 服务。

2026-10-25 已确认用户只有免费 Apple 开发者账号，本机 profile 没有 `com.apple.developer.hid.virtual.device`。自编译组件不能继承作者的受限权限。用户因此选择自动安装官方原包，并要求移除试验性的 Swift 后端、签名脚本、双后端抽象和无效配置选项。这些试验代码已删除。

保留现有 `OjdGamepadClient` 与 `GamepadInput`，Application / Operation 和 Windows 输入实现不变。按钮、方向键、双摇杆、双扳机、组合保持、短按、暂停、异常与退出释放仍使用已有完整状态调度，不复制状态机。

## 安装与生命周期

“设置 → 游戏设置 → Mac 手柄服务”提供“一键配置”“检查”“连接手柄”“断开”和“自动启动手柄服务”。打开页面不下载、不启动服务、不创建设备；按钮操作在后台执行，安装后保存实例配置。任务运行期间拒绝安装和连接变更，修改连接参数沿用已有停止任务、清理控制器的机制。

手柄设置只重建输入控制器，不清除已经完成的应用初始化。普通连接和断开也保留应用就绪状态，因此一键配置后可以直接使用“准备游戏”；游戏平台、窗口等其他参数仍遵循原有重新启动要求。

一键配置过程：

1. 已有 `/Applications/OpenJoystickDriver.app` 时检查并复用，不覆盖现有版本。
2. 未安装时从官方固定 release 下载完整 DMG，核对 SHA-256，再只读挂载。
3. 核对应用版本、完整签名、作者 Team、虚拟 HID entitlement 和系统信任检查。
4. 原样复制完整 `.app`；需要写入应用目录时由 macOS 显示管理员授权。保留作者的应用身份、签名、profile、公证信息和包内版权，不删改包内文件，不重签名、不注册 USB DriverKit 扩展。
5. 创建项目自己的 `ojd` 符号链接，不写入全局命令目录；保存路径并启用按需启动。

首次普通系统输入权限仍由用户本人确认。自动安装不能代替这一步，也不保证完全无弹窗。OJD 可能显示自身菜单栏入口；不通过修改包内 GUI 隐藏它。

开始连接时，启用了按需启动才调用官方后台启动命令，然后校验服务状态并建立一个中立 feed。界面连接使用当前实例控制器持有的手柄，不另建测试设备。停止只释放该实例输入，不退出可能被其他应用使用的 OJD 全局服务，也不更改其开机登录项。

配置只新增 `ojd_auto_start`，默认 `false` 保留旧行为；一键配置成功后才保存为 `true`。现有 `ojd_cli_path` 保持原含义。安装失败不改实例配置，未知或旧版本安装保留原状，不自动升级。

## 固定来源与许可

- [OJD 0.6.0-alpha.1](https://github.com/xsyetopz/OpenJoystickDriver/releases/tag/0.6.0-alpha.1)，提交 `3552be925d7dacef3fd895ac0c6cbf39e9d3cd70`。
- 官方 DMG：`OpenJoystickDriver-0.6.0-alpha.1-macOS.dmg`，29,419,483 字节，SHA-256 `d2b771ffe4382b7bfd218932c7003227216d334a14154e95976c4f114b1c2056`。
- 签名身份：`com.openjoystickdriver`，作者 Team `9PQP6CDMQT`，虚拟设备 persona `GameControllerCompatible`，Xbox Series Bluetooth `045E:0B13`。
- [MIT 许可](https://github.com/xsyetopz/OpenJoystickDriver/blob/3552be925d7dacef3fd895ac0c6cbf39e9d3cd70/LICENSE)，Copyright (c) 2026 Krystian J.。下载原包并保留原内容及版权；若未来随项目离线分发，也须附带该许可与依赖声明。
- 项目随附完整许可：`assets/third_party/ojd/LICENSE`；官方包内第三方依赖声明原样保留。
- [作者签名说明](https://github.com/xsyetopz/OpenJoystickDriver/blob/3552be925d7dacef3fd895ac0c6cbf39e9d3cd70/docs/development/signing.md)与 [Apple 虚拟 HID 权限](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.hid.virtual.device)。复用已签名原包不会把权限转移给项目 Python 或自编译服务。

这一步提供源码 GUI 中的一键依赖配置入口。Mac 总安装包、签名、公证和卸载流程仍属于发行阶段，不能把本入口当作完整安装器已经交付。外部 OJD 服务的 CLI 仍没有逐帧设备创建回执，连接存活不能替代 GameController 与游戏实际识别验证。

## 本机验证记录

2026-10-25 已完成：新版源码 GUI 启动，一键配置复用现有官方包、保存项目命令入口、启用按需启动；OJD 从未运行状态由 GUI 后台启动，手柄连接成功，所有按键释放。`codesign` 通过作者 Team 和虚拟 HID 权限核对；在沙箱外进行只读 `spctl` 检查，结果为 `accepted / Notarized Developer ID`。未重装已有 OJD、未注册 USB 扩展。

实测发现并修复设置页错误清除应用初始化状态的问题。修复后“准备游戏”开始执行，进入登录设置操作，随后因游戏窗口未成为前台而安全中止。紧接着计算机锁屏，CUA 要求用户手动解锁。该线程当时尚未完成游戏内输入验收。2026-10-26 日常迁移在相同设置与输入实现上完成了菜单导航、阿朔右摇杆、三场自动战斗和原 GUI 任务组收尾，结束后释放输入；不能把这些任务覆盖以外的输入组合也称为逐项通过。 新安装路径以最小模拟测试验证，没有为验证而卸载已安装软件。

设置归属的后续事项：游戏路径、启动等待、截图裁剪和支持说明仍在账号管理页，用户要求后续一起移入游戏设置；本次稳定提交只包含已经完成的手柄服务设置迁移。
