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
status_ui = root / "submodules/TelegramUI/Components/Chat/ChatMessageDateAndStatusNode/Sources/ChatMessageDateAndStatusNode.swift"
bubble_ui = root / "submodules/TelegramUI/Components/Chat/ChatMessageBubbleItemNode/Sources/ChatMessageBubbleItemNode.swift"
interactive_file_ui = root / "submodules/TelegramUI/Components/Chat/ChatMessageInteractiveFileNode/Sources/ChatMessageInteractiveFileNode.swift"
interactive_media_ui = root / "submodules/TelegramUI/Components/Chat/ChatMessageInteractiveMediaNode/Sources/ChatMessageInteractiveMediaNode.swift"

for path in (capture, delete, state, status_ui, bubble_ui, interactive_file_ui, interactive_media_ui):
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
                namespace: 1,
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


# Render the original AyuGram trash-bin image beside the timestamp.
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

# This is the original AyuGram Desktop Telegram/Resources/icons/ayu/trash_bin.png
# embedded directly from the 20x24 PNG so its exact artwork is used in the IPA.
icon_declaration = '''private let ayuGramDeletedMessageIcon: UIImage? = {
    guard let data = Data(base64Encoded: "iVBORw0KGgoAAAANSUhEUgAAABQAAAAYCAYAAAD6S912AAAACXBIWXMAAAsTAAALEwEAmpwYAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAADcSURBVHgB7ZTRDYQgDIZ/zL3rBjqCIziSo+gErqATuIIj6ATqBBwl8UGgQAhvd19CYgr90haiACCRkQKZ+YQOtG2Lqqr0977veoWQ3BqGQZp0XSd9OZZQVSObptGJ53lawnVdpapan3EJBYxLmaYJSoYY+r7HsiyvmCV8oLk9szMJzdEqm9oJQW27cp3PRgkRoixLZ7xIaYm47zteGIN6AfHC67oQgquQvWU1d/gQQjjjbMu+OW7bxu6xwnEc2aR5ntk9tmWCnk9d168YVX4cB5KEKWT/H/6FvyD8Au03q6Ilts/6AAAAAElFTkSuQmCC") else {
        return nil
    }
    return UIImage(data: data)?.withRenderingMode(.alwaysTemplate)
}()'''
icon_anchor = "private let reactionFont = Font.regular(12.0)\n"
if "private let ayuGramDeletedMessageIcon" not in status_text:
    if icon_anchor not in status_text:
        raise SystemExit("Could not locate status-node icon declaration anchor.")
    status_text = status_text.replace(icon_anchor, icon_anchor + "\n" + icon_declaration + "\n", 1)

# Keep an ASImageNode for the deletion icon, independent of message text.
if "private var deletedIconNode: ASImageNode?" not in status_text:
    prop_anchor = "    private var impressionIcon: ASImageNode?\n"
    if prop_anchor not in status_text:
        raise SystemExit("Could not locate date/status image-node properties.")
    status_text = status_text.replace(prop_anchor, prop_anchor + "    private var deletedIconNode: ASImageNode?\n", 1)

if "var currentDeletedIconNode = self.deletedIconNode" not in status_text:
    current_anchor = "        var currentImpressionIcon = self.impressionIcon\n"
    if current_anchor not in status_text:
        raise SystemExit("Could not locate date/status layout node locals.")
    status_text = status_text.replace(current_anchor, current_anchor + "        var currentDeletedIconNode = self.deletedIconNode\n", 1)

status_anchor = "            var updatedDateText = arguments.dateText\n"
status_replacement = """            var updatedDateText = arguments.dateText
"""
if status_anchor in status_text:
    status_text = status_text.replace(status_anchor, status_replacement, 1)
elif "var updatedDateText = arguments.dateText" not in status_text:
    raise SystemExit("Could not locate timestamp label for deleted icon.")

