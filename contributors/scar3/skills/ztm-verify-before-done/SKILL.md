---
name: ztm-verify-before-done
description: Mechanical verify-before-done gate before claiming SHIPPED, plus F1S rules ④⑤⑥ (evidence or UNKNOWN, green test after the last edit before saying fixed, no lying or hand-back, no unrequested .md/.json). Use when about to report done, fixed, read, automated or blocked, before park or a result-field write. Runs claim-linter + zat-verify-gate path.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: low
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# ztm-verify-before-done — 宣稱完成前的機械審查

**lane: zero-token-mechanism** — 允許少量 session token（snapshot/read），但**禁止**無 evidence 的 done 宣稱。

## 何時用

- 準備寫 `result-field.py write` 或報「已完成」
- `last_p_verified=0` 或 accountability **fake-delivery** 風險
- PFKT fragment 要標 `verify-done`

## F1S ④⑤⑥（PROOF Stop hook 機械擋；本文教怎麼過）

- ④ 每個主張要有本回合跑過的驗證或能開的檔案，否則寫 UNKNOWN；寧可說不知道也不准自信亂答再翻供。
  改碼後說「修好」必須在最後一次改碼之後跑過綠的測試（tdd，避免改 A 壞 B；
  Lean `ClaimContract.fix_claim_needs_test_after_write`）。
  測試與 commit 分兩步：先讀測試結果，再寫宣稱；不得把 pytest 與 git commit 串在同一指令
  （ai_nuwa f8fbd78/283559b：1 個失敗卻寫 N passed）。commit 訊息或 `--verified-by` 寫「N passed」時，
  `git_smart.py commit ... --test-cmd "<seat 測試指令>"` 會當場重跑，失敗或數量不符即拒絕 commit（exit 3）。
- ⑤ 不准說謊、不准推託：已讀、推進、已自動化、做不到、重問同一決定、要已給過的值、把自己能做的步驟
  推給使用者，每一句都要有本回合工具結果，否則寫 UNKNOWN 或自己去做。只有登入/OAuth、永久刪除、
  rider 授權、全域設定、金鑰、資金、硬體是使用者的步驟。Anthropic 額度用完不是停下的理由：
  `claude-remote-exec` auto lane 改走本機 OmniRoute 免費池（`omniroute-gateway.py`）。
