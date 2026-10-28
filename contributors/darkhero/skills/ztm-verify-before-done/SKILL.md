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
  被 PROOF write gate 擋下時先判斷是不是誤判（引號內的 `>`、工具必備的 manifest、harness 指定的
  side-session-notes 資料夾），誤判就改 `claude-proof-hook.py` 加測試；不是誤判就把內容寫進回覆。
  同一個檔換副檔名（.txt）或換檔名再寫＝繞過 gate，禁止（ai_theater 2026-10-26／27 x3）。
- 「進度」只算使用者看得到的成果（例：帳本有真實成交、正式網站上線、使用者可用的功能），不是 commit 數、
  文件數、告警或驗證腳本；做不到就直接說卡在哪一步（ai_trader owner 2026-09-21／10-12，f1s-reverse-learning）。
  模擬／回測的判決（NOT_QUALIFIED、乾跑通過）是資訊不是進度，也不能拿來當「沒有下一步」的理由：真路線卡在
  只有使用者能做的步驟（開戶 KYC、入金、登入終端機）時照 f1s-intake §3 寫一行等它發生，其餘自己能做的
  （連線層、demo 真送單、對帳、復原）繼續做到帳本會動為止（ai_trader owner 2026-10-29
  「只要 50 美金才具備操作意義 否則半年都在講幹話」）。
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

只在某一個 checkout 紅、乾淨 worktree 綠的失敗是路徑狀態，不是邏輯：不要當「既有失敗」略過，也不要放寬行為；
把那份狀態（.env、stop 檔、runtime 檔）加進乾淨 worktree 重現，再於 fixture 把每個模組層級路徑都釘到暫存目錄
（patch.multiple / monkeypatch），只釘一半等於沒釘（ai_trader 979d7a5e6）。

## 程式審查（kyloren 15 Skills：Superpowers / Addy Osmani）

非 trivial 的改碼在宣稱完成前，交給沒寫這段程式的 subagent 走技能 `independent-review`
（生成者不得是自己產出的唯一裁判）；審查結果與 diff 一起引用。

## 重犯的錯誤改成機械檢查（kyloren_bot 83845712，Uncle Bob）

同一種錯誤第二次出現時，加一道機械檢查（測試、lint、依賴規則檔、hook 的判斷類別），不要再加一段散文規則；
長規則文件會被模型當成建議。非 trivial 的邏輯可加 mutation test 當驗證的一部分。

## 即時擷取不能無人看管（operator 2026-10-24，jci_taipei 數位第八次會議漏錄 55 分鐘）

錄會議、字幕側錄、直播／串流下載這類**錯過就無法重來**的擷取，「開了」不等於「錄到了」，「會一直跑到結束」更不是完成：

1. **兩個獨立來源**：主線用本機錄音（讀回檔案在長大才算開了），網頁字幕側錄只當第二來源；背景分頁可能被節流、
   掉出會議或字幕停更（2026-10-24 12:03 字幕停了，側錄程式還在跑，記到 0 句）。
2. **登記看門狗再結束回合**：`python C:\ai_workspace\_skill\engines\f1s_live.py capture add --name <名稱> --file <會長大的檔>
   --stale-s 90 --check-every-s 300 --hours <時數>`。閒置時檔案停止長大就立刻叫醒你（CAPTURE STALLED），
   每 check-every 秒叫醒你複查（CAPTURE CHECK）；結束時 `capture done --name <名稱>`。
3. **停滯就救、而且馬上說**：恢復（重開字幕、重新加入、重啟錄音、換來源），讀回又在長大，同時在對話裡告訴 operator。
4. 機械強制：`claude-run-until-done-hook.py` 看到結尾寫「會一直錄／跑到結束、不用做任何事、進行中」卻沒登記看門狗，
   就擋下回合結束並給出上面的指令。

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

## 「X 有效／X 預測 Y」要先登記再算（ai_trader c874f3bc7，F1S 2026-10-24 吸收）

