# Mac 命令行入口

在仓库根目录使用已有虚拟环境，无需打开一条龙 GUI。复用当前账户的原应用、任务顺序、启用状态、计划、策略和运行记录，不另建配置体系。

```shell
# 列出原应用及 Mac 支持情况，不操作游戏
PYTHONPATH=src uv run --no-sync python -m zzz_od.macos.cli --list

# 预览当前账户的启用任务与入口限制，不初始化模型或连接设备
PYTHONPATH=src uv run --no-sync python -m zzz_od.macos.cli --dry-run

# 按原计划运行一条龙
PYTHONPATH=src uv run --no-sync python -m zzz_od.macos.cli

# 单独运行原任务，沿用该任务在 one_dragon 组中的配置
PYTHONPATH=src uv run --no-sync python -m zzz_od.macos.cli --app engagement_reward
```

先在原 GUI 配置当前账户为 macOS PlayCover，准备好模型及系统权限。与 GUI、联调脚本保持单一采集/手柄持有者，启动 CLI 前退出其他控制进程。使用当前图形登录会话，游戏必须能持续提供有效画面；此入口没有改变原后台/跨桌面限制。

运行时自动调用原准备游戏流程，按需冷启动、进入已保存账号并确认手柄模式。初始 AppKit 连接在主线程完成，应用调度在工作线程执行，主线程持续处理 Cocoa 事件。没有 QApplication、窗口、界面图片或 GUI 初始化，OCR/采集/战斗模型内存仍需要保留；没有给出未经测量的节省量。

结果以 JSON 输出到标准输出，原运行日志写标准错误和 `.log/log.txt`。退出码 0 表示成功，1 表示运行失败或配置不支持，2 表示命令参数/宿主不支持，130 表示 Ctrl+C 或 SIGTERM 中断。停止后等待原 Operation 收尾，再关闭输入和采集。整组结束还会核对已启用子任务的失败记录，不能以“全部结束”掩盖任务失败；`failed_apps` 列出失败项。

仅支持当前账户；原多账号、结束后操作及各任务适配限制仍有效。`--dry-run` 只预览启用任务和入口限制，不保证资源足够，也不穷举各任务计划的运行时校验。单任务调用沿用原独立运行语义，是否跳过已完成由原任务决定；整组调用沿用原组的已完成跳过逻辑。

## 2026-10-27 验证

- 8项聚焦测试通过：预览不初始化模型/控制器、内部/未适配应用拒绝、子任务失败影响退出码、停止期间主线程继续处理事件、未建控制器时退出清理。
- 当前账户2的七项日常预览成功；独立进程检查未导入 PySide6、qfluentwidgets 或 zzz_od.gui。
- 22:57—22:58 CLI 单独运行原活跃度奖励应用，确认手柄会话、进入日常、识别无可领取奖励并返回大世界，结果成功、退出码0。不消耗电量。证据在本机 `.debug/macos/cli_engagement_20261027.json` 及同名 `.log`。
- 本次没有重跑整组首次领奖、战斗任务或冷启动 CLI；此前原GUI冷启动准备成功不能替代这些分支的CLI验收。
