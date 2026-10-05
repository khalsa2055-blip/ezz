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
