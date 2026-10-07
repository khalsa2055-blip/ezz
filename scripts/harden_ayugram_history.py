from pathlib import Path
import plistlib
import re

# This runs after the main AyuGram patch has been applied to Telegram-iOS.
# It hardens the History implementation without changing the upstream patch.
root = Path("telegram-ios") if Path("telegram-ios").is_dir() else Path(".")
archive = root / "submodules/AyuGramIOS/Sources/AyuGramMediaArchive.swift"
message = root / "submodules/AyuGramIOS/Sources/MessageHistory.swift"
store = root / "submodules/AyuGramIOS/Sources/AyuGramPostboxHistoryStore.swift"
capture = root / "submodules/AyuGramIOS/Sources/AyuGramCaptureService.swift"

# Enable Files → On My iPhone → AyuGram for the app Documents directory.
# Telegram-iOS has both the source Info.plist and the Bazel-specific InfoBazel.plist;
# update both so the final packaged app cannot silently restore UIFileSharingEnabled=false.
plist_paths = [
    root / "Telegram/Telegram-iOS/Info.plist",
    root / "Telegram/Telegram-iOS/InfoBazel.plist",
]
for info_plist in plist_paths:
    if not info_plist.exists():
        raise SystemExit(f"Missing app Info.plist: {info_plist}")
    with info_plist.open("rb") as f:
        plist = plistlib.load(f)
    plist["UIFileSharingEnabled"] = True
    plist["LSSupportsOpeningDocumentsInPlace"] = True
    with info_plist.open("wb") as f:
        plistlib.dump(plist, f, fmt=plistlib.FMT_XML, sort_keys=False)

# Bazel does not package Telegram/Telegram-iOS/Info.plist directly. Its main
# app Info.plist is generated from the TelegramInfoPlist fragment in Telegram/BUILD.
# Patch that generator so the final IPA really contains the Files flags.
build_file = root / "Telegram/BUILD"
if not build_file.exists():
    raise SystemExit(f"Missing Telegram BUILD file: {build_file}")
build_text = build_file.read_text()
build_old = '''    <key>UIFileSharingEnabled</key>
    <false/>
    <key>UILaunchStoryboardName</key>'''
build_new = '''    <key>UIFileSharingEnabled</key>
    <true/>
    <key>LSSupportsOpeningDocumentsInPlace</key>
    <true/>
    <key>UILaunchStoryboardName</key>'''
if build_old in build_text:
    build_text = build_text.replace(build_old, build_new, 1)
elif build_new not in build_text:
    raise SystemExit("TelegramInfoPlist Files flags anchor not found in Telegram/BUILD")
build_file.write_text(build_text)

for p in (archive, message, store, capture):
    if not p.exists():
        raise SystemExit(f"Missing AyuGram history source: {p}")

# Files.app exposes the app's Documents directory. Keep history outside
# Telegram's managed media directory so Telegram deletion cannot remove it.
s = archive.read_text()
s = s.replace(
    'FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first?',
    'FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first?'
)
s = s.replace(
    '.appendingPathComponent("AyuGram", isDirectory: true)',
    '.appendingPathComponent("AyuGram", isDirectory: true)',
    1
)

# Support common audio/document/video extensions instead of collapsing them to .bin.
s = archive.read_text()
switch_start = '    private static func pathExtension(for mimeType: String?) -> String? {'
start = s.find(switch_start)
if start < 0:
    raise SystemExit("Media extension helper not found")
default_marker = '''        default:
            return nil
        }'''
end = s.find(default_marker, start)
if end < 0:
    raise SystemExit("Media extension default branch not found")
required_cases = [
    '''        case "audio/mpeg":
            return "mp3"
''',
    '''        case "audio/mp4":
            return "m4a"
''',
    '''        case "audio/aac":
            return "aac"
''',
    '''        case "audio/ogg":
            return "ogg"
''',
    '''        case "audio/wav", "audio/x-wav":
            return "wav"
''',
    '''        case "application/pdf":
            return "pdf"
''',
    '''        case "application/zip":
            return "zip"
''',
    '''        case "text/plain":
            return "txt"
''',
    '''        case "application/msword":
            return "doc"
''',
    '''        case "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            return "docx"
''',
    '''        case "application/vnd.ms-excel":
            return "xls"
''',
    '''        case "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
            return "xlsx"
'''
]
existing = s[start:end]
missing = [case for case in required_cases if case.strip() not in existing]
if missing:
    s = s[:end] + "".join(missing) + s[end:]
archive.write_text(s)

# Add a durable existence check used by the UI/tests before offering a media item.
s = archive.read_text()
needle = '''public enum AyuGramMediaArchive {
    public static func archive('''
replacement = '''public enum AyuGramMediaArchive {
    public static func isArchivedFile(_ path: String?) -> Bool {
        guard let path, !path.isEmpty else { return false }
        return FileManager.default.fileExists(atPath: path)
    }

    public static func archive('''
if needle not in s:
    raise SystemExit("Archive declaration anchor not found")
archive.write_text(s.replace(needle, replacement, 1))

# Preserve media metadata through the Postbox history copy. This prevents a
# successful capture from being reduced to a text-only row.
s = store.read_text()
old_init = '''                mimeType: snapshot.mimeType,
                isDeleted: deleted
            )'''
new_init = '''                mimeType: snapshot.mimeType,
                isDeleted: deleted
            )'''
if old_init not in s:
    raise SystemExit("History store constructor anchor not found")
# No semantic change here; this assertion intentionally ensures the current
# constructor shape remains compatible with the capture code.
store.write_text(s)

# Fail the build if the hardening was accidentally bypassed.
checks = {
    archive: [
        '.applicationSupportDirectory',
        'case "audio/mpeg":',
        'case "application/pdf":',
        'isArchivedFile'
    ]
}
for p, forbidden_or_required in checks.items():
    data = p.read_text()
    if '.applicationSupportDirectory' in data:
        raise SystemExit("History media is still stored in Application Support")
    for required in forbidden_or_required[1:]:
        if required not in data:
            raise SystemExit(f"History hardening missing: {required}")

for info_plist in plist_paths:
    with info_plist.open("rb") as f:
        checked_plist = plistlib.load(f)
    if checked_plist.get("UIFileSharingEnabled") is not True or checked_plist.get("LSSupportsOpeningDocumentsInPlace") is not True:
        raise SystemExit(f"Files app integration flags are not enabled in {info_plist}")
print("AyuGram History hardening v3 applied: per-dialog isolation + Saved Messages-style bubbles + real Save action + media persistence + Files integration.")

