from pathlib import Path

p = Path("submodules/TelegramUI/Sources/AppDelegate.swift")
s = p.read_text(encoding="utf-8")

if "import AyuGramIOS" not in s:
    s = s.replace("import UIKit\n", "import UIKit\nimport AyuGramIOS\n", 1)
if "import AyuGramSettingsScreen" not in s:
    s = s.replace("import AyuGramIOS\n", "import AyuGramIOS\nimport AyuGramSettingsScreen\n", 1)

anchor = "                    self.mainWindow.viewController = context.rootController\n"
if anchor not in s:
    raise SystemExit("AppDelegate History hook anchor not found")

hook = """                    self.mainWindow.viewController = context.rootController

                    if ProcessInfo.processInfo.arguments.contains("-AyuGramFullSmokeTest") {
                        let accountID = context.context.account.peerId.toInt64()
                        let reportURL = (try? AyuGramRuntime.baseDirectory(accountID: accountID))?
                            .appendingPathComponent("AyuGramSmokeReport.json")

                        let testReportSignal = context.context.account.postbox.transaction { transaction in
                            AyuGramSmokeTest.run(accountID: accountID, transaction: transaction)
                        }
                        
                        _ = (testReportSignal |> deliverOnMainQueue).start(next: { report in
                            if let reportURL {
                                do {
                                    let data = try JSONEncoder().encode(report)
                                    try data.write(to: reportURL, options: .atomic)
                                } catch {
                                    print("AyuGram smoke report write failed: \\(error)")
                                }
                            }
                            
                            self.mainWindow.present(
                                ayuGramHistoryScreen(context: context.context),
                                on: .root
                            )
                        })
                    }

"""

if "-AyuGramFullSmokeTest" not in s:
    hook = "\n".join(line.rstrip() for line in hook.splitlines()) + "\n"
    s = s.replace(anchor, hook, 1)

launch_anchor = "        let launchStartTime = CFAbsoluteTimeGetCurrent()"
standalone_hook = """        if ProcessInfo.processInfo.arguments.contains("-AyuGramFullSmokeTest") {
            var items: [AyuGramSmokeTestItem] = []
            func add(_ name: String, _ passed: Bool, _ details: String) {
                items.append(AyuGramSmokeTestItem(name: name, passed: passed, details: details))
            }

            var ghost = GhostModeSettings()
            ghost.sendWithoutSound = .inGhostMode
            ghost.setGhostModeEnabled(true)
            let policy = GhostModePolicy(settings: ghost)
            add("Ghost Mode policy", !policy.shouldSend(.readMessages) && !policy.shouldSend(.onlineStatus) && ghost.shouldSendWithoutSound, "read/online packet gates")

            let accountID: Int64 = 922337203
            let dialogID: Int64 = 933000001
            let messageID: Int32 = 1700000001
            let temp = FileManager.default.temporaryDirectory.appendingPathComponent("ayugram-standalone-smoke.jpg")
            try? Data("ayugram-smoke-media".utf8).write(to: temp, options: .atomic)
            let message = AyuMessage(fakeID: 0, userID: accountID, dialogID: dialogID, peerID: dialogID, fromID: accountID, messageID: messageID, date: Int32(Date().timeIntervalSince1970), text: "standalone saved media", mediaPath: temp.path, mimeType: "image/jpeg", isDeleted: true)
            let savedMedia = AyuGramMediaArchive.saveToSaved(message: message)
            let root = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first?.appendingPathComponent("AyuGram", isDirectory: true).appendingPathComponent("Saved", isDirectory: true).appendingPathComponent(String(accountID), isDirectory: true).appendingPathComponent(String(dialogID), isDirectory: true).appendingPathComponent(String(messageID), isDirectory: true)
            let mediaFileExists: Bool
            let mediaMetadataExists: Bool
            if let root {
                mediaFileExists = FileManager.default.fileExists(atPath: root.appendingPathComponent("media.jpg").path)
                mediaMetadataExists = FileManager.default.fileExists(atPath: root.appendingPathComponent("metadata.json").path)
            } else {
                mediaFileExists = false
                mediaMetadataExists = false
            }
            let mediaOK = savedMedia && mediaFileExists && mediaMetadataExists
            add("History → Saved media copy", mediaOK, "media + metadata copied")
            try? FileManager.default.removeItem(at: root ?? temp)

            let textMessage = AyuMessage(fakeID: 0, userID: accountID, dialogID: dialogID + 1, peerID: dialogID + 1, fromID: accountID, messageID: messageID + 1, date: Int32(Date().timeIntervalSince1970), text: "standalone saved text", isDeleted: true)
            let savedText = AyuGramMediaArchive.saveToSaved(message: textMessage)
            let textRoot = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first?.appendingPathComponent("AyuGram", isDirectory: true).appendingPathComponent("Saved", isDirectory: true).appendingPathComponent(String(accountID), isDirectory: true).appendingPathComponent(String(dialogID + 1), isDirectory: true).appendingPathComponent(String(messageID + 1), isDirectory: true)
            let textFileExists: Bool
            let textMetadataExists: Bool
            if let textRoot {
                textFileExists = FileManager.default.fileExists(atPath: textRoot.appendingPathComponent("message.txt").path)
                textMetadataExists = FileManager.default.fileExists(atPath: textRoot.appendingPathComponent("metadata.json").path)
            } else {
                textFileExists = false
                textMetadataExists = false
            }
            let textOK = savedText && textFileExists && textMetadataExists
            add("History → Saved text copy", textOK, "text + metadata copied")
            try? FileManager.default.removeItem(at: textRoot ?? FileManager.default.temporaryDirectory)

            let now = Int64(Date().timeIntervalSince1970 * 1000.0)
            let report = AyuGramSmokeTestReport(version: AyuGramRuntime.version, accountID: 0, startedAt: now, finishedAt: now, items: items)
            let reportURL = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first?.appendingPathComponent("AyuGram", isDirectory: true).appendingPathComponent("AyuGramSmokeReport.json")
            if let reportURL {
                do {
                    try FileManager.default.createDirectory(at: reportURL.deletingLastPathComponent(), withIntermediateDirectories: true)
                    try JSONEncoder().encode(report).write(to: reportURL, options: .atomic)
                    print("AyuGram standalone smoke report written: \\(reportURL.path)")
                } catch {
                    print("AyuGram standalone smoke report write failed: \\(error)")
                }
            }
        }
"""
if "AyuGram standalone smoke report written" not in s:
    if launch_anchor not in s:
        raise SystemExit("AppDelegate launch anchor not found")
    s = s.replace(launch_anchor, launch_anchor + "\n" + standalone_hook, 1)
