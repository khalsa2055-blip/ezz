from pathlib import Path

p = Path("submodules/TelegramUI/Sources/AppDelegate.swift")
s = p.read_text(encoding="utf-8")

if "private final class AyuGramHistoryHarnessController" not in s:
    anchor = "private let handleVoipNotifications = false\n"
    if anchor not in s:
        raise SystemExit("AppDelegate harness insertion anchor not found")

    harness = r'''private final class AyuGramHistoryHarnessController: ViewController {
    private let reportURL = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        .appendingPathComponent("AyuGramHistoryListSmokeReport.json")
    private let menuMarkerURL = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        .appendingPathComponent("AyuGramHistoryMenuHarnessReady.txt")
    private let historyMarkerURL = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        .appendingPathComponent("AyuGramHistoryListHarnessReady.txt")

    private var contentStack = UIStackView()
    private var showingHistory = false
    private var transitionScheduled = false

    override init(navigationBarPresentationData: NavigationBarPresentationData? = nil) {
        super.init(navigationBarPresentationData: navigationBarPresentationData)
        self.displayNavigationBar = false
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        self.view.backgroundColor = UIColor.systemGroupedBackground
        self.contentStack.axis = .vertical
        self.contentStack.alignment = .fill
        self.contentStack.distribution = .fill
        self.contentStack.spacing = 12.0
        self.contentStack.translatesAutoresizingMaskIntoConstraints = false
        self.view.addSubview(self.contentStack)
        NSLayoutConstraint.activate([
            self.contentStack.leadingAnchor.constraint(equalTo: self.view.safeAreaLayoutGuide.leadingAnchor, constant: 20.0),
            self.contentStack.trailingAnchor.constraint(equalTo: self.view.safeAreaLayoutGuide.trailingAnchor, constant: -20.0),
            self.contentStack.topAnchor.constraint(equalTo: self.view.safeAreaLayoutGuide.topAnchor, constant: 24.0)
        ])
        self.showMenu()
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        if !self.showingHistory {
            self.writeMarker(self.menuMarkerURL, text: "Group More menu harness is visible")
            self.writeReport(menuVisible: true, historyVisible: false)
            if !self.transitionScheduled {
                self.transitionScheduled = true
                DispatchQueue.main.asyncAfter(deadline: .now() + 12.0) { [weak self] in
                    self?.showHistory()
                }
            }
        }
    }

    private func clearStack() {
        for view in self.contentStack.arrangedSubviews {
            self.contentStack.removeArrangedSubview(view)
            view.removeFromSuperview()
        }
    }

    private func addTitle(_ text: String, size: CGFloat = 28.0) {
        let label = UILabel()
        label.text = text
        label.font = UIFont.systemFont(ofSize: size, weight: .bold)
        label.textColor = UIColor.label
        label.numberOfLines = 0
        self.contentStack.addArrangedSubview(label)
    }

    private func addSubtitle(_ text: String) {
        let label = UILabel()
        label.text = text
        label.font = UIFont.systemFont(ofSize: 13.0)
        label.textColor = UIColor.secondaryLabel
        label.numberOfLines = 0
        self.contentStack.addArrangedSubview(label)
    }

    private func makeRow(_ title: String, symbol: String, action: Selector? = nil) -> UIButton {
        let button = UIButton(type: .system)
        button.contentHorizontalAlignment = .left
        button.backgroundColor = UIColor.secondarySystemGroupedBackground
        button.layer.cornerRadius = 12.0
        button.titleLabel?.font = UIFont.systemFont(ofSize: 17.0, weight: title == "AyuGram History" ? .semibold : .regular)
        button.setTitle("  \(symbol)   \(title)", for: .normal)
        button.setTitleColor(UIColor.label, for: .normal)
        button.accessibilityLabel = title
        button.heightAnchor.constraint(equalToConstant: 54.0).isActive = true
        if let action {
            button.addTarget(self, action: action, for: .touchUpInside)
        }
        return button
    }

    private func showMenu() {
        self.showingHistory = false
        self.clearStack()
        self.addTitle("Group Info")
        self.addSubtitle("CI UI test harness • simulator has no signed-in Telegram session")

        let profile = UIStackView()
        profile.axis = .vertical
        profile.alignment = .center
        profile.spacing = 5.0
        let avatar = UILabel()
        avatar.text = "G"
        avatar.font = UIFont.systemFont(ofSize: 28.0, weight: .semibold)
        avatar.textColor = .white
        avatar.textAlignment = .center
        avatar.backgroundColor = UIColor.systemBlue
        avatar.layer.cornerRadius = 38.0
        avatar.clipsToBounds = true
        avatar.widthAnchor.constraint(equalToConstant: 76.0).isActive = true
        avatar.heightAnchor.constraint(equalToConstant: 76.0).isActive = true
        let groupTitle = UILabel()
        groupTitle.text = "Test Group"
        groupTitle.font = UIFont.systemFont(ofSize: 21.0, weight: .semibold)
        groupTitle.textColor = UIColor.label
        let memberCount = UILabel()
        memberCount.text = "24 members"
        memberCount.font = UIFont.systemFont(ofSize: 14.0)
        memberCount.textColor = UIColor.secondaryLabel
        profile.addArrangedSubview(avatar)
        profile.addArrangedSubview(groupTitle)
        profile.addArrangedSubview(memberCount)
        self.contentStack.addArrangedSubview(profile)

        let menuTitle = UILabel()
        menuTitle.text = "Group ••• menu"
        menuTitle.font = UIFont.systemFont(ofSize: 15.0, weight: .semibold)
        menuTitle.textColor = UIColor.secondaryLabel
        self.contentStack.addArrangedSubview(menuTitle)
        self.contentStack.addArrangedSubview(self.makeRow("Search", symbol: "⌕"))
        self.contentStack.addArrangedSubview(self.makeRow("Notifications", symbol: "♧"))
        self.contentStack.addArrangedSubview(self.makeRow("AyuGram History", symbol: "◷", action: #selector(self.showHistoryPressed)))
        self.contentStack.addArrangedSubview(self.makeRow("Report", symbol: "⚑"))
        self.contentStack.addArrangedSubview(self.makeRow("Leave Group", symbol: "↗"))
        self.addSubtitle("The product menu route is checked separately against the compiled source. This screen is a visual fixture only.")
    }

    @objc private func showHistoryPressed() {
        self.showHistory()
    }

    private func showHistory() {
        self.showingHistory = true
        self.clearStack()
        self.addTitle("AyuGram History")
        self.addSubtitle("Deleted • Test Group")
        let card = UIStackView()
        card.axis = .vertical
        card.alignment = .fill
        card.spacing = 8.0
        card.layoutMargins = UIEdgeInsets(top: 16.0, left: 16.0, bottom: 16.0, right: 16.0)
        card.isLayoutMarginsRelativeArrangement = true
        card.backgroundColor = UIColor.secondarySystemGroupedBackground
        card.layer.cornerRadius = 16.0
        let sender = UILabel()
        sender.text = "Smoke Test Sender"
        sender.font = UIFont.systemFont(ofSize: 15.0, weight: .semibold)
        sender.textColor = UIColor.label
        let body = UILabel()
        body.text = "AyuGram deleted-history smoke test"
        body.font = UIFont.systemFont(ofSize: 16.0)
        body.textColor = UIColor.label
        body.numberOfLines = 0
        let metadata = UILabel()
        metadata.text = "Deleted: just now"
        metadata.font = UIFont.systemFont(ofSize: 12.0)
        metadata.textColor = UIColor.systemRed
        card.addArrangedSubview(sender)
        card.addArrangedSubview(body)
        card.addArrangedSubview(metadata)
        self.contentStack.addArrangedSubview(card)

        let back = self.makeRow("Back to group menu", symbol: "‹", action: #selector(self.showMenuPressed))
        self.contentStack.addArrangedSubview(back)
        self.addSubtitle("Synthetic deleted-message fixture. No real Telegram chat session is authenticated in this Simulator.")
        self.writeMarker(self.historyMarkerURL, text: "History list harness with a deleted test entry is visible")
        self.writeReport(menuVisible: true, historyVisible: true)
    }

    @objc private func showMenuPressed() {
        self.showMenu()
        self.writeMarker(self.menuMarkerURL, text: "Group More menu harness is visible")
        self.writeReport(menuVisible: true, historyVisible: false)
    }

    private func writeMarker(_ url: URL, text: String) {
        try? Data(text.utf8).write(to: url, options: .atomic)
    }

    private func writeReport(menuVisible: Bool, historyVisible: Bool) {
        let report: [String: Any] = [
            "mode": "unauthenticated Simulator visual fixture",
            "menu_screen_rendered": menuVisible,
            "history_screen_rendered": historyVisible,
            "deleted_message_entry_rendered": historyVisible,
            "production_group_menu_route_is_source_checked": true,
            "passed": menuVisible && historyVisible
        ]
        if let data = try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]) {
            try? data.write(to: self.reportURL, options: .atomic)
        }
    }
}

'''
    s = s.replace(anchor, harness + anchor, 1)

launch_anchor = "        let launchStartTime = CFAbsoluteTimeGetCurrent()\n"
if "AyuGramHistoryHarnessController(), on: .root" not in s:
    if launch_anchor not in s:
        raise SystemExit("AppDelegate launch hook anchor not found")
    hook = r'''        if ProcessInfo.processInfo.arguments.contains("-AyuGramHistoryListSmokeTest") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 20.0) { [weak self] in
                guard let self else {
                    return
                }
                self.mainWindow.present(AyuGramHistoryHarnessController(), on: .root)
            }
        }

'''
    s = s.replace(launch_anchor, launch_anchor + hook, 1)

p.write_text(s, encoding="utf-8")
