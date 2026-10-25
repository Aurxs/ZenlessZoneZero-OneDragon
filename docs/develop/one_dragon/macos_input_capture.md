# macOS 手柄输入与窗口采集

本组件提供独立的手柄输入协议和窗口帧，不依赖 Windows 输入控制器，也不修改 OJD 或 HID 驱动。游戏流程通过后续业务适配器组合这些能力。

## 输入

`GamepadInput` 定义按键、组合键、摇杆、归零、暂停和关闭接口，`GamepadState` 表示一个完整手柄状态。`OjdGamepadClient` 调用已安装的官方 OJD CLI，持续传入完整状态；CLI 路径保留名为 `ojd` 的符号链接，不解析为 GUI 程序名。

输入使用单调时钟维护按住期限和操作代数。暂停、断线和关闭清空旧动作，不在恢复后重新发送。每次短按至少 100ms，发送队列避免累积相同的长保持帧。连接服务不代表游戏已识别设备，必须用实际游戏画面验证。

## 采集

`MacWindowCapture` 按 bundle ID、PID 和窗口 ID 绑定 ScreenCaptureKit 窗口。`sck_frame_converter` 按缓冲步长转换 BGRA，保留真实采集时间和序号，输出独立 RGB 数组。明确配置标题栏裁剪后检查 16:9，再归一化为项目的 1920×1080；不把错误比例强行拉伸。

静态画面的 Idle 回调只更新流仍有效的观察时间，不伪造像素帧时间。失效、断流或超时必须由上层暂停输入。已有 Qt 应用不被改成后台禁止激活模式；命令行工具单独准备必要的 Cocoa 环境。

### 跨 Space 采集设计

- 保留 `onScreenWindowsOnly=False` 枚举及 `desktopIndependentWindow` 过滤，允许绑定其他 Space 的窗口。`on_screen=False` 只是观测值，不能据此判定窗口关闭或最小化。窗口身份仍需同时匹配 bundle ID、PID 和窗口 ID。
- `streamDidBecomeInactive` 使缓存帧失效，但不永久关闭流；同一流仍可接收 Complete 帧。失活期间、或从不可见窗口直接启动时，第一张图只用于比较，第二张不同的图才可提供给控制器。重复 Complete 保留上一次变化的真实时间与序号，Idle 也不能延长跨桌面画面的有效期。超过原有 0.5 秒期限仍无变化就拒绝用图。完全静止的跨桌面菜单也会保守拒绝，不能仅凭 SCK 状态区分静止与冻结。
- `streamDidBecomeActive` 后仍等待新 Complete；通知本身、读取截图和诊断均不能刷新有效帧时间。失活之前已开始转换的回调会被丢弃。真正的停止或错误仍须重新开始采集，输入暂停后仍须显式恢复，不重放旧动作。
- 只读探测记录窗口枚举、SCK 状态、原生观察时间、像素帧序号与图像摘要。无回调表示采集不再产出；只有 Idle 或重复像素不能单独证明游戏继续渲染。需要可见动画的连续变化作为跨 Space 实测证据。
- 不切 Space 来维持运行，不改 PlayCover 渲染分辨率，不使用桌面截图替代游戏窗口，不通过重启流或重复截图给旧像素刷新时间。多显示器按独立窗口过滤处理，实测与最小化支持另记。