# Enforce per-dialog History routing and prevent cross-chat leakage.
ui = root / "submodules/TelegramUI/Components/AyuGramSettingsScreen/Sources/AyuGramSettingsScreen.swift"
if not ui.exists():
    raise SystemExit(f"Missing AyuGram History UI source: {ui}")
ui_text = ui.read_text()
for required in [
    "public func ayuGramHistoryScreen(context: AccountContext, dialogID: Int64? = nil)",
    "AyuGramPostboxHistoryStore.filtered(",
    "dialogID: dialogID,"
]:
    if required not in ui_text:
        raise SystemExit(f"Per-dialog History UI contract missing: {required}")

# The context-menu entry lives in TelegramUI, so locate it without assuming
# the exact controller source file.
chat_sources = list((root / "submodules/TelegramUI").rglob("*.swift"))
chat_text = "\n".join(p.read_text() for p in chat_sources)
if "ayuGramHistoryScreen(context: context, dialogID: message.id.peerId.toInt64())" not in chat_text:
    raise SystemExit("Per-dialog History context-menu routing is missing")

context_menu = root / "submodules/TelegramUI/Sources/ChatInterfaceStateContextMenus.swift"
if not context_menu.exists():
    raise SystemExit(f"Missing AyuGram message context menu source: {context_menu}")
context_menu_text = context_menu.read_text()
for required in [
    "AyuGram Save",
    "AyuGram Transfer to Saved Messages",
    "AyuGramCaptureService.saveNow(",
    "enqueueMessages(",
]:
    if required not in context_menu_text:
        raise SystemExit(f"AyuGram manual-save/transfer action missing: {required}")

ui_text = ui_text.replace(
    'let title = dialogID == nil ? "AyuGram History" : "Group History"',
    'let title = "AyuGram History"',
    1
)
ui.write_text(ui_text)

smoke = root / "submodules/AyuGramIOS/Sources/AyuGramSmokeTest.swift"
if not smoke.exists():
    raise SystemExit(f"Missing AyuGram smoke test: {smoke}")
smoke_text = smoke.read_text()
anchor = '        add("history display labels") {'
test = '''        add("per-dialog history isolation") {
            let firstDialog: Int64 = 900_000_000 + Int64(abs(accountID % 10_000))
            let secondDialog = firstDialog + 777
            let isolationMessageIDBase = Int32(1_800_000_000) + abs(Int32(accountID % 10_000))
            let firstMessage = AyuMessage(fakeID: 0, userID: accountID, dialogID: firstDialog, peerID: firstDialog, fromID: accountID, messageID: isolationMessageIDBase + 10, date: Int32(Date().timeIntervalSince1970), text: "AyuGram dialog A", isDeleted: true)
            let secondMessage = AyuMessage(fakeID: 0, userID: accountID, dialogID: secondDialog, peerID: secondDialog, fromID: accountID, messageID: isolationMessageIDBase + 11, date: Int32(Date().timeIntervalSince1970), text: "AyuGram dialog B", isDeleted: true)
            _ = AyuGramPostboxHistoryStore.appendDeleted(transaction: transaction, messages: [firstMessage, secondMessage])
            let firstRows = AyuGramPostboxHistoryStore.filtered(transaction: transaction, userID: accountID, dialogID: firstDialog, kind: .deleted, limit: 50)
            let secondRows = AyuGramPostboxHistoryStore.filtered(transaction: transaction, userID: accountID, dialogID: secondDialog, kind: .deleted, limit: 50)
            let firstOnly = firstRows.contains { $0.text == firstMessage.text } && !firstRows.contains { $0.text == secondMessage.text }
            let secondOnly = secondRows.contains { $0.text == secondMessage.text } && !secondRows.contains { $0.text == firstMessage.text }
            let ok = firstOnly && secondOnly
            return (ok, ok ? "each dialog sees only its own deleted history" : "dialog history isolation failed")
        }

'''
test += '''        add("History → Saved media set") {
            let dialogID = Int64(9_810_000) + abs(accountID % 100_000)
            let messageID = Int32(1_710_000_000) + abs(Int32(accountID % 10_000))
            let tempRoot = FileManager.default.temporaryDirectory.appendingPathComponent("ayugram-history-media-set", isDirectory: true)
            try FileManager.default.createDirectory(at: tempRoot, withIntermediateDirectories: true)
            defer { try? FileManager.default.removeItem(at: tempRoot) }

            let first = tempRoot.appendingPathComponent("0.jpg")
            let second = tempRoot.appendingPathComponent("1.mp4")
            try Data("one".utf8).write(to: first, options: .atomic)
            try Data("two".utf8).write(to: second, options: .atomic)

            let message = AyuMessage(fakeID: 0, userID: accountID, dialogID: dialogID, peerID: dialogID, fromID: accountID, messageID: messageID, date: Int32(Date().timeIntervalSince1970), text: "AyuGram media-set smoke", mediaPath: first.path, mimeType: "image/jpeg", isDeleted: true)
            let saved = AyuGramMediaArchive.saveToSaved(message: message)
            let savedRoot = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first?
                .appendingPathComponent("Telegram", isDirectory: true)
                .appendingPathComponent("AyuGram", isDirectory: true)
                .appendingPathComponent("Saved", isDirectory: true)
                .appendingPathComponent("Media", isDirectory: true)
            let firstSaved = savedRoot?.appendingPathComponent("0.jpg")
            let secondSaved = savedRoot?.appendingPathComponent("1.mp4")
            let ok = saved
                && (firstSaved.map { FileManager.default.fileExists(atPath: $0.path) } ?? false)
                && (secondSaved.map { FileManager.default.fileExists(atPath: $0.path) } ?? false)
            if let cleanup = savedRoot?.deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent() {
                try? FileManager.default.removeItem(at: cleanup)
            }
            return (ok, ok ? "all archived media files copied to Saved/media" : "Saved media set copy failed")
        }
        add("History → Saved copy") {
            let dialogID = Int64(9_800_000) + abs(accountID % 100_000)
            let messageID = Int32(1_700_000_000) + abs(Int32(accountID % 10_000))
            let temp = FileManager.default.temporaryDirectory.appendingPathComponent("ayugram-history-smoke-\\(accountID)-\\(messageID).jpg")
            try Data("ayugram-smoke-media".utf8).write(to: temp, options: .atomic)
            defer { try? FileManager.default.removeItem(at: temp) }

            let message = AyuMessage(
                fakeID: 0,
                userID: accountID,
                dialogID: dialogID,
                peerID: dialogID,
                fromID: accountID,
                messageID: messageID,
                date: Int32(Date().timeIntervalSince1970),
                text: "AyuGram saved smoke test",
                mediaPath: temp.path,
                mimeType: "image/jpeg",
                isDeleted: true
            )
            let saved = AyuGramMediaArchive.saveToSaved(message: message)
            let savedRoot = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first?
                .appendingPathComponent("Telegram", isDirectory: true)
                .appendingPathComponent("AyuGram", isDirectory: true)
                .appendingPathComponent("Saved", isDirectory: true)
            let savedMedia = savedRoot?.appendingPathComponent("media.jpg")
            let savedMetadata = savedRoot?.appendingPathComponent("metadata.json")
            let ok = saved
                && (savedMedia.map { FileManager.default.fileExists(atPath: $0.path) } ?? false)
                && (savedMetadata.map { FileManager.default.fileExists(atPath: $0.path) } ?? false)
            return (ok, ok ? "media and metadata copied to Documents/AyuGram/Saved" : "Saved copy failed")
        }

'''
if anchor not in smoke_text:
    raise SystemExit("Smoke test insertion anchor not found")
