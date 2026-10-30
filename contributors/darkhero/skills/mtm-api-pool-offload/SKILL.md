---
name: mtm-api-pool-offload
description: >-
  Free-pool background research for every seat (ai_trader, ai_ut, ai_ziyaoastro, ai_darkhero, jci_taipei...):
  web search + page reading + summarising, speech-to-text and OCR run on the free model pool / local engines
  at zero Claude tokens. Use INSTEAD of WebSearch/WebFetch or reading long pages into context whenever the
  task needs background facts, a page or video summary, a transcript, or text from an image. Results are
  drafts: verify load-bearing facts against the fetched source before relying on them.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: vault-schema-only
    scheduler: on-demand
    token_budget: zero-local
    required: false
    concept_id: POOL_OFFLOAD
    species: POOL
    registry: _registry/skill-taxonomy.json
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# 免費池背景查資料（POOL）

operator 2026-10-15：「把免費模型額度用在做這種背景資料搜尋、語音辨識、光學辨識…靠 f1s 技能化然後全自動綁定」。
免費模型較笨、較慢，所以只交給它「量大、固定、不需頂級推理」的工作；判斷與決策留給本對話的模型。

## 指令（全部 0 Claude token）

| 需求 | 指令 | 跑在哪 |
|---|---|---|
| 網路搜尋＋讀前幾名網頁＋摘要 | `python %AI_WORKSPACE%\_skill\engines\distill-url.py --search "<query>" [--n 5] --json` | DuckDuckGo 免金鑰＋免費池 |
| 單一網址（網頁、YouTube、IG、Threads）摘要 | `python %AI_WORKSPACE%\_skill\engines\distill-url.py <url> --json` | 依網址自動選路 |
| 影片／音檔 → 逐字稿 | `python %AI_WORKSPACE%\_skill\engines\distill-media.py <file> --engine local [--digest]` | 本機 whisper，不外送 |
| 圖片 → 文字（OCR） | `python %AI_WORKSPACE%\ai_darkhero\line\image_ocr.py <image>` | 免費 Gemini |
| 大量文件分類／比對 | `_skill/engines/_llm.py` 的 `Pool().chat(...)` | 免費池（gemini、nvidia-nim…） |

## 免費模型能力標籤（2026-10-16 本機實測；文字任務綁定在 `_llm.Pool.chat_for(task, messages)`）

免費池＝本機 OmniRoute 閘道（127.0.0.1:20128，1106 個模型）＋ hub 金鑰表的免費 provider＋本機引擎。

| 任務標籤 | 先用 | 再用 | 實測 |
|---|---|---|---|
| `summary` 中文摘要 | gemini | OmniRoute `auto/coding` | 2 輪全對、1–3 秒 |
| `extract` 抽取成 JSON | gemini | OmniRoute `ddgw/gpt-5.4-mini` → `auto/coding` | 2 輪全對；`jsonmode=True` 時散文回覆算該路失敗（`not-json`），自動換下一條 |
| `reasoning` 計算／推理 | OmniRoute `auto/reasoning` | gemini | 2 輪全對、2–4 秒 |
| `bulk` 大量分類比對 | gemini | OmniRoute `ddgw/gpt-5.4-mini` → `auto/coding` | ai_trader 2026-10-18 40 則標題純 JSON 標註：ddgw 2.0／1.6／2.3 秒每次可解析、與 gemini 一致 88/120；`auto/coding`、`auto/reasoning` 回散文、閘道 gemini-2.5-flash 截斷、`cfp/zai-org/glm-5.2` 54 秒。ddgw 上游免金鑰、會 503「Failed to acquire VQD token」（curator 同夜實測），所以 `auto/coding` 留作末位（同夜 chat/completions 4.2 秒回合法 JSON） |
| `translate` 翻譯（日→繁中等） | gemini | `auto/reasoning` → `ddgw/gpt-5.4-mini` → `cfp/zai-org/glm-5.2` → nvidia `glm-5.3-flash` | 全部譯對；1.1／1.8／1.8／11–49／42 秒 |
| OCR 圖片讀字 | gemini 視覺（`image_ocr.py`） | — | 合成簽到圖逐字正確、2.7 秒 |
| 語音轉文字 日／中 | 本機 faster-whisper（`distill-media.py --engine local --lang ja`） | Deepgram（`--engine deepgram`，音檔會外送）、`medium` 重試 | 日文合成音逐字正確、30 秒 |
| 網路搜尋 | gemini Google 搜尋（`distill-url.py --search`，每把 key 輪 `GEMINI_MODELS`） | Google News RSS（免 key，連結是 news.google.com 轉址）→ DuckDuckGo／Bing；全失敗看 `websearch.LAST_ERRORS`／stderr（429＝額度用完，不是查無結果） | 期交所官網排第一；2026-10-16 gemini 全 429 時 News RSS 仍回 96/96 |
| embeddings 向量 | OmniRoute `gemini/gemini-embedding-001`（`/v1/embeddings`） | — | 3072 維、0.5 秒 |
| 語音合成 TTS | 本機 edge-tts（技能 `zh-tts-narrate`） | Windows SAPI | — |
| 文生圖／圖生影片 | 本機 SD.Next A770（`sdnext_a770`） | — | OmniRoute flux／aihorde 逾時或排隊 >1000 秒 |

