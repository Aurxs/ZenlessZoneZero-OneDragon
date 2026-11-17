---
name: zzz-od-macos-cli
description: 在 Apple Silicon macOS 上通过命令行查看、预览、运行或排查绝区零一条龙任务时使用。
---

# macOS CLI

使用已安装项目的原 CLI，不建立另一套任务调度。适用于用户和 agent；命令中的工作目录为实际仓库根目录，不假设用户名、安装路径、账户或日程。

## 1. 先确认环境与范围

- 使用 Apple Silicon macOS、原生 arm64 Python 和项目已有依赖环境；游戏由 PlayCover 运行。将当前账户平台设为 `macOS PlayCover`，复用其任务、编队与资源配置。
- 先读当前 `--help`；版本升级后重新核对参数。CLI 使用当前账户，不支持 `--instance`、Windows 的 `-i/-o/-c`、远程状态查询或通用 `--stop` 参数。
- 确认没有其他 GUI、CLI、诊断程序或 agent 占用游戏/控制器，避免重复输入。已有任务未结束或资源结果不明时先查原进程、输出和记录，不直接重跑。
- 仅执行用户授权的任务、资源及次数。程序支持某项功能不等于用户授权购买、补电、领取额外奖励或修改配置。不要从技能中推导固定每日计划。
- 更新代码时核对分支、远端与未提交改动，沿项目配置的正确代码源安全更新；分叉、冲突或保护阻断时停止，不强制覆盖、不自行重建环境。

## 2. 命令和全部参数

以下命令均从仓库根目录运行；若已有环境解释器不在 `.venv/bin/python`，使用实际项目解释器，不另建环境。

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -B -m zzz_od.macos.cli --help
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -B -m zzz_od.macos.cli --list
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -B -m zzz_od.macos.cli --dry-run
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -B -m zzz_od.macos.cli --app APP_ID --dry-run
```

`APP_ID` 是占位符，替换为 `--list` 实际返回且可独立调用的任务 ID。

| 参数 | 作用与限制 |
| --- | --- |
| `-h`, `--help` | 打印帮助并退出，不创建任务上下文。 |
| `--app APP_ID` | 默认 `one_dragon`；指定原注册任务，不接受未知或不可独立调用的内部任务。 |
| `--list` | 列出注册任务的 `app_id`、`name`、`unavailable_reason`，不操作游戏。 |
| `--dry-run` | 验证账户平台及入口限制，返回当前账户、任务与限制；不初始化模型、采集或输入，不重置运行记录。 |
| `--resume-lost-void` | 仅与实际运行的 `--app lost_void` 配合，续接已核实的战线肃清中断挑战。 |
| `--resume-store-refreshed` | 必须同时带 `--resume-lost-void`；只用于已确认刷新过一次的当前商店，避免重复刷新。 |
| `--resume-signin-reward` | 仅与实际运行的 `--app daily_signin` 配合，续接已确认的当日卦象奖励/结果页。 |

`--list` 与 `--dry-run` 互斥。恢复参数不能用于这两种预览模式；不把恢复参数当作忽略错误或跳过初始化的开关。参数组合错误或宿主不是 Apple Silicon macOS 时，由 argparse 退出，退出码为 2。当前账户平台错误、未知任务或不适配则返回错误 JSON，退出码为 1。

`--list` 的空 `unavailable_reason` 只表示该任务的单项入口没有适配拒绝，不能保证当前资源和界面就绪；整组还需要 `--dry-run` 检查启用任务和配置。预览虽然不操作游戏，仍会创建并读取项目上下文，不是完全脱离安装环境的静态命令。

## 3. 选择任务与典型流程

1. 获取 `--list`，检查任务是否可独立调用及 `unavailable_reason`。
2. 读取当前账户计划和授权范围，用相同 `--app` 做 `--dry-run`。默认整组预览返回已启用项；单项预览返回该项的 `limits`。以安装版本的实际输出为准，不将未适配项默默跳过。
3. 核对记录、游戏刷新周期及已发生的奖励/耗电，确认不会重复后，去掉 `--dry-run` 执行一次。
4. 等待该进程真正结束，检查退出码和最终 JSON，再核对各任务实际结果。需要下一项时串行执行，不并发启动。

```sh
# 执行当前账户已启用的一条龙任务组
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -B -m zzz_od.macos.cli
# 执行一个已核实可独立调用的原任务
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -B -m zzz_od.macos.cli --app APP_ID
```

常见任务 ID 与能力边界（不是固定计划）：

| ID | 作用/核对点 |
| --- | --- |
| `one_dragon` | 当前账户启用的任务组；Mac 不支持多账户整组运行，结束后操作应为“无”。 |
| `daily_signin` | 当前 Mac 卦象签到适配；不假设其他签到地点已支持。 |
| `random_play`, `coffee` | 录像店与咖啡；核对当前地点、配置及是否已完成。 |
| `charge_plan` | 原体力计划；核对副本、卡数、编队、消耗、恢复设置与预览限制。 |
| `engagement_reward`, `ridu_weekly`, `city_fund` | 领取已达成奖励；周纪领奖不等于代做周任务，城募不等于购买等级或付费计划。 |
| `lost_void`, `notorious_hunt`, `intel_board` | 对应周常类应用；核对实际周期、目标与剩余次数，不凭任务名假设可以重复。 |
| `auto_battle`, `dodge_assistant` | 独立战斗/闪避助手；可能持续等待战斗，不把没有立即退出视作失败。 |
| `suibian_temple` | 以当前预览限制为准，不能假定随便观全部子功能可用。 |
| `predefined_team_checker` | 同步识别到的预备编队信息，属于配置写入，先确认用户授权。 |
| `mouse_sensitivity_checker` | Mac 摇杆校准并保存当前账户参数，属于配置写入，不当作只读状态探测。 |

恢复只能在确认原执行停止、当前界面与已发生资源变化后使用：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -B -m zzz_od.macos.cli --app lost_void --resume-lost-void
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -B -m zzz_od.macos.cli --app lost_void --resume-lost-void --resume-store-refreshed
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -B -m zzz_od.macos.cli --app daily_signin --resume-signin-reward
```

