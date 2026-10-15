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
| `extract` 抽取成 JSON | gemini | OmniRoute `auto/coding` | 2 輪全對 |
| `reasoning` 計算／推理 | OmniRoute `auto/reasoning` | gemini | 2 輪全對、2–4 秒 |
| `bulk` 大量分類比對 | gemini | OmniRoute `auto/coding` | 最穩 |
| `translate` 翻譯（日→繁中等） | gemini | `auto/reasoning` → `ddgw/gpt-5.4-mini` → `cfp/zai-org/glm-5.2` → nvidia `glm-5.3-flash` | 全部譯對；1.1／1.8／1.8／11–49／42 秒 |
| OCR 圖片讀字 | gemini 視覺（`image_ocr.py`） | — | 合成簽到圖逐字正確、2.7 秒 |
| 語音轉文字 日／中 | 本機 faster-whisper（`distill-media.py --engine local --lang ja`） | Deepgram（`--engine deepgram`，音檔會外送）、`medium` 重試 | 日文合成音逐字正確、30 秒 |
| 網路搜尋 | gemini Google 搜尋（`distill-url.py --search`） | DuckDuckGo／Bing | 期交所官網排第一 |
| embeddings 向量 | OmniRoute `gemini/gemini-embedding-001`（`/v1/embeddings`） | — | 3072 維、0.5 秒 |
| 語音合成 TTS | 本機 edge-tts（技能 `zh-tts-narrate`） | Windows SAPI | — |
| 文生圖／圖生影片 | 本機 SD.Next A770（`sdnext_a770`） | — | OmniRoute flux／aihorde 逾時或排隊 >1000 秒 |

不路由（2026-10-16 實測失敗）：OmniRoute 的 `/v1/ocr`、`/v1/web/fetch`、`/v1/audio/speech`、`/v1/audio/transcriptions`、
`/v1/rerank`（缺 provider 憑證或 404）、OmniRoute 視覺（gemini／gemma 90 秒逾時，`zc/*` spawn zcode 失敗）、
`auto/chat`（104 秒）、`auto/fast`、`auto/writing`（不存在）、`zc/*`、`oc/deepseek-v4-flash-free`（暫停 30 分）、
`cerebras/*`（403）、nvidia `deepseek-v4-*`（已下架，410）。
**不是免費、永不路由**：`dva/*`、`cxa/*`、`aug/*`、`no-think/*`（轉接付費訂閱的 Claude／GPT）。
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

## 規則

- 結果是草稿：數字、日期、費率、法規這類會被拿來做決定的事實，要回到抓下來的原文或官方網址核對，並在回覆附來源網址；核對不了就寫 UNKNOWN。
- 不送出去的東西：金鑰、帳戶與持倉資料、`ai_ut` 的 UT.xlsx 內容（專有資料）、任何 operator 標成私密的檔案。查詢字串可以送，資料本身不送。語音預設用本機（`--engine local`）。
- 輸出留在指令的 JSON 或既有收據，只把摘要與來源網址帶進對話，不新開 .md/.json。
- 免費池回空或全部 provider 失敗：照實回報，再改用本對話的工具，不要編。

## 2026-10-15 修掉的搜尋問題（ai_ut、ai_trader 實用回報）

- DuckDuckGo 兩個後端都回 0 筆、Bing 回無關頁：改成 gemini 搜尋優先，抓取的關鍵字結果要和查詢有交集才保留。
- Bing `ck/a` 轉址沒解：已解成真網址。
- 「taifex.com」被當成「x.com」擋掉、`<header>` 被當成 `<head>` 刪掉整頁：期交所保證金表現在抓得到。
- `--json` 在 cp950 主控台崩潰、輸出混入記錄行：已改成 UTF-8、記錄改走 stderr，標準輸出只剩 JSON。

## 驗收（2026-10-15 實測）

- `distill-url.py --search "微型臺指期貨 保證金 期交所 2026"`：7 秒，回傳來源網址與摘要；保證金 35,050 元和期交所數字一致。
- `image_ocr.py <截圖>`：正確讀出側欄標題。
- OmniRoute：健康，可路由 1102 個模型，只綁 127.0.0.1。
