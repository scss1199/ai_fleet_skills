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
- 「一次能跑幾個」這類容量問題先量再答，答案是三層最小值：技術（先量傳輸層再猜瓶頸——同一程序對 N 個項目扇出 1→N
  量每輪毫秒，再量 k 個程序同掛的總吞吐與每程序減速）、資源（每項最小保證金／配額／VRAM 加總，對照手上有的）、
  期望值（規則在單一項目上的 t）；多開只是把負期望乘以 N。探測失敗記到項目名＋錯誤碼，「N 筆失敗」不算量測
  （ai_trader 2026-10-29 8d6b8715f：MT5 0.02 ms/檔、224 檔 4.3 ms/輪、8 程序合計 1 萬輪/秒，瓶頸不在 IPC；
  14 檔保證金 916 AUD、50 美金只夠 1 檔；receipt runtime/fx_lane/capacity-20261029T132351.json）。
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
- 「對得上」不是證據：要驗一個模型／規則／分析準不準，題目在看答案前就凍結成「規則→預測」，並與對照組
  （隨機替身、換資料、負對照）比分；事後拿結果回頭找對應（「她說 X，圖上也有 Y」）總是對得上，不算命中。
  只有真資料與夠多替身分得開的題目才列入；回報附 p 值與多重比較警語，知道預期答案的受測者會汙染那組題目；
  「N/N 一致」沒有對照組就不是訊號（ai_ziyaoastro 2026-10-24／29：fate_probe、synastry_null 凍題＋隨機替身，
  合盤所有主題都沒贏過隨機配對 p 0.25–0.82）。

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

## 勝率先拆出場機制再歸因（ai_trader v37 2f2140f3d，F1S 2026-10-31 吸收）

回報任何規則、模型或車道的勝率／敗率前，先把每筆結果按**出場機制**分組（到目標、停損、視窗結束強平／逾時平倉、手動），
各組列筆數與淨額：勝率是出場機制決定的，不是訊號——出場政策可以把勝率買上去，淨值與 t 不會因此轉正。
做法：(1) 勝率單獨不算進步，勝率、強平率、淨值、t 四個數同一行一起報，缺一寫 UNKNOWN；(2) 出場政策的候選跟進場門檻一樣
整族預先登記（走上面「要先登記再算」），挑選只用登記時寫好的準則，**事後看到更好的同族變體不接線**，只在收據裡記；
(3) 留倉到視窗後的政策（resolve／trailing）結算要掃 D+1 的成交列，否則勝率被截斷。
ai_trader FX demo 帳本 52 筆：視窗結束強平 20 筆 0 勝、到目標 29 筆全勝、停損只 3 筆，中位持有 3,513 s＝整個視窗；
v37 96 組出場×門檻 NOT_QUALIFIED（family p 1.0、walk-forward −136.7 USD），預先登記的 P2 樣本外勝率 56.5→78.0%、強平 50→8%、
淨 −45.8→−42.4 USD；同組 flatten 版淨更好（−11.2）但事後才看到，沒接線。收據 runtime/research/fx_exit_policy/report-20261030T234347.json、
settlement-<day>.json 的 by_magic／exits。這是 ④ 的證據規則不是新 gate：PROOF 不加片語比對。

## 大表的極值格子先驗方法（ai_trader 044cb51de，F1S 2026-10-30 吸收）

任何大規模統計表（相關矩陣、排序分數、回測總表、評分面板）交付前，先看極值格子：top／bottom N 若**貼在值域邊界**（±1.000、0、滿分）
或**全等於同一個數**，先懷疑方法再懷疑資料，不准當發現交付。做法：(1) 取 top/bottom 各 N 格，附每格的樣本數（共同日數、交易筆數）；
(2) 邊界值配小樣本＝近似法貼邊的假象，改成精確公式（分母用每對自己的共同觀測，不用全表共同數）再算一次；
(3) 修完的 top 要能用一句話解釋成已知關係（同一資產兩個時鐘、母子公司），解釋不出來的留 UNKNOWN。
ai_trader 第一版 9,330×9,330 相關矩陣用「各自視窗 z 分數除以共同日數」近似，top pairs 全是 ±1.000；改成六個遮罩矩陣乘法的精確 Pearson 後，
top 變成同一資產兩個時鐘（FX ETF vs 匯率隔日 bar）。收據 ai_trader/sinopac-trading-system/runtime/research/correlation_matrix/order19-receipt.json（first_build_defect）。

同一類表的**本徵分解**（相關／共變異矩陣的 eigenportfolio、因子數）另有三條讀法（ai_trader d85dd5bbf，F1S 2026-10-31 吸收）：
(1) 本徵值大不等於可預測，結構只認兩個數——高於 Marchenko–Pastur 上緣（q=N/T）的個數，與**半樣本本徵向量 |cos|**，
跨半樣本不穩（|cos| 低於約 0.5）的方向就算 λ 很大也只列不當因子；(2) 兩兩共同日拼出的矩陣可能不是半正定（最小本徵值為負），
拿本徵向量當權重前先做 PSD 修補或改成共同日宇宙，否則寫 UNKNOWN；(3) 對稱／不對稱先量（||A−Aᵀ||/||A||）再選解法：
對稱用 Lanczos（eigsh），有向 lag 矩陣用 Arnoldi（eigs）。ai_trader 9,330 檔：λ1 占 29.6%、60 個高於 MP 邊界 14.56，
但半樣本 |cos| k=1 0.78、k=3 0.32、k≥5 ≤0.33→只有前 3–4 個方向是結構，最小本徵值 −155。收據 runtime/research/correlation_matrix/eigen/summary.json
（marchenko_pastur.above_upper_edge、stability.cos_first_vs_second）。

## 大掃描相關檢定的三道閘（ai_trader e60f51a5d，F1S 2026-10-30 吸收）

一個饋送、因子或特徵對幾千檔標的掃相關（或對幾百個假設掃分數）後說「X 與 Y 相關」，掃描本身會製造贏家：格子越多，
碰巧越過固定門檻的越多。交付前三道閘全過才算有東西，缺一道寫 UNKNOWN：(1) **solid-n 下限**——頭條極值只能來自共同觀測數
≥ 下限（ai_trader 用 SOLID_N=200）的格子，薄格（n 63–85）的 |corr| 只列不排名；(2) **循環位移 surrogate**——把饋送整列循環位移
（位移 ≥ 最小格數，抽 ≥ 200 次）重算同一個統計量，真值要超過 surrogate 的 p95，並附「碰巧越過門檻的期望格數」與實際越過數並列；
(3) **對已持有資訊的增量 R²**——目標先回歸在矩陣已有的對照列（如 ^VIX，須早於交易時段已知），加入饋送後 R² 多出的量才是貢獻，
相關高但增量 R² 接近 0 ＝ 重複資訊、權重 0。ai_trader 2026-10-30 五個免費情緒饋送掃 9,330 檔：第一版 6/48 過 band，全是薄格或已持有的
VIX 資訊（VVIX→TWII −0.396 但增量 R² 0.009）；加三道閘後碰巧期望 2.4 vs 實際 6、最佳增量 R² 0.03–0.05，結論反轉為零權重。
重用範本：`ai_trader/sinopac-trading-system/scripts/sentiment_feeds.py` 的 `band()`（surrogate）、`incremental()`（增量 R²）、SOLID_N 遮罩；
收據 `runtime/research/sentiment_feeds/report.json`（expected_above_band_by_chance、above_band_solid、incremental_best）。
這是 ④ 的證據規則不是新 gate：PROOF 不加片語比對。

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