燒錄字幕（fansub）對照語料是意譯：時間對得上、句意常對不上（ai_theater 2026-10-18 實測 117 對只有 12 對經詞彙錨點確認同義），只能當語體／詞彙參考注入 prompt，不能當逐句 ground truth；要用就先經錨點篩選，篩選結果仍是草稿。

不路由（2026-10-16 實測失敗）：OmniRoute 的 `/v1/ocr`、`/v1/web/fetch`、`/v1/audio/speech`、`/v1/audio/transcriptions`、
`/v1/rerank`（缺 provider 憑證或 404）、OmniRoute 視覺（gemini／gemma 90 秒逾時，`zc/*` spawn zcode 失敗）、
`auto/chat`（104 秒）、`auto/fast`、`auto/writing`（不存在）、`zc/*`、`oc/deepseek-v4-flash-free`（暫停 30 分）、
`cerebras/*`（403）、nvidia `deepseek-v4-*`（已下架，410）。
**不是免費、永不路由**：`dva/*`、`cxa/*`、`aug/*`、`no-think/*`（轉接付費訂閱的 Claude／GPT）。
Claude Max 方案附的 Anthropic API 月額度同樣屬付費訂閱、不進免費池：超額即計費，連結 Console 組織與設上限是 operator 的帳務決定。
其他 provider 的金鑰狀態看 `python _skill\engines\key-health.py summary`；新金鑰可用後重跑實測再改標籤。

## 各座位任務 → 免費池對應（2026-10-16 掃描）

| 座位 | 任務 | 對應 |
|---|---|---|
| ai_theater | 日文語音轉文字、日→繁中字幕翻譯、翻譯複核 | 本機 whisper；翻譯照 operator 2026-10-05 釘在本機 :11436，`translate` 路由只當備援 |
| ai_metadata | 日→繁中個人頁翻譯、圖片標籤 OCR、GoPro 語音轉文字 | `translate`、`image_ocr.py`、`distill-media` |
| jci_taipei | 中文會議語音轉文字、手寫簽到 OCR、會議紀錄、講者標註 | `distill-media`（local／deepgram）、`image_ocr.py`、`summary`／`extract` |
| ai_career | 即時面試語音轉文字、英／日→繁中翻譯 | 本機 whisper、`translate` |
| ai_accountancy | 收據 OCR → JSON | gemini（GAS 內）；單一 provider，配額吃緊時沒有備援 |
| ai_eatery、ai_trader | 貼文／文章 → JSON 卡片 | `extract` |
| ai_zonghe、ai_ut、ai_trader | 背景網路搜尋與真假辯證 | `distill-url.py --search`、`reasoning` |
| ai_ziyaoastro | 占卜解讀、照片 → JSON、語音 → 文字 | `summary`／`reasoning`、gemini 視覺、gemini 多模態 |
| ai_demo、sdnext_a770、ai_hgame | 語音合成、文生圖、放大 | 本機（edge-tts、SD.Next、ESRGAN） |

```python
import sys; sys.path.insert(0, r"C:\ai_workspace\_skill\engines"); import _llm
_llm.Pool().chat_for("summary", [{"role": "user", "content": "..."}])
```

Claude Code 本身的額度用完時，`claude-remote-exec` 的 auto lane 另外走本機 OmniRoute 閘道
（`omniroute-gateway.py status` 檢查，127.0.0.1:20128）。

## 三層分工：固定撈零模型、量大免費池、思考才用高智能

operator 2026-10-16（ai_trader）：「只要搜東西，確定哪些網站是有效資料後固定撈資料的方式就用免費的機制；高智能的模型處理需要思考的事情」。
先用第 2、3 層搜一次確定哪些網站真的有資料；之後同一個資料源就降到第 1 層固定撈，不再花任何模型 token。

