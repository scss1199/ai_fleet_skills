# 目前申請成功的 API — 本機實況（seat `ai_darkhero`）

> **快照日期 2026-08-18**。這份文件會過期；**不要相信日期，重跑指令**：
>
> ```powershell
> python %AI_WORKSPACE%\_skill\engines\api-matrix-report.py --markdown
> ```
>
> 下面每一列都是那道指令的輸出（讀 `_secrets/`，但結構上不可能印出 key 值：
> 每把 key 在進入任何輸出路徑前已被縮成 `{present: bool, status: str}`）。

## 一句話結論

**現在真的叫得動的：4 個 provider、10 把 key** — `cerebras`(4)、`deepgram`(4)、
`nvidia-nim`(1)、`sambanova`(1)。

## 判決字彙

| verdict | 意思 | 該做什麼 |
|---|---|---|
| `OK` / `PARTIAL` | 有 live key | 用它 |
| `DEAD` | 申請成功過，現在打不通 | 去 console 重 mint |
| `DROPPED` | 試過、要付錢或太慢、已放棄（tombstone）| **不要重申請** |
| `NO-KEY` | 有 recipe，從沒申請 | 可以去申請 |
| `UNTESTED` | 有值沒驗過 | 跑 `key-health.py --dry` |
| `CLI-STORE` | token 在 gh/flyctl/wrangler 裡，我們不持有 | 用 `token-onboard.py list` 問 |
| `VAULT-*` | 值該在 `_secrets/vault.json` | `VAULT-MISSING` = 該補 |

## 全表

| provider | verdict | keys (live/dead/untested) | store | console to mint at |
|---|---|---|---|---|
| `cerebras` | OK | 4/0/0 | api-matrix | <https://cloud.cerebras.ai/platform/org_4k4tmdwkke2pmrredhkm3p6j/apikeys> |
| `deepgram` | OK | 4/0/0 | api-matrix | <https://console.deepgram.com/> |
| `github` | CLI-STORE | 0/0/0 | cli-store | <https://github.com/settings/tokens?type=beta> |
| `nvidia-nim` | OK | 1/0/0 | api-matrix | <https://build.nvidia.com/settings/api-keys> |
| `sambanova` | OK | 1/0/0 | api-matrix | <https://cloud.sambanova.ai/apis> |
| `cf_ai` | NO-KEY | 0/0/0 | api-matrix | <https://dash.cloudflare.com/profile/api-tokens> |
| `claude_code` | VAULT-MISSING | 0/0/0 | vault | 無 dashboard 頁；終端跑 `claude setup-token` |
| `cloudflare` | VAULT-MISSING | 0/0/0 | vault | <https://dash.cloudflare.com/profile/api-tokens> |
| `cursor` | UNTESTED | 0/0/1 | api-matrix | <https://cursor.com/dashboard> |
| `fireworks` | DROPPED | 0/1/0 | api-matrix | <https://app.fireworks.ai/settings/users/api-keys> |
| `fly` | VAULT-MISSING | 0/0/0 | vault | <https://fly.io/user/personal_access_tokens> |
| `gemini` | DEAD | 0/3/0 | api-matrix | <https://aistudio.google.com/api-keys?project=gen-lang-client-0533620858> |
| `groq` | DEAD | 0/5/0 | api-matrix | <https://console.groq.com/keys> |
| `huggingface` | DEAD | 0/1/0 | api-matrix | <https://huggingface.co/settings/tokens> |
| `mistral` | DEAD | 0/1/0 | api-matrix | <https://console.mistral.ai/api-keys> |
| `ollama` | DROPPED | 0/1/0 | api-matrix | （本機，無 console）|
| `openrouter` | DEAD | 0/1/0 | api-matrix | <https://openrouter.ai/settings/keys> |
| `together` | DROPPED | 0/1/0 | api-matrix | <https://api.together.xyz/settings/api-keys> |
| `vercel` | VAULT-MISSING | 0/0/0 | vault | <https://vercel.com/account/settings/tokens> |
| `xai` | DEAD | 0/1/0 | api-matrix | <https://console.x.ai/team/default/api-keys> |

## 持有 key 的帳號（只有識別碼，沒有值）

- **cerebras** — `ai_scar3`=ok, `ai_darkhero`=ok, `ai_altos`=ok, `jci_taipei`=ok
- **deepgram** — `jci_taipei`=ok, `ai_darkhero`=ok, `ai_scar3`=ok, `ai_altos`=ok
- **nvidia-nim** — `scss1199@gmail.com`=ok
- **sambanova** — `acct1`=ok
- **cursor** — untested
- **gemini** — `claude_api_key (proj 165319715959)`=quota0, `claude_api_key (proj 609211293343)`=quota0, `gen-lang-client-0189698048`=quota0
- **groq** — `sssc1219@`, `scss1199@`, `raynor1219@`, `kyloren19911199@`, `heartlink_tw@`（gmail）＝全部 `restricted`
- **huggingface** — harvested=quota0 ／ **mistral** — acct1=quota0 ／ **openrouter** — harvested=quota0
- **xai** — `jci_taipei`=http400
- **fireworks** — acct1=disabled（要付錢）／ **together** — acct1=invalid（要付錢）／ **ollama** — `local-rtx2070`=disabled（RTX2070 熱機 ~5s 可跑，冷載太慢）

Vault（非 LLM）服務區段：`fathom`、`network`、`resend`、`social`

## 驗證強度（誠實標註，不要當成全部都剛驗過）

