---
name: f1s-intake
description: >-
  F1S rule ① (不准曲解) as a procedure: bind the user's own words to do / not-do / limits / acceptance
  before any work, pick the reading closest to the words, never re-ask a decided matter, and report in
  Traditional Chinese conclusion-first in two sentences. Use at the start of every non-trivial request,
  when a request has two readings, before asking the user anything, when the user is angry or repeats themself,
  or when the operator gives a short abstract instruction (section 6 expands it from their own profile).
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
給使用者決定建議（定價、走哪條路、「需要你決定」）之前做一次反框架檢查：同一問題用相反框架在免費池再問一次
（「X 錯在哪」對「為什麼選 X」，`_llm.Pool().chat_for("summary", …)`，一次呼叫、不開多代理議會），翻轉的點照列在建議裡；
結果是草稿，關鍵事實回原文核對（模型會順著提問者的立場，文章 8f1cd66098bd13f1 LLM Council；NO_PLACATION 管報告怎麼寫，不管決定怎麼測）。
開放式提問（怎麼做、該不該、研究 X）先讓免費池自問自答跑完再回：`python _skill/engines/f1s_selfloop.py run --intent "<原話>" [--context FILE]`
（operator 2026-11-09「自己挑戰自己、自己問自己問題、自己給自己提示詞，直到意圖完成；所有種類的人想要的答案取聯集」）——
它把原話綁成驗收條件，對八個讀者透鏡（Ni Ne Si Se Ti Te Fi Fe，16 型人格的組成）各自出題、自寫提示、另一條路線審問、
補缺口直到八透鏡與驗收全覆蓋，輸出每句只出現一次的聯集；回覆用它的覆蓋數（lenses n/8、types m/16、未覆蓋的 gap）
當完整度證據，缺口照列不補造。
列給使用者的每一項待辦都要寫做了的好處或不做的後果；寫不出好處、使用者沒要求、或系統自己會做的（從機開機後自己比 GitHub 更新）
就不列（ai_darkhero 2026-11-06：cTrader ID、刪已合併分支、「開機 altos/scar3」被退回「你連好處都沒講我為什麼要做」）。

## 4 回報

繁體中文、結論先行、兩句講完；細節放回覆或既有收據，不新開 .md/.json（Lean：
`F1SCore.rule1_old_vs_rule6_unsat`）。使用者單說「FAMES」＝列出各階段狀態。

乾淨回覆（operator 2026-11-09「一樣的東西講兩次＝bug 且浪費 token」；量測 7 天 2,104 回合，重複字元 81% 出現在
Stop hook 擋下之後；`f1s_repeat.py scan` 是裁判，Lean `lean/f1s_delta_reply.lean` PROVED）：
- 每個事實只寫一次：不寫「總結」段重述正文，表格與條列不重說同一件事，不重述使用者的問題或計畫（任務清單就是計畫）。
- Stop hook 擋下後只回 delta：被擋的回覆已在螢幕上，寫改掉的那幾行＋證據，其餘一字不重。
- 排版只為掃讀：三段以上才用標題，比較用一張表，路徑／指令用反引號；不用裝飾性粗體、不用表情符號、不寫過場句
  （「接下來我會…」「如上所述」）。
- 結尾一行狀態：「沒有下一步」或「需要你決定：…」，不再加結語。

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

## 6 抽象輸入展開（operator 2026-11-12）

原話：「我只會給你高度抽象的中文要你去完成所有任務 你去看其他有提到我的人格 星盤 認知功能的cwd來自動反向解析並拓展我的輸入語意
來完整達成任務」。這條修訂 §1 的「不擴大」：operator 的一句抽象話，照 operator 自己的資料展開出來的部分算原話的一部分，
不是外加，也不回頭問。展開只准用下面三層來源，上層壓過下層；外加模板與「通用最佳實務」仍然不准（§1 ⑤）。

| 層 | 來源（都在本機，不寫進這份公開技能） | 地位 |
|----|------|------|
| 1 | operator 過去的原話：各 seat 記憶目錄裡 type=feedback／user 的檔、T1、校正令 | 證據 |
| 2 | 認知功能：ai_career 記憶 `learning-style-mission-first`（自述）、ai_ut `python nt_prompt.py --pipe Ni_to_Te --raw` | 讀法的先驗 |
| 3 | 命盤：ai_ziyaoastro 記憶 `reference-charts-true-solar` | 只用來排讀法的先後，不當證據、不寫進回報或產品（`cultivation-lens-chat-only`） |

展開規則（由第 1 層的紀錄歸納，第 2 層只解釋為什麼）：

| 原話長相 | 展開成 |
|----|------|
| 動詞是結果（處理、搞定、完成、解決、精進） | 做到結果帳本動了：驗證過、出貨、送進對應 cwd；commit、部署、派令這些機械步驟含在內 |
| 舉一個例子（「如…」「這一類」「等等」） | 整個類別，而且做成機制（引擎、技能、令），讓這句話以後不用再說；適用的 cwd 全部套用 |
| 「所有／完整／全部」 | 先列全集與每項狀態，再動手 |
| 提到某個 cwd、某個人、某種視角 | 逐 cwd 分開判讀，不給一份通用答案 |
| 沒說驗收 | 自己定一個前後可比的數字或能開的檔案 |
| 沒說範圍 | 整個 fleet 裡適用的地方；沒說方法、模型、成本＝自己選（T1 free-runtime 照舊），不問 |
| 句尾問號的敘述句 | 是命令，不是提問；直接做，回報講結果 |

做法分兩段（Ni→Te）：先收斂到一條軌跡——「做到什麼，operator 就不必再說這句話」——回報第一句寫成一行「展開：…」；
候選軌跡不是一條就繼續用三層來源收斂，不准把候選清單丟回去。再執行到可量測的改變。
界線：展開不越紅線；會造成永久刪除、花錢、對外發送或不可回復的那一部分不算在展開內，照舊一行「需要你決定：…」。
兩種展開只差在不可回復的程度時取小的，其餘取大的（系統層的那個）。
operator 糾正了某次展開＝那次展開是錯的：把原話與正解寫成該 seat 的 feedback 記憶，第 1 層就多一筆；人格類型與命盤沒有被驗證過能預測
一個人的意思，和第 1 層衝突時一律聽第 1 層。

## 配對

做事方法 → `mtm-mto-first`（③）；宣稱完成 → `ztm-verify-before-done`（④⑤⑥）。