| 層 | 工作 | 怎麼跑 | ai_trader 實例（2026-10-16 回報） |
|---|---|---|---|
| 1 零模型 | 已確認有效的網站，固定格式定期撈 | 背景腳本（pythonw／CREATE_NO_WINDOW）或既有 rider；新的週期 rider 仍要 operator 授權（T1） | `scripts/news_archive_pull.py` 撈 cnyes 免金鑰新聞檔，13 category-day/分、0 token；收據 `sinopac-trading-system/runtime/data/news_archive/pull_log.jsonl` |
| 2 免費池 | 量大、固定格式的標註／抽取／分類 | `_llm.Pool().chat_for("bulk" 或 "extract", ..., jsonmode=True)`：要 JSON 就開 `jsonmode`，散文回覆才會被當失敗換路 | 40 則標題語氣標註 0.9 秒（gemini 路由），比字典法多標出 25/40；gemini 共享日配額讓 10-16 的標註在 15 天停下、之後每天約 200 秒，10-18 改 ddgw 先行（`news_tone_label.py` `GATEWAY_MODELS`，收據 `news_archive/labels/label_log.jsonl`） |
| 3 高智能 | 推理、判斷、決定 | 本對話模型；本對話額度用完→`claude-remote-exec` auto lane（`_registry/claude-remote-probe.json` 10-16 probe ok） | 期望值題 48 秒答對 |

第 2 層會自己停：每次 `chat_for` 都寫一列到 `_logs/api-usage/<seat>.jsonl`（`api_budget.py`；provider 層級、只有次數，沒有金鑰值），
429 自動停用該 provider 15 分鐘，實測 rpd 用完就在呼叫前跳過。`python _skill\engines\api_budget.py show` 看今日用量，
`learn --write` 從 429 回推每個 provider 的實測上限；背景標註不必等 key-health 的 ok／quota0 才知道額度沒了。

## 並行派發（operator 2026-10-27「時間最貴…叫不同的免費模型去執行足夠簡單的任務」）

一批互不依賴、格式固定的簡單工作（分類、抽取、改寫、逐條判讀）不要一條一條叫，用
`_llm.Pool().fan_out([messages, ...], task="extract", jsonmode=True, workers=4)`：每條工作輪流分給不同的免費供應者同時跑
（各家額度並行消耗），失敗或 jsonmode 回散文的那條自動退回 `chat_for(task)`；回傳順序同輸入。永不派 ollama
（本機模型可能落在 A770，斷電紅線）。結果仍是草稿：關鍵事實回原文核對。

## 規則

- 結果是草稿：數字、日期、費率、法規這類會被拿來做決定的事實，要回到抓下來的原文或官方網址核對，並在回覆附來源網址；核對不了就寫 UNKNOWN。
- 交叉審問法（2026-10-29，kyloren-knowledge 664f9c3d…：前 Google 高管訪談的做法）：研究類提示不問「你覺得怎麼樣」——那只會得到
  順著你的答案；要「把支持與反對的理由全部列出，寫成報告」。第一家模型答完，把答案原樣丟給第二家問「少了什麼、哪裡偏了」，
  再回第一家或第三家潤飾，來回至少兩輪、至少兩家 provider（`fan_out` 的輪流派發天生就跨家；單題用 `chat_for` 連叫兩家）。
  分工不變：海量資訊處理、快速搜資料外包給模型；判斷與決定留在第 3 層，外包思考會變笨。
- 本機模型的量化下限（2026-10-29，kyloren-knowledge 75d3972b…：FP16 每參數 2 bytes、INT8 1、INT4 0.5）：INT4／Q4 已是品質極限，
  幾百億參數硬塞 Q2／Q3 不如換小一號模型跑 Q8。darkhero 現況（2026-10-29 `ollama list`／`show`）：qwen2.5-coder 14B 全為 Q4_K_M、
  deepseek-r1 8B q8_0、qwen3 8B／14B 預設 Q4，沒有 Q2／Q3；新增本機模型時先看 `ollama show` 的 quantization，不收 Q2／Q3。
