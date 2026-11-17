<!-- markdownlint-restore -->
<div align="center">

<img src="https://socialify.git.ci/Aurxs/ZenlessZoneZero-OneDragon-MacOS/image?description=1&font=Inter&language=1&logo=https%3A%2F%2Fgithub.com%2FAurxs%2FZenlessZoneZero-OneDragon-MacOS%2Fblob%2Fmain%2F.github%2Fimage%2Fellen.png%3Fraw%3Dtrue&name=1&owner=1&pattern=Charlie+Brown&theme=Light" alt="ZenlessZoneZero-OneDragon-MacOS"/>
<div>

---

</div>

__ZenlessZoneZero-OneDragon-MacOS__


<div>
    <img alt="macOS" src="https://img.shields.io/badge/macOS-Apple%20Silicon-blueviolet">
    <img alt="commit" src="https://img.shields.io/github/commit-activity/m/Aurxs/ZenlessZoneZero-OneDragon-MacOS?color=blue">
</div>
<div>
    <img alt="stars" src="https://img.shields.io/github/stars/Aurxs/ZenlessZoneZero-OneDragon-MacOS?style=social">
</div>

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/OneDragon-Anything/ZenlessZoneZero-OneDragon)

学习实践 __图像识别 & 自动化__ 的智能解决方案

✨ 如果喜欢本项目，欢迎右上角点亮`Star`支持 ✨

</div>

## 🚀 功能介绍

<div align="left">

🤖 __自动战斗__：支持自定义逻辑、技能标记、条件、变量等进阶用法

🛡️ __闪避助手__：基于声音、图像一体化模型识别，轻占用，高准确

🧹 __日常清理__：影像店、刮刮乐、咖啡店、材料、奖励等全日常清理

☕ __空洞作战__：基于大模型训练的识别、事件、寻路的功能模块

⏲️ __更多功能__： 定时启动、多账号切换、定时任务、自动对话……

</div>

## 🍎 macOS 部署

Apple Silicon Mac 使用 PlayCover 运行 iOS 版《绝区零》，一条龙沿用原 GUI 和任务配置，通过原生手柄操作游戏。

