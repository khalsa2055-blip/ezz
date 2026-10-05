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
    hook = "\n".join(line.rstrip() for line in hook.splitlines()) + "\n"\n    s = s.replace(anchor, hook, 1)

p.write_text(s, encoding="utf-8")
