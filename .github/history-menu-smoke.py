from pathlib import Path

p = Path("submodules/TelegramUI/Sources/AppDelegate.swift")
s = p.read_text(encoding="utf-8")

if "AyuGramHistoryMenuSmokeTest" in s:
    raise SystemExit("History menu smoke hook already exists")

anchor = "                    self.mainWindow.viewController = context.rootController\n"
if anchor not in s:
    raise SystemExit("AppDelegate History menu hook anchor not found")

hook = r'''                    self.mainWindow.viewController = context.rootController

                    if ProcessInfo.processInfo.arguments.contains("-AyuGramHistoryMenuSmokeTest") {
                        let accountID = context.context.account.peerId.toInt64()
                        let baseDirectory = try? AyuGramRuntime.baseDirectory(accountID: accountID)
                        let reportURL = baseDirectory?.appendingPathComponent("AyuGramHistoryMenuSmokeReport.json")
                        let markerURL = baseDirectory?.appendingPathComponent("AyuGramHistoryMoreMenuPresented.txt")

                        func writeResult(deletedHistoryOK: Bool, menuVisible: Bool) {
                            let report: [String: Any] = [
                                "deleted_history_entry_present": deletedHistoryOK,
                                "more_menu_ayu_gram_history_visible": menuVisible,
                                "passed": deletedHistoryOK && menuVisible
                            ]
                            if let reportURL, let data = try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]) {
                                try? data.write(to: reportURL, options: .atomic)
                            }
                            if menuVisible {
                                try? Data("AyuGram History button visible in actual More/Settings list".utf8).write(to: markerURL ?? reportURL ?? URL(fileURLWithPath: "/tmp/AyuGramHistoryMoreMenuPresented.txt"), options: .atomic)
                            }
                        }

                        let deletedDialogID: Int64 = 9_970_000_001
                        let deletedMessageID: Int32 = 1_990_000_001

                        let deletionSignal = context.context.account.postbox.transaction { transaction -> Bool in
                            let message = AyuMessage(
                                fakeID: 0,
                                userID: accountID,
                                dialogID: deletedDialogID,
                                peerID: deletedDialogID,
                                fromID: accountID,
                                messageID: deletedMessageID,
                                date: Int32(Date().timeIntervalSince1970),
                                text: "AyuGram deleted-history smoke test",
                                isDeleted: true
                            )
                            _ = AyuGramPostboxHistoryStore.appendDeleted(transaction: transaction, messages: [message])
                            let rows = AyuGramPostboxHistoryStore.filtered(
                                transaction: transaction,
                                userID: accountID,
                                dialogID: deletedDialogID,
                                kind: .deleted,
                                limit: 50
                            )
                            return rows.contains(where: { $0.text == message.text })
                        }

                        _ = (deletionSignal |> deliverOnMainQueue).start(next: { deletedHistoryOK in
                            let accountPeerSignal = context.context.engine.data.get(
                                TelegramEngine.EngineData.Item.Peer.Peer(id: context.context.account.peerId)
                            )
                            _ = (accountPeerSignal |> deliverOnMainQueue).start(next: { accountPeer in
                                guard let accountPeer,
                                      let settingsController = context.context.sharedContext.makePeerInfoController(
                                        context: context.context,
                                        updatedPresentationData: nil,
                                        peer: accountPeer,
                                        mode: .generic,
                                        avatarInitiallyExpanded: false,
                                        fromChat: false,
                                        requestsContext: nil
                                      ) else {
                                    writeResult(deletedHistoryOK: deletedHistoryOK, menuVisible: false)
                                    return
                                }

                                self.mainWindow.present(settingsController, on: .root)

                                func findScrollViews(_ view: UIView, into result: inout [UIScrollView]) {
                                    if let scroll = view as? UIScrollView {
                                        result.append(scroll)
                                    }
                                    for subview in view.subviews {
                                        findScrollViews(subview, into: &result)
                                    }
                                }

                                func hasHistoryAccessibilityElement(_ view: UIView) -> Bool {
                                    if view.accessibilityLabel == "AyuGram History" {
                                        return true
                                    }
                                    if let elements = view.accessibilityElements {
                                        for element in elements {
                                            if let object = element as? NSObject,
                                               let label = object.accessibilityLabel,
                                               label == "AyuGram History" {
                                                return true
                                            }
                                        }
                                    }
                                    for subview in view.subviews {
                                        if hasHistoryAccessibilityElement(subview) {
                                            return true
                                        }
                                    }
                                    return false
                                }

                                func attemptMenuCheck(_ attempt: Int) {
                                    guard attempt <= 24 else {
                                        writeResult(deletedHistoryOK: deletedHistoryOK, menuVisible: false)
                                        return
                                    }

                                    var scrollViews: [UIScrollView] = []
                                    findScrollViews(settingsController.view, into: &scrollViews)
                                    for scroll in scrollViews {
                                        let maxY = max(-scroll.adjustedContentInset.top, scroll.contentSize.height - scroll.bounds.height + scroll.adjustedContentInset.bottom)
                                        scroll.setContentOffset(CGPoint(x: scroll.contentOffset.x, y: maxY), animated: false)
                                    }

                                    settingsController.view.layoutIfNeeded()

                                    if hasHistoryAccessibilityElement(settingsController.view) {
                                        writeResult(deletedHistoryOK: deletedHistoryOK, menuVisible: true)
                                        return
                                    }

                                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                                        attemptMenuCheck(attempt + 1)
                                    }
                                }

                                DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
                                    attemptMenuCheck(1)
                                }
                            })
                        })
                    }

'''

s = s.replace(anchor, hook, 1)
p.write_text(s, encoding="utf-8")
