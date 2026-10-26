# Mac 镜头转向校准

共同边界见[手柄迁移开发约定](../macos_gamepad_workflow.md)。本组件复用原“一条龙 → 灵敏度校准”页面和 `MouseSensitivityChecker` 应用，不修改 Windows 鼠标、Xbox/DS4、OJD 或 HID 的实现。

## 使用范围

当前使用迷失之地入口层的唯一感叹号图标作为静止目标；角色不会移动，也不进行交互或战斗。已打开战况菜单时，只有同时识别到重新开始、退出战斗与返回才按一次 B 关闭。没有有效截图、目标不唯一或运行暂停时不发送校准输入。

GUI 点击开始后直接执行生产 `GamepadLostVoidCalibrateTurn(force=True)`。不能把 `op_to_enter_game` 当成必定执行的前置：原框架在窗口就绪时可跳过该恢复入口。

## 测量与保存

右摇杆以0.5幅度推动0.16秒，等待动画后读取同一唯一图标的水平位移，再反向推动相同时长。只有两次方向正确、位移在20至700像素、相对差不超过35%、最终回差不超过150像素才保存。

保存到当前实例的 `macos.yml`：

- `turn_distance_per_second`：该摇杆幅度对应的像素距离速度。
- `turn_stick_amplitude`：与速度配套的幅度；旧配置默认1.0，保持原参数含义。

失败保留旧参数，不写 `game_config.turn_dx` 或 Windows 的手柄速度。当前只测距离，不宣称完成 `turn_degrees_per_second` 的角度校准。

`ZMacController.move_camera` 仍核对暂停状态、新帧和连接，仅更新右摇杆，保留左摇杆状态。迷失之地移动继续复用原检测与脱困；Mac 子类把目标偏差转换为有界脉冲，进入中心容差后开始移动，不反复发落在摇杆死区内的小幅输入。

## 验证范围

双向保存、失败保留、唯一目标、暂停和原应用节点的聚焦测试放在独立测试仓 `test/tools/macos/test_gamepad_turn_calibration.py`；镜头入口的暂停保护放在原控制器测试中。实机结果与本机参数见[迁移进度](../macos_migration_progress.md)。