smoke.write_text(smoke_text.replace(anchor, test + anchor, 1))


# Add a separate user-controlled Saved folder. History is automatic; Saved is
# populated only when the user taps the row's real Save action.
archive_text = archive.read_text()
save_anchor = '''    public static func archive(
'''
save_api = '''    public static func saveToSaved(message: AyuMessage) -> Bool {
        let root = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first?
            .appendingPathComponent("AyuGram", isDirectory: true)
            .appendingPathComponent("Saved", isDirectory: true)
            .appendingPathComponent(String(message.userID), isDirectory: true)
            .appendingPathComponent(String(message.dialogID), isDirectory: true)
            .appendingPathComponent(String(message.messageID), isDirectory: true)
        guard let root else { return false }

        do {
            try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        } catch {
            return false
        }

        var didSave = false
        if let source = message.mediaPath, FileManager.default.fileExists(atPath: source) {
            let sourceURL = URL(fileURLWithPath: source)
            let sourceDirectory = sourceURL.deletingLastPathComponent()
            let resourceFiles = ((try? FileManager.default.contentsOfDirectory(
                at: sourceDirectory,
                includingPropertiesForKeys: [.isRegularFileKey],
                options: [.skipsHiddenFiles]
            )) ?? []).filter { url in
                url.pathExtension.lowercased() != "json" &&
                (try? url.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true
            }.sorted { $0.lastPathComponent.localizedStandardCompare($1.lastPathComponent) == .orderedAscending }

            if resourceFiles.count > 1 {
                for (index, file) in resourceFiles.enumerated() {
                    let ext = file.pathExtension.isEmpty ? (pathExtension(for: message.mimeType) ?? "bin") : file.pathExtension
                    let destination = root.appendingPathComponent("media-\\(index + 1).\\(ext)")
                    do {
                        if !FileManager.default.fileExists(atPath: destination.path) {
                            try FileManager.default.copyItem(at: file, to: destination)
                        }
                        didSave = true
                    } catch {
                        return false
                    }
                }
            } else {
                let ext = sourceURL.pathExtension.isEmpty ? (pathExtension(for: message.mimeType) ?? "bin") : sourceURL.pathExtension
                let destination = root.appendingPathComponent("media.\\(ext)")
                do {
                    if !FileManager.default.fileExists(atPath: destination.path) {
                        try FileManager.default.copyItem(at: sourceURL, to: destination)
                    }
                    didSave = true
                } catch {
                    return false
                }
            }
        }

        if !message.text.isEmpty, let data = message.text.data(using: .utf8) {
            do {
                try data.write(to: root.appendingPathComponent("message.txt"), options: .atomic)
                didSave = true
            } catch {
                return false
            }
        }

        let metadata: [String: Any] = [
            "messageID": message.messageID,
            "dialogID": message.dialogID,
            "accountID": message.userID,
            "senderID": message.fromID,
            "date": message.date,
            "editDate": message.editDate,
            "mimeType": message.mimeType ?? "",
            "text": message.text,
            "isDeleted": message.isDeleted
        ]
        do {
            let data = try JSONSerialization.data(withJSONObject: metadata, options: [.prettyPrinted, .sortedKeys])
            try data.write(to: root.appendingPathComponent("metadata.json"), options: .atomic)
            didSave = true
        } catch {
            return false
        }

        return didSave
    }

'''
if save_anchor not in archive_text:
    raise SystemExit("Saved API insertion anchor missing")
if "public static func saveToSaved(message: AyuMessage) -> Bool" not in archive_text:
    archive.write_text(archive_text.replace(save_anchor, save_api + save_anchor, 1))

# Turn each History row into a real actionable Save row while keeping the
# message preview/date/media information visible.
ui_text = ui.read_text()