- 不送出去的東西：金鑰、帳戶與持倉資料、`ai_ut` 的 UT.xlsx 內容（專有資料）、任何 operator 標成私密的檔案。查詢字串可以送，資料本身不送。語音預設用本機（`--engine local`）。
- 輸出留在指令的 JSON 或既有收據，只把摘要與來源網址帶進對話，不新開 .md/.json。
- 免費池回空或全部 provider 失敗：照實回報，再改用本對話的工具，不要編。
- 確認一個資料源時一併記下：免金鑰與否、歷史深度（每類別第一天）、每日量與每頁耗時（決定節奏與總時數），以及
  同題試過失敗的來源和錯誤碼，讓別的座位不再重探；原始 JSON 按日落地並把 sha256 寫進 pull_log。
  指定的免金鑰端點回 503／429 時，退路要留痕不偽裝：把狀態碼＋回應本文原樣記進 pull_log，先讀 429 頁面指到的說明
  （Dukascopy 歷史已搬到 AWS Requester-Pays，要 AWS 憑證付費，不是暫時故障），再換同等免金鑰來源、同一個誠實 UA，
  收據裡寫一段重疊區間交叉比對（共同小時的 tick 數、價格區間、中位點差），兩源對不上的小時標出來，不把替代源寫成原指定源。
  （ai_trader 3013762dd `scripts/pull_fx_ticks.py`；收據 runtime/research/fx_scalp/report-20261029T012045.json
  `data.dukascopy_cross_check`／`data.journal_errors`）ai_trader 2026-10-16：
  cnyes `api.cnyes.com/media/api/v1/newslist/category/<cat>?startAt=&endAt=&limit=30&page=N` 免金鑰、帶日期與個股標籤
  （headline 2012 起、tw_stock／us_stock／wd_stock 2015 起，約 0.7 秒一頁、一個類別一年約 8 分鐘）；同題 GDELT 這台 IP 429、
  FinMind 新聞無 token 400、Google News RSS 只存約 2 天。
- 抓到的「內文」只是裸網址或登入牆殼（IG/Threads 登出頁的選單字）不算讀過：長度門檻擋不住它，要比對頁面是否含
  真內容；讀不到就改用內建瀏覽器 `get_page_text` 或標 UNKNOWN（ai_trader owner-links 2026-10-12：73 項裡 63 項是殼）。
- 免金鑰世界總經第 1 層來源（ai_trader 2026-10-28 實測，`scripts/pull_world_macro.py`，commit ff5159dc6，332 區 2,353 序列）：
  FRED `fredgraph.csv?id=<id>`（一次一個 id，多 id 回 zip）、IMF WEO DataMapper `api/v1/<indicator>`（全經濟體 1980–2031）、
  World Bank api v2（`per_page=20000`，一指標一頁）、OECD SDMX（CLI 用 `DSD_STES@DF_CLI`，`format=csvfilewithlabels`）、
  BIS stats api v2（`WS_CBPOL` 政策利率 36 區含 TW）、ECB data-api（`FM.B.U2.EUR.4F.KR.MRR_FR.LEV`）。stooq 對每個代號都回
  robots 頁，不要路由過去。這些不需金鑰，`f1s-harvest.py api` 查不到是正常的（它只登記金鑰／API host）。
- 長錄音轉文字（ai_trader 2026-10-29，4 小時餐廳錄音，faster-whisper medium int8 CPU）：
  兩支不同手機的錄音先比 PCM（ffmpeg 解成 16k 單聲道逐點相減，max|A−B|=0 就是同源，只轉一支；sha256 不同、大小相同不代表不同聲音）。
  單程序 4 執行緒約 2.7 倍即時，8 程序並行加總卻沒有線性放大（記憶體頻寬飽和；run_log 24 塊、約 14,493 秒音訊花約 2.5 小時，
  每塊 234–6,992 秒不等），所以要快是切 10 分鐘塊、最需要的時段先跑、每塊逐段 flush JSONL，先交出要用的部分；開跑前照
  windows-runtime-pitfalls 先拿 load grant。講者分群：pyannote 管線要 HF token 不能離線，但快取的 `wespeaker-voxceleb-resnet34-LM`
  可離線在 CPU 載入；whisper 段落取 embedding 後 `AgglomerativeClustering` 用 cosine/average 會把約 90% 併成一群，
  `linkage="ward"`、`n_clusters=人數` 才分得開；基頻中位數猜性別（>165 Hz 女）只能標「推定」。
