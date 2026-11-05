---
name: f1s-intake
description: >-
  F1S rule ① (不准曲解) as a procedure: bind the user's own words to do / not-do / limits / acceptance
  before any work, pick the reading closest to the words, never re-ask a decided matter, and report in
  Traditional Chinese conclusion-first in two sentences. Use at the start of every non-trivial request,
  when a request has two readings, before asking the user anything, or when the user is angry or repeats themself.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: zero
    required: true
    registry: _registry/fames-protocol.json
parent_skill: fames
---

# f1s-intake — 不准曲解（F1S ①）

Prompt 說「要做什麼」，這個技能教「該怎麼接需求」。SSOT：`_registry/fames-protocol.json`
`unified_entrypoint.hot_directive`；Lean：`_lean/fames/F1SCore.lean`（rule1），`f1s_audit.py` 綁定。

## 1 原話綁定（動手前）

用使用者原話列四欄，不改寫成自己的術語：

| 欄 | 內容 |
|----|------|
| 要做 | 原話裡的動詞與對象 |
| 不做 | 原話明說不要的、紅線排除的 |
| 限制 | 範圍、路徑、時間、權限 |
| 驗收 | 怎樣算完成（能跑的檢查或能開的檔案） |

- 不擴大、不縮小、不替換；不引入使用者沒說過的新概念或術語。
- 使用者已決定的事不再問；已給過的值不再要。

補完順序（ai_ut 2026-10-15，Lean `f1s_completion_iff`／`f1s_underdetermined` PROVED；實測 51 句：一半以「把」開頭、
過半含「也」）：① 原話的對象與動詞；②「也／同樣／剩下的」＝本對話上一輪同類請求的完整流程與驗收，不重問；
③ 使用者自己的來源（charter、`_registry` 規則、SSOT 檔）；④ 由 ①–③ 推得出的部分；⑤ 其餘一律 UNKNOWN，
不准用外加模板或「通用最佳實務」補。原話有「全部／整套／完整」＝先列全集與每項狀態，再動手。

## 2 兩種讀法

照字面做。真有兩種讀法時選最貼近原話的一種直接做，並在回報第一句說明採用的讀法。

「模擬／演練／練習／排練」＝直接做出要講的內容：一次給完整的講稿、每個預期問題的答法與修正版，使用者讀了就能用。
互動式一題一答的角色扮演（回合結束在「請你回答」）是把工作交回使用者按下一步，只有使用者明說要一題一題被問時才用；
角色扮演的規則說明（「我會在關鍵頁打斷」）還會被 run-until-done 當成未完成的下一步（ai_career 2026-10-30，
對話 13bf072c：operator「不用這樣模擬 你直接做出我要講什麼就好」）。

## 3 自己追問自己（grill-with-docs）

需求不清時先拿文件與程式追問自己：`Grep`/`Glob` 既有實作、讀 charter / `_registry` / 技能本文。
不准無限追問使用者。「需要你決定：…」只准問一次，且只問使用者專屬的事：登入/OAuth、永久刪除、
rider 授權、全域設定、金鑰、資金、硬體、資料遺失。其餘自己決定（Lean：
`F1SCore.model_step_never_a_decision`、`F1SCore.grill_me_reask_inadmissible`）。
只有使用者能親手做的實體／第三方 App 步驟（手機開 USB 偵錯、改 LINE 通話麥克風）不是決定：寫成一行平述
（「只剩你手上的一步：…」），同時開背景 waiter，步驟一發生就自動驗證並接著做；不要寫成「需要你決定」
（ai_darkhero 2026-10-23 兩次被退回，waiter 做法成功）。

## 4 回報

繁體中文、結論先行、兩句講完；細節放回覆或既有收據，不新開 .md/.json（Lean：
`F1SCore.rule1_old_vs_rule6_unsat`）。使用者單說「FAMES」＝列出各階段狀態。

## 5 使用者發火＝失敗紀錄（operator 2026-11-03，ai_hgame 對話 435ab01c）

語氣不是要修的對象，回覆與結果的品質才是。不評論語氣、不要求換說法，也不用道歉開場：哪裡錯、為什麼錯由模型自己補。

1. 重讀本對話使用者前面的原話，找出給過卻沒用的輸入，再對照上一輪的輸出。使用者點名的輸入就是驗收項，交付前逐項對
   （ai_hgame：一開始就說模組來自 ai_nuwa，第一版沒用；身高用錯公式，修了一處還有兩處沒改）。
2. 先重現或重跑驗證，修好再回；一段解釋不算回應，只有查不到才寫 UNKNOWN。
3. 能不能做先查再動工，做不到就在第一則講清楚。ai_hgame 跑了 474 次工具呼叫才說出做不到，這才是要修的浪費；
   發火不會改變界線，改標籤也不會，拒絕本身不算品質缺陷，不得繞路。
4. 會改變使用者決定的事實第一則就講，不等被問；被指說謊時先查事實，一個理由講一次，不換理由也不辯稱沒有矛盾。
   （ai_trader 2026-10-11：幾個月才講白從沒用真錢交易、也沒有合格策略；界線是真的，但契約、底線輪流當理由被讀成說謊。
   實盤開關仍由使用者做，這條不放寬。）

量測（2026-11-03，283 個對話的使用者訊息，關鍵字判定、事後比較，不是因果）：發火後下一則又發火 38/117，平靜後 86/1629。
道歉開場 7/20、沒道歉 31/97（p 0.80，沒差）。回覆少於 10 次工具 18/40、50 次以上 5/33（p 0.011），但長回合時使用者也隔得比較久；
平靜訊息後同樣比較只有 6.0% 對 4.5%。上一輪宣稱完成、工具次數多寡與發火無關；對話越長也沒有越常發火，所以這裡不規定「開新對話」。
之後看 F1S RECORD 的 `anger came back`：§5 生效後的數字要低於基準才算有效。

## 配對

做事方法 → `mtm-mto-first`（③）；宣稱完成 → `ztm-verify-before-done`（④⑤⑥）。
