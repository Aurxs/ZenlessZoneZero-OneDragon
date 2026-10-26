# Mac 标题栏裁剪与采集缩放

窗口采集继续使用原`MacWindowCapture`和严格16:9归一化，不根据黑边或画面比例猜测标题栏。共同约定见[手柄迁移开发约定](../macos_gamepad_workflow.md)。

## 当前账户参数

游戏设置的Mac运行设置新增“标题栏高度（逻辑点）”。非0时按每帧的窗口点到输出像素缩放计算顶部裁剪；为0时使用已有“截图顶部裁剪（旧像素配置）”。旧账户不自动改单位。修改任一参数仍停止旧连接并要求重启，继续通过原账户配置与YAML适配器保存。

本机已确认标题栏为28逻辑点，当前账户设置`capture_top_inset_points=28`；旧`capture_top_inset_pixels=56`保留为兼容值，逻辑点设置优先。不能把其他机器的标题栏直接填成28，需先确认窗口装饰高度。

## 帧与启动点击

SCK输出可能为1倍或2倍。每个Complete帧保留自己的`pixel_scale`，由`scaleFactor`与`contentScale`计算；标题栏逻辑点据此转换成当前帧的裁剪像素。缓冲提取的`contentRect`已经包含内容缩放，保持原来的只乘显示缩放方式。字段定义见[Apple SCStreamFrameInfo](https://developer.apple.com/documentation/screencapturekit/scstreamframeinfo)。

启动专用指针直接使用确认过的逻辑点高度，避免把SCK输出像素与当前窗口逻辑点混用。旧像素调用保持原换算。Windows输入和窗口路径未修改。

裁剪后仍须通过16:9校验；有效帧时间、Idle观察与过期保护保持原有语义，不能通过修改时间或拉伸图片来掩盖错误比例。

## 验证边界

1倍与2倍合成帧、旧像素兼容、启动逻辑点、配置冲突和原Idle检查共8项通过；原控制器初始化1项、原启动坐标与拒绝错误比例2项通过。当前原生只读实测为1072×631、scaleFactor=1、contentScale=1，裁去28后成功得到1920×1080；2倍由合成帧覆盖，不把它写成本轮切屏实测。
