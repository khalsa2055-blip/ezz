from pathlib import Path
import re

# This runs after the main AyuGram patch has been applied to Telegram-iOS.
# It hardens the History implementation without changing the upstream patch.
root = Path("telegram-ios") if Path("telegram-ios").is_dir() else Path(".")
archive = root / "submodules/AyuGramIOS/Sources/AyuGramMediaArchive.swift"
message = root / "submodules/AyuGramIOS/Sources/MessageHistory.swift"
store = root / "submodules/AyuGramIOS/Sources/AyuGramPostboxHistoryStore.swift"
capture = root / "submodules/AyuGramIOS/Sources/AyuGramCaptureService.swift"

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

print("AyuGram History hardening applied: Documents/AyuGram/History + audio/document MIME support.")

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
old_enum = '''private enum AyuHistoryEntry: ItemListNodeEntry {
    case header(String)
    case item(Int64, String)
    case empty(String)

    var section: ItemListSectionId { return 0 }

    var stableId: Int64 {
        switch self {
        case .header:
            return 0
        case let .item(id, _):
            return id
        case .empty:
            return 1
        }
    }

    static func == (lhs: AyuHistoryEntry, rhs: AyuHistoryEntry) -> Bool {
        switch (lhs, rhs) {
        case let (.header(a), .header(b)):
            return a == b
        case let (.item(aId, a), .item(bId, b)):
            return aId == bId && a == b
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
        case let .item(_, text), let .empty(text):
            return ItemListTextItem(presentationData: presentationData, text: .plain(text), sectionId: self.section)
        }
    }
}'''
new_enum = '''private enum AyuHistoryEntry: ItemListNodeEntry {
    case header(String)
    case item(Int64, String, AyuMessage)
    case empty(String)

    var section: ItemListSectionId { return 0 }

    var stableId: Int64 {
        switch self {
        case .header:
            return 0
        case let .item(id, _, _):
            return id
        case .empty:
            return 1
        }
    }

    static func == (lhs: AyuHistoryEntry, rhs: AyuHistoryEntry) -> Bool {
        switch (lhs, rhs) {
        case let (.header(a), .header(b)):
            return a == b
        case let (.item(aId, a, _), .item(bId, b, _)):
            return aId == bId && a == b
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
        case let .item(_, text, message):
            return ItemListActionItem(
                presentationData: presentationData,
                systemStyle: .glass,
                title: text,
                kind: .generic,
                alignment: .natural,
                sectionId: self.section,
                style: .blocks,
                action: {
                    _ = AyuGramMediaArchive.saveToSaved(message: message)
                }
            )
        case let .empty(text):
            return ItemListTextItem(presentationData: presentationData, text: .plain(text), sectionId: self.section)
        }
    }
}'''
if old_enum not in ui_text:
    raise SystemExit("History entry UI anchor missing")
ui_text = ui_text.replace(old_enum, new_enum, 1)

old_entry_line = '''        let body = message.text.isEmpty ? "(media)\\(mediaLabel)" : "\\(message.text)\\(mediaLabel)"
        entries.append(.item(message.fakeID, "\\(kind) • \\(date)\\(mediaLabel)\\n\\(body)"))
'''
new_entry_line = '''        let body = message.text.isEmpty ? "(media)\\(mediaLabel)" : "\\(message.text)\\(mediaLabel)"
        let preview = "\\(kind) • \\(date)\\n\\(body)\\n💾 Save"
        entries.append(.item(message.fakeID, preview, message))
'''
if old_entry_line not in ui_text:
    raise SystemExit("History row construction anchor missing")
ui.write_text(ui_text.replace(old_entry_line, new_entry_line, 1))

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
test = '''        add("History → Saved copy") {
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
if "add("History → Saved copy")" not in smoke_text:
    smoke.write_text(smoke_text.replace(anchor, test + anchor, 1))