本项目实际使用 [PlayCover 4.0.0 Pre-release](https://github.com/PlayCover/PlayCover/releases/tag/4.0.0-prerelease)（标签 `4.0.0-prerelease`，预发布版），首次部署请从该发行页下载。

本仓库是 [上游一条龙](https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon) 的 Mac 版，安装和更新请使用 [Aurxs/ZenlessZoneZero-OneDragon-MacOS](https://github.com/Aurxs/ZenlessZoneZero-OneDragon-MacOS)。已有安装目录无需随仓库改名；旧 `origin` 地址的处理见更新说明。

首次安装请按 [macOS 部署与 PlayCover 设置](../docs/develop/setup/macos.md) 操作：包含源码环境、PlayCover 图像与游戏设置、系统权限、手柄组件和首次准备游戏。图像设置为 **Resizable（可缩放）＋自定义长宽比 1920:1080＋缩放 1.0**。

Mac 已适配日常任务、自动战斗与部分周常；具体范围看任务卡片及 [迁移进度](../docs/develop/zzz/macos_migration_progress.md)。运行时保持游戏与一条龙在同一桌面，运行实例选“仅运行当前”，“结束后”选“无”。

首次运行迷失之地前，须按部署指南完成 [手柄镜头校准](../docs/develop/setup/macos.md#手柄镜头校准迷失之地必做)。普通体力战斗无需先校准，缺少镜头参数时会自动关闭本次战斗的周期转向。

### 已安装用户更新

退出一条龙 GUI、CLI 和联调进程，在原项目目录打开终端，先检查仓库状态：

```shell
git remote get-url origin
git branch --show-current
git status --short
```

确认 `origin` 为 `https://github.com/Aurxs/ZenlessZoneZero-OneDragon-MacOS.git`、当前分支为 `main`，且状态输出为空后，再更新：

```shell
git pull --ff-only origin main
```

如果本次更新包含 `pyproject.toml` 或 `uv.lock` 的变动，再同步依赖；普通代码更新可跳过：

```shell
uv sync --frozen --python 3.11
```

完成后重新打开原启动入口，或在项目目录运行：

```shell
PYTHONPATH=src uv run --no-sync python -m zzz_od.macos.main
```

账户、任务计划、运行记录和本机配置会保留，普通代码更新无需重装 OJD、重新授权或重建本机启动应用。有本地改动、来源不符或无法快进时，先保留改动并按 [更新说明](../docs/develop/setup/macos.md#更新已有安装) 处理，不要强制覆盖。

**旧版本 GUI 的「代码同步」曾指向上游，可能覆盖 Mac 适配代码，首次获取此修复请使用上述终端步骤。** 修复后的 **资源管理 → 资源 → Mac 版代码同步** 仅从 Aurxs 的 Mac 仓库更新；自动模式和地区预设也不会切换到上游代码源。依赖变更仍需在终端同步，Mac 不提供 Windows 启动器下载。

如果已经更新错版本，或通过 GitHub「Download ZIP」获取源码，请按 [更新异常处理](../docs/develop/setup/macos.md#更新错版本或没有-git-元数据) 恢复。

## 📸 页面预览

<div align="center">

![App Interface](./image/app.webp#gh-light-mode-only "操作界面")
*✨ 简洁直观的操作界面 ✨*

</div>

## ⚠️ 免责声明

📌 本项目仅供学习交流，开发者团队保留最终解释权

🎨 项目LOGO版权归[巡夜子](https://github.com/yokuminto)及全体开发者所有

⚖️ 使用本工具产生的一切风险需自行承担

🚫 本项目未授权任何个人、商家、自媒体账号等进行售卖

🚫 若您遇到商家使用本软件进行代练并收费，产生的任何问题及后果与本软件无关

🚫 开发者团队不会为您提供任何"售后"服务

## 🌟 贡献者们

<div>

感谢参与项目的所有贡献者 ([完整名单](https://github.com/DoctorReid/ZenlessZoneZero-OneDragon/graphs/contributors))：

![Contributors](https://contrib.rocks/image?repo=DoctorReid/ZenlessZoneZero-OneDragon&columns=12)

是你们的参与共同构建了这个项目，让这个项目越来越好♡
如果想要参与开发，欢迎查看 [贡献者招募](../docs/develop/RECRUITING.md)（技术栈 / 参与方式 / 成长故事），并按 [快速开始](../docs/develop/setup/quickstart.md) 把项目跑起来，期待你的加入 ✨

</div>

## 📢 上游官方渠道

<div>

🔗 [官方网站](https://one-dragon.com/)
> 项目简介 | 新手入门 | 功能说明 | 配置说明

💬 [官方频道](https://pd.qq.com/g/onedrag00n)
> 公告要闻 | 软件科研 | 游戏攻略 | 趣闻分享

❓ [官方文档](https://docs.qq.com/doc/p/7add96a4600d363b75d2df83bb2635a7c6a969b5)
> 常见问题 | 故障速查 | 疑难诊断 | 更新指南

👉 [官方议题](https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon/issues)
> 故障反馈 | 问题讨论 | 优化建议 | 建言收集

👨‍👨‍👦‍👦 玩家社群
> 闲聊吹水 | 趣闻互动 | 交流同好 | 晒卡吸欧
>
> 见频道关联群聊，入群前先对该项目点个 ⭐star，入群问题的项目仓库的答案为ZenlessZoneZero-OneDragon，入群后需校验你的 Github 账号的 username
>
> 提示：推荐 GitHub 用户加入，并注意 username 和 Name 的区别，请遵守群规，友善交流

</div>

## 📝 签名策略 (Code Signing Policy)

免费代码签名由 [SignPath.io](https://signpath.io/) 提供，证书由 [SignPath Foundation](https://signpath.org/) 颁发

审批人：[DoctorReid](https://github.com/DoctorReid) [ShadowLemoon](https://github.com/ShadowLemoon)

Free code signing provided by [SignPath.io](https://signpath.io/), certificate by [SignPath Foundation](https://signpath.org/)

Approvers: [DoctorReid](https://github.com/DoctorReid) [ShadowLemoon](https://github.com/ShadowLemoon)

## 🔒 隐私政策 (Privacy Policy)

本程序的隐私政策详见：[隐私政策](PRIVACY.md)。

See the [Privacy Policy](PRIVACY.md).
