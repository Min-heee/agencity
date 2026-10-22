// 에이전시티 맥 앱: 설치 폴더의 start.py --app을 켜고, 알려 준 주소(127.0.0.1)를 창 하나에 보여 줘요.
//
// bin/make_mac_app.sh가 이 맥에서 직접 컴파일해서 "Agencity.app"으로 묶어요(서명 계정 없이 임시 서명).
// - 설치 폴더: Contents/Resources/install_dir.txt (폴더를 옮기면 앱을 다시 만들어요)
// - 서버: /usr/bin/env python3 <설치 폴더>/start.py --app → 출력의 AGENCITY_URL=… 줄을 읽어 창에 열어요.
//   앱을 끝내면 SIGTERM을 보내고, 3초 뒤에도 남아 있으면 강제로 꺼요. 앱이 갑자기 꺼져도 start.py는
//   앱과 이어진 표준입력이 닫히는 걸 보고 스스로 꺼요.
//   start.py에는 AGENCITY_APP=1과 AGENCITY_APP_BUNDLE=<이 앱 경로>를 넘겨요(앱 안 업데이트가 이 자리에 앱을 다시 만들어 열어요).
// - 127.0.0.1이 아닌 링크와 새 창(window.open, target=_blank)은 기본 브라우저로 열어요.
// - 창을 닫아도 앱(과 서버)은 켜 둬요. Dock 아이콘을 누르면 창이 다시 떠요. 끄려면 ⌘Q.
// - Agencity --make-iconset <폴더>: 아이콘 PNG들을 그려요(make_mac_app.sh가 iconutil로 묶어요).
// macOS 12 이상, Swift 5.5 이상에서 컴파일되게 새 문법은 쓰지 않아요.

import AppKit
import WebKit

let appTitle = "에이전시티"
let urlPrefix = "AGENCITY_URL="
let notePrefix = "AGENCITY_NOTE="

func tildePath(_ path: String) -> String {
    let home = NSHomeDirectory()
    return path == home || path.hasPrefix(home + "/") ? "~" + path.dropFirst(home.count) : path
}

func isLocalPage(_ url: URL) -> Bool {
    let scheme = (url.scheme ?? "").lowercased()
    let host = (url.host ?? "").lowercased()
    return (scheme == "http" || scheme == "https") && (host == "127.0.0.1" || host == "localhost")
}

/// 메인 스레드에서 실행해요. GCD 메인 큐 대신 런루프에 올려서, 끄기를 기다리는 동안(terminateLater)에도 돌아요.
/// (메인 큐 블록 안에서 NSApp.terminate를 부르면 그 안의 기다림이 메인 큐를 막아 영영 안 꺼져요.)
func onMainRunLoop(_ block: @escaping () -> Void) {
    RunLoop.main.perform(inModes: [.common, .modalPanel], block: block)
    CFRunLoopWakeUp(CFRunLoopGetMain())
}

/// 앱 밖(기본 브라우저·Claude 앱 등)으로 여는 링크. 파일이나 다른 앱을 실행하는 주소는 열지 않아요.
func openOutside(_ url: URL?) {
    guard let url = url else { return }
    let scheme = (url.scheme ?? "").lowercased()
    if ["http", "https", "mailto", "claude"].contains(scheme) {
        NSWorkspace.shared.open(url)
    } else {
        NSLog("에이전시티: 열지 않은 링크 %@", url.absoluteString)
    }
}

// MARK: - start.py 실행

final class OfficeServer {
    let installDir: String
    var onURL: ((URL) -> Void)?
    var onNote: ((String) -> Void)?
    var onExit: ((Int32, Bool) -> Void)?   // (종료 코드, 주소를 받았는지)
    private(set) var url: URL?
    private var process: Process?
    private var input: Pipe?      // 쓰지 않고 열어만 둬요. 앱이 꺼지면 닫혀서 start.py가 알아채요.
    private var pending = Data()
    private var lines: [String] = []

    init(installDir: String) {
        self.installDir = installDir
    }

    var isRunning: Bool { return process?.isRunning ?? false }

    /// 최근 출력(오류 화면에 보여 줘요).
    func recentOutput(_ n: Int = 40) -> String {
        return lines.suffix(n).joined(separator: "\n")
    }

