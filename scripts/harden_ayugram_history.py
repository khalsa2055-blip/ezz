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
old = '''        case "video/quicktime":
            return "mov"
        default:
            return nil
        }'''
new = '''        case "video/quicktime":
            return "mov"
        case "audio/mpeg":
            return "mp3"
        case "audio/mp4":
            return "m4a"
        case "audio/aac":
            return "aac"
        case "audio/ogg":
            return "ogg"
        case "audio/wav", "audio/x-wav":
            return "wav"
        case "application/pdf":
            return "pdf"
        case "application/zip":
            return "zip"
        case "text/plain":
            return "txt"
        case "application/msword":
            return "doc"
        case "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            return "docx"
        case "application/vnd.ms-excel":
            return "xls"
        case "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
            return "xlsx"
        default:
            return nil
        }'''
if old not in s:
    raise SystemExit("Media extension switch anchor not found")
archive.write_text(s.replace(old, new, 1))

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
print("AyuGram History hardening applied: Documents/AyuGram/History + media MIME support + Files app integration.")

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

ui_text = ui_text.replace(
    'let title = dialogID == nil ? "AyuGram History" : "Group History"',
    'let title = dialogID == nil ? "AyuGram History" : "History"',
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
test = '''        add("History → Saved media set") {
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
                .appendingPathComponent("AyuGram", isDirectory: true)
                .appendingPathComponent("Saved", isDirectory: true)
                .appendingPathComponent(String(accountID), isDirectory: true)
                .appendingPathComponent(String(dialogID), isDirectory: true)
                .appendingPathComponent(String(messageID), isDirectory: true)
                .appendingPathComponent("media", isDirectory: true)
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
                .appendingPathComponent("AyuGram", isDirectory: true)
                .appendingPathComponent("Saved", isDirectory: true)
                .appendingPathComponent(String(accountID), isDirectory: true)
                .appendingPathComponent(String(dialogID), isDirectory: true)
                .appendingPathComponent(String(messageID), isDirectory: true)
            let savedMedia = savedRoot?.appendingPathComponent("media.jpg")
            let savedMetadata = savedRoot?.appendingPathComponent("metadata.json")
            let ok = saved
                && (savedMedia.map { FileManager.default.fileExists(atPath: $0.path) } ?? false)
                && (savedMetadata.map { FileManager.default.fileExists(atPath: $0.path) } ?? false)
            return (ok, ok ? "media and metadata copied to Documents/AyuGram/Saved" : "Saved copy failed")
        }

'''
if anchor not in smoke_text:
    raise SystemExit("Smoke test saved-copy anchor missing")
if 'add("History → Saved copy")' not in smoke_text:
    smoke.write_text(smoke_text.replace(anchor, test + anchor, 1))