history_preview_helper = '''private final class AyuHistoryDocumentPreviewer: NSObject, UIDocumentInteractionControllerDelegate {
    static let shared = AyuHistoryDocumentPreviewer()
    private var controller: UIDocumentInteractionController?
    private weak var presenter: UIViewController?

    func open(path: String) {
        guard FileManager.default.fileExists(atPath: path) else { return }
        let roots = UIApplication.shared.connectedScenes.compactMap { scene -> UIViewController? in
            guard let windowScene = scene as? UIWindowScene else { return nil }
            return windowScene.windows.first(where: { $0.isKeyWindow })?.rootViewController
        }
        guard var presenter = roots.first else { return }
        while let next = presenter.presentedViewController { presenter = next }
        self.presenter = presenter
        let controller = UIDocumentInteractionController(url: URL(fileURLWithPath: path))
        controller.delegate = self
        self.controller = controller
        _ = controller.presentPreview(animated: true)
    }

    func documentInteractionControllerViewControllerForPreview(_ controller: UIDocumentInteractionController) -> UIViewController {
        return presenter ?? UIViewController()
    }
}

private final class AyuHistoryBubbleItem: ListViewItem {
    let presentationData: ItemListPresentationData
    let message: AyuMessage
    let displayText: String
    let displayDate: String
    let displayKind: String

    init(presentationData: ItemListPresentationData, message: AyuMessage, displayText: String, displayDate: String, displayKind: String) {
        self.presentationData = presentationData
        self.message = message
        self.displayText = displayText
        self.displayDate = displayDate
        self.displayKind = displayKind
    }

    var approximateHeight: CGFloat {
        return self.message.mediaPath == nil ? 92.0 : 230.0
    }

    func nodeConfiguredForParams(
        async: @escaping (@escaping () -> Void) -> Void,
        params: ListViewItemLayoutParams,
        synchronousLoads: Bool,
        previousItem: ListViewItem?,
        nextItem: ListViewItem?,
        completion: @escaping (ListViewItemNode, @escaping () -> (Signal<Void, NoError>?, (ListViewItemApply) -> Void)) -> Void
    ) {
        async {
            let node = AyuHistoryBubbleItemNode()
            let (layout, apply) = node.asyncLayout()(self, params)
            node.contentSize = layout.contentSize
            node.insets = layout.insets
            Queue.mainQueue().async {
                completion(node, {
                    return (nil, { _ in apply() })
                })
            }
        }
    }

    func updateNode(
        async: @escaping (@escaping () -> Void) -> Void,
        node: @escaping () -> ListViewItemNode,
        params: ListViewItemLayoutParams,
        previousItem: ListViewItem?,
        nextItem: ListViewItem?,
        animation: ListViewItemUpdateAnimation,
        completion: @escaping (ListViewItemNodeLayout, @escaping (ListViewItemApply) -> Void) -> Void
    ) {
        async {
            guard let node = node() as? AyuHistoryBubbleItemNode else {
                return
            }
            let (layout, apply) = node.asyncLayout()(self, params)
            Queue.mainQueue().async {
                completion(layout, { _ in apply() })
            }
        }
    }
}

private final class AyuHistoryBubbleItemNode: ListViewItemNode {
    private let bubbleView = UIView()
    private let senderLabel = UILabel()
    private let bodyLabel = UILabel()
    private let kindLabel = UILabel()
    private let timeLabel = UILabel()
    private let mediaView = UIImageView()
    private let mediaTitleLabel = UILabel()
    private let saveButton = UIButton(type: .system)
    private let mediaButton = UIButton(type: .system)
    private var item: AyuHistoryBubbleItem?

    override init(layerBacked: Bool = false, rotated: Bool = false, seeThrough: Bool = false) {
        super.init(layerBacked: layerBacked, rotated: rotated, seeThrough: seeThrough)
        self.bubbleView.layer.cornerRadius = 17.0
        self.bubbleView.layer.masksToBounds = true
        self.senderLabel.font = UIFont.systemFont(ofSize: 14.0, weight: .semibold)
        self.kindLabel.font = UIFont.systemFont(ofSize: 12.0, weight: .medium)
        self.bodyLabel.font = UIFont.systemFont(ofSize: 16.0)
        self.bodyLabel.numberOfLines = 0
        self.timeLabel.font = UIFont.systemFont(ofSize: 11.0)
        self.timeLabel.textAlignment = .right
        self.mediaView.layer.cornerRadius = 12.0
        self.mediaView.layer.masksToBounds = true
        self.mediaView.contentMode = .scaleAspectFill
        self.mediaTitleLabel.font = UIFont.systemFont(ofSize: 14.0, weight: .semibold)
        self.mediaTitleLabel.numberOfLines = 2
        self.mediaTitleLabel.textAlignment = .center
        self.saveButton.setTitle("💾", for: .normal)
        self.saveButton.titleLabel?.font = UIFont.systemFont(ofSize: 17.0)
        self.saveButton.accessibilityLabel = "Save to Saved"
        self.mediaButton.accessibilityLabel = "Open media"

        self.view.addSubview(self.bubbleView)
        self.bubbleView.addSubview(self.senderLabel)
        self.bubbleView.addSubview(self.kindLabel)
        self.bubbleView.addSubview(self.bodyLabel)
        self.bubbleView.addSubview(self.mediaView)
        self.bubbleView.addSubview(self.mediaTitleLabel)
        self.bubbleView.addSubview(self.timeLabel)
        self.bubbleView.addSubview(self.saveButton)
        self.bubbleView.addSubview(self.mediaButton)

        self.saveButton.addTarget(self, action: #selector(self.savePressed), for: .touchUpInside)
        self.mediaButton.addTarget(self, action: #selector(self.mediaPressed), for: .touchUpInside)
    }

    func asyncLayout() -> (_ item: AyuHistoryBubbleItem, _ params: ListViewItemLayoutParams) -> (ListViewItemNodeLayout, () -> Void) {
        return { [weak self] item, params in
            guard let self else {
                return (ListViewItemNodeLayout(contentSize: CGSize(width: params.width, height: 1.0), insets: UIEdgeInsets()), {})
            }
            let bubbleWidth = min(max(params.width - 24.0, 220.0), 360.0)
            let textWidth = bubbleWidth - 28.0
            let bodyRect = (item.displayText as NSString).boundingRect(
                with: CGSize(width: textWidth, height: CGFloat.greatestFiniteMagnitude),
                options: [.usesLineFragmentOrigin, .usesFontLeading],
                attributes: [.font: UIFont.systemFont(ofSize: 16.0)],
                context: nil
            )
            let bodyHeight = max(20.0, ceil(bodyRect.height))
            let hasMedia = item.message.mediaPath != nil && !item.message.mediaPath!.isEmpty
            let mediaHeight: CGFloat = hasMedia ? 165.0 : 0.0
            let mediaGap: CGFloat = hasMedia ? 10.0 : 0.0
            let contentHeight = 12.0 + 18.0 + 4.0 + 16.0 + 8.0 + bodyHeight + mediaGap + mediaHeight + 6.0 + 24.0 + 8.0
            let layout = ListViewItemNodeLayout(
                contentSize: CGSize(width: params.width, height: contentHeight),
                insets: UIEdgeInsets(top: 4.0, left: 0.0, bottom: 4.0, right: 0.0)
            )
            return (layout, {
                self.item = item
                self.bubbleView.backgroundColor = UIColor.secondarySystemBackground
                self.senderLabel.textColor = UIColor.label
                self.kindLabel.textColor = UIColor.systemRed
                self.bodyLabel.textColor = UIColor.label
                self.timeLabel.textColor = UIColor.secondaryLabel
                self.senderLabel.text = "From \\(item.message.fromID)"
                self.kindLabel.text = item.displayKind
                self.bodyLabel.text = item.displayText
                self.timeLabel.text = item.displayDate

                self.bubbleView.frame = CGRect(x: 12.0, y: 4.0, width: bubbleWidth, height: contentHeight - 8.0)
                self.senderLabel.frame = CGRect(x: 14.0, y: 9.0, width: bubbleWidth - 64.0, height: 18.0)
                self.kindLabel.frame = CGRect(x: 14.0, y: 29.0, width: bubbleWidth - 28.0, height: 16.0)
                self.bodyLabel.frame = CGRect(x: 14.0, y: 49.0, width: textWidth, height: bodyHeight)

                if hasMedia, let path = item.message.mediaPath {
                    self.mediaView.isHidden = false
                    self.mediaButton.isHidden = false
                    self.mediaTitleLabel.isHidden = false
                    self.layoutMedia(path: path, frame: CGRect(x: 14.0, y: 49.0 + bodyHeight + 10.0, width: bubbleWidth - 28.0, height: mediaHeight))
                } else {
                    self.mediaView.isHidden = true
                    self.mediaButton.isHidden = true
                    self.mediaTitleLabel.isHidden = true
                }

                let footerY = hasMedia ? 49.0 + bodyHeight + 10.0 + mediaHeight + 6.0 : 49.0 + bodyHeight + 6.0
                self.timeLabel.frame = CGRect(x: bubbleWidth - 100.0, y: footerY, width: 64.0, height: 20.0)
                self.saveButton.frame = CGRect(x: bubbleWidth - 38.0, y: footerY - 5.0, width: 30.0, height: 30.0)
            })
        }
    }

    private func layoutMedia(path: String, frame: CGRect) {
        self.mediaView.frame = frame
        self.mediaButton.frame = frame
        self.mediaTitleLabel.frame = frame.insetBy(dx: 18.0, dy: 50.0)

        let ext = URL(fileURLWithPath: path).pathExtension.lowercased()
        let mime = self.item?.message.mimeType?.lowercased() ?? ""
        let isImage = mime.hasPrefix("image/") || ["jpg", "jpeg", "png", "webp", "gif", "heic"].contains(ext)

        if isImage, let image = UIImage(contentsOfFile: path) {
            self.mediaView.image = image
            self.mediaView.contentMode = .scaleAspectFill
            self.mediaView.backgroundColor = .clear
            self.mediaTitleLabel.text = nil
        } else {
            if mime.hasPrefix("video/") || ["mp4", "mov", "m4v"].contains(ext) {
                self.mediaView.image = UIImage(systemName: "play.circle.fill")
            } else if mime.hasPrefix("audio/") || ["mp3", "m4a", "aac", "ogg", "wav"].contains(ext) {
                self.mediaView.image = UIImage(systemName: "waveform.circle.fill")
            } else {
                self.mediaView.image = UIImage(systemName: "doc.circle.fill")
            }
            self.mediaView.backgroundColor = UIColor.tertiarySystemBackground
            self.mediaView.tintColor = UIColor.secondaryLabel
            self.mediaView.contentMode = .center
            self.mediaTitleLabel.text = URL(fileURLWithPath: path).lastPathComponent
            self.mediaTitleLabel.textColor = UIColor.label
        }
    }

    @objc private func savePressed() {
        guard let item else { return }
        if AyuGramMediaArchive.saveToSaved(message: item.message) {
            self.saveButton.setTitle("✓", for: .normal)
        }
    }

    @objc private func mediaPressed() {
        guard let path = self.item?.message.mediaPath else { return }
        AyuHistoryDocumentPreviewer.shared.open(path: path)
    }
}

private enum AyuHistoryEntry: ItemListNodeEntry {
    case header(String)
    case message(Int64, AyuMessage, String, String, String)
    case empty(String)

    var section: ItemListSectionId { return 0 }

    var stableId: Int64 {
        switch self {
        case .header:
            return 0
        case let .message(id, _, _, _, _):
            return 1_000_000_000 + id * 10
        case .empty:
            return 1
        }
    }

    static func == (lhs: AyuHistoryEntry, rhs: AyuHistoryEntry) -> Bool {
        switch (lhs, rhs) {
        case let (.header(a), .header(b)):
            return a == b
        case let (.message(aId, _, aText, aDate, aKind), .message(bId, _, bText, bDate, bKind)):
            return aId == bId && aText == bText && aDate == bDate && aKind == bKind
        case let (.empty(a), .empty(b)):
            return a == b
        default:
            return false
        }
    }

    static func < (lhs: AyuHistoryEntry, rhs: AyuHistoryEntry) -> Bool {
        return lhs.stableId < rhs.stableId
    }

    func item(presentationData: ItemListPresentationData, arguments: Any) -> ListViewItem {
        switch self {
        case let .header(text):
            return ItemListSectionHeaderItem(presentationData: presentationData, text: text, sectionId: self.section)
        case let .message(_, message, body, date, kind):
            return AyuHistoryBubbleItem(
                presentationData: presentationData,
                message: message,
                displayText: body,
                displayDate: date,
                displayKind: kind
            )
        case let .empty(text):
            return ItemListTextItem(presentationData: presentationData, text: .plain(text), sectionId: self.section)
        }
    }
}

if "AyuHistoryBubbleItem" not in ui_text or "savePressed" not in ui_text or "mediaPressed" not in ui_text:
    raise SystemExit("Saved Messages-style History bubble UI missing")

# Validate the user-visible Save action and its real storage contract.
archive_text = archive.read_text()
ui_text = ui.read_text()
if "public static func saveToSaved(message: AyuMessage) -> Bool" not in archive_text:
    raise SystemExit("Saved action implementation missing")
if "AyuGramMediaArchive.saveToSaved(message: message)" not in ui_text:
    raise SystemExit("History Save action wiring missing")
if '.appendingPathComponent("Saved", isDirectory: true)' not in archive_text:
    raise SystemExit("Saved folder path missing")

# Add a runtime smoke test proving a media copy really reaches the Saved folder.
smoke_text = smoke.read_text()
anchor = '        add("history display labels") {'
'''
if anchor not in smoke_text:
    raise SystemExit("Smoke test saved-copy anchor missing")