    func start() throws {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        p.arguments = ["python3", installDir + "/start.py", "--app"]
        p.currentDirectoryURL = URL(fileURLWithPath: installDir)
        p.environment = OfficeServer.childEnvironment()
        let inp = Pipe(), out = Pipe()
        p.standardInput = inp
        p.standardOutput = out
        p.standardError = out    // 표준출력과 한 줄씩 섞여도 순서대로 보여요
        out.fileHandleForReading.readabilityHandler = { [weak self] h in
            let d = h.availableData
            if d.isEmpty { h.readabilityHandler = nil }
            DispatchQueue.main.async { self?.consume(d) }
        }
        p.terminationHandler = { [weak self] proc in
            let code = proc.terminationStatus
            // 남은 출력이 먼저 들어오게 조금 기다려요.
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { self?.finished(proc, code) }
        }
        url = nil
        pending = Data()
        lines = []
        try p.run()
        process = p
        input = inp
        NSLog("에이전시티: start.py를 켰어요 (pid %d, %@)", p.processIdentifier, installDir)
    }

    /// SIGTERM → 3초 안에 안 꺼지면 start.py와 그 자식(서버)까지 강제로 꺼요.
    func stop(then done: @escaping () -> Void) {
        guard let p = process, p.isRunning else { done(); return }
        let pid = p.processIdentifier
        p.terminate()
        DispatchQueue.global().async {
            let deadline = Date().addingTimeInterval(3)
            while p.isRunning && Date() < deadline { usleep(50_000) }
            if p.isRunning {
                NSLog("에이전시티: 3초 안에 꺼지지 않아 강제로 꺼요 (pid %d)", pid)
                for c in OfficeServer.childPIDs(pid) { kill(c, SIGKILL) }
                kill(pid, SIGKILL)
                let until = Date().addingTimeInterval(1)
                while p.isRunning && Date() < until { usleep(20_000) }
            }
            onMainRunLoop(done)
        }
    }

    private func consume(_ d: Data) {
        pending.append(d)
        while let nl = pending.firstIndex(of: 0x0A) {
            let line = String(decoding: pending[pending.startIndex..<nl], as: UTF8.self)
            pending.removeSubrange(pending.startIndex...nl)
            handle(line)
        }
        if d.isEmpty && !pending.isEmpty {   // 끝: 줄바꿈 없이 남은 출력
            handle(String(decoding: pending, as: UTF8.self))
            pending = Data()
        } else if pending.count > 64 * 1024 {
            handle(String(decoding: pending, as: UTF8.self))
            pending = Data()
        }
    }

    private func handle(_ line: String) {
        lines.append(line)
        if lines.count > 400 { lines.removeFirst(lines.count - 400) }
        if line.hasPrefix(urlPrefix) && url == nil {
            let s = line.dropFirst(urlPrefix.count).trimmingCharacters(in: .whitespacesAndNewlines)
            if let u = URL(string: s), u.scheme == "http", u.host == "127.0.0.1" {
                url = u
                NSLog("에이전시티: 주소 %@", s)
                onURL?(u)
            }
        } else if line.hasPrefix(notePrefix) {
            onNote?(String(line.dropFirst(notePrefix.count)))
        }
    }

    private func finished(_ p: Process, _ code: Int32) {
        guard p === process else { return }
        process = nil
        input = nil
        NSLog("에이전시티: start.py가 끝났어요 (코드 %d)", code)
        let cb = onExit
        onURL = nil; onNote = nil; onExit = nil   // 콜백이 이 객체를 잡고 있지 않게
        cb?(code, url != nil)
    }

    /// Finder에서 켠 앱은 PATH가 짧아요. Homebrew 등의 python3·gh·jq를 찾을 수 있게 앞에 붙여요.
    static func childEnvironment() -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        var parts = (env["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin").split(separator: ":").map(String.init)
        for dir in [NSHomeDirectory() + "/.local/bin", "/usr/local/bin", "/opt/homebrew/sbin", "/opt/homebrew/bin"]
        where !parts.contains(dir) {
            parts.insert(dir, at: 0)
        }
        env["PATH"] = parts.joined(separator: ":")
        env["PYTHONUNBUFFERED"] = "1"
        env["AGENCITY_APP"] = "1"   // 맥 앱 안에서 켠 서버라는 표시
        // 앱 안 업데이트(bin/self_update.py)가 이 앱을 같은 자리에 다시 만들고 열 수 있게 앱 경로를 알려요.
        let bundle = Bundle.main.bundlePath
        if bundle.hasSuffix(".app") {
            env["AGENCITY_APP_BUNDLE"] = bundle
        } else {
            env.removeValue(forKey: "AGENCITY_APP_BUNDLE")
        }
        return env
    }