- 錄音／逐字稿要「統整、琢磨」別人說的話（操盤手、顧問、會議發言）時，交付物是逐條主張帳本，不是再一份摘要
  （ai_trader 2026-10-29：34 條，6 條被本 seat 已登記的回測否定、11 條事實成立、3 條純自述）：每條標講者、原句時間戳與
  evidence_status ∈ TESTED_POS／TESTED_NEG／FACT_OK／UNTESTED／SELF_REPORT／UNKNOWN；TESTED 要指向本 seat 的測試或收據，FACT 要指向
  能開的來源，自述與未測的不得寫成事實。講者由內容判定（聲紋分群會把一個人的話標到別人頭上，疑點回原音）；先找講話者自己
  數字互相矛盾的地方。對方推薦的平台／券商／供應商另列來源表，附主管機關態度、評分網站的 pay-to-rate 報導與投訴數，結論寫在
  使用者所在地的法律保護下。之後再有人引用這段錄音，直接用帳本的 evidence_status 回答。
  UNTESTED 而現有資料量得動的主張，用講者自己講的數字當預先登記門檻（supported_if 寫進收據、附 design_sha256）直接量：收據 JSON
  進該 seat 的 runtime/research/，結果回寫帳本該列，不另開 .md（ai_trader 505d100c6 scripts/research_voice_claims.py；
  runtime/research/voice_claims/report-20261030T194453Z.json：c6 台指 1 分鐘振幅中位數落 [70,80]、c23 四組外匯 D1 方向性）。
  同一套做法適用任何進來的語音訊息、會議錄音、聊天建議。先用 seat 手上已有的檔案結清，不為一條主張新拉資料；講者的數字要
  掃 seat 有的每個解析度（1／5／15／30／60 分）再判：判決只看他說的單位，但數字真正吻合的解析度寫進該列（ai_trader order #22：
  70–80 點是 60 分鐘中位數 78，不是 1 分鐘的 9，c6 仍 TESTED_NEG）。結清後仍 UNTESTED 的每列要寫「還缺什麼資料」（帳本 note 欄，
  例「需要 owner 實際標點位的資料集；目前沒有」），下次資料到了直接量，不必重讀錄音。
  回報第一句講使用者的結果帳本（成交／帳戶／實際產出）動了沒，研究判決只是附註（ztm-verify-before-done 「進度」規則）。
- 固定撈腳本的 User-Agent 用誠實的工具名（例 `ai_trader-research-pull/1.0`），不要裝成瀏覽器：只有 OS 字串、沒有其他瀏覽器
  標頭的假瀏覽器 UA 讓 FRED 讀取逾時、IMF 回 403，誠實 UA 兩者都 2 秒內回（ai_trader 2026-10-28，10 組 UA×端點）。

## 2026-10-15 修掉的搜尋問題（ai_ut、ai_trader 實用回報）

- DuckDuckGo 兩個後端都回 0 筆、Bing 回無關頁：改成 gemini 搜尋優先，抓取的關鍵字結果要和查詢有交集才保留。
- Bing `ck/a` 轉址沒解：已解成真網址。
- 「taifex.com」被當成「x.com」擋掉、`<header>` 被當成 `<head>` 刪掉整頁：期交所保證金表現在抓得到。
- `--json` 在 cp950 主控台崩潰、輸出混入記錄行：已改成 UTF-8、記錄改走 stderr，標準輸出只剩 JSON。

## 封鎖源的退路階梯（2026-10-20 實測，查人物／百科類時常遇到）

查百科、人物、事件背景時，單一來源常被擋，別因為第一條失敗就回報查無：

- 百度百科：`distill-url.py` 與 WebFetch 常回 403／安全驗證殼；改用內建瀏覽器 `get_page_text`（本回合這樣讀到嚴弘森、
  中新網 2014 汪正揚專訪全文）。
- 維基百科：直接猜的消歧義標題會 404（本回合 `汪正揚_(黑客)` 404）；改用 MediaWiki API 先搜標題再取全文——
  `https://zh.wikipedia.org/w/api.php?action=query&list=search&srsearch=<詞>&format=json`，再
  `action=query&prop=extracts&explaintext=1&titles=<命中標題>&redirects=1`。搜尋也可能把近音詞排到前面（本回合把
  「汪正揚」配到不相關條目），命中標題要先核對是不是同一個人再採用。
- DuckDuckGo／Gemini 搜尋整批回 0 或 429 時，Bing 網頁搜尋（內建瀏覽器開 `bing.com/search?q=`）通常仍可列出
  官方媒體原文連結；Bing 的 `ck/a` 轉址要用 `li.b_algo h2 a` 的 href 或頁面文字裡的真網址，別把轉址當來源。
- 原始影片的轉述會變形：本回合第二支影片把 METR／OpenAI 事件講成「700 個 AI 聯手攻擊人類系統」，但原文
  （metr.org 2026-08-26）說那是評測內 agent 想規避評分器、對單一平台 Hugging Face 的入侵，且多數規避並未成功。
  影片＝指標不是事實，load-bearing 的主張一律回官方原文核對後才寫（本段強化既有「結果是草稿」規則）。

## 驗收（2026-10-15 實測）

- `distill-url.py --search "微型臺指期貨 保證金 期交所 2026"`：7 秒，回傳來源網址與摘要；保證金 35,050 元和期交所數字一致。
- `image_ocr.py <截圖>`：正確讀出側欄標題。
- OmniRoute：健康，可路由 1102 個模型，只綁 127.0.0.1。