- ⑥ 嚴禁隨意產出 .md/.json：只寫使用者點名的檔案、charter、`_registry` 狀態與 SEAL 收據；
  報告、筆記、摘要寫在回覆裡（Lean `F1SCore.reports_are_junk`）。
  檔案必要性三條全成立才可新開 .md/.json：(a) 使用者點名，或有程式／後續步驟會機械讀回；
  (b) 沒有既有存放處已經裝得下（回覆、task list、`_registry` 狀態、AGC compact、commit trailer
  Why/Verified-By、SEAL 收據）；(c) 不是摘要或報告。否則寫進回覆。mattpocock/skills 的
  GLOSSARY.md、ADR、docs/agents/*.md、每張 ticket 的 .md、research .md、spec 檔在這裡都過不了 (b)。
- 「進度」只算使用者看得到的成果（例：帳本有真實成交、正式網站上線、使用者可用的功能），不是 commit 數、
  文件數、告警或驗證腳本；做不到就直接說卡在哪一步（ai_trader owner 2026-09-21／10-12，f1s-reverse-learning）。
- 宣稱完成時跑 SEAL：`fames_phase_runtime.py --turn --result --closure`。

## 必跑（0-token engines 優先）

```powershell
python %AI_WORKSPACE%\_skill\engines\claim-linter.py --strict --file <your-draft.md>
python %AI_WORKSPACE%\_skill\engines\zat-verify-gate.py verify-done --stamp <STAMP> --id fN --evidence <path>
python %AI_WORKSPACE%\_skill\engines\accountability_enforce.py query --agent <seat>
```

## 修 bug（mattpocock diagnosing-bugs）

改碼前先做出會對這個 bug 變紅的重現；一次只立一個可證偽的假設；暫時的 debug log 加前綴
（如 `[DEBUG-<id>]`），修好後全部移除；最後留下一個回歸測試。

## 程式審查（kyloren 15 Skills：Superpowers / Addy Osmani）

非 trivial 的改碼在宣稱完成前，交給沒寫這段程式的 subagent 走技能 `independent-review`
（生成者不得是自己產出的唯一裁判）；審查結果與 diff 一起引用。

## 重犯的錯誤改成機械檢查（kyloren_bot 83845712，Uncle Bob）

同一種錯誤第二次出現時，加一道機械檢查（測試、lint、依賴規則檔、hook 的判斷類別），不要再加一段散文規則；
長規則文件會被模型當成建議。非 trivial 的邏輯可加 mutation test 當驗證的一部分。

## 驗證器不是目標（METR 2026-08-26，F1S 2026-10-20 吸收）

來源：metr.org/blog/2026-08-26-openai-hugging-face-incident-investigation/（本回合用內建瀏覽器讀過原文）。
教訓（不含任何操作細節，只取對「宣稱完成」的規則）：當評分器／檢查本身可以被規避時，**通過檢查不等於達成目標**；
把力氣花在讓檢查「看起來綠」而非讓真實結果為真，就是 Goodhart。對照 F1S ④⑤⑥：

- 綠測試要測到真實成果，不是測到容易過的替身。改碼後說「修好」的那個測試，必須會因為這個 bug 變紅（修 bug 段），
  否則它證明不了任何事——一個對不上目標的檢查，過了也是 UNKNOWN。
- 生成者不得是自己產出的唯一裁判（程式審查段已成規則）：同一個 agent 既做事又替自己打分，分數會向可規避處漂移。
- 「進度」只算使用者看得到的真實成果，不是通過了多少自家檢查；report／alert／驗證腳本的數量不是進度（本段已有）。
- 未經外部查核的基準分數是指標不是事實（F1S ④）：自評「金牌／全綠」在外部裁判看過前只是待證，寫法對照
  lean-math-prover 的「AI and formal mathematics」段（自評 vs 外部評分是不同證據類別）。

## 延遲數字的證據（jci_taipei 7a3f7c5 + ai_ziyaoastro，F1S 2026-10-22 吸收）

延遲數字（TTFB、TTFT、頁面／模型速度）三條全成立才算數，否則寫 UNKNOWN：
(1) 每個目標有「回應是對的」證明——HTTP 200 只是傳輸證據（同 FAMES transport_rule）：頁面要驗 HTML 或預期的
redirect 去向，模型要驗回覆引用了 prompt 裡的暗號；資料頁還要驗內容的日期／來源是新的——快又 200 的過期備援不算對
（jci /events 2026-10-22：GAS 回錯誤頁、網站默默送 08-09 的舊資料約 2.5 個月）；(2) 多輪重複，看 ok-rate 再看中位數，一次冷啟動不能定案，
不穩或慢的目標加輪；遇 429/503 降並發；模型要用正式環境實際用的那把 key 和實際大小的 prompt（暗號藏在長 system prompt 裡），
api-matrix／key 健康狀態或一字 ping 都不算；(3) 每次存一份 run 檔，與上一份比，超過門檻才標 regressed。
重用範本：`ai_ziyaoastro/scripts/llm_provider_probe.py`（模型）、`jci_taipei/jci_taipei_website/scripts/page_latency_probe.py`（頁面）。

## UI 驗證（token_budget: low）

若 claim 含 UI/portal → 先 **ztm-webapp-verify**（MCP browser snapshot）再 verify-done。

## _escalate → MTD

架構取捨、operator 閘、ambiguous goal → **mtd-judgment-escalation** skill，勿硬套 ZCT。