    static func childPIDs(_ pid: Int32) -> [Int32] {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/pgrep")
        p.arguments = ["-P", String(pid)]
        let out = Pipe()
        p.standardOutput = out
        p.standardError = FileHandle.nullDevice
        do { try p.run() } catch { return [] }
        let data = out.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()
        return String(decoding: data, as: UTF8.self).split(separator: "\n").compactMap { Int32($0) }
    }
}

// MARK: - 켜는 중·오류 화면

final class StatusView: NSView {
    private let icon = NSImageView()
    private let spinner = NSProgressIndicator()
    private let title = NSTextField(labelWithString: "")
    private let message = NSTextField(wrappingLabelWithString: "")
    private let logScroll = NSTextView.scrollableTextView()
    private var logView: NSTextView { return logScroll.documentView as! NSTextView }
    private let buttons = NSStackView()
    let retryButton = NSButton(title: "다시 시도", target: nil, action: nil)
    let folderButton = NSButton(title: "설치 폴더 열기", target: nil, action: nil)
    let quitButton = NSButton(title: "끝내기", target: nil, action: nil)

    override init(frame: NSRect) {
        super.init(frame: frame)
        icon.image = NSApp.applicationIconImage
        icon.imageScaling = .scaleProportionallyUpOrDown
        spinner.style = .spinning
        spinner.controlSize = .regular
        title.font = NSFont.systemFont(ofSize: 20, weight: .semibold)
        title.alignment = .center
        message.font = NSFont.systemFont(ofSize: 13)
        message.textColor = .secondaryLabelColor
        message.alignment = .center
        message.isSelectable = true
        message.preferredMaxLayoutWidth = 560
        logView.isEditable = false
        logView.isSelectable = true
        logView.font = NSFont.monospacedSystemFont(ofSize: 11, weight: .regular)
        logView.textContainerInset = NSSize(width: 6, height: 6)
        logScroll.borderType = .bezelBorder
        retryButton.keyEquivalent = "\r"
        retryButton.bezelStyle = .rounded
        folderButton.bezelStyle = .rounded
        quitButton.bezelStyle = .rounded
        buttons.orientation = .horizontal
        buttons.spacing = 10
        for b in [quitButton, folderButton, retryButton] { buttons.addArrangedSubview(b) }

        let stack = NSStackView(views: [icon, spinner, title, message, logScroll, buttons])
        stack.orientation = .vertical
        stack.alignment = .centerX
        stack.spacing = 14
        stack.setCustomSpacing(18, after: icon)
        stack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(stack)
        NSLayoutConstraint.activate([
            stack.centerXAnchor.constraint(equalTo: centerXAnchor),
            stack.centerYAnchor.constraint(equalTo: centerYAnchor),
            stack.widthAnchor.constraint(lessThanOrEqualTo: widthAnchor, constant: -48),
            stack.topAnchor.constraint(greaterThanOrEqualTo: topAnchor, constant: 24),
            icon.widthAnchor.constraint(equalToConstant: 72),
            icon.heightAnchor.constraint(equalToConstant: 72),
            message.widthAnchor.constraint(lessThanOrEqualToConstant: 560),
            logScroll.heightAnchor.constraint(equalToConstant: 220),
            logScroll.widthAnchor.constraint(lessThanOrEqualTo: widthAnchor, constant: -48),
        ])
        let wide = logScroll.widthAnchor.constraint(equalToConstant: 600)   // 창이 좁으면 줄어들게
        wide.priority = .defaultHigh
        wide.isActive = true
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }

    override func draw(_ dirtyRect: NSRect) {
        NSColor.windowBackgroundColor.setFill()
        dirtyRect.fill()
    }

    func showProgress(_ text: String, _ detail: String = "") {
        isHidden = false
        spinner.isHidden = false
        spinner.startAnimation(nil)
        title.stringValue = text
        message.stringValue = detail
        message.isHidden = detail.isEmpty
        logScroll.isHidden = true
        buttons.isHidden = true
    }

