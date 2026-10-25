#!/usr/bin/env swift
// 只读观察 GameController；不激活应用，不发送键鼠或手柄输入。
import Darwin
import Foundation
import GameController
import AppKit

/// 保存本进程改动前的队列和回调，以便断开或退出时恢复。
final class ControllerRecord {
    let controller: GCController
    let number: Int
    let previousQueue: DispatchQueue
    let previousHandler: GCExtendedGamepadValueChangedHandler?
    var changes: Int = 0

    init(controller: GCController, number: Int) {
        self.controller = controller
        self.number = number
        self.previousQueue = controller.handlerQueue
        self.previousHandler = controller.extendedGamepad?.valueChangedHandler
    }

    func restore() -> Void {
        controller.extendedGamepad?.valueChangedHandler = previousHandler
        controller.handlerQueue = previousQueue
    }
}

/// 所有设备通知、输入回调、信号和计时器均在主线程处理。
final class ControllerProbe {
    let started: TimeInterval = ProcessInfo.processInfo.systemUptime
    let formatter: ISO8601DateFormatter = ISO8601DateFormatter()
    let duration: TimeInterval
    let appkitEnabled: Bool
    let previousBackgroundMonitoring: Bool = GCController.shouldMonitorBackgroundEvents
    var observers: [NSObjectProtocol] = []
    var records: [ObjectIdentifier: ControllerRecord] = [:]
    var numbers: [ObjectIdentifier: Int] = [:]
    var retainedControllers: [GCController] = []
    var signalSources: [DispatchSourceSignal] = []
    var previousSignals: [Int32: sig_t] = [:]
    var timer: Timer? = nil
    var nextNumber: Int = 1
    var totalChanges: Int = 0
    var finished: Bool = false
    var exitCode: Int32 = 0

    init(duration: TimeInterval, appkitEnabled: Bool) {
        self.duration = duration
        self.appkitEnabled = appkitEnabled
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    }

    func emit(_ event: String, _ fields: [String: Any] = [:]) -> Void {
        var payload: [String: Any] = fields
        payload["event"] = event
        payload["time"] = formatter.string(from: Date())
        payload["elapsed_seconds"] = ProcessInfo.processInfo.systemUptime - started
        do {
            let data: Data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
            FileHandle.standardOutput.write(data)
            FileHandle.standardOutput.write(Data([10]))
        } catch {
            FileHandle.standardError.write(Data("JSON 编码失败：\(error)\n".utf8))
        }
    }

    func buttonState(_ button: GCControllerButtonInput) -> [String: Any] {
        return ["value": button.value, "pressed": button.isPressed]
    }

    func padState(_ pad: GCControllerDirectionPad) -> [String: Any] {
        return [
            "x": pad.xAxis.value, "y": pad.yAxis.value,
            "up": buttonState(pad.up), "down": buttonState(pad.down),
            "left": buttonState(pad.left), "right": buttonState(pad.right),
        ]
    }

    func state(_ gamepad: GCExtendedGamepad) -> [String: Any] {
        var buttons: [String: Any] = [:]
        // physicalInputProfile 收录该设备暴露的附加按钮；标准项在下方使用固定名称。
        for (name, button) in gamepad.controller?.physicalInputProfile.buttons ?? [:] {
            buttons[name] = buttonState(button)
        }
        let standard: [(String, GCControllerButtonInput?)] = [
            ("buttonA", gamepad.buttonA), ("buttonB", gamepad.buttonB),
            ("buttonX", gamepad.buttonX), ("buttonY", gamepad.buttonY),
            ("leftShoulder", gamepad.leftShoulder), ("rightShoulder", gamepad.rightShoulder),
            ("leftTrigger", gamepad.leftTrigger), ("rightTrigger", gamepad.rightTrigger),
            ("buttonMenu", gamepad.buttonMenu), ("buttonOptions", gamepad.buttonOptions),
            ("buttonHome", gamepad.buttonHome),
            ("leftThumbstickButton", gamepad.leftThumbstickButton),
            ("rightThumbstickButton", gamepad.rightThumbstickButton),
        ]
        for (name, button) in standard {
            buttons[name] = button.map(buttonState) ?? NSNull()
        }
        return [
            "buttons": buttons,
            "leftThumbstick": padState(gamepad.leftThumbstick),
            "rightThumbstick": padState(gamepad.rightThumbstick),
            "dpad": padState(gamepad.dpad),
        ]
    }

    func connect(_ controller: GCController, source: String) -> Void {
        guard !finished else { return }
        let identity: ObjectIdentifier = ObjectIdentifier(controller)
        guard records[identity] == nil else { return }
        let number: Int
        if let known: Int = numbers[identity] {
            number = known
        } else {
            number = nextNumber
            nextNumber += 1
            numbers[identity] = number
            // 保留身份对象，避免已断开的对象地址被复用而混淆编号。
            retainedControllers.append(controller)
        }
        let record: ControllerRecord = ControllerRecord(controller: controller, number: number)
        records[identity] = record
        controller.handlerQueue = .main
        emit("connected", [
            "controller": number, "source": source,
            "vendorName": controller.vendorName as Any? ?? NSNull(),
            "productCategory": controller.productCategory,
            "extendedGamepad": controller.extendedGamepad != nil,
        ])
        guard let gamepad: GCExtendedGamepad = controller.extendedGamepad else { return }
        gamepad.valueChangedHandler = { [weak self, weak record] pad, element in
            guard let self: ControllerProbe = self,
                  let record: ControllerRecord = record, !self.finished else { return }
            record.changes += 1
            self.totalChanges += 1
            self.emit("value_changed", [
                "controller": record.number,
                "element": element.localizedName as Any? ?? String(describing: type(of: element)),
                "state": self.state(pad),
            ])
        }
        emit("initial_state", ["controller": number, "state": state(gamepad)])
    }

