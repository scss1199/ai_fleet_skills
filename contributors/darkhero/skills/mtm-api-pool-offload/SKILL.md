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

Claude Code 本身的額度用完時，`claude-remote-exec` 的 auto lane 另外走本機 OmniRoute 閘道
（`omniroute-gateway.py status` 檢查，127.0.0.1:20128）。

## 規則

- 結果是草稿：數字、日期、費率、法規這類會被拿來做決定的事實，要回到抓下來的原文或官方網址核對，並在回覆附來源網址；核對不了就寫 UNKNOWN。
- 不送出去的東西：金鑰、帳戶與持倉資料、`ai_ut` 的 UT.xlsx 內容（專有資料）、任何 operator 標成私密的檔案。查詢字串可以送，資料本身不送。語音預設用本機（`--engine local`）。
- 輸出留在指令的 JSON 或既有收據，只把摘要與來源網址帶進對話，不新開 .md/.json。
- 免費池回空或全部 provider 失敗：照實回報，再改用本對話的工具，不要編。

## 驗收（2026-10-15 實測）

- `distill-url.py --search "微型臺指期貨 保證金 期交所 2026"`：7 秒，回傳來源網址與摘要；保證金 35,050 元和期交所數字一致。
- `image_ocr.py <截圖>`：正確讀出側欄標題。
- OmniRoute：健康，可路由 1102 個模型，只綁 127.0.0.1。
