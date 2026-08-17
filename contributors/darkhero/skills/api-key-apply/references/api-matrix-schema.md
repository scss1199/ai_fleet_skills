# `_secrets/api-matrix.json` — 完整 schema 與補齊程序

> 觀測日期 **2026-08-18**，直接讀本機檔案得出（`version: 2`, `updated: 2026-06-07`,
> 14 endpoints / 26 key rows）。此檔 **gitignored**，ACL 只有 SYSTEM + owner。
> 本文件不含任何 key 值，只有結構。

## 0 先確認你要改的是哪一個檔

| 你想記的東西 | 該去的檔 |
|---|---|
| LLM / STT 的 API key 本體 | `_secrets/api-matrix.json` ← **本文件** |
| 一般服務的 env 憑證（LINE / Resend / GCP…） | `_secrets/vault.json` |
| gh / flyctl / wrangler 的 token | **不要記**，留在工具自己的憑證庫 |
| 「哪裡去申請」的網址 | `_registry/api-console-map.json`（可 git） |
| 「怎麼申請＋怎麼驗」的 recipe | `_registry/token-onboard.json`（可 git） |
| 給別的 seat 看的名稱層 | `_registry/api-capability-manifest.json`（可 git） |

寫錯檔 = secret-contract 違規（`federation.never_syncable`）。

## 1 頂層

```jsonc
{
  "version": 2,
  "updated": "2026-06-07",      // 手改時一起改；engine 寫入時自動更新
  "user_agent": "<browser UA>", // 見 §4 Cloudflare
  "note":  "SECRET, gitignored. …",
  "endpoints": { "<provider>": { … } },   // dict，14 個，key = provider 名
  "keys":      [ { … } ]                  // list，26 筆，一個 provider 可多筆
}
```

**不變式（目前 100% 成立，破了就是 bug）**：`keys[].provider` 的集合
== `endpoints` 的 key 集合。有值卻沒 endpoint = 打不出去；有 endpoint 卻沒 key = 假清單。

## 2 `endpoints["<provider>"]`

| 欄位 | 出現率 | 說明 |
|---|---|---|
| `url` | 14/14 **必填** | 完整 endpoint，含路徑（`…/v1/chat/completions`，不是 base URL）|
| `schema` | 14/14 **必填** | 決定 request/response 怎麼組，見下表 |
| `models` | 13/14 | 可用模型陣列 |
| `family` | 13/14 | 模型族，給 router 挑替代品用 |
| `model` | 1/14 | 只有一個模型時的單數寫法（相容用，新增請用 `models`）|
| `_note` | 3/14 | 給人看的注意事項；底線開頭 = 非機器欄位 |

`schema` 目前實際存在的值（**新增前先確認 caller 支援**）：
`openai`、`openai-local`、`openai_vision`、`gemini`、`deepgram`、`cursor-cloud`

`family` 目前的值：
`gpt-oss`、`llama`、`qwen`、`deepseek`、`mistral`、`gemini`、`grok`、`whisper`、`mixed-free`、`null`

範例（cerebras，真實結構）：

```json
"cerebras": {
  "url": "https://api.cerebras.ai/v1/chat/completions",
  "models": ["gpt-oss-120b", "zai-glm-4.7"],
  "schema": "openai",
  "family": "gpt-oss"
}
```

## 3 `keys[]` 一筆

| 欄位 | 出現率 | 說明 |
|---|---|---|
| `provider` | 26/26 **必填** | 必須對得上 `endpoints` 的某個 key |
| `status` | 26/26 **必填** | 見 §5 狀態字彙 |
| `key` | 25/26 | 值本體。**空字串或整個欄位不存在 = tombstone**，見 §6 |
| `note` | 25/26 | 為什麼是這個狀態、什麼時候放棄的 |
| `account` | 15/26 | 人類可讀的帳號標籤（`ai_scar3`、`scss1199@gmail.com`）|
| `account_id` | 10/26 | provider 端的 org/project id — **定址不是認證**，可存 |
| `model` | 11/26 | 這把 key 綁死的模型（帳號層級限制時才寫）|
| `used_by` | 2/26 | 哪個部署在用（如 `["ziyaoastro-fly"]`），輪換前先看這個 |
| `family` | 1/26 | 覆寫 endpoint 的 family |