date_layout_anchor = """            let dateFont = Font.regular(floor(arguments.presentationData.fontSize.baseDisplaySize * 11.0 / 17.0))
            let (date, dateApply) = dateLayout(TextNodeLayoutArguments(attributedString: NSAttributedString(string: updatedDateText, font: dateFont, textColor: dateColor), backgroundColor: nil, maximumNumberOfLines: 1, truncationType: .middle, constrainedSize: arguments.constrainedSize, alignment: .natural, cutout: nil, insets: UIEdgeInsets()))
"""
date_layout_replacement = """            let deletedIconImage: UIImage? = arguments.isDeletedRetained ? ayuGramDeletedMessageIcon?.withTintColor(dateColor, renderingMode: .alwaysOriginal) : nil
            let deletedIconSize: CGSize = deletedIconImage == nil ? CGSize.zero : CGSize(width: 10.0, height: 12.0)
            let deletedIconSpacing: CGFloat = deletedIconImage == nil ? 0.0 : 3.0
            if deletedIconImage != nil {
                if currentDeletedIconNode == nil {
                    let iconNode = ASImageNode()
                    iconNode.isLayerBacked = true
                    iconNode.displayWithoutProcessing = true
                    iconNode.displaysAsynchronously = false
                    iconNode.contentMode = .scaleAspectFit
                    currentDeletedIconNode = iconNode
                }
            } else {
                currentDeletedIconNode = nil
            }

            let dateFont = Font.regular(floor(arguments.presentationData.fontSize.baseDisplaySize * 11.0 / 17.0))
            let (date, dateApply) = dateLayout(TextNodeLayoutArguments(attributedString: NSAttributedString(string: updatedDateText, font: dateFont, textColor: dateColor), backgroundColor: nil, maximumNumberOfLines: 1, truncationType: .middle, constrainedSize: arguments.constrainedSize, alignment: .natural, cutout: nil, insets: UIEdgeInsets()))
"""
if date_layout_anchor in status_text:
    status_text = status_text.replace(date_layout_anchor, date_layout_replacement, 1)
elif "let deletedIconSize: CGSize" not in status_text:
    raise SystemExit("Could not insert deleted-icon layout sizing.")

layout_anchor = "            let layoutSize = CGSize(width: leftInset + impressionWidth + date.size.width + statusWidth + backgroundInsets.left + backgroundInsets.right, height: date.size.height + backgroundInsets.top + backgroundInsets.bottom)"
layout_replacement = "            let layoutSize = CGSize(width: leftInset + impressionWidth + deletedIconSize.width + deletedIconSpacing + date.size.width + statusWidth + backgroundInsets.left + backgroundInsets.right, height: date.size.height + backgroundInsets.top + backgroundInsets.bottom)"
if layout_anchor in status_text:
    status_text = status_text.replace(layout_anchor, layout_replacement, 1)
elif layout_replacement not in status_text:
    raise SystemExit("Could not account for the deletion icon in timestamp width.")

status_text = status_text.replace(
    "leftInset + impressionWidth + date.size.width +",
    "leftInset + impressionWidth + deletedIconSize.width + deletedIconSpacing + date.size.width +"
)
status_text = status_text.replace(
    "leftInset + date.size.width + 8.5",
    "leftInset + deletedIconSize.width + deletedIconSpacing + date.size.width + 8.5"
)

date_frame_anchor = "                        animation.animator.updateFrame(layer: strongSelf.dateNode.layer, frame: CGRect(origin: CGPoint(x: leftOffset + leftInset + backgroundInsets.left + impressionWidth, y: backgroundInsets.top + 1.0 + offset + verticalInset), size: date.size), completion: nil)"
date_frame_replacement = """                        if let currentDeletedIconNode = currentDeletedIconNode, let deletedIconImage = deletedIconImage {
                            currentDeletedIconNode.image = deletedIconImage
                            let deletedIconFrame = CGRect(
                                origin: CGPoint(
                                    x: leftOffset + leftInset + backgroundInsets.left + impressionWidth,
                                    y: backgroundInsets.top + 1.0 + offset + verticalInset + floor((date.size.height - deletedIconSize.height) / 2.0)
                                ),
                                size: deletedIconSize
                            )
                            if currentDeletedIconNode.supernode == nil {
                                strongSelf.deletedIconNode = currentDeletedIconNode
                                strongSelf.addSubnode(currentDeletedIconNode)
                                currentDeletedIconNode.frame = deletedIconFrame
                            } else {
                                animation.animator.updateFrame(layer: currentDeletedIconNode.layer, frame: deletedIconFrame, completion: nil)
                            }
                        } else if let deletedIconNode = strongSelf.deletedIconNode {
                            deletedIconNode.removeFromSupernode()
                            strongSelf.deletedIconNode = nil
                        }

                        animation.animator.updateFrame(layer: strongSelf.dateNode.layer, frame: CGRect(origin: CGPoint(x: leftOffset + leftInset + backgroundInsets.left + impressionWidth + deletedIconSize.width + deletedIconSpacing, y: backgroundInsets.top + 1.0 + offset + verticalInset), size: date.size), completion: nil)"""
