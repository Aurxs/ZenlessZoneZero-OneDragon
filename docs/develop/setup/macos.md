# macOS 部署与 PlayCover 设置

适用于 Apple Silicon Mac、PlayCover iOS 客户端和一条龙原生手柄路径。已有可运行环境可直接核对配置，无需重装。

## 1. 安装 PlayCover 和游戏

1. 按 [PlayCover 官方说明](https://docs.playcover.io/getting_started/download_playcover.html) 安装 PlayCover。
2. 准备《绝区零》已解密的 iOS `.ipa`，拖入 PlayCover App 库安装，要求见 [官方 IPA 安装说明](https://docs.playcover.io/getting_started/download_ipa.html)。本项目不提供游戏安装包。
3. **完全退出游戏**，右键 App 库中的“绝区零”→ **设置**，核对下表。选项名称参考 PlayCover **3.1.0（1633）**。

| 页面 | 设置 | 值 |
|---|---|---|
| 图像 | iOS 机型 | iPad Pro 12.9 英寸第 5 代（M1 / 8GB） |
| 图像 | 分辨率 | **Resizable（可缩放）**；部分中文界面显示 `settings.picker.adaptiveRes.6` |
| 图像 | 长宽比 | **自定义，填写 `1920:1080`** |
| 图像 | 分辨率缩放 | **`1.0`** |
| 图像 | 修复窗口化显示问题 | 开启，方式为“正常” |
| 图像 | 设备方向 | 默认 |
| 图像 | 隐藏标题栏 | 关闭 |
| 绕过 | PlayChain | 开启，其余开关关闭 |
| 杂项 / 详细信息 | PlayTools | 保持已安装；不要点击“移除 PlayTools” |

**先选 Resizable，再设置自定义长宽比**，不要混用分辨率菜单里的“自定义”或“1080p”。`1920:1080` 表示 16:9，窗口可自由缩放；保持游戏内容铺满宽度、底边对齐，没有左右或底部黑边。一条龙会自动排除标题栏并适配截图。

配置后启动游戏，由本人完成资源下载、协议和首次登录，确认能进入游戏并保留登录状态。无需制作或导入触屏键位图。

## 2. 安装并启动一条龙

需要 **Git、uv 和原生 arm64 Python 3.11**（`>=3.11.9,<3.12`）。缺少 Git 时先安装 Apple Command Line Tools；uv 安装见 [官方文档](https://docs.astral.sh/uv/getting-started/installation/)。

首次部署到新目录：

```shell
git clone --branch main https://github.com/Aurxs/ZenlessZoneZero-OneDragon.git
cd ZenlessZoneZero-OneDragon
uv sync --frozen --python 3.11
PYTHONPATH=src uv run --no-sync python -m zzz_od.macos.main
```

日常在仓库根目录执行最后一行即可，无需重复安装依赖或克隆测试仓。

## 3. 配置一条龙

### 游戏设置

打开 **设置 → 游戏设置 → Mac 运行设置**，配置当前账户：

| 项目 | 配置 |
|---|---|
| 游戏平台 | **macOS PlayCover**，保存后重启一条龙 |
| 游戏应用标识 | 国服为 **`com.miHoYo.Nap`**；其他客户端按 PlayCover 详情页填写 |
| PlayCover 游戏路径 | 默认安装位置留空；其他位置填写实际完整 `.app` 路径 |
| 自动适配游戏窗口 | **开启**，无需手填标题栏高度或顶部裁剪值 |

其他运行参数保持默认即可。游戏路径不能填写别名或 `Info.plist`。

### 手柄服务

打开 **设置 → 手柄 → 手柄服务**：

1. 点击 **一键配置**，安装或复用 OJD 官方组件，并自动保存路径、开启自动启动。
2. 按系统提示完成管理员授权及输入权限；点击 **检查** 核对服务状态。
3. 点击 **连接手柄**，确认显示“已连接，可以开始准备游戏”。无需另开 OJD GUI 或创建第二个手柄。

动作按键和界面快捷键也在“设置 → 手柄”，应与游戏内手柄键位一致。

### 权限和资源

- 在 **系统设置 → 隐私与安全性** 中，为实际启动一条龙的终端、Python 或开发 `.app` 授予**屏幕录制**权限；启动时切换手柄模式还需**辅助功能 / 事件投递**权限。按实际弹窗授权后重启对应程序；OJD 的输入权限另按系统提示授予。
- 在一条龙 **资源管理 → 资源** 中准备 OCR 和任务所需模型：自动战斗需要闪光识别，迷失之地另需检测模型。等待下载和初始化完成后再运行任务。

## 4. 准备游戏并运行

1. 游戏和一条龙保持在**同一个 macOS 桌面 / Space**，使用窗口模式；运行时不要最小化游戏或锁屏。
2. 在 **一条龙 → 运行** 页点击 **准备游戏（启动并切换手柄）**。程序会按需启动游戏、短暂置前切换输入模式，直至确认手柄大世界；遇到密码、验证码、扫码或协议页面，先自行处理后重试。
3. 准备成功后，配置体力计划、编队和自动战斗策略；需要自动转向的任务先完成 [右摇杆校准](../zzz/application/macos_turn_calibration.md)。
4. 运行实例设为 **仅运行当前**，“结束后”设为 **无**。按任务卡片的 Mac 适配提示选择任务，关闭“Mac 暂未适配”项，再点击开始。

运行期间只保留一个一条龙 GUI、CLI 或联调进程占用手柄和采集。“手柄已连接”后仍需执行“准备游戏”。

## 常见问题

| 现象 | 处理 |
|---|---|
| 窗口竖屏、裁切或有黑边 | 退出游戏，复核 Resizable、`1920:1080`、缩放 `1.0`、默认方向和显示标题栏，再重开 |
| 冷启动找不到游戏 | 核对游戏应用标识和 `.app` 路径；默认安装位置可留空 |
| 无法截图、启动点击无响应或切桌面后画面冻结 | 核对实际启动入口的屏幕录制、辅助功能权限，并将游戏放回同一桌面后重试 |

按需阅读：[无 GUI 运行](../zzz/application/macos_cli.md) · [生成本地启动应用](../../../tools/macos/README.md#生成本地-gui-开发应用) · [窗口适配说明](../zzz/application/macos_capture_scaling.md) · [任务适配进度](../zzz/macos_migration_progress.md)。