    func setDetail(_ detail: String) {
        message.stringValue = detail
        message.isHidden = detail.isEmpty
    }

    func showError(_ text: String, _ detail: String, log: String, folder: Bool) {
        isHidden = false
        spinner.stopAnimation(nil)
        spinner.isHidden = true
        title.stringValue = text
        message.stringValue = detail
        message.isHidden = detail.isEmpty
        logView.string = log
        logView.scrollToEndOfDocument(nil)
        logScroll.isHidden = log.isEmpty
        folderButton.isHidden = !folder
        buttons.isHidden = false
        window?.makeFirstResponder(retryButton)
    }

    func hide() {
        spinner.stopAnimation(nil)
        isHidden = true
    }
}

// MARK: - 앱

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var status: StatusView!
    var server: OfficeServer?
    var installDir = ""
    var pageURL: URL?
    var note: String?
    var quitting = false
    var signalSources: [DispatchSourceSignal] = []

    func applicationDidFinishLaunching(_ notification: Notification) {
        UserDefaults.standard.set(false, forKey: "NSFullScreenMenuItemEverywhere")
        buildMenus()
        buildWindow()
        catchSignals()
        installDir = readInstallDir()
        startServer()
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return false   // 창을 닫아도 서버는 켜 둬요(총괄 전달이 끊기지 않게)
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindow(nil)
        return true
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if quitting { return .terminateCancel }   // 이미 끄는 중
        guard let s = server, s.isRunning else { return .terminateNow }
        quitting = true
        status.showProgress("끄는 중이에요…")
        NSLog("에이전시티: 끄는 중이에요. start.py에 종료 신호를 보내요")
        s.stop {
            NSLog("에이전시티: start.py가 꺼졌어요. 앱을 끝내요")
            NSApp.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }

    /// kill·로그아웃 등으로 받은 종료 신호도 ⌘Q처럼 서버를 정리하고 끝내요.
    func catchSignals() {
        for sig in [SIGTERM, SIGINT, SIGHUP] {
            // 무시(SIG_IGN)로 두면 자식(start.py)에게 그대로 물려져서, 빈 처리기를 둬요(exec 때 기본값으로 돌아가요).
            signal(sig) { _ in }
            let src = DispatchSource.makeSignalSource(signal: sig, queue: .main)
            src.setEventHandler { onMainRunLoop { NSApp.terminate(nil) } }
            src.resume()
            signalSources.append(src)
        }
    }

    // MARK: 설치 폴더와 서버

    func readInstallDir() -> String {
        if let f = Bundle.main.url(forResource: "install_dir", withExtension: "txt"),
           let s = try? String(contentsOf: f, encoding: .utf8) {
            return s.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return ""
    }

    func startServer() {
        note = nil
        let startPy = installDir + "/start.py"
        guard !installDir.isEmpty, FileManager.default.fileExists(atPath: startPy) else {
            let shown = installDir.isEmpty ? "(적혀 있지 않아요)" : tildePath(installDir)
            status.showError("설치 폴더를 찾지 못했어요",
                             "앱이 가리키는 폴더 \(shown) 에 start.py가 없어요. 폴더를 옮겼다면 새 위치에서 "
                                + "sh bin/make_mac_app.sh 로 앱을 다시 만들거나, 설치 줄을 다시 실행해 주세요.",
                             log: "", folder: false)
            return
        }
        status.showProgress("사무실을 켜는 중이에요…", tildePath(installDir))
        let s = OfficeServer(installDir: installDir)
        s.onURL = { [weak self] u in self?.open(u) }
        s.onNote = { [weak self] n in self?.note = n }
        s.onExit = { [weak self] code, gotURL in self?.serverExited(s, code, gotURL) }
        server = s
        do {
            try s.start()
        } catch {
            server = nil
            status.showError("에이전시티를 켜지 못했어요", "python3를 실행하지 못했어요: \(error.localizedDescription)",
                             log: "", folder: true)
            return
        }
        // 폴더 접근을 묻는 창(문서·다운로드 폴더 등)이 떠 있으면 거기서 멈춰 있을 수 있어요.
        DispatchQueue.main.asyncAfter(deadline: .now() + 12) { [weak self] in
            guard let self = self, self.server === s, s.isRunning, s.url == nil else { return }
            self.status.setDetail("조금 오래 걸리고 있어요. 폴더 접근을 묻는 창이 떠 있으면 허용해 주세요.")
        }
    }

    func open(_ u: URL) {
        pageURL = u
        webView.load(URLRequest(url: u))
    }

    func serverExited(_ s: OfficeServer, _ code: Int32, _ gotURL: Bool) {
        guard server === s, !quitting else { return }
        server = nil
        if !gotURL {
            var hint = "아래 기록을 확인해 주세요. 터미널에서 python3 \"\(tildePath(installDir))/start.py\" 로 켜 보면 더 자세히 볼 수 있어요."
            if code == 127 {
                hint = "python3를 찾지 못했어요. 터미널에서 xcode-select --install 로 명령어 도구를 설치한 뒤 다시 시도해 주세요."
            }
            status.showError("에이전시티를 켜지 못했어요", hint, log: s.recentOutput(), folder: true)
            return
        }
        // 이미 켜져 있던 사무실을 알려 주고 끝난 경우(그 서버는 다른 곳에서 켠 것)면 그대로 써요.
        guard let u = s.url else { return }
        probe(u) { [weak self] alive in
            guard let self = self, !alive, self.server == nil, !self.quitting else { return }
            self.status.showError("사무실 서버가 꺼졌어요", "다시 켜려면 아래 단추를 눌러요.",
                                  log: s.recentOutput(), folder: true)
        }
    }

    func probe(_ u: URL, _ done: @escaping (Bool) -> Void) {
        let cfg = URLSessionConfiguration.ephemeral
        cfg.connectionProxyDictionary = [:]
        cfg.timeoutIntervalForRequest = 2
        let session = URLSession(configuration: cfg)
        session.dataTask(with: u.appendingPathComponent("api/state")) { _, resp, _ in
            let ok = (resp as? HTTPURLResponse)?.statusCode == 200
            DispatchQueue.main.async { done(ok) }
        }.resume()
        session.finishTasksAndInvalidate()
    }

    @objc func retry(_ sender: Any?) {
        if let s = server, s.isRunning, let u = pageURL {
            status.showProgress("다시 여는 중이에요…")
            webView.load(URLRequest(url: u))
        } else {
            startServer()
        }
    }

    @objc func openInstallFolder(_ sender: Any?) {
        guard !installDir.isEmpty else { return }
        NSWorkspace.shared.open(URL(fileURLWithPath: installDir))
    }

    // MARK: 창

    func buildWindow() {
        var rect = NSRect(x: 0, y: 0, width: 1280, height: 820)
        if let vf = NSScreen.main?.visibleFrame {
            rect.size.width = min(rect.width, vf.width - 60)
            rect.size.height = min(rect.height, vf.height - 60)
        }
        window = NSWindow(contentRect: rect, styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = appTitle
        window.minSize = NSSize(width: 640, height: 460)
        window.isReleasedWhenClosed = false
        window.tabbingMode = .disallowed
        window.collectionBehavior.insert(.fullScreenPrimary)
        window.delegate = self
        window.center()
        window.setFrameAutosaveName("AgencityMain")

        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        let ver = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0"
        config.applicationNameForUserAgent = "AgencityApp/\(ver)"   // 페이지가 앱 안인지 알 수 있게
        webView = WKWebView(frame: window.contentLayoutRect, configuration: config)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsBackForwardNavigationGestures = true
        webView.allowsMagnification = true
        let zoom = UserDefaults.standard.double(forKey: "pageZoom")
        if zoom >= 0.5 && zoom <= 3 { webView.pageZoom = CGFloat(zoom) }
        #if compiler(>=5.8)
        if #available(macOS 13.3, *) { webView.isInspectable = true }
        #endif

        let container = NSView(frame: window.contentLayoutRect)
        webView.frame = container.bounds
        webView.autoresizingMask = [.width, .height]
        container.addSubview(webView)
        status = StatusView(frame: container.bounds)
        status.autoresizingMask = [.width, .height]
        status.retryButton.target = self
        status.retryButton.action = #selector(retry(_:))
        status.folderButton.target = self
        status.folderButton.action = #selector(openInstallFolder(_:))
        status.quitButton.target = NSApp
        status.quitButton.action = #selector(NSApplication.terminate(_:))
        container.addSubview(status)
        window.contentView = container
        window.makeKeyAndOrderFront(nil)
    }

    @objc func showWindow(_ sender: Any?) {
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    // MARK: 메뉴

    func buildMenus() {
        let main = NSMenu()
        func add(_ menu: NSMenu, _ title: String, _ action: Selector?, _ key: String = "",
                 _ mods: NSEvent.ModifierFlags = [.command], target: AnyObject? = nil) {
            let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
            item.keyEquivalentModifierMask = mods
            item.target = target
            menu.addItem(item)
        }
        func top(_ title: String) -> NSMenu {
            let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
            let menu = NSMenu(title: title)
            item.submenu = menu
            main.addItem(item)
            return menu
        }
        let name = "Agencity"

        let app = top(name)
        add(app, "\(name)에 관하여", #selector(NSApplication.orderFrontStandardAboutPanel(_:)))
        app.addItem(.separator())
        let services = NSMenuItem(title: "서비스", action: nil, keyEquivalent: "")
        services.submenu = NSMenu(title: "서비스")
        NSApp.servicesMenu = services.submenu
        app.addItem(services)
        app.addItem(.separator())
        add(app, "\(name) 가리기", #selector(NSApplication.hide(_:)), "h")
        add(app, "기타 가리기", #selector(NSApplication.hideOtherApplications(_:)), "h", [.command, .option])
        add(app, "모두 보기", #selector(NSApplication.unhideAllApplications(_:)))
        app.addItem(.separator())
        add(app, "\(name) 종료", #selector(NSApplication.terminate(_:)), "q")

        let edit = top("편집")
        add(edit, "실행 취소", Selector(("undo:")), "z")
        add(edit, "실행 복귀", Selector(("redo:")), "z", [.command, .shift])
        edit.addItem(.separator())
        add(edit, "오려두기", #selector(NSText.cut(_:)), "x")
        add(edit, "복사하기", #selector(NSText.copy(_:)), "c")
        add(edit, "붙여넣기", #selector(NSText.paste(_:)), "v")
        add(edit, "삭제", #selector(NSText.delete(_:)))
        add(edit, "전체 선택", #selector(NSText.selectAll(_:)), "a")

        let view = top("보기")
        add(view, "새로고침", #selector(reloadPage(_:)), "r", target: self)
        view.addItem(.separator())
        add(view, "뒤로", #selector(goBack(_:)), "[", target: self)
        add(view, "앞으로", #selector(goForward(_:)), "]", target: self)
        add(view, "사무실 첫 화면", #selector(goHome(_:)), "h", [.command, .shift], target: self)
        view.addItem(.separator())
        add(view, "실제 크기", #selector(zoomReset(_:)), "0", target: self)
        add(view, "확대", #selector(zoomIn(_:)), "=", target: self)
        add(view, "축소", #selector(zoomOut(_:)), "-", target: self)
        view.addItem(.separator())
        add(view, "브라우저에서 열기", #selector(openInBrowser(_:)), target: self)
        view.addItem(.separator())
        add(view, "전체 화면 시작", #selector(NSWindow.toggleFullScreen(_:)), "f", [.command, .control])

        let win = top("윈도우")
        add(win, "최소화", #selector(NSWindow.performMiniaturize(_:)), "m")
        add(win, "확대/축소", #selector(NSWindow.performZoom(_:)))
        add(win, "닫기", #selector(NSWindow.performClose(_:)), "w")
        win.addItem(.separator())
        add(win, "사무실 창 보기", #selector(showWindow(_:)), "1", target: self)
        win.addItem(.separator())
        add(win, "모두 앞으로 가져오기", #selector(NSApplication.arrangeInFront(_:)))
        NSApp.windowsMenu = win

        let help = top("도움말")
        add(help, "에이전시티 안내(GitHub)", #selector(openHelp(_:)), target: self)
        add(help, "설치 폴더 열기", #selector(openInstallFolder(_:)), target: self)
        NSApp.helpMenu = help

        NSApp.mainMenu = main
    }

    @objc func reloadPage(_ sender: Any?) {
        if !status.isHidden || webView.url == nil { retry(nil) } else { webView.reload() }
    }

    @objc func goBack(_ sender: Any?) { webView.goBack() }
    @objc func goForward(_ sender: Any?) { webView.goForward() }

    @objc func goHome(_ sender: Any?) {
        if let u = pageURL { webView.load(URLRequest(url: u)) }
    }

    func setZoom(_ z: CGFloat) {
        let v = max(0.5, min(3, z))
        webView.pageZoom = v
        UserDefaults.standard.set(Double(v), forKey: "pageZoom")
    }

    @objc func zoomReset(_ sender: Any?) { setZoom(1) }
    @objc func zoomIn(_ sender: Any?) { setZoom(webView.pageZoom + 0.1) }
    @objc func zoomOut(_ sender: Any?) { setZoom(webView.pageZoom - 0.1) }

    @objc func openInBrowser(_ sender: Any?) {
        if let u = webView.url ?? pageURL, isLocalPage(u) { NSWorkspace.shared.open(u) }
    }

    @objc func openHelp(_ sender: Any?) {
        openOutside(URL(string: "https://github.com/Min-heee/agencity#readme"))
    }

    // MARK: 웹 화면

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.allow); return }
        let scheme = (url.scheme ?? "").lowercased()
        if ["about", "data", "blob"].contains(scheme) { decisionHandler(.allow); return }
        if let frame = navigationAction.targetFrame {
            if !frame.isMainFrame || isLocalPage(url) { decisionHandler(.allow); return }
        }
        // 새 창(target=_blank)이나 바깥 주소는 기본 브라우저로
        openOutside(url)
        decisionHandler(.cancel)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        openOutside(navigationAction.request.url)   // window.open도 기본 브라우저로(앱 안에는 새 창이 없어요)
        return nil
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        status.hide()
        if let n = note {
            note = nil
            let a = NSAlert()
            a.messageText = "예전 버전이 켜져 있어요"
            a.informativeText = n
            a.addButton(withTitle: "확인")
            a.beginSheetModal(for: window, completionHandler: nil)
        }
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        loadFailed(error)
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        loadFailed(error)
    }

    func loadFailed(_ error: Error) {
        let e = error as NSError
        // 링크를 브라우저로 넘기며 취소한 경우는 오류가 아니에요.
        if e.domain == NSURLErrorDomain && e.code == NSURLErrorCancelled { return }
        if e.domain == "WebKitErrorDomain" && (e.code == 102 || e.code == 204) { return }
        if let u = e.userInfo[NSURLErrorFailingURLErrorKey] as? URL, !isLocalPage(u) { return }
        let running = server?.isRunning ?? false
        status.showError("사무실 화면을 열지 못했어요",
                         running ? "잠시 뒤 다시 시도해 주세요." : "사무실 서버가 꺼져 있어요. 다시 켜려면 아래 단추를 눌러요.",
                         log: e.localizedDescription, folder: false)
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        webView.reload()
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let a = NSAlert()
        a.messageText = message
        a.addButton(withTitle: "확인")
        sheet(a) { _ in completionHandler() }
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let a = NSAlert()
        a.messageText = message
        a.addButton(withTitle: "확인")
        a.addButton(withTitle: "취소")
        sheet(a) { r in completionHandler(r == .alertFirstButtonReturn) }
    }

    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String, defaultText: String?,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (String?) -> Void) {
        let a = NSAlert()
        a.messageText = prompt
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 300, height: 24))
        field.stringValue = defaultText ?? ""
        a.accessoryView = field
        a.addButton(withTitle: "확인")
        a.addButton(withTitle: "취소")
        a.window.initialFirstResponder = field
        sheet(a) { r in completionHandler(r == .alertFirstButtonReturn ? field.stringValue : nil) }
    }

    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = parameters.allowsDirectories
        panel.canChooseFiles = true
        panel.beginSheetModal(for: window) { r in completionHandler(r == .OK ? panel.urls : nil) }
    }

    func sheet(_ a: NSAlert, _ done: @escaping (NSApplication.ModalResponse) -> Void) {
        if !window.isVisible { showWindow(nil) }
        if window.attachedSheet != nil {
            done(a.runModal())
        } else {
            a.beginSheetModal(for: window, completionHandler: done)
        }
    }
}

// MARK: - 아이콘 (1024 기준으로 그려요: 주황 타일 위에 층마다 불 켜진 사무실 건물)

func color(_ hex: UInt32) -> NSColor {
    return NSColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
                   blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
}

func drawIcon(_ px: CGFloat) {
    let k = px / 1024
    let tf = NSAffineTransform()
    tf.scale(by: k)
    tf.concat()
    func box(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat, _ r: CGFloat, _ c: UInt32) {
        color(c).setFill()
        NSBezierPath(roundedRect: NSRect(x: x, y: y, width: w, height: h), xRadius: r, yRadius: r).fill()
    }

    // 타일(그림자 + 위에서 아래로 짙어지는 주황)
    let tile = NSBezierPath(roundedRect: NSRect(x: 100, y: 100, width: 824, height: 824), xRadius: 185, yRadius: 185)
    NSGraphicsContext.saveGraphicsState()
    let shadow = NSShadow()
    shadow.shadowColor = NSColor(white: 0, alpha: 0.3)
    shadow.shadowOffset = NSSize(width: 0, height: -10 * k)
    shadow.shadowBlurRadius = 22 * k
    shadow.set()
    color(0xC9603F).setFill()
    tile.fill()
    NSGraphicsContext.restoreGraphicsState()
    NSGradient(starting: color(0xC2583A), ending: color(0xE8906C))?.draw(in: tile, angle: 90)

    // 건물: 양옆 낮은 동 + 가운데 높은 동, 꼭대기 안테나
    box(222, 196, 170, 344, 22, 0xF3DCCB)
    box(632, 196, 170, 264, 22, 0xF3DCCB)
    box(508, 780, 10, 76, 4, 0xFFF4EA)
    box(495, 846, 36, 36, 18, 0xFFC24B)
    box(352, 196, 320, 600, 26, 0xFFF6EE)
    color(0xC2583A).setFill()
    NSBezierPath(rect: NSRect(x: 200, y: 180, width: 624, height: 16)).fill()   // 땅

    // 창문: 불 켜진 층 = 일하는 팀
    let lit: [[Bool]] = [[true, false, true], [true, true, false], [false, true, true], [true, false, true], [true, true, true]]
    for (row, cols) in lit.enumerated() {
        for (col, on) in cols.enumerated() {
            box(390 + CGFloat(col) * 94, 690 - CGFloat(row) * 84, 56, 50, 8, on ? 0xFFC24B : 0xEBD3C2)
        }
    }
    for (i, on) in [true, false, true].enumerated() { box(262, 452 - CGFloat(i) * 84, 50, 46, 8, on ? 0xFFC24B : 0xE5C9B6) }
    for (i, on) in [false, true].enumerated() { box(712, 372 - CGFloat(i) * 84, 50, 46, 8, on ? 0xFFC24B : 0xE5C9B6) }
    box(472, 196, 80, 96, 14, 0xC2583A)   // 문
}

func makeIconset(_ dir: String) -> Bool {
    let names: [(Int, String)] = [(16, "16x16"), (32, "16x16@2x"), (32, "32x32"), (64, "32x32@2x"), (128, "128x128"),
                                  (256, "128x128@2x"), (256, "256x256"), (512, "256x256@2x"), (512, "512x512"),
                                  (1024, "512x512@2x")]
    do {
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        for (px, name) in names {
            guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px, bitsPerSample: 8,
                                             samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                             colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0),
                  let ctx = NSGraphicsContext(bitmapImageRep: rep) else { return false }
            NSGraphicsContext.saveGraphicsState()
            NSGraphicsContext.current = ctx
            drawIcon(CGFloat(px))
            ctx.flushGraphics()
            NSGraphicsContext.restoreGraphicsState()
            guard let png = rep.representation(using: .png, properties: [:]) else { return false }
            try png.write(to: URL(fileURLWithPath: dir + "/icon_\(name).png"))
        }
        return true
    } catch {
        FileHandle.standardError.write("아이콘을 그리지 못했어요: \(error.localizedDescription)\n".data(using: .utf8)!)
        return false
    }
}

// MARK: - 시작

let args = CommandLine.arguments
if args.count >= 3 && args[1] == "--make-iconset" {
    exit(makeIconset(args[2]) ? 0 : 1)
}
let delegate = AppDelegate()
NSApplication.shared.delegate = delegate
NSApplication.shared.setActivationPolicy(.regular)
NSApplication.shared.run()