不要为验证恢复入口而重复出战、刷新商店或领奖。整组与单任务的完成跳过语义可能不同；单项入口不是天然幂等接口。

## 4. 状态、结果与停止

- `--list` 返回任务数组；`--dry-run` 返回 `instance_idx`、`app_id`、`tasks`，其中每项含 `app_id`、`name`、`limits`。
- 实际运行结束的 JSON 含 `success`、`app_id`、`instance_idx`、`finish_reason`、`status`、`failed_apps`。日志可能混在标准输出中，读取最后的结果 JSON，不把整个输出直接当单个 JSON 文档。
- 正常完成且整组没有失败子项时退出 0，否则退出 1；异常结果可能仅含 `success: false` 和 `status`。中断退出 130；参数错误通常为 2。`failed_apps` 是整组失败记录汇总，不保证单项失败时有内容。
- 程序成功不证明资源足够、所有计划次数完成或所有奖励已领。区分成功、已完成跳过、资源不足、失败、结果不明，核对任务记录及必要界面证据。
- CLI 没有独立状态子命令。只读检查当前进程、原日志和已保存任务记录；记录的 `run_status` 为 0 待运行、1 成功、2 失败、3 运行中，3 也可能是中断遗留。不要通过启动另一个运行上下文查询状态，不要清记录或改日期强迫重跑。
- 终端内按 Ctrl-C，或对已核实属于本任务的 PID 发送 SIGINT/SIGTERM。CLI 会登记中断并等待原任务停止、释放资源；等待真实退出，不能马上并发重启。不要宽泛杀掉其他游戏/用户进程，也不默认强杀。

## 5. 错误与安全处理

| 现象 | 操作 |
| --- | --- |
| 非 Apple Silicon / 非原生 Python | 修正环境选择，不伪装平台或跳过检查。 |
| 当前账户不是 macOS PlayCover | 在用户授权下通过原账户管理修正，CLI 不提供账户切换参数。 |
| 未知任务 / 不可独立调用 / 暂未适配 | 回到 `--list`、预览与当前配置，不能通过内部类强行运行。 |
| 初始化失败 / `NOT_STARTED` / 没有有效采集帧 | 查原日志与实际窗口是否就绪；确认未发生任务动作后有限重试，不复用旧帧。 |
| 辅助功能、屏幕采集、登录或验证码阻断 | 停止并说明需要用户处理的具体环节；不绕系统授权、自动解锁或转用另一宿主规避。 |
| 超时、未知页面、资源不足或结果不明 | 保留原记录，核对已经发生的消耗/奖励，再决定是否允许恢复；不盲目重发。 |
| 配置、依赖或代码变化 | 区分环境错误与任务错误；仅做获准的针对性处理，不默认升级全部依赖、重写计划或降低保护。 |

## 6. 公共技能与私人记录分离

本技能只维护可复用的 CLI 接口、步骤和安全判据。不向任何版本控制技能、design 或公共文档追加某位用户的运行时间线、账户/队伍/余额、设备绝对路径、日志、截图、失败现场或私人开发过程。确需保存执行证据时使用用户授权的本机私有运行目录；不要复制到本技能，也不要提交或推送这些记录。源码接口变化才更新公共使用说明。