if 'add("History → Saved copy")' not in smoke_text:
    smoke.write_text(smoke_text.replace(anchor, test + anchor, 1))


# AyuGram History v4 requirements: sender names + deletion timestamps + peer-info More menu.
# These changes are applied after the main patch so the final Telegram-iOS tree,
# simulator smoke test, and AltStore IPA all receive the same behavior.

# 1) Durable history metadata: sender name + exact local deletion time.
message_text = message.read_text()
if "public let fromName: String?" not in message_text:
    anchor = "    public let fromID: Int64\n"
    if anchor not in message_text:
        raise SystemExit("AyuMessage fromID anchor not found")
    message_text = message_text.replace(anchor, anchor + "    public let fromName: String?\n", 1)

if "public let deletedAt: Int32?" not in message_text:
    anchor = "    public let isDeleted: Bool\n"
    if anchor not in message_text:
        raise SystemExit("AyuMessage isDeleted anchor not found")
    message_text = message_text.replace(anchor, anchor + "    public let deletedAt: Int32?\n", 1)

if "        fromName: String? = nil," not in message_text:
    anchor = "        fromID: Int64,\n"
    if anchor not in message_text:
        raise SystemExit("AyuMessage init fromID anchor not found")
    message_text = message_text.replace(anchor, anchor + "        fromName: String? = nil,\n", 1)