同一個 provider 多帳號就多筆，不要塞成陣列 —— cerebras 現在 4 筆、groq 5 筆。

## 4 `user_agent`：Cloudflare 的坑

檔案自己的 `note` 寫著：Groq 在 Cloudflare 後面，**必須送瀏覽器 User-Agent**，
否則吃 CF error 1010。

判讀規則：**403 + CF body（`error code: 1010` / `Just a moment`）不是 key 死掉**，
是 urllib 的 TLS/JA3 指紋被擋。把這種情況標成 `invalid` 會讓 operator 去重申請一把
一模一樣會失敗的 key。

## 5 狀態字彙（`api-matrix-report.py` 就是照這個分類）

| 值 | 群 | 意思 |
|---|---|---|
| `ok` | LIVE | 最近一次真的叫得動模型 |
| `quota0` | DEAD | 認證過得去，額度用光 |
| `restricted` | DEAD | 帳號被限制（groq 五個帳號現況）|
| `invalid` | DEAD | 憑證本身不被接受 |
| `http400` / `http404` | DEAD | 端點或 payload 對不上（xai 現況）|
| `disabled` | DEAD | 我們自己關掉的 |
| `untested` | UNTESTED | 有值，沒驗過 |

**「認證得過」≠「叫得動」**：`token-onboard.py list` 打 identity endpoint，額度用光的 key 回 OK；
`key-health.py` 送真的 completion，同一把回 `quota0`。兩者都沒說謊，是兩個問題。
`status` 記錄的是 **後者**。

## 6 Tombstone：申請過、不能用、已放棄

有 `status` 但沒有 key 值的列（現況 3 筆：`ollama`/`together`/`fireworks`），
配上 `note` 說明放棄原因。**這是刻意保留的**：刪掉它，下次盤點就會看到「沒有 key」，
然後派人去重新申請一個已知會失敗的東西。

`api-matrix-report.py` 把這種列判為 `DROPPED`（歸在 "TRIED AND DROPPED"），
不會混進 `NO-KEY` 待辦。

## 7 怎麼補齊一份完整的 matrix

新增一個 provider，四件事一次做完（少做一件就會出現 §1 的不變式破洞）：

1. **加 endpoint** — `endpoints["<provider>"] = {url, schema, models, family}`
2. **收 key** — `python _skill\engines\key-onboard.py <provider> --key-stdin`
   （值走 stdin，不走 argv；engine 會自動建 endpoint 骨架並驗一次）
3. **補 console** — 在 `_registry/api-console-map.json` 加一筆 mint 網址，
   否則將來輪換時沒人知道去哪裡按；`api-matrix-report.py --gaps` 會抓這個洞
4. **發布名稱層** — `python _skill\engines\api_registry.py sync --publish`

驗收指令：

```powershell
python %AI_WORKSPACE%\_skill\engines\api-matrix-report.py
python %AI_WORKSPACE%\_skill\engines\api-matrix-report.py --gaps
```

`--gaps` 的四個洞應該只剩下你**刻意**留的那些。

## 8 手改 JSON 的注意事項

- 這個檔會被 engine 覆寫（`key-onboard.py` / `key-health.py` 都會寫回）。
  手改完馬上跑一次 `api-matrix-report.py` 確認讀得到，不要放著等下次被蓋。
- `key-health.py` **沒有 argparse**：只認 `--dry`，其他參數（含 `--help`）一律忽略
  並且**照樣跑 live probe 並寫檔**。要試它請直接讀 code。
- 編碼 UTF-8；`_note` 這種底線欄位是給人看的，engine 不讀。

## CITE

`_secrets/api-matrix.json`（結構，2026-08-18 實讀）· `_registry/secret-contract.json` ·
`_registry/api-console-map.json` · `_skill/engines/key-onboard.py` ·
`_skill/engines/key-health.py` · `_skill/engines/api-matrix-report.py`