if date_frame_anchor in status_text:
    status_text = status_text.replace(date_frame_anchor, date_frame_replacement, 1)
elif "strongSelf.deletedIconNode = currentDeletedIconNode" not in status_text:
    raise SystemExit("Could not insert the original trash icon beside the timestamp.")

if "var isDeletedRetained: Bool" not in status_text or "self.isDeletedRetained = isDeletedRetained" not in status_text:
    raise SystemExit("Could not wire retained-message state into timestamp arguments.")
status_ui.write_text(status_text, encoding="utf-8")

bubble_text = bubble_ui.read_text(encoding="utf-8")
bubble_anchor = "                    edited: edited && !item.presentationData.isPreview,\n"
bubble_replacement = bubble_anchor + "                    isDeletedRetained: item.message.id.namespace == 1,\n"
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
                        isDeletedRetained: arguments.message.id.namespace == 1,
                        impressionCount:"""
if interactive_anchor in interactive_file_text:
    interactive_file_text = interactive_file_text.replace(interactive_anchor, interactive_replacement, 1)
elif "isDeletedRetained: arguments.message.id.namespace == 1," not in interactive_file_text:
    raise SystemExit("Could not pass retained-message state to interactive file timestamp UI.")
interactive_file_ui.write_text(interactive_file_text, encoding="utf-8")

# Photo/video messages use ChatMessageInteractiveMediaNode instead of the text
# bubble or file node. Pass the same local-namespace flag to their timestamp too.
interactive_media_text = interactive_media_ui.read_text(encoding="utf-8")
media_anchor = """                    edited: dateAndStatus.edited && !presentationData.isPreview,
                    impressionCount:"""
media_replacement = """                    edited: dateAndStatus.edited && !presentationData.isPreview,
                    isDeletedRetained: message.id.namespace == 1,
                    impressionCount:"""
if media_anchor in interactive_media_text:
    interactive_media_text = interactive_media_text.replace(media_anchor, media_replacement, 1)
elif "isDeletedRetained: message.id.namespace == 1," not in interactive_media_text:
    raise SystemExit("Could not pass retained-message state to interactive media timestamp UI.")
interactive_media_ui.write_text(interactive_media_text, encoding="utf-8")

# Fail the build early if each message-rendering path is wired to the deleted flag.
checks = {
    "local namespace clone": "namespace: 1," in capture_text,
    "timestamp status argument": "isDeletedRetained: item.message.id.namespace == 1" in bubble_text,
    "Postbox local insertion": "transaction.addMessages([localCopy], location: .Random)" in capture_text,
    "original AyuGram trash icon asset": "ayuGramDeletedMessageIcon" in status_text and "strongSelf.deletedIconNode = currentDeletedIconNode" in status_text,
    "timestamp uses image, not emoji text": 'updatedDateText = "🗑️ " + updatedDateText' not in status_text,
    "interactive-file timestamp flag": "isDeletedRetained: arguments.message.id.namespace == 1," in interactive_file_text,
    "interactive-media timestamp flag": "isDeletedRetained: message.id.namespace == 1," in interactive_media_text,
    "backward-compatible initializer default": "isDeletedRetained: Bool = false," in status_text,
    "History remains enabled": "AyuGramPostboxHistoryStore.appendDeleted" in capture_text,
    "regular deletion allow-list": "AyuGramCaptureService.captureDeleted(" in delete_text and "mediaCaptures.append(AyuMessageMediaCapture(messageID: message.id.id, resources: resources))" in delete_text,
    "channel deletion allow-list": "AyuGramCaptureService.captureDeleted(" in state_text and "mediaCaptures.append(AyuMessageMediaCapture(messageID: message.id.id, resources: resources))" in state_text,
    "copy-protection guard remains": "!message.isCopyProtected(), !message.containsSecretMedia" in delete_text and "!message.isCopyProtected(), !message.containsSecretMedia" in state_text,
}
failed = [name for name, passed in checks.items() if not passed]
if failed:
    raise SystemExit("Keep-deleted-in-chat integration checks failed: " + ", ".join(failed))

print("AyuGram keep-deleted-in-chat integration applied: Local copies remain enabled, secret/copy-protected messages stay excluded, and the original AyuGram trash-bin icon is wired beside timestamps.")
