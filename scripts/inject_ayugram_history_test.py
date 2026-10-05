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

                    if ProcessInfo.processInfo.arguments.contains("-AyuGramHistoryTest") {
                        let accountID = context.context.account.peerId.toInt64()
                        let now = Int32(Date().timeIntervalSince1970)
                        _ = (context.context.account.postbox.transaction { transaction in
                            let deleted = AyuMessage(
                                fakeID: 0,
                                userID: accountID,
                                dialogID: 0,
                                peerID: 0,
                                fromID: accountID,
                                messageID: 100001,
                                date: now - 60,
                                text: "AyuGram History test — deleted message",
                                isDeleted: true
                            )
                            let edited = AyuMessage(
                                fakeID: 0,
                                userID: accountID,
                                dialogID: 0,
                                peerID: 0,
                                fromID: accountID,
                                messageID: 100002,
                                date: now - 30,
                                editDate: now - 5,
                                text: "AyuGram History test — edited message",
                                isDeleted: false
                            )
                            _ = AyuGramPostboxHistoryStore.appendDeleted(transaction: transaction, messages: [deleted])
                            _ = AyuGramPostboxHistoryStore.appendEdited(transaction: transaction, messages: [edited])
                        }.startStandalone())

                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                            self.mainWindow.present(
                                ayuGramHistoryScreen(context: context.context),
                                on: .root
                            )
                        }
                    }

"""
if "-AyuGramHistoryTest" not in s:
    s = s.replace(anchor, hook, 1)

p.write_text(s, encoding="utf-8")
