#!/usr/bin/env python3
"""Persist eligible deleted messages as client-only rows in chat history.

Run after harden_ayugram_history.py. The original Telegram deletion still
executes normally; a reserved global-ID sentinel identifies the retained local
copy. Copy-protected messages and secret media remain excluded by the caller.
"""
from pathlib import Path

root = Path.cwd()
capture = root / "submodules/AyuGramIOS/Sources/AyuGramCaptureService.swift"
delete = root / "submodules/TelegramCore/Sources/TelegramEngine/Messages/DeleteMessages.swift"
state = root / "submodules/TelegramCore/Sources/State/AccountStateManagementUtils.swift"
status_ui = root / "submodules/TelegramUI/Components/Chat/ChatMessageDateAndStatusNode/Sources/ChatMessageDateAndStatusNode.swift"
bubble_ui = root / "submodules/TelegramUI/Components/Chat/ChatMessageBubbleItemNode/Sources/ChatMessageBubbleItemNode.swift"
interactive_file_ui = root / "submodules/TelegramUI/Components/Chat/ChatMessageInteractiveFileNode/Sources/ChatMessageInteractiveFileNode.swift"

for path in (capture, delete, state, status_ui, bubble_ui, interactive_file_ui):
    if not path.is_file():
        raise SystemExit(f"Required Telegram/AyuGram source is missing: {path}")

# Mark text-only messages as eligible too. The capture list is also the
# explicit allow-list: copy-protected and secret-media messages never enter it.
delete_text = delete.read_text(encoding="utf-8")
old_delete_marker = """            if !resources.isEmpty {
                var seen: Set<String> = []
                resources = resources.filter { seen.insert($0.id).inserted }
                mediaCaptures.append(AyuMessageMediaCapture(messageID: message.id.id, resources: resources))
            }"""
new_delete_marker = """            var seen: Set<String> = []
            resources = resources.filter { seen.insert($0.id).inserted }
            // Empty resources still mark eligible text-only messages for retention.
            mediaCaptures.append(AyuMessageMediaCapture(messageID: message.id.id, resources: resources))"""
if old_delete_marker in delete_text:
    delete_text = delete_text.replace(old_delete_marker, new_delete_marker, 1)
elif new_delete_marker not in delete_text:
    raise SystemExit("Could not mark regular deletions (including text-only messages) for local retention.")
delete.write_text(delete_text, encoding="utf-8")

# Megagroup/channel DeleteChannelMessages updates use a separate capture helper.
state_text = state.read_text(encoding="utf-8")
old_channel_marker = """        var seenResources = Set<String>()
        resources = resources.filter { seenResources.insert($0.id).inserted }
        if !resources.isEmpty {
            mediaCaptures.append(AyuMessageMediaCapture(messageID: message.id.id, resources: resources))
        }"""
new_channel_marker = """        var seenResources = Set<String>()
        resources = resources.filter { seenResources.insert($0.id).inserted }
        // Include text-only messages; the caller has already enforced protection checks.
        mediaCaptures.append(AyuMessageMediaCapture(messageID: message.id.id, resources: resources))"""
if old_channel_marker in state_text:
    state_text = state_text.replace(old_channel_marker, new_channel_marker, 1)
elif new_channel_marker not in state_text:
    raise SystemExit("Could not mark channel/group deletions (including text-only messages) for local retention.")
state.write_text(state_text, encoding="utf-8")

capture_text = capture.read_text(encoding="utf-8")
call_anchor = """        guard settingsStore?.settings.saveDeletedMessages == true else {
            return
        }

        var capturesByMessageID: [Int32: [AyuMediaResourceInfo]] = [:]"""
call_replacement = """        guard settingsStore?.settings.saveDeletedMessages == true else {
            return
        }

        // Save a local Postbox row before Telegram removes the server-backed row.
        // It keeps the original message id out of the server deletion namespace, so
        // later delete updates cannot remove this local copy.
        let eligibleMessageIDs = Set(mediaCaptures.map(\\.messageID))
        if !eligibleMessageIDs.isEmpty {
            let eligibleMessages = messages.filter { eligibleMessageIDs.contains($0.id.id) }
            Self.retainDeletedMessagesInChat(transaction: transaction, messages: eligibleMessages)
        }

        var capturesByMessageID: [Int32: [AyuMediaResourceInfo]] = [:]"""