官方依据：[独立窗口过滤](https://developer.apple.com/documentation/screencapturekit/sccontentfilter/init(desktopindependentwindow:))、[非活动通知](https://developer.apple.com/documentation/screencapturekit/scstreamdelegate/streamdidbecomeinactive(_:))及[恢复活动通知](https://developer.apple.com/documentation/screencapturekit/scstreamdelegate/streamdidbecomeactive(_:))。后两者描述共享窗口退出与重新出现，不等同于游戏失去前台焦点，也不保证其他 Space 内游戏仍渲染。

### 本机结果与支持边界（2026-10-25）

**当前不能宣称支持 PlayCover 绝区零跨 Space 自动运行。** 已完成窗口发现、临时失活后的接收恢复及冻结保护；本机游戏在另一 Space 时停止输出变化画面。原代码会在 Inactive 时永久拒收后续回调；仅修复这一点仍不够，因为系统会对冻结图像持续发送带新时间戳的 Complete。

环境：M3 Max / 36GB、macOS 26.7.1、PlayCover 3.1.0、绝区零 iOS 3.3.0；单显示器。窗口 PID 65881、ID 12115，953×564 逻辑点、1906×1128 像素，顶部裁剪 56px 后归一到 1920×1080。未修改游戏或 PlayCover 分辨率/缩放配置。

| 情形 | 实测证据 | 结论 |
|---|---|---|
| 同桌面、Codex 前台 | 三秒基线 91 张 Complete，六次取样摘要各不相同，帧龄约 18–22ms | 游戏后台持续变化，采集正常 |
| 用户从游戏桌面切至桌面 2 | `.debug/macos/space-transition.jsonl`：窗口从当前桌面可见变为不可见，收到 Inactive，但 Complete 计数仍增长 | Inactive 不是流已经停止，不能永久丢弃回调 |
| 在桌面 2 直接创建采集 | `.debug/macos/space2-direct.jsonl`：可枚举并绑定同一窗口，8 秒 236 次 Complete，8 次取样摘要全部相同；前台始终 Codex，游戏不在当前桌面 | 能取到游戏表面，不能证明实时渲染；截图为阿朔附近大世界，不是黑图或桌面截图 |
| 用户回到游戏可见桌面 | `.debug/macos/space2-guarded.jsonl`：文件名沿用原计划，但记录实际为窗口可见、Safari 前台；四次摘要均不同 | 不能将这次误记为跨 Space，通过同桌面恢复对照 |
| 桌面 2 的冻结保护 | `.debug/macos/space2-guarded-final.jsonl`：5 秒 148 次 Complete，内容序号保持 1，内容时间不断变旧，五次取图均为 None | 重复缓冲没有变成有效新帧，保护生效 |

上述采集均使用生产 `MacWindowCapture`，工具不创建手柄、不发送游戏输入、不触发日常、不启动或停止 GUI。桌面位置由用户调整；测试后本工具的所有流和进程已结束，用户最后停在桌面 2。已有 GUI 未热更新，需以后正常重启才能加载新代码。

上游 [PlayCover #1568](https://github.com/PlayCover/PlayCover/issues/1568) 报告了 macOS 15 起不可见 iOS 游戏暂停的问题；[PlayTools #226](https://github.com/PlayCover/PlayTools/pull/226)（核实时仍 Open、未合并，head `70bdc17108597e28781cef5c42ed14c2c07bfeea`）提出在游戏进程内处理后台生命周期并使用静音音频保活。作者报告测试过绝区零，也记录了立即重启及 OBS 共存问题。它与本机冻结现象吻合，但本轮未注入、替换或验证此补丁，不能当作已解决。仅在采集进程里改 SCK 参数不能让暂停的游戏生成新画面。

截图中的 `blockSleepSpamming` 是限制 `usleep()` 调用以避免资源耗尽，并非跨 Space 保活开关，见[上游设置说明](https://github.com/PlayCover/PlayCover/blob/24bbed786fe1d5acfb0ffc2e619e126bdc09f22b/PlayCover/en.lproj/Localizable.strings)。本轮没有改动这些开关。

多显示器：独立窗口过滤不绑定指定显示器，枚举也不按显示器过滤；本机只有一个活动显示器，因此未作实测支持承诺。最小化、锁屏、睡眠恢复同样未验证。游戏以后若能够在另一 Space 持续渲染，该采集路径可按变化像素工作，但仍须重新验收；当前不能把采集层修复写成跨 Space 游戏运行已完成。

### 只读诊断工具

确认没有其他任务正在做游戏现场验证后，可运行：

```shell
PYTHONPATH=src .venv/bin/python tools/macos/capture_probe.py --duration 15 --top-inset-pixels 56 --output .debug/macos/capture-check.jsonl
```

工具最多运行 120 秒，只绑定指定 bundle ID/标题，日志文件必须不存在。可加 `--save-frames` 保存取样时发生变化的截图副本，落盘图遮挡 UID，内存帧保持原样。工具不主动切 Space；通过用户切换及日志中的窗口当前可见性共同确定场景。`active` 记录原生共享内容状态，不代表前台应用；`sample_counts` 是回调状态计数，不能拿 Complete 数量当有效变化帧数量。诊断模式退出码 0 只表示观察完成，不表示跨 Space 验收通过。

## 验证范围

输入探测工具为 `tools/macos/gamepad_probe.py` 和 `gamecontroller_probe.swift`。输入的有限按键、游戏识别和当前桌面 SCK 采集已在本机验证；命令行 GameController 观察器的枚举结果不能覆盖游戏实际识别结果。跨桌面采集的实际限制见上表。

测试在独立测试仓覆盖假 OJD 服务、按键释放、队列期限、像素转换、窗口绑定和静态帧有效性；测试不申请系统权限或发送真实输入。启动阶段必需的触屏点击属于独立适配器，不作为本手柄协议的回退方式。

本轮快速验证：新增跨 Space 测试 4 项；相关既有 Idle/帧转换测试 14 项；控制器缺帧、长按暂停与中立状态测试 5 项，共 23 项通过。修改文件 Ruff 通过。后续补充初始化首帧等待时，仅重跑受影响的 4 项测试；不扩展全量验证。