| 供應商 | 這次是否真的 live probe |
|---|---|
| cerebras(4)、nvidia-nim(1)、sambanova(1) | ✅ 有，2026-08-18 送過真 completion |
| **deepgram(4)** | ❌ **沒有** — `key-health.py` 對 deepgram 標 `skip`，那 4 個 `ok` 是**上次已知**狀態 |
| xai、cursor、ollama | ❌ 同樣 `skip`，狀態為上次已知 |

所以「10 把 live key」裡，**實測過的是 6 把**，deepgram 那 4 把是繼承來的。要補實測得先讓
`key-health.py` 支援 deepgram 的 schema。

**gemini 這次由 `ok` 翻成 `quota0`**（3 把全部），是 2026-08-18 真的 probe 出來的結果。

## 交叉驗證（三條獨立 code path 一致）

| 來源 | 結論 |
|---|---|
| `api-matrix-report.py` | CALLABLE NOW (4): cerebras, deepgram, nvidia-nim, sambanova |
| `key-health.py --dry` | WORKING keys by provider: `{nvidia-nim:1, sambanova:1, cerebras:4, deepgram:4}` |
| `api_registry.py sync` → `_registry/api-availability/ai_darkhero.json` | `callable: true` 的正好是同 4 個 |
| `token-onboard.py list` | github=OK ↔ CLI-STORE；cloudflare/vercel/fly/claude_code=MISSING ↔ VAULT-MISSING |

## 已知洞（`api-matrix-report.py --gaps`）

- **有值但沒 console（3）**：`deepgram`、`ollama`、`xai` — 現在能用，但輪換時沒人知道去哪按。
  修法：在 `_registry/api-console-map.json` 補一列。
- **有 recipe 沒 key（1）**：`cf_ai` — 從沒申請過，想要就去申請。
- 有 console 沒值：0 ／ 有值沒 catalog：0（2026-08-18 `sync --publish` 後補上 deepgram、xai）

## 其他已登入的 console（非 LLM key，但屬於「已申請成功」）

SSOT：`_registry/api-console-map.json` — 49 筆，`kind` 分布為
`app` 14、`service-console` 20、`llm-key-console` 11、`infra-dashboard` 2、`misc` 2。
上面那張全表已涵蓋 11 筆 `llm-key-console`；以下是**其餘 20 筆憑證發放頁 + 2 筆基礎設施台**（全數列出）：

| kind | 服務 | 網址 |
|---|---|---|
| service-console | LINE Developers · Messaging API（channel 2010168048） | <https://developers.line.biz/console/channel/2010168048/messaging-api> |
| service-console | LINE Developers · Console（所有 channel） | <https://developers.line.biz/console/> |
| service-console | 永豐金 · API 管理介面 | <https://www.sinotrade.com.tw/newweb/PythonAPIKey/> |
| service-console | 永豐金 · 簽署中心（OpenAPI） | <https://www.sinotrade.com.tw/newweb/signCenter/F_openApi/> |
| service-console | Meta · 圖形 API 測試工具 | <https://developers.facebook.com/tools/explorer/33551954441086090/> |
| service-console | Meta · My Apps | <https://developers.facebook.com/apps/> |
| service-console | GCP · APIs & Credentials（iron-wave-466411-v5） | <https://console.cloud.google.com/apis/credentials?project=iron-wave-466411-v5> |
| service-console | GCP · OAuth clients（新版 console） | <https://console.cloud.google.com/auth/clients?project=iron-wave-466411-v5> |
| service-console | GCP · Service accounts | <https://console.cloud.google.com/iam-admin/serviceaccounts?project=iron-wave-466411-v5> |
| service-console | GCP · API library（啟用 API） | <https://console.cloud.google.com/apis/library?project=iron-wave-466411-v5> |
| service-console | Firebase · Console | <https://console.firebase.google.com/> |
| service-console | Google Apps Script · 專案 | <https://script.google.com/home> |
| service-console | Google 帳戶 · 第三方連線 | <https://myaccount.google.com/connections> |
| service-console | Cloudflare · API tokens | <https://dash.cloudflare.com/profile/api-tokens> |
| service-console | Vercel · Account tokens | <https://vercel.com/account/settings/tokens> |
| service-console | GitHub · Fine-grained tokens | <https://github.com/settings/personal-access-tokens> |
| service-console | GitHub · Classic tokens | <https://github.com/settings/tokens> |
| service-console | Fly.io · Personal access tokens | <https://fly.io/user/personal_access_tokens> |
| service-console | Resend · API keys | <https://resend.com/api-keys> |
| service-console | Telegram · BotFather | <https://t.me/BotFather> |
| infra-dashboard | Cloudflare · Workers & Pages | <https://dash.cloudflare.com/3024c6a374db2b7e605510f8da5f159e/workers-and-pages> |
| infra-dashboard | Vercel · scss1199s-projects | <https://vercel.com/scss1199s-projects> |

其餘 14 筆 `app` 是已上線的 `*.kyloren.workers.dev` 應用與 `www.fracdigi.com`、
`claude-hr.fly.dev` 等成品網址，不發憑證，故不列在這；`misc` 2 筆為 Wolfram|Alpha 與 SBC Shopping。

## CITE

`_secrets/api-matrix.json`（2026-08-18 實讀，無值外洩）·
`_registry/api-availability/ai_darkhero.json`（2026-08-18 `sync` 重生）·
`_registry/api-capability-manifest.json`（2026-08-18 `sync --publish`）·
`_registry/api-console-map.json` · `_skill/engines/api-matrix-report.py`