    func disconnect(_ controller: GCController) -> Void {
        let identity: ObjectIdentifier = ObjectIdentifier(controller)
        guard let record: ControllerRecord = records.removeValue(forKey: identity) else { return }
        emit("disconnected", ["controller": record.number, "changes": record.changes])
        record.restore()
    }

    func start() -> Void {
        let center: NotificationCenter = NotificationCenter.default
        // 先订阅，再枚举，以免两者之间漏掉连接；connect 按对象身份去重。
        observers.append(center.addObserver(forName: .GCControllerDidConnect, object: nil, queue: .main) {
            [weak self] notification in
            if let controller: GCController = notification.object as? GCController {
                self?.connect(controller, source: "notification")
            }
        })
        observers.append(center.addObserver(forName: .GCControllerDidDisconnect, object: nil, queue: .main) {
            [weak self] notification in
            if let controller: GCController = notification.object as? GCController {
                self?.disconnect(controller)
            }
        })
        GCController.shouldMonitorBackgroundEvents = true
        emit("started", [
            "duration_seconds": duration, "read_only": true,
            "runtime": appkitEnabled ? "appkit" : "foundation",
            "backgroundMonitoring": true,
            "note": "后台监听仅影响本观察进程；不能据此判断游戏失焦输入已通过",
        ])
        for controller: GCController in GCController.controllers() {
            connect(controller, source: "enumeration")
        }
        emit("enumeration_complete", ["connected_controllers": records.count])
        for number: Int32 in [SIGINT, SIGTERM] {
            previousSignals[number] = signal(number, SIG_IGN)
            let source: DispatchSourceSignal = DispatchSource.makeSignalSource(signal: number, queue: .main)
            source.setEventHandler { [weak self] in
                self?.finish(reason: "signal", signum: number)
            }
            signalSources.append(source)
            source.resume()
        }
        timer = Timer.scheduledTimer(withTimeInterval: duration, repeats: false) { [weak self] _ in
            self?.finish(reason: "duration")
        }
    }

    func finish(reason: String, signum: Int32? = nil) -> Void {
        guard !finished else { return }
        finished = true
        timer?.invalidate()
        timer = nil
        for observer: NSObjectProtocol in observers {
            NotificationCenter.default.removeObserver(observer)
        }
        observers.removeAll()
        for record: ControllerRecord in records.values {
            if let gamepad: GCExtendedGamepad = record.controller.extendedGamepad {
                emit("final_state", ["controller": record.number, "state": state(gamepad)])
            }
            record.restore()
        }
        GCController.shouldMonitorBackgroundEvents = previousBackgroundMonitoring
        for source: DispatchSourceSignal in signalSources { source.cancel() }
        signalSources.removeAll()
        for (number, handler) in previousSignals { signal(number, handler) }
        previousSignals.removeAll()
        if let number: Int32 = signum { exitCode = 128 + number }
        emit("summary", [
            "reason": reason, "signal": signum as Any? ?? NSNull(),
            "controllers_seen": numbers.count, "connected_controllers": records.count,
            "value_changes": totalChanges, "exitcode": exitCode,
            "backgroundMonitoringRestored": previousBackgroundMonitoring,
        ])
        records.removeAll()
        retainedControllers.removeAll()
    }
}

func parseOptions(_ arguments: [String]) -> (duration: TimeInterval, appkit: Bool)? {
    var duration: TimeInterval = 15
    var durationSeen: Bool = false
    var appkit: Bool = false
    var iterator: IndexingIterator<[String]> = arguments.makeIterator()
    while let argument: String = iterator.next() {
        switch argument {
        case "--appkit":
            guard !appkit else { return nil }
            appkit = true
        case "--duration":
            guard !durationSeen, let text: String = iterator.next(),
                  let value: Double = Double(text), value.isFinite,
                  value > 0, value <= 300 else { return nil }
            durationSeen = true
            duration = value
        default:
            return nil
        }
    }
    return (duration, appkit)
}

let arguments: [String] = Array(CommandLine.arguments.dropFirst())
if arguments == ["--help"] || arguments == ["-h"] {
    print("用法：gamecontroller_probe [--duration 秒数] [--appkit]（默认 15，最大 300，只读 JSONL）")
    exit(0)
}
guard let options: (duration: TimeInterval, appkit: Bool) = parseOptions(arguments) else {
    FileHandle.standardError.write(Data("参数错误：仅接受 --appkit 和 --duration（大于 0 且不超过 300 的有限秒数），各一次\n".utf8))
    exit(2)
}
// shared 完成 AppKit 初始化；prohibited 禁止窗口和激活，不调用 finishLaunching/run。
let application: NSApplication? = options.appkit ? NSApplication.shared : nil
if let application: NSApplication = application {
    guard application.activationPolicy() == .prohibited || application.setActivationPolicy(.prohibited) else {
        FileHandle.standardError.write(Data("无法设置禁止激活策略（当前值 \(application.activationPolicy().rawValue)），停止观察\n".utf8))
        exit(1)
    }
}
let probe: ControllerProbe = ControllerProbe(duration: options.duration, appkitEnabled: options.appkit)
probe.start()
while !probe.finished {
    _ = RunLoop.main.run(mode: .default, before: Date(timeIntervalSinceNow: 0.05))
}
exit(probe.exitCode)
