# macOS 部署与 PlayCover 设置

适用于 Apple Silicon Mac、PlayCover iOS 客户端和一条龙原生手柄路径。首次部署按本文顺序进行；已有可运行环境直接核对设置，无需重装。

**PlayCover 设置基准：2026-11-09 本机逐页观察。** 应用自报版本为 **3.1.0（1633）**，国服《绝区零》为 **3.3.0**，详情页确认 **PlayTools 已安装**。以下表格记录这次实际值，按这一组配置复现；旧迁移记录中的缩放 `2` 不作为当前部署值。它们不表示每个开关都已单独验证为自动化必需项。

## 1. 准备 PlayCover 和游戏

1. 将 PlayCover 安装到“应用程序”目录，安装方法见 [PlayCover 官方说明](https://docs.playcover.io/getting_started/download_playcover.html)。上方版本号用于对照本次环境，不代表所有同号构建都具有相同选项。
2. 准备可由 PlayCover 安装的《绝区零》iOS `.ipa`，在 App 库点击顶部“＋”选择文件，或把文件拖入 App 库。PlayCover 要求可安装的已解密 IPA，格式说明见 [官方 IPA 安装文档](https://docs.playcover.io/getting_started/download_ipa.html)。本项目不提供游戏安装包。
3. 在游戏完全退出时，按下文核对 PlayCover 全局设置和《绝区零》应用设置。修改后重新启动游戏才应用；见 [PlayCover 图像设置说明](https://docs.playcover.io/settings/graphics)。
4. 首次启动由本人完成游戏资源下载、协议和账号登录，确认能正常进入游戏并保留登录状态。后续一条龙使用已保存账号；遇到密码、验证码、扫码或协议页面会停止提示。

## 2. PlayCover 全局设置：逐页对照

入口是 **macOS 菜单栏 → PlayCover → 设置…**，与右键游戏打开的“绝区零 设定”不同。

### 更新

| 项目 | 本次观察值 |
|---|---|
| 自动检查更新 | 关闭 |

“检查更新”是手动操作按钮。本次只查看页面，没有更新 PlayCover。

### IPA 来源

本次来源列表为空。通过本地 IPA 安装即可按当前环境部署，无需先添加 IPA 来源；该页的添加、删除、移动和刷新只管理 IPA 资源库。

### KeyCover

| 项目 | 本次观察值 |
|---|---|
| KeyCover 状态 | 使用管理密码启用（Enabled with Managed Password） |
| 启动时提示 KeyCover | 开启 |

新安装按 PlayCover 自身引导完成管理密码设置；已有环境保留原凭据，出现解锁提示时由本人处理。链数量和当前解锁数量属于会话状态，不是需要照填的部署参数。“重置”“更改主密码”“锁定所有链”均不属于本教程的配置步骤。

### 安装

| 项目 | 本次观察值 |
|---|---|
| 应用程序类型 | `public.app-category.none`（未分类） |
| `preferences.toggle.showAppStorePopup` | 开启 |
| 显示安装 PlayTools 弹窗 | 关闭 |
| 总是安装 PlayTools | 开启 |

这组设置会在安装应用时自动安装 PlayTools。已安装游戏还需在其“详细信息”页确认“已安装 PlayTools：是”，全局开关本身不能证明旧应用已安装。全局安装行为见 [PlayCover 设置说明](https://docs.playcover.io/other_features/playcover_settings.html)。

### 卸载

| 项目 | 本次观察值 |
|---|---|
| 显示警告弹窗 | 开启 |
| 清除应用数据 | 关闭 |
| 移除键盘映射 | 关闭 |
| 清除设置 | 关闭 |
| 移除授权 | 关闭 |
| 移除 PlayChain | 关闭 |

这些选项只控制卸载时如何处理文件。“删除未使用的文件”是清理操作，部署时不用点击。

## 3. 《绝区零》应用设置：逐页对照

入口是 **PlayCover → App 库 → 右键“绝区零”图标 → 设置**。以下五个页签都需核对，图像和杂项页需向下滚动到底部。

部分选项在本次中文界面中直接显示 `settings.…`，下表保留原文并说明含义，名称对应 [PlayCover 上游英文资源](https://github.com/PlayCover/PlayCover/blob/24bbed786fe1d5acfb0ffc2e619e126bdc09f22b/PlayCover/en.lproj/Localizable.strings)。无需为了显示名称而重置设置。

### 键盘映射

| 项目 | 本次观察值 |
|---|---|
| 启用键盘映射布局 | 开启 |
| 智能按键映射 | 开启 |
| 启用滚轮 | 开启 |
| `settings.toggle.disableBuiltinMouse`（禁用应用内置鼠标支持） | 关闭 |
| 鼠标灵敏度 | `50` |

保留当前这组开关。一条龙通过游戏原生手柄界面操作，部署无需另行制作或导入触屏键位图；一条龙发出的动作按键在“设置 → 手柄”配置，并与游戏内设置保持一致。

### 图像设置

| 项目 | 本次观察值 |
|---|---|
| 选择 iOS 机型 | `iPad Pro (12.9-inch) (5th gen) \| M1 \| 8GB` |
| 分辨率 | `settings.picker.adaptiveRes.6`，即 **Resizable（可缩放）** |
| 长宽比 | 选中 `settings.picker.aspectRatio.custom`（自定义） |
| 自定义长宽比的两个输入框 | **`1920` : `1080`** |
| 分辨率缩放 | **`1.0`** |
| 修复窗口化显示问题 | 开启 |
| 窗口修复方式 | 正常；本次下拉框为灰色 |
| `settings.settings.displayRotation`（设备方向） | `settings.settings.displayRotation.default`（默认） |
| 禁用显示器息屏 | 关闭 |
| `settings.toggle.hideTitleBar`（隐藏标题栏） | 关闭，即显示标题栏 |
| `settings.toggle.floatingWindow`（悬浮窗口） | 关闭 |

**先在“分辨率”选 Resizable，再在“长宽比”选自定义，填写 `1920:1080`。** 分辨率下拉菜单里的“自定义”和下方“自定义长宽比”是两个不同设置；这里使用的是后者。若所用构建没有 Resizable 选项，先核对 PlayCover 构建，不能用菜单里的“1080p”代替后宣称配置相同。

这里的 `1920:1080` 表示 **16:9 长宽比**，不要求游戏窗口外框或内部渲染像素固定为 1920×1080。窗口可正常拖动缩放；一条龙会忽略顶部标题栏并把游戏内容归一到识别尺寸。保持内容铺满宽度、底边对齐，没有左右或底部黑边。具体规则见 [游戏窗口自动适配](../zzz/application/macos_capture_scaling.md)。

### 绕过

| 项目 | 本次观察值 |
|---|---|
| 启用 PlayChain（试验阶段） | **开启** |
| PlayChain 调试 | 关闭 |
| 启用绕过越狱检测（试验阶段） | 关闭 |
| 插入内省库 | 关闭 |
| 强制插入 iOS 框架 | 关闭 |
| `settings.toggle.checkMicPermissionSync`（同步检查麦克风权限） | 关闭 |
| `settings.toggle.blockSleepSpamming`（限制频繁的 `usleep()` 调用） | 关闭 |

PlayChain 用于保存和访问登录等密钥数据，与“绕过越狱检测”是独立选项，见 [PlayChain 官方说明](https://docs.playcover.io/miscellaneous/playchain.html)。`blockSleepSpamming` 不是后台保活开关；部署按当前关闭值保留。

### 杂项

| 项目 | 本次观察值 |
|---|---|
| 应用程序类型 | `public.app-category.none`（未分类） |
| 启用 Discord 动态 | 开启 |
| 启用 Metal 性能面板 | 关闭 |
| 用 LLDB 高性能调试器打开 | 关闭 |
| 在终端里打开 | 勾选但灰色，随调试器关闭而不可用 |
| 在 root 目录启动应用程序 | 开启；指工作目录 `/`，不表示以 root 用户运行 |
| `settings.toggle.limitMotionUpdateFrequency`（限制运动传感器更新频率） | 关闭 |
| `settings.toggle.ignoreUnityKeyboardInitializationError`（忽略 Unity 键盘初始化错误） | 关闭 |
| `settings.customPlugins.title`（自定义插件） | 空；没有添加插件 |
| 页面底部 PlayTools 按钮 | 显示“移除 PlayTools”，保持已安装状态 |

“自定义 Discord 动态”用于编辑展示内容，不是自动化参数。保持 PlayTools 已安装，无需点击“移除 PlayTools”。

### 详细信息

该页为只读信息，重点核对应用身份与 PlayTools 状态。

| 项目 | 本次观察值 |
|---|---|
| 显示名称 | 绝区零 |
| Bundle 名称 / 可执行文件名称 | `ZenlessZoneZero` |
| Bundle ID | **`com.miHoYo.Nap`** |
| Bundle 版本号 | `3.3.0` |
| 应用程序类型 | `public.app-category.none` |
| 最低 OS 版本 | `11`；这是 iOS 应用元信息，不是本项目 macOS 最低版本承诺 |
| 已安装 PlayTools | **是** |

“链接”指向真实应用包中的 `Info.plist`。本次应用位于 `~/Library/Containers/io.playcover.PlayCover/Applications/com.miHoYo.Nap.app`；`~` 代表各自的用户主目录，无需照抄别人的用户名。“别名”是另外的启动入口，不作为一条龙的游戏应用路径。

## 4. 安装一条龙源码环境

需要原生 **arm64 Python 3.11**（项目约束 `>=3.11.9,<3.12`）、Git 和 uv。终端也使用原生 Apple Silicon 环境。尚未安装 Git 时，可先安装 Apple Command Line Tools；uv 的安装方法见 [uv 官方文档](https://docs.astral.sh/uv/getting-started/installation/)。

以下命令用于**首次部署到新目录**，使用包含 Mac 迁移成果的个人仓库 `main`：

```shell
git clone --branch main https://github.com/Aurxs/ZenlessZoneZero-OneDragon.git
cd ZenlessZoneZero-OneDragon
uv sync --frozen --python 3.11
PYTHONPATH=src uv run --no-sync python -m zzz_od.macos.main
```

日常只需在仓库根目录执行最后一行启动原 GUI。已有 `.venv` 不重复初始化；源码部署沿用该个人仓库分支更新。开发和跑聚焦测试时再按需安装 `dev` 依赖组，运行任务不需要先克隆测试仓。

需要 Finder 中的本地开发启动入口时，可按 [Mac 工具说明](../../../tools/macos/README.md#生成本地-gui-开发应用) 生成开发 `.app`。它绑定当前目录和虚拟环境，属于本机入口；当前教程仍以源码部署为准。

## 5. 配置一条龙与系统权限

这里的参数属于一条龙，和前面的 PlayCover 设置分别保存。下表是当前代码提供的初次配置值；PlayCover 观察值仍以前文为准。

### 设置 → 游戏设置 → Mac 运行设置（当前账户）

| 项目 | 初次配置 |
|---|---|
| 游戏平台 | **macOS PlayCover**，保存后退出并重新启动一条龙 |
| 游戏应用标识 | 国服填写 **`com.miHoYo.Nap`**，与 PlayCover 详情一致 |
| PlayCover 游戏路径 | 默认安装位置可留空；其他位置填写实际完整 `.app` 路径 |
| 启动窗口等待（秒） | `45` |
| 自动适配游戏窗口 | **开启** |
| 截图顶部裁剪（旧像素配置） / 标题栏高度（逻辑点） | 自动适配开启时保持禁用，无需照抄旧记录的 `56px` 等本机数值 |
| 界面操作间隔（毫秒） | `500`，即 0.5 秒 |

填写游戏路径时使用真实 `.app` 目录；可从 PlayCover 详情页“链接”去掉末尾的 `/Info.plist` 得到。账户管理页用于账户管理；即使初始化提示仍提到“账户管理”，游戏平台和上述运行参数也在 **设置 → 游戏设置** 修改。

### 设置 → 手柄 → 手柄服务

1. 点击“安装 / 检查 OJD 官方组件”上的 **一键配置**。已有官方组件会校验并复用，缺少时下载固定的官方签名版本；完成后自动保存组件路径并开启“自动启动手柄服务”。
2. 按 macOS 提示由本人完成管理员授权及所需输入权限。首次授权后可点击“检查”查看服务和权限状态。
3. 点击 **连接手柄**，看到“已连接，可以开始准备游戏”。这里只建立中立手柄，不会替你操作游戏。

无需另外启动 OJD GUI 或手工创建第二个手柄。安装来源和生命周期见 [手柄组件说明](../zzz/macos_gamepad_service.md)。动作按键映射、界面快捷键也在“设置 → 手柄”，需要与游戏内的手柄键位保持一致。

### 系统权限与模型资源

- 在 **系统设置 → 隐私与安全性** 中，为实际运行一条龙的应用或 Python 进程授予屏幕录制权限；启动时按需切换触屏到手柄还需要辅助功能 / 事件投递权限。系统显示的授权对象取决于终端、Python 或开发 `.app` 启动方式，按实际弹窗核对，授权后重新启动相应程序。
- OJD 所需输入权限按其系统提示授予；给 PlayCover 权限不能代替给一条龙和 OJD 授权。
- 一条龙 **资源管理 → 资源** 中准备 OCR 和所用任务的模型。自动战斗需要闪光识别，迷失之地另需其检测模型。等待初始化和所需下载完成后再准备游戏；资源下载异常可在本页设置下载源与代理。
- Mac 的 OCR 使用 CPU，闪光与迷失检测可按界面选择 CPU / Core ML。性能开关与 PlayCover“分辨率缩放”是不同参数，部署时无需据此修改前文观察值。

## 6. 首次准备与运行任务

1. 保持游戏和一条龙位于**同一个 macOS 桌面 / Space**，游戏使用上述带标题栏的窗口。不要最小化、锁屏或把游戏放到另一个全屏桌面后运行。
2. 在一条龙 **一条龙 → 运行** 页点击 **准备游戏（启动并切换手柄）**。游戏未运行时先连接手柄再启动；已运行则复用。触屏布局会短暂置前并用鼠标切换，之后截图确认手柄大世界；本步骤不执行体力任务。
3. 看到准备成功、游戏已显示手柄提示后，配置原有体力计划、编队和自动战斗策略。需要转向参数的任务按 [Mac 右摇杆校准说明](../zzz/application/macos_turn_calibration.md) 使用现有校准入口。
4. 运行实例选择 **仅运行当前**，“结束后”选择 **无**；按任务卡片的 Mac 适配提示启用任务，关闭仍启用的“Mac暂未适配”项，然后开始。

任务运行期间只保留一个一条龙 GUI、CLI 或联调控制进程持有手柄和采集。设置页“已连接”只证明服务连接，“准备游戏”成功才确认游戏已进入可识别的手柄大世界。当前任务覆盖以 [迁移进度](../zzz/macos_migration_progress.md) 和任务卡片为准。

日后需要无 GUI 运行，先完成上述配置和首次准备，再按 [正式 CLI 说明](../zzz/application/macos_cli.md) 使用同一账户配置。

## 常见卡点

| 现象 | 核对位置与处理 |
|---|---|
| 中文界面显示 `settings.picker.adaptiveRes.6` | 就是本次使用的 Resizable，按图像表配置，不需要重置 |
| 窗口竖屏、被裁切或出现黑边 | 退出游戏，复核 Resizable、自定义长宽比 `1920:1080`、缩放 `1.0`、默认方向和显示标题栏，再重开游戏 |
| 要求配置 macOS 平台，初始化不继续 | “设置 → 游戏设置”选择 macOS PlayCover，保存后重启一条龙 |
| 冷启动找不到游戏 | 核对 Bundle ID；默认路径可留空，自定义路径须指向实际 `.app`，不能填别名或 `Info.plist` |
| 无法截图、枚举窗口或执行启动点击 | 核对实际启动入口的屏幕录制、辅助功能权限；游戏须在当前图形登录会话与同一桌面 |
| 手柄已连接，但仍在触屏或登录界面 | 用“准备游戏”确认；凭据、协议和未知登录弹窗先由本人处理，再重试 |
| 切桌面后画面冻结、任务停止 | 将游戏放回运行桌面后重试；当前配置不承诺跨 Space 持续运行，见 [采集边界](../one_dragon/macos_input_capture.md) |
| 开始时提示任务未适配或多账号限制 | 按提示关闭对应任务，运行实例设“仅运行当前”，结束后设“无” |

本次只核对设置并整理教程，没有修改 PlayCover 开关、安装组件、启动游戏任务或重新验收各项自动化。
