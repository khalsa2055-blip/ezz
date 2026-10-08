from pathlib import Path

p = Path("submodules/TelegramUI/Sources/AppDelegate.swift")
s = p.read_text(encoding="utf-8")

if "AyuGramHistoryListSmokeTest" in s:
    raise SystemExit("History list smoke hook already exists")

anchor = '                    if ProcessInfo.processInfo.arguments.contains("-AyuGramFullSmokeTest") {'
if anchor not in s:
    raise SystemExit("Existing AppDelegate smoke hook anchor not found")

hook = r'''                    if ProcessInfo.processInfo.arguments.contains("-AyuGramHistoryListSmokeTest") {
                        let accountID = context.context.account.peerId.toInt64()
                        let dialogID: Int64 = 9_970_000_001
                        let messageID: Int32 = 1_990_000_001
                        let documentsDirectory = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first ?? FileManager.default.temporaryDirectory
                        let reportURL = documentsDirectory.appendingPathComponent("AyuGramHistoryListSmokeReport.json")
                        let markerURL = documentsDirectory.appendingPathComponent("AyuGramHistoryListPresented.txt")

                        func writeHistoryReport(deletedEntryPresent: Bool, historyPresentationRequested: Bool, detail: String) {
                            let report: [String: Any] = [
                                "deleted_history_entry_present": deletedEntryPresent,
                                "history_screen_presentation_requested": historyPresentationRequested,
                                "dialog_id": dialogID,
                                "message_text": "AyuGram deleted-history smoke test",
                                "detail": detail,
                                "passed": deletedEntryPresent && historyPresentationRequested
                            ]
                            do {
                                let data = try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
                                try data.write(to: reportURL, options: .atomic)
                                if historyPresentationRequested {
                                    try Data("AyuGram History screen presentation requested".utf8).write(to: markerURL, options: .atomic)
                                }
                            } catch {
                                print("AyuGram History-only report write failed: \(error)")
                            }
                        }

                        writeHistoryReport(deletedEntryPresent: false, historyPresentationRequested: false, detail: "test started")

                        let deletedEntrySignal = context.context.account.postbox.transaction { transaction -> Bool in
                            let message = AyuMessage(
                                fakeID: 0,
                                userID: accountID,
                                dialogID: dialogID,
                                peerID: dialogID,
                                fromID: accountID,
                                messageID: messageID,
                                date: Int32(Date().timeIntervalSince1970),
                                text: "AyuGram deleted-history smoke test",
                                isDeleted: true
                            )
                            _ = AyuGramPostboxHistoryStore.appendDeleted(transaction: transaction, messages: [message])
                            let rows = AyuGramPostboxHistoryStore.filtered(
                                transaction: transaction,
                                userID: accountID,
                                dialogID: dialogID,
                                kind: .deleted,
                                limit: 50
                            )
                            return rows.contains(where: { $0.text == message.text })
                        }

                        _ = (deletedEntrySignal |> deliverOnMainQueue).start(next: { deletedEntryPresent in
                            self.mainWindow.present(
                                ayuGramHistoryScreen(context: context.context, dialogID: dialogID),
                                on: .root
                            )
                            DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) {
                                writeHistoryReport(
                                    deletedEntryPresent: deletedEntryPresent,
                                    historyPresentationRequested: true,
                                    detail: deletedEntryPresent
                                        ? "deleted row persisted and the matching History screen was presented"
                                        : "History screen was presented, but the deleted test row was not found in Postbox"
                                )
                            }
                        })
                    }

'''
p.write_text(s.replace(anchor, hook + anchor, 1), encoding="utf-8")