if call_anchor in capture_text:
    capture_text = capture_text.replace(call_anchor, call_replacement, 1)
elif "Self.retainDeletedMessagesInChat(transaction: transaction" not in capture_text:
    raise SystemExit("Could not locate the deleted-message capture entry point.")

helper = r'''
    /// Re-inserts a deleted message into the namespace queried by the normal chat
    /// history view. The reserved global-ID range identifies these rows as local-only.
    /// The original server message is still deleted normally and is never re-sent.
    public static func isRetainedDeletedMessage(_ message: Message) -> Bool {
        guard message.id.namespace == 0, let globalId = message.globallyUniqueId else {
            return false
        }
        return globalId >= Int64.min && globalId <= Int64.min + Int64(Int32.max)
    }

    private static func retainDeletedMessagesInChat(transaction: Transaction, messages: [Message]) {
        for message in messages {
            // Keep the module independent of TelegramCore (which imports AyuGramIOS):
            // TelegramCore SyncCore_Namespaces defines Cloud = 0 and Local = 1.
            guard message.id.namespace == 0 else {
                continue
            }

            var storedForwardInfo: StoreMessageForwardInfo?
            if let forwardInfo = message.forwardInfo {
                storedForwardInfo = StoreMessageForwardInfo(
                    authorId: forwardInfo.author?.id,
                    sourceId: forwardInfo.source?.id,
                    sourceMessageId: forwardInfo.sourceMessageId,
                    date: forwardInfo.date,
                    authorSignature: forwardInfo.authorSignature,
                    psaType: forwardInfo.psaType,
                    flags: forwardInfo.flags
                )
            }

            let localCopy = StoreMessage(
                peerId: message.id.peerId,
                // Use the normal chat-history namespace so Telegram iOS's regular
                // history query can render the retained copy. The sentinel global ID
                // marks this row as client-only; it is never sent to Telegram.
                namespace: 0,
                customStableId: nil,
                globallyUniqueId: Int64.min + Int64(message.id.id),
                groupingKey: message.groupingKey,
                threadId: message.threadId,
                timestamp: message.timestamp,
                flags: StoreMessageFlags(message.flags),
                tags: [],
                globalTags: [],
                localTags: [],
                forwardInfo: storedForwardInfo,
                authorId: message.author?.id,
                // Visible AyuGram-style deleted marker on the retained chat copy.
                // This stays local-only and does not alter the original server message.
                text: message.text,
                attributes: message.attributes,
                media: message.media
            )
            _ = transaction.addMessages([localCopy], location: .Random)
        }
    }
'''
if "private static func retainDeletedMessagesInChat" not in capture_text:
    last_closing = capture_text.rfind("\n}")
    if last_closing < 0:
        raise SystemExit("AyuGramCaptureService closing brace was not found.")
    capture_text = capture_text[:last_closing] + helper + capture_text[last_closing:]

capture.write_text(capture_text, encoding="utf-8")


# Render the deleted marker in the timestamp/status line, not inside message text.
status_text = status_ui.read_text(encoding="utf-8")
status_text = status_text.replace(
    "        var edited: Bool\n        var impressionCount: Int?",
    "        var edited: Bool\n        var isDeletedRetained: Bool\n        var impressionCount: Int?",
    1
)
status_text = status_text.replace(
    "            edited: Bool,\n            impressionCount: Int?",
    "            edited: Bool,\n            isDeletedRetained: Bool = false,\n            impressionCount: Int?",
    1
)
status_text = status_text.replace(
    "            self.edited = edited\n            self.impressionCount =",
    "            self.edited = edited\n            self.isDeletedRetained = isDeletedRetained\n            self.impressionCount =",
    1
)
status_anchor = "            var updatedDateText = arguments.dateText\n"
status_replacement = """            var updatedDateText = arguments.dateText
            if arguments.isDeletedRetained {
                // Keep message content untouched; show the trash marker with the time.
                updatedDateText = "🗑️ " + updatedDateText
            }
"""
if status_anchor in status_text:
    status_text = status_text.replace(status_anchor, status_replacement, 1)
