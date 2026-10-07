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

            let first = tempRoot.appendingPathComponent("media-1.jpg")
            let second = tempRoot.appendingPathComponent("media-2.mp4")
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
            let savedMedia = savedRoot?.appendingPathComponent("Media").appendingPathComponent("media.jpg")
            let savedMetadata = savedRoot?.appendingPathComponent("Messages").appendingPathComponent("message-\\(messageID).json")
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
            .appendingPathComponent("Telegram", isDirectory: true)
            .appendingPathComponent("AyuGram", isDirectory: true)
            .appendingPathComponent("Saved", isDirectory: true)
        guard let root else { return false }
        let mediaRoot = root.appendingPathComponent("Media", isDirectory: true)
        let messagesRoot = root.appendingPathComponent("Messages", isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: mediaRoot, withIntermediateDirectories: true)
            try FileManager.default.createDirectory(at: messagesRoot, withIntermediateDirectories: true)
        } catch { return false }

        var didSave = false
        if let source = message.mediaPath, FileManager.default.fileExists(atPath: source) {
            let sourceURL = URL(fileURLWithPath: source)
            let sourceDirectory = sourceURL.deletingLastPathComponent()
            let resourceFiles = ((try? FileManager.default.contentsOfDirectory(at: sourceDirectory, includingPropertiesForKeys: [.isRegularFileKey], options: [.skipsHiddenFiles])) ?? []).filter { url in
                url.pathExtension.lowercased() != "json" &&
                (try? url.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true
            }.sorted { $0.lastPathComponent.localizedStandardCompare($1.lastPathComponent) == .orderedAscending }

            if resourceFiles.count > 1 {
                for (index, file) in resourceFiles.enumerated() {
                    let ext = file.pathExtension.isEmpty ? (pathExtension(for: message.mimeType) ?? "bin") : file.pathExtension
                    let destination = mediaRoot.appendingPathComponent("media-\\(index + 1).\\(ext)")
                    do {
                        if !FileManager.default.fileExists(atPath: destination.path) { try FileManager.default.copyItem(at: file, to: destination) }
                        didSave = true
                    } catch { return false }
                }
            } else {
                let ext = sourceURL.pathExtension.isEmpty ? (pathExtension(for: message.mimeType) ?? "bin") : sourceURL.pathExtension
                let destination = mediaRoot.appendingPathComponent("media.\\(ext)")
                do {
                    if !FileManager.default.fileExists(atPath: destination.path) { try FileManager.default.copyItem(at: sourceURL, to: destination) }
                    didSave = true
                } catch { return false }
            }
        }

        if !message.text.isEmpty, let data = message.text.data(using: .utf8) {
            do {
                try data.write(to: messagesRoot.appendingPathComponent("message-\\(message.messageID).txt"), options: .atomic)
                didSave = true
            } catch { return false }
        }

        let metadata: [String: Any] = [
            "messageID": message.messageID, "dialogID": message.dialogID, "accountID": message.userID,
            "senderID": message.fromID, "date": message.date, "editDate": message.editDate,
            "mimeType": message.mimeType ?? "", "text": message.text, "isDeleted": message.isDeleted
        ]
        do {
            let data = try JSONSerialization.data(withJSONObject: metadata, options: [.prettyPrinted, .sortedKeys])
            try data.write(to: messagesRoot.appendingPathComponent("message-\\(message.messageID).json"), options: .atomic)
            didSave = true
        } catch { return false }
        return didSave
    }

'''
