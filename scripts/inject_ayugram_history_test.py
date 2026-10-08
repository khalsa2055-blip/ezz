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
                                    let historyMarker = reportURL.deletingLastPathComponent().appendingPathComponent("AyuGramHistoryPresented.txt")
                                    try? Data("AyuGram History ready".utf8).write(to: historyMarker, options: .atomic)
                                } catch {
                                    print("AyuGram smoke report write failed: \(error)")
                                }
                            }

                            self.mainWindow.present(
                                ayuGramHistoryScreen(context: context.context),
                                on: .root
                            )
                        })
                    }

"""

if "AyuGram History ready" not in s:
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

            // Verify the actual user-facing Saved layout:
            // Documents/Telegram/AyuGram/Saved/Media
            // Documents/Telegram/AyuGram/Saved/Messages
            let savedRoot = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first?
                .appendingPathComponent("Telegram", isDirectory: true)
                .appendingPathComponent("AyuGram", isDirectory: true)
                .appendingPathComponent("Saved", isDirectory: true)
            let mediaRoot = savedRoot?.appendingPathComponent("Media", isDirectory: true)
            let messagesRoot = savedRoot?.appendingPathComponent("Messages", isDirectory: true)

            let tempRoot = FileManager.default.temporaryDirectory.appendingPathComponent("ayugram-standalone-smoke-media", isDirectory: true)
            try? FileManager.default.createDirectory(at: tempRoot, withIntermediateDirectories: true)
            let firstMedia = tempRoot.appendingPathComponent("0.jpg")
            let secondMedia = tempRoot.appendingPathComponent("1.mp4")
            try? Data("ayugram-smoke-photo".utf8).write(to: firstMedia, options: .atomic)
            try? Data("ayugram-smoke-video".utf8).write(to: secondMedia, options: .atomic)

            let message = AyuMessage(
                fakeID: 0,
                userID: accountID,
                dialogID: dialogID,
                peerID: dialogID,
                fromID: accountID,
                messageID: messageID,
                date: Int32(Date().timeIntervalSince1970),
                text: "standalone saved media",
                mediaPath: firstMedia.path,
                mimeType: "image/jpeg",
                isDeleted: true
            )
            let savedMedia = AyuGramMediaArchive.saveToSaved(message: message)
            let firstSaved = mediaRoot?.appendingPathComponent("media-1.jpg")
            let secondSaved = mediaRoot?.appendingPathComponent("media-2.mp4")
            let mediaMetadata = messagesRoot?.appendingPathComponent("message-\\(messageID).json")
            let mediaText = messagesRoot?.appendingPathComponent("message-\\(messageID).txt")
            let mediaOK = savedMedia
                && (firstSaved.map { FileManager.default.fileExists(atPath: $0.path) } ?? false)
                && (secondSaved.map { FileManager.default.fileExists(atPath: $0.path) } ?? false)
                && (mediaMetadata.map { FileManager.default.fileExists(atPath: $0.path) } ?? false)
                && (mediaText.map { FileManager.default.fileExists(atPath: $0.path) } ?? false)
            add("History → Saved media copy", mediaOK, "album media + text + metadata copied to Media/Messages")
            try? FileManager.default.removeItem(at: tempRoot)

            let textMessage = AyuMessage(
                fakeID: 0,
                userID: accountID,
                dialogID: dialogID + 1,
                peerID: dialogID + 1,
                fromID: accountID,
                messageID: messageID + 1,
                date: Int32(Date().timeIntervalSince1970),
                text: "standalone saved text",
                isDeleted: true
            )
            let savedText = AyuGramMediaArchive.saveToSaved(message: textMessage)
            let textFile = messagesRoot?.appendingPathComponent("message-\\(messageID + 1).txt")
            let textMetadata = messagesRoot?.appendingPathComponent("message-\\(messageID + 1).json")
            let textOK = savedText
                && (textFile.map { FileManager.default.fileExists(atPath: $0.path) } ?? false)
                && (textMetadata.map { FileManager.default.fileExists(atPath: $0.path) } ?? false)
            add("History → Saved text copy", textOK, "text + metadata copied to Messages")
            
            if let mediaRoot {
                try? FileManager.default.removeItem(at: mediaRoot.deletingLastPathComponent())
            }
            
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

s = "\n".join(line.rstrip() for line in s.splitlines()) + "\n"

p.write_text(s, encoding="utf-8")