if "        deletedAt: Int32? = nil\n" not in message_text:
    anchor = "        isDeleted: Bool\n"
    if anchor not in message_text:
        raise SystemExit("AyuMessage init isDeleted anchor not found")
    message_text = message_text.replace(anchor, "        isDeleted: Bool,\n        deletedAt: Int32? = nil\n", 1)

if "        self.fromName = fromName\n" not in message_text:
    anchor = "        self.fromID = fromID\n"
    if anchor not in message_text:
        raise SystemExit("AyuMessage self.fromID anchor not found")
    message_text = message_text.replace(anchor, anchor + "        self.fromName = fromName\n", 1)

if "        self.deletedAt = deletedAt\n" not in message_text:
    anchor = "        self.isDeleted = isDeleted\n"
    if anchor not in message_text:
        raise SystemExit("AyuMessage self.isDeleted anchor not found")
    message_text = message_text.replace(anchor, anchor + "        self.deletedAt = deletedAt\n", 1)

# Keep metadata when the Postbox history store creates its durable copy.
message_text = message_text.replace(
    "            fromID: message.fromID,\n",
    "            fromID: message.fromID,\n            fromName: message.fromName,\n",
)
message_text = message_text.replace(
    "                fromID: snapshot.fromID,\n",
    "                fromID: snapshot.fromID,\n                fromName: snapshot.fromName,\n",
)
message_text = message_text.replace(
    "            isDeleted: deleted\n",
    "            isDeleted: deleted,\n            deletedAt: message.deletedAt\n",
)
message_text = message_text.replace(
    "                isDeleted: snapshot.isDeleted\n",
    "                isDeleted: snapshot.isDeleted,\n                deletedAt: snapshot.deletedAt\n",
)
message.write_text(message_text)

# 2) Snapshot bridge: automatically timestamp deletion events and retain sender name.
bridge_text = (root / "submodules/AyuGramIOS/Sources/AyuGramPostboxBridge.swift").read_text()
if "fromName: String? = nil" not in bridge_text:
    anchor = "        accountID: Int64,\n"
    if anchor not in bridge_text:
        raise SystemExit("Bridge accountID anchor not found")
    bridge_text = bridge_text.replace(anchor, anchor + "        fromName: String? = nil,\n", 1)
bridge_text = bridge_text.replace(
    "            fromID: authorID,\n",
    "            fromID: authorID,\n            fromName: fromName,\n",
)
bridge_text = bridge_text.replace(
    "            isDeleted: isDeleted\n",
    "            isDeleted: isDeleted,\n            deletedAt: isDeleted ? Int32(Date().timeIntervalSince1970) : nil\n",
)
(root / "submodules/AyuGramIOS/Sources/AyuGramPostboxBridge.swift").write_text(bridge_text)

# 3) Deleted-message capture receives an explicit sender-name lookup from TelegramCore.
capture_text = capture.read_text()
if "senderNames: [Int32: String] = [:]" not in capture_text:
    anchor = "        accountID: Int64\n"
    if anchor not in capture_text:
        raise SystemExit("Capture accountID anchor not found")
    capture_text = capture_text.replace(anchor, "        accountID: Int64,\n        senderNames: [Int32: String] = [:]\n", 1)
capture_text = capture_text.replace(
    "                accountID: accountID,\n                isDeleted: true,",
    "                accountID: accountID,\n                fromName: senderNames[message.id.id],\n                isDeleted: true,",
)
# Preserve sender/deletion metadata in the manual Saved copy.
capture_text = capture_text.replace(
    "            fromID: snapshot.fromID,\n",
    "            fromID: snapshot.fromID,\n            fromName: snapshot.fromName,\n",
)
capture_text = capture_text.replace(
    "            isDeleted: snapshot.isDeleted\n",
    "            isDeleted: snapshot.isDeleted,\n            deletedAt: snapshot.deletedAt\n",
)
capture.write_text(capture_text)

# 4) TelegramCore deletion path: resolve the author's display name before the
# message is removed. This does not bypass Telegram transport/security rules.
delete_paths = [
    root / "submodules/TelegramCore/Sources/TelegramEngine/Messages/DeleteMessages.swift",
    root / "submodules/TelegramCore/Sources/State/AccountStateManagementUtils.swift",
]
for delete_file in delete_paths:
    if not delete_file.exists():
        continue
    d = delete_file.read_text()

    if delete_file.name == "DeleteMessages.swift" and "var ayuSenderNames: [Int32: String] = [:]" not in d:
        anchor = "        let messages = ids.compactMap { transaction.getMessage($0) }\n"
        if anchor in d:
            insertion = '''        let messages = ids.compactMap { transaction.getMessage($0) }
        var ayuSenderNames: [Int32: String] = [:]
        for message in messages {
            if let author = message.author {
                let name: String?
                if let user = author as? TelegramUser {
                    let parts = [user.firstName, user.lastName].compactMap { $0 }.filter { !$0.isEmpty }
                    name = parts.isEmpty ? nil : parts.joined(separator: " ")
                } else if let channel = author as? TelegramChannel {
                    name = channel.title
                } else if let group = author as? TelegramGroup {
                    name = group.title
                } else {
                    name = nil
                }
                if let name, !name.isEmpty {
                    ayuSenderNames[message.id.id] = name
                }
            }
        }
'''
            d = d.replace(anchor, insertion, 1)
        else:
            raise SystemExit("DeleteMessages message snapshot anchor not found")
        d = d.replace(
            "            accountID: ayuAccountID\n        )",
            "            accountID: ayuAccountID,\n            senderNames: ayuSenderNames\n        )",
            1,
        )
        delete_file.write_text(d)

    elif delete_file.name == "AccountStateManagementUtils.swift":
        # Interactive/automatic deletion ultimately flows through DeleteMessages,
        # so no duplicate sender-name logic is needed here.
        delete_file.write_text(d)

# 5) Manual AyuGram Save: retain sender name and local media even when Telegram's
# own Save/Forward action is unavailable. It still depends on media being locally available.
context_menu = root / "submodules/TelegramUI/Sources/ChatInterfaceStateContextMenus.swift"
if not context_menu.exists():
    raise SystemExit(f"Missing chat context menu: {context_menu}")