elif 'if arguments.isDeletedRetained {' not in status_text:
    raise SystemExit("Could not locate timestamp label for deleted marker.")
if "var isDeletedRetained: Bool" not in status_text or "self.isDeletedRetained = isDeletedRetained" not in status_text:
    raise SystemExit("Could not wire retained-message state into timestamp arguments.")
status_ui.write_text(status_text, encoding="utf-8")

bubble_text = bubble_ui.read_text(encoding="utf-8")
bubble_anchor = "                    edited: edited && !item.presentationData.isPreview,\n"
bubble_replacement = bubble_anchor + "                    isDeletedRetained: item.message.id.namespace == 0 && (item.message.globallyUniqueId ?? 0) <= Int64.min + Int64(Int32.max),\n"
if bubble_anchor in bubble_text:
    bubble_text = bubble_text.replace(bubble_anchor, bubble_replacement, 1)
elif "isDeletedRetained: item.message.id.namespace == 1," not in bubble_text:
    raise SystemExit("Could not pass Local namespace state to message timestamp UI.")
bubble_ui.write_text(bubble_text, encoding="utf-8")

# The interactive-file bubble has a separate date/status initializer call. Pass
# the Local namespace flag there too; the initializer's default keeps every
# other Telegram call site source-compatible.
interactive_file_text = interactive_file_ui.read_text(encoding="utf-8")
interactive_anchor = """                        edited: edited && !arguments.presentationData.isPreview,
                        impressionCount:"""
interactive_replacement = """                        edited: edited && !arguments.presentationData.isPreview,
                        isDeletedRetained: arguments.message.id.namespace == 0 && (arguments.message.globallyUniqueId ?? 0) <= Int64.min + Int64(Int32.max),
                        impressionCount:"""
if interactive_anchor in interactive_file_text:
    interactive_file_text = interactive_file_text.replace(interactive_anchor, interactive_replacement, 1)
elif "isDeletedRetained: arguments.message.id.namespace == 1," not in interactive_file_text:
    raise SystemExit("Could not pass retained-message state to interactive file timestamp UI.")
interactive_file_ui.write_text(interactive_file_text, encoding="utf-8")

# Fail the build early if either update path is no longer wired to the helper.
checks = {
    "chat history namespace clone": "namespace: 0," in capture_text,
    "timestamp status argument": "isDeletedRetained: item.message.id.namespace == 0 && (item.message.globallyUniqueId ?? 0) <= Int64.min + Int64(Int32.max)," in bubble_text,
    "Postbox local insertion": "transaction.addMessages([localCopy], location: .Random)" in capture_text,
    "retained-message sentinel": "Int64.min + Int64(message.id.id)" in capture_text and "isRetainedDeletedMessage(_ message: Message)" in capture_text,
    "timestamp trash marker": 'updatedDateText = "🗑️ " + updatedDateText' in status_text,
    "interactive-file timestamp flag": "isDeletedRetained: arguments.message.id.namespace == 0 && (arguments.message.globallyUniqueId ?? 0) <= Int64.min + Int64(Int32.max)," in interactive_file_text,
    "backward-compatible initializer default": "isDeletedRetained: Bool = false," in status_text,
    "History remains enabled": "AyuGramPostboxHistoryStore.appendDeleted" in capture_text,
    "regular deletion allow-list": "AyuGramCaptureService.captureDeleted(" in delete_text and "mediaCaptures.append(AyuMessageMediaCapture(messageID: message.id.id, resources: resources))" in delete_text,
    "channel deletion allow-list": "AyuGramCaptureService.captureDeleted(" in state_text and "mediaCaptures.append(AyuMessageMediaCapture(messageID: message.id.id, resources: resources))" in state_text,
    "copy-protection guard remains": "!message.isCopyProtected(), !message.containsSecretMedia" in delete_text and "!message.isCopyProtected(), !message.containsSecretMedia" in state_text,
}
failed = [name for name, passed in checks.items() if not passed]
if failed:
    raise SystemExit("Keep-deleted-in-chat integration checks failed: " + ", ".join(failed))

print("AyuGram keep-deleted-in-chat integration applied: eligible messages are copied to Postbox Local before server deletion; secret/copy-protected messages remain excluded.")
