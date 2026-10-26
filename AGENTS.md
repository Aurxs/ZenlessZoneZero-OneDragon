# AGENTS.md

## 开始 Mac 迁移任务前

- 默认按 macOS / Apple Silicon / PlayCover 原生手柄迁移开展工作，保留上游 Windows 能力与增量合并边界；不要重新做平台选型、安装已可用的输入服务或从零搭框架。
- 先读并遵循 [Mac 手柄迁移开发约定](docs/develop/zzz/macos_gamepad_workflow.md)，再读[迁移进度](docs/develop/zzz/macos_migration_progress.md)顶部的当前入口及与任务相关的最新记录。历史阶段结论不能覆盖后面的验收结果。
- 收到“继续迁移”时，先查看两仓状态与已有实现，再选择未完成项推进；不要仅给计划或要求用户重复介绍背景。开发顺序和待条件验证以进度文件及本次用户要求为准。
- 做自定义体力材料时，从[体力迁移开发起点](docs/develop/zzz/macos_daily_routine.md#下一阶段更换体力材料与副本)开始，逐项追踪原计划字段到手柄选择路径；不能只放宽支持范围检查。
- 先执行 `git status --short`、`git -C zzz-od-test status --short`，保留已有改动。确认是否已有 GUI 或联调进程占用手柄/采集，避免两个进程或线程同时操作游戏。

## 实现边界

- 先复用原 Application、Operation、配置、运行记录和自动战斗；Mac 路径放 `src/zzz_od/operation/gamepad/`，通过原应用的平台分支接入，不新增平行的 Mac 任务体系。
- 不修改既有 Windows Xbox/DS4、OJD 或 HID 底层输入来迁就业务。界面操作使用新增兼容层，复用 `GamepadOperation` 的可配置等待；实时战斗保持原时序。
- 先通过已有准备游戏流程确认手柄模式，再开发和定位。触屏与手柄布局不同；必要启动点击只走已有启动适配层，不让自动任务依赖用户手动切模式。
- 移动端画面差异放 `assets/game_data/platform/ios_gamepad/`；保留 PC 资源。基准为 1920×1080，复用已有窗口归一化，不另写分辨率适配。
- 保留 PySide6 / Fluent GUI 与原计划编辑器。功能参数放游戏设置或对应任务设置，账户页负责账户管理；继续使用当前实例配置及 `YamlConfigAdapter`。
- 每个已支持任务必须能由一条龙独立完成。Computer Use 可观察游戏、操作一条龙 GUI；不能以手动游戏按键补完流程后宣称自动化通过。
- 不主动并行操作游戏。除非用户明确要求代理或新线程，否则由当前代理完成映射和验证；要求并行且未指定模型时，按工具支持选择 GPT-6.1-sol / xhigh，并隔离写入范围和设备占用。

## 代码与文档入口

- 原任务与配置：`src/zzz_od/application/`；手柄路径：`src/zzz_od/operation/gamepad/`；GUI：`src/zzz_od/gui/`。
- Mac 入口与能力提示：`src/zzz_od/macos/`；实例参数：`src/zzz_od/config/macos_config.py`；启动模式识别：`src/zzz_od/operation/enter_game/`。
- 公共框架：`src/one_dragon/`；公共 Qt 组件：`src/one_dragon_qt/`；OCR：`src/onnxocr/`。优先复用，不为单个路径大改框架。
- 涉及游戏交互前，读相关 `docs/game/gameplay/`、`docs/game/screens/`、`assets/game_data/screen_info/`、移动端覆盖及原代码。只补缺少的画面知识，不重复手动走完已有路径。
- 新画面按 `skills/zzz-od-dev-screen-onboarding/SKILL.md`，玩法补档按 `skills/zzz-od-dev-gameplay-onboarding/SKILL.md`；技能源文件在根目录 `skills/`，不要因工具目录未映射就认定缺失。
- 画面区域通过现有 CRUD 工具维护，模板通过 `TemplateInfo` 保存，不能手改缓存。流程、参数与验收写 `docs/develop/zzz/`，玩法和画面事实写 `docs/game/`。
- 精确状态与本机参数放[迁移进度](docs/develop/zzz/macos_migration_progress.md)，不堆进本文件。共同开发约定只维护一份，其他文档引用它。

## 本地运行与快速验证

在仓库根目录使用已有 `.venv`、Python 3.11 和 uv；优先 macOS zsh 可执行命令：

```shell
# 原 GUI 的 Mac 入口；仅在没有同类运行进程时启动
PYTHONPATH=src uv run --no-sync python -m zzz_od.macos.main
# 单个相关测试文件；不要替换成全量测试
QT_QPA_PLATFORM=offscreen PYTHONPATH=src uv run --no-sync pytest zzz-od-test/test/具体测试文件.py -q
# 只检查本次修改的 Python 文件
uv run --no-sync ruff check src/具体修改文件.py
```

- 默认不运行 `uv sync`、升级依赖、重写锁文件或重建已有授权的开发 app。仅在确认缺少依赖或启动器确需重建时处理；工具说明见 [tools/macos/README.md](tools/macos/README.md)。
- 普通 Qt 控件可离屏测试；完整原生 AppWindow 不用 offscreen。实机联调优先原 GUI / 已有生产 Operation 入口；主线程须维持 Cocoa 事件循环，参考 `tools/macos/run_combat_simulation.py`。
- `.debug/` 中脚本、截图与会话只属于本地证据；使用前检查是否存在、是否适用，不把忽略文件当成其他 checkout 必有的正式能力。
- 测试只写独立仓 `zzz-od-test/test/`，截图按该仓 `screens/` 约定归档，主仓不放测试。搜索用 `rg --files --no-ignore zzz-od-test/test` 或显式路径，避免忽略规则漏掉测试。
- 验证快速且聚焦：小型文档/参数/UI 调整只做必要检查；新功能只补关键行为的最小测试。不要跑全量 pytest、全量 Ruff、重复已经通过的检查，也不要删除或削弱已有测试。
- 未领取、已领取、资源不足、可选弹窗要区分。次数用完就记待条件，不反复消耗；通过已有目标不能证明所有材料或 Boss 都可用。

## 编码约束

- 函数签名和类成员写类型注解；使用 `list[str]`、`X | Y`，仅类型引用放 `TYPE_CHECKING`；禁止相对导入。
- 中文注释和 docstring；用直白语言，不造术语。构造函数显式列参数，不用 `**kwargs`；路径用 `pathlib`，格式化用 f-string。
- `__init__.py` 默认不导出模块。配置沿用 YAML / `YamlConfig`，GUI 优先现有 setting card 与 `AdapterInitMixin`。
- `ZContext` 的实例配置更新遵循 `reload_instance_config()` 机制。节点沿用 round 返回值与装饰器；父节点超时需覆盖子流程与等待。
- GPU/ONNX 异步推理通过 `gpu_executor.submit`，不并发直调多个 session。
- 详细架构与开发规范按需查[开发入口](docs/develop/README.md)、[编码规范](docs/develop/spec/agent_guidelines.md)、[应用开发](docs/develop/guides/application_plugin_guide.md)、[测试说明](docs/develop/testing/README.md)。

## 提交与协作

- 按本项目已对齐的习惯：完整组件或稳定、可运行的检查点完成后主动单独 commit；不提交半成品，不积攒成一个大提交。文档整理可独立提交。
- 主仓与测试仓使用同名分支，分别精确暂存自己的改动并配对提交；主仓不会收录被忽略的测试仓。没有测试改动时不制造空测试提交。
- 推送、开 PR、合并、删除分支、reset 按用户授权范围执行；不要把组件 commit 的约定扩大成任意远端操作。推送前核对 remote，避免写入上游。切换分支前按用户要求保存当前改动。
- 提交说明写清做了什么；PR 遵循 Conventional Commits，说明问题、最终改动、验证和限制。涉及两仓时关联 PR，跨仓链接使用完整仓库名；合并测试仓后再合并主仓。详细流程见 [development_workflow.md](docs/develop/development_workflow.md)。
- 不因风格问题大改原代码。新对话或并行任务的已有改动不能覆盖、回退或夹带提交。
- 修改本文件遵循[入口规范](docs/develop/harness/entry_files.md)，需用户明确要求或确认；其他 AI 入口引用本文件，不复制正文。
- 创建或修改技能前先读 `skills/zzz-od-dev-skill-guide/SKILL.md`；技能源在 `skills/`，重要决策同步其 `design.md`（若存在）。