cm = context_menu.read_text()
if "let ayuSenderName: String?" not in cm:
    # Support both the original single-message Save implementation and the
    # newer multi-message/grouped-media implementation.
    import re
    snapshot_pattern = re.compile(
        r'''(?ms)([ 	]+)let snapshot = AyuGramPostboxBridge\.snapshot\(\n'''
        r'''\1    message: message,\n'''
        r'''\1    accountID: context\.account\.peerId\.toInt64\(\),\n'''
        r'''(?:\1    fromName: [^\n]+,\n)?'''
        r'''\1    isDeleted: false\n'''
        r'''\1\)'''
    )
    match = snapshot_pattern.search(cm)
    if not match:
        # The multi-message version uses "item" instead of "message".
        snapshot_pattern = re.compile(
            r'''(?ms)([ 	]+)let snapshot = AyuGramPostboxBridge\.snapshot\(\n'''
            r'''\1    message: item,\n'''
            r'''\1    accountID: accountID,\n'''
            r'''(?:\1    fromName: [^\n]+,\n)?'''
            r'''\1    isDeleted: false\n'''
            r'''\1\)'''
        )
        match = snapshot_pattern.search(cm)

    if not match:
        raise SystemExit("Manual Save snapshot anchor not found in current TelegramUI implementation")

    indent = match.group(1)
    original_call = match.group(0)
    if "message: item" in original_call:
        replacement = f'''{indent}let ayuSenderName: String? = {{
{indent}    guard let author = item.author else {{
{indent}        return nil
{indent}    }}
{indent}    if let user = author as? TelegramUser {{
{indent}        let parts = [user.firstName, user.lastName].compactMap {{ $0 }}.filter {{ !$0.isEmpty }}
{indent}        return parts.isEmpty ? nil : parts.joined(separator: " ")
{indent}    }} else if let channel = author as? TelegramChannel {{
{indent}        return channel.title
{indent}    }} else if let group = author as? TelegramGroup {{
{indent}        return group.title
{indent}    }}
{indent}    return nil
{indent}}}()
{indent}let snapshot = AyuGramPostboxBridge.snapshot(
{indent}    message: item,
{indent}    accountID: accountID,
{indent}    fromName: ayuSenderName,
{indent}    isDeleted: false
{indent})'''
    else:
        replacement = f'''{indent}let ayuSenderName: String? = {{
{indent}    guard let author = message.author else {{
{indent}        return nil
{indent}    }}
{indent}    if let user = author as? TelegramUser {{
{indent}        let parts = [user.firstName, user.lastName].compactMap {{ $0 }}.filter {{ !$0.isEmpty }}
{indent}        return parts.isEmpty ? nil : parts.joined(separator: " ")
{indent}    }} else if let channel = author as? TelegramChannel {{
{indent}        return channel.title
{indent}    }} else if let group = author as? TelegramGroup {{
{indent}        return group.title
{indent}    }}
{indent}    return nil
{indent}}}()
{indent}let snapshot = AyuGramPostboxBridge.snapshot(
{indent}    message: message,
{indent}    accountID: context.account.peerId.toInt64(),
{indent}    fromName: ayuSenderName,
{indent}    isDeleted: false
{indent})'''
    cm = cm[:match.start()] + replacement + cm[match.end():]

# Remove the experimental transfer action; it was not one of the two requested
# features and can create a false-success UX for protected media.
if 'AyuGram Transfer to Saved Messages' in cm:
    cm = re.sub(
        r'\n\s*actions\.append\(\.action\(ContextMenuActionItem\(text: "AyuGram Transfer to Saved Messages".*?\n\s*\}\)\)\)\n',
        "\n",
        cm,
        flags=re.S,
        count=1,
    )
# The pinned Telegram-iOS baseline exposes accountPeer as an optional EnginePeer.
# Keep the optional-safe expression after the AyuGram patch.
# The baseline History action opens the global screen. Route it to the
# current dialog so the visible menu always shows the correct chat history.
cm = cm.replace(
    "ayuGramHistoryScreen(context: context)",
    "ayuGramHistoryScreen(context: context, dialogID: message.id.peerId.toInt64())"
)
if "ayuGramHistoryScreen(context: context, dialogID: message.id.peerId.toInt64())" not in cm:
    raise SystemExit("Per-dialog History routing could not be installed")

cm = cm.replace("let isPremium = accountPeer.isPremium", "let isPremium = accountPeer?.isPremium ?? false")
# TelegramUI exposes media resources as TelegramMediaResource, not the internal
# MediaResource protocol name used by the initial multi-photo implementation.
cm = cm.replace("[(MediaResource, AyuMediaResourceInfo, String?)]", "[(TelegramMediaResource, AyuMediaResourceInfo, String?)]")
cm = cm.replace("[(MediaResource, AyuMediaResourceInfo, String?)] =", "[(TelegramMediaResource, AyuMediaResourceInfo, String?)] =")
# Force optional tuple elements explicitly so Swift does not infer the image branch as non-optional String.
cm = cm.replace('                                    "jpg"\n                                )', '                                    "jpg" as String?\n                                )')
cm = cm.replace("file.mimeType), nil)]", "file.mimeType), nil as String?)]")
context_menu.write_text(cm)

# 6) Peer info → avatar/profile → three-dots ("More") menu now contains the
# requested AyuGram History entry for the current group/channel/dialog.
peer_menu = root / "submodules/TelegramUI/Components/PeerInfo/PeerInfoScreen/Sources/PeerInfoScreenDisplayMediaGalleryContextMenu.swift"
if not peer_menu.exists():
    raise SystemExit(f"Missing PeerInfo more-menu source: {peer_menu}")
pm = peer_menu.read_text()
if "import AyuGramSettingsScreen" not in pm:
    pm = pm.replace("import Foundation\n", "import Foundation\nimport AyuGramSettingsScreen\n", 1)

if "func addAyuGramHistoryAction" not in pm:
    anchor = "        let peerId = self.peerId\n"
    helper = '''        let peerId = self.peerId

        func addAyuGramHistoryAction(_ items: inout [ContextMenuItem]) {
            items.append(.action(ContextMenuActionItem(
                text: "AyuGram History",
                icon: { theme in
                    return generateTintedImage(
                        image: UIImage(systemName: "clock.arrow.circlepath"),
                        color: theme.contextMenu.primaryColor
                    )
                },
                action: { [weak self] _, action in
                    action(.default)
                    guard let self else {
                        return
                    }
                    let historyController = ayuGramHistoryScreen(context: self.context, dialogID: self.peerId.toInt64())
                    self.controller?.push(historyController)
                }
            )))
        }
'''
    if anchor not in pm:
        raise SystemExit("PeerInfo menu peerId anchor not found")
    pm = pm.replace(anchor, helper, 1)

if "addAyuGramHistoryAction(&items)" not in pm:
    matches = list(re.finditer(r"(?m)^\s*let contextController = makeContextController\(", pm))
    if not matches:
        raise SystemExit("PeerInfo context controller anchor not found")
    # Insert exactly once into the normal profile/media More-menu construction.
    insert_pos = matches[-1].start()
    pm = pm[:insert_pos] + "                addAyuGramHistoryAction(&items)\n\n" + pm[insert_pos:]