凡是擬合、調參、挑選後說「X 有效」的量化主張（交易規則、模型挑選、文章／排序 A/B、F1S 自家紀錄量測），
引用一個**早於結論收據**的登記 commit，否則寫 UNKNOWN。ai_trader 30 條手工研究線在設計先固定後 24 條 NOT_QUALIFIED，
matrix engine 333 個假設 2026-10-23 全數 SCREEN_FAIL——樣本內通過的都沒撐過。步驟：
(1) 釘資料：原始檔寫一次不覆寫，sha256 manifest＋請求日誌；(2) 登記 commit：設計文字、整個參數族、manifest hash 在第一個數字前 commit，
腳本或其函式庫自上次 commit 後有改、或 manifest 不同，run 就拒跑；前測開始存列後，在測試裡把每個 gate 檔釘成 sha256（CRLF 當 LF 讀，
否則 CRLF 與 LF checkout 同文字不同 hash），共用檔（成本表、I/O helper）一改就讓測試失敗，pin 只能在同一 commit 附理由移動；
改共用 helper 前先列出哪些登記設計的 gate_files() 含它（「已 commit 且未修改」擋不住共用檔悄悄改掉設計 hash：ai_trader v8-owner 前測開跑後被 4874a0087、014ed0474 移過，
範本 `tests/test_forward_design_pins.py` eae82caba）；(3) 整個族做多重檢定校正（Reality Check／Romano-Wolf）、
預先命名的 walk-forward、成本壓力，收斂成一個結論字；(4) 自動迴圈用 append-only 帳本：id = sha(spec + 登記截止日)，篩選只讀截止日前、
前測只讀之後，晉級對所有前測中假設做 Bonferroni，登記過的永不編輯；(5) 累計揭露試了幾個（v29：登記 287／總 1,103）。
重用範本（ai_trader/sinopac-trading-system/scripts）：`pull_twse_intraday5s.py`（寫一次＋日誌）、
`research_cash_intraday_leadlag.py` 的 `registration()`/`run()`（登記守門）、`matrix_engine.py` 的 `register()`/`screen()`/`forward()`/`decide()`（帳本＋前測 Bonferroni）。
這是證據規則不是新 gate：PROOF 不加片語比對，照 ④ 由寫的人引用登記 commit 與收據。

## 參考樣本是量測目標，不是素材（ai_photo 2026-10-27，F1S 2026-10-28 吸收）

使用者點名「理想狀態是 <資料夾／截圖／聲音／文章>」時，那份參考在整個任務裡對之後每一次修改都有效（f1s-intake 原話綁定；
「我講過」＝已給過的參考沒被用）。做法：(1) 先量參考——把「像」拆成可量的數字（開眼比例、眼下明暗差、版面尺寸、語速、句長）；
(2) 只動主體自己的內容往那些數字靠，設上限（單次最多 +25% 之類）並守住自然不變量（成對的部位同一比例，光線、膚色、虹膜不換）；
**把參考的像素／段落貼到主體上不算達到參考**，光線與陰影對不上就會不自然、不對稱；(3) 做完再量一次主體，
結案要附「參考值／改前／改後」三欄與並排對照（左原圖、中舊版、右新版），舊版留 `_prev` 不覆寫；(4) 沒量到參考值的部位要寫明沒動。
量測數值與口味（哪種臉要多亮）留在座位自己的 memory，這裡只留程序。
（ai_photo IMG_0054 大小眼＝整雙眼從 20261010 貼過來；IMG_0063 沒精神＝只銳化沒量眼下 −15～−29 vs 參考 −10～−13；
重做：兩眼開眼比例同到 0.365，commit 990d901，58 測試）

## UI 驗證（token_budget: low）

若 claim 含 UI/portal → 先 **ztm-webapp-verify**（MCP browser snapshot）再 verify-done。

## _escalate → MTD

架構取捨、operator 閘、ambiguous goal → **mtd-judgment-escalation** skill，勿硬套 ZCT。