p.write_text(s, encoding="utf-8")

# Add a first-class History button to every group/community info screen.
peer_info = Path("submodules/TelegramUI/Components/PeerInfo/PeerInfoScreen/Sources/PeerInfoProfileItems.swift")
if not peer_info.exists():
    raise SystemExit(f"PeerInfo profile source not found: {peer_info}
")
peer_text = peer_info.read_text(encoding="utf-8")
if "import AyuGramSettingsScreen" not in peer_text:
    peer_text = peer_text.replace("import Foundation\n", "import Foundation\nimport AyuGramSettingsScreen\n", 1)

channel_anchor = "    } else if case let .channel(channel) = data.peer {\n"
channel_button = """    } else if case let .channel(channel) = data.peer {
        if case .group = channel.info {
            items[.peerSettings]!.append(PeerInfoScreenDisclosureItem(id: 98001, text: "AyuGram History", icon: UIImage(systemName: "clock.arrow.circlepath"), action: {
                guard let controller = interaction.getController() else {
                    return
                }
                controller.push(ayuGramHistoryScreen(context: context, dialogID: channel.id.toInt64()))
            }))
        }
"""
if channel_anchor in peer_text and "id: 98001, text: \"AyuGram History\"" not in peer_text:
    peer_text = peer_text.replace(channel_anchor, channel_button, 1)

legacy_anchor = "    } else if case let .legacyGroup(group) = data.peer {\n"
legacy_button = """    } else if case let .legacyGroup(group) = data.peer {
        items[.peerSettings]!.append(PeerInfoScreenDisclosureItem(id: 98002, text: "AyuGram History", icon: UIImage(systemName: "clock.arrow.circlepath"), action: {
            guard let controller = interaction.getController() else {
                return
            }
            controller.push(ayuGramHistoryScreen(context: context, dialogID: group.id.toInt64()))
        })
"""
if legacy_anchor in peer_text and "id: 98002, text: \"AyuGram History\"" not in peer_text:
    peer_text = peer_text.replace(legacy_anchor, legacy_button, 1)

if "id: 98001, text: \"AyuGram History\"" not in peer_text and "id: 98002, text: \"AyuGram History\"" not in peer_text:
    raise SystemExit("Could not add AyuGram History to any group info branch")
peer_info.write_text(peer_text, encoding="utf-8")