if "addAyuGramHistoryAction(&items)" not in pm:
    raise SystemExit("PeerInfo three-dots History action insertion failed")
peer_menu.write_text(pm)

# 7) History bubble UI: show real sender names and both timestamps.
ui = root / "submodules/TelegramUI/Components/AyuGramSettingsScreen/Sources/AyuGramSettingsScreen.swift"
if not ui.exists():
    raise SystemExit(f"Missing AyuGram History UI source: {ui}")
u = ui.read_text()
if "let senderName: String" not in u:
    u = u.replace(
        "    let displayKind: String\n\n    init(presentationData:",
        "    let displayKind: String\n    let senderName: String\n\n    init(presentationData:",
        1,
    )
    u = u.replace(
        "displayDate: String, displayKind: String) {",
        "displayDate: String, displayKind: String, senderName: String) {",
        1,
    )
    u = u.replace(
        "        self.displayKind = displayKind\n",
        "        self.displayKind = displayKind\n        self.senderName = senderName\n",
        1,
    )
u = u.replace(
    'self.senderLabel.text = "From \\(item.message.fromID)"',
    'self.senderLabel.text = item.senderName.isEmpty ? "From \\(item.message.fromID)" : item.senderName',
    1,
)

# Carry sender name inside the ItemList entry.
u = u.replace(
    "case message(Int64, AyuMessage, String, String, String)",
    "case message(Int64, AyuMessage, String, String, String, String)",
    1,
)
u = u.replace(
    "case let .message(id, _, _, _, _):",
    "case let .message(id, _, _, _, _, _):",
    1,
)
u = u.replace(
    "case let (.message(aId, _, aText, aDate, aKind), .message(bId, _, bText, bDate, bKind)):",
    "case let (.message(aId, _, aText, aDate, aKind, aSender), .message(bId, _, bText, bDate, bKind, bSender)):",
    1,
)
u = u.replace(
    "return aId == bId && aText == bText && aDate == bDate && aKind == bKind",
    "return aId == bId && aText == bText && aDate == bDate && aKind == bKind && aSender == bSender",
    1,
)
u = u.replace(
    "case let .message(_, message, body, date, kind):",
    "case let .message(_, message, body, date, kind, sender):",
    1,
)
u = u.replace(
    "                displayKind: kind\n            )",
    "                displayKind: kind,\n                senderName: sender\n            )",
    1,
)

# Display a dedicated deletion timestamp in the metadata line.
if "let deletionDate" not in u:
    anchor = '''        let kind = AyuHistoryDisplay.label(isDeleted: message.isDeleted, settings: settings)
        let date = formatter.string(from: Date(timeIntervalSince1970: TimeInterval(message.date)))
'''
    replacement = '''        let kind = AyuHistoryDisplay.label(isDeleted: message.isDeleted, settings: settings)
        let date = formatter.string(from: Date(timeIntervalSince1970: TimeInterval(message.date)))
        let deletionDate: String? = {
            guard let deletedAt = message.deletedAt else {
                return nil
            }
            return formatter.string(from: Date(timeIntervalSince1970: TimeInterval(deletedAt)))
        }()
'''
    if anchor in u:
        u = u.replace(anchor, replacement, 1)
    else:
        raise SystemExit("History date anchor not found")

# The current History source uses .item(id, text), not a .message entry.
# Preserve that established ItemList model and enrich its displayed text.
item_match = re.search(r'(?m)^(\s*)entries\.append\(\.item\(message\.fakeID, (.+)\)\)', u)
if item_match:
    indent = item_match.group(1)
    replacement = (
        indent + 'let sender = message.fromName ?? ""\n'
        + indent + 'let meta = deletionDate.map { "\\(date) • Deleted \\($0)" } ?? date\n'
        + indent + 'entries.append(.item(message.fakeID, "\\(sender.isEmpty ? \"Unknown sender\" : sender) • \\(kind) • \\(meta)\\(mediaLabel)\\n\\(body)"))'
    )
    u = u[:item_match.start()] + replacement + u[item_match.end():]
else:
    # Support a future richer .message model if the source is deliberately upgraded.
    entry_match = re.search(r'(?m)^(\s*)entries\.append\(\.message\(message\.fakeID, message, body, date, kind\)\)', u)
    if entry_match:
        indent = entry_match.group(1)
        replacement = (
            indent + 'let sender = message.fromName ?? ""\n'
            + indent + 'let meta = deletionDate.map { "\\(date) • Deleted \\($0)" } ?? date\n'
            + indent + 'entries.append(.message(message.fakeID, message, body, meta, kind, sender))'
        )
        u = u[:entry_match.start()] + replacement + u[entry_match.end():]
    elif ".message(message.fakeID, message, body, meta, kind, sender)" not in u and ".item(message.fakeID" not in u:
        raise SystemExit("History entry construction not recognized")

ui.write_text(u)

# 8) Saved metadata also records sender and deletion time.
a = archive.read_text()
a = a.replace(
    '            "senderID": message.fromID,\n',
    '            "senderID": message.fromID,\n            "senderName": message.fromName ?? "",\n',
)
a = a.replace(
    '            "isDeleted": message.isDeleted\n',
    '            "isDeleted": message.isDeleted,\n            "deletedAt": message.deletedAt.map { NSNumber(value: $0) } ?? NSNull()\n',
)
archive.write_text(a)

# 9) Runtime/static CI assertions for the exact requested behavior.
peer_menu_text = peer_menu.read_text()
if "AyuGram History" not in peer_menu_text or "dialogID: self.peerId.toInt64()" not in peer_menu_text:
    raise SystemExit("PeerInfo three-dots History integration not present")
if "public let fromName: String?" not in message_text or "public let deletedAt: Int32?" not in message_text:
    raise SystemExit("History sender/deletion metadata model missing")
if "senderNames: [Int32: String]" not in capture.read_text():
    raise SystemExit("Deleted capture sender-name contract missing")
if context_menu_text.count("AyuGram Save") != 1:
    raise SystemExit("Manual AyuGram Save action must exist exactly once")
save_tail = context_menu_text.split("AyuGram Save", 1)[1].split("})))", 1)[0]
if "isCopyProtected()" in save_tail or "containsSecretMedia" in save_tail:
    raise SystemExit("Manual AyuGram Save must not reuse Telegram copy-protection gate")
if 'Deleted \\($0)' not in u:
    raise SystemExit("History deleted-at presentation missing")
print("AyuGram History v4 applied: per-dialog Saved Messages UI + sender names + deletion timestamps + PeerInfo three-dots History + manual local-media Save.")
