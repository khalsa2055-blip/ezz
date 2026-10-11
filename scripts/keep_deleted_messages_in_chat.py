#!/usr/bin/env python3
"""Persist an eligible, local-only copy of each deleted message in its chat.

Run after harden_ayugram_history.py. The original Telegram deletion still
executes normally; this adds a separate Postbox Local-namespace entry, matching
AyuGram's anti-recall/reinjection model without sending anything to Telegram.
Copy-protected messages and secret media remain excluded by the caller.
"""
from pathlib import Path

root = Path.cwd()
capture = root / "submodules/AyuGramIOS/Sources/AyuGramCaptureService.swift"
delete = root / "submodules/TelegramCore/Sources/TelegramEngine/Messages/DeleteMessages.swift"
state = root / "submodules/TelegramCore/Sources/State/AccountStateManagementUtils.swift"

for path in (capture, delete, state):
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
    /// Re-inserts a deleted message as a local-only history entry. Postbox
    /// persists Local-namespace messages across launches; the server-side
    /// Cloud message is still deleted normally and is never re-sent.
    private static func retainDeletedMessagesInChat(transaction: Transaction, messages: [Message]) {
        for message in messages {
            guard message.id.namespace == Namespaces.Message.Cloud else {
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
                namespace: Namespaces.Message.Local,
                customStableId: nil,
                globallyUniqueId: Int64.random(in: Int64.min...Int64.max),
                groupingKey: message.groupingKey,
                threadId: message.threadId,
                timestamp: message.timestamp,
                flags: StoreMessageFlags(message.flags),
                tags: [],
                globalTags: [],
                localTags: [],
                forwardInfo: storedForwardInfo,
                authorId: message.author?.id,
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

# Fail the build early if either update path is no longer wired to the helper.
checks = {
    "local namespace clone": "namespace: Namespaces.Message.Local" in capture_text,
    "Postbox local insertion": "transaction.addMessages([localCopy], location: .Random)" in capture_text,
    "History remains enabled": "AyuGramPostboxHistoryStore.appendDeleted" in capture_text,
    "regular deletion allow-list": "AyuGramCaptureService.captureDeleted(" in delete_text and "mediaCaptures.append(AyuMessageMediaCapture(messageID: message.id.id, resources: resources))" in delete_text,
    "channel deletion allow-list": "AyuGramCaptureService.captureDeleted(" in state_text and "mediaCaptures.append(AyuMessageMediaCapture(messageID: message.id.id, resources: resources))" in state_text,
    "copy-protection guard remains": "!message.isCopyProtected(), !message.containsSecretMedia" in delete_text and "!message.isCopyProtected(), !message.containsSecretMedia" in state_text,
}
failed = [name for name, passed in checks.items() if not passed]
if failed:
    raise SystemExit("Keep-deleted-in-chat integration checks failed: " + ", ".join(failed))

print("AyuGram keep-deleted-in-chat integration applied: eligible messages are copied to Postbox Local before server deletion; secret/copy-protected messages remain excluded.")
