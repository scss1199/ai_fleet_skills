---
name: api-key-apply
description: >-
  MTE-Skill: end-to-end API key application loop — hunt a free tier, human signs up,
  store the value locally, probe it live, publish names-only to the fleet. Also the
  build/repair procedure for _secrets/api-matrix.json. Species MTE.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: values-local-only
    scheduler: on-demand
    token_budget: low
    required: false
    concept_id: API_KEY_APPLY
    species: MTE
    registry: _registry/skill-taxonomy.json
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# MTE — API Key 申請流程（Apply · Store · Probe · Publish）

> **Species:** `MTE` · SSOT: `_registry/skill-taxonomy.json`
> **紅線:** agent 永遠不註冊帳號、不填憑證、不把 key 印回終端。註冊是 operator 的動作。

## When to use

- 要新增一個免費 tier 供應商（LLM / STT / infra token）
- 既有 key 掛了要換（quota0 / restricted / invalid）
- 要回答「我現在到底有哪些 API 打得通」
- `_secrets/api-matrix.json` 缺欄位、缺 endpoint、狀態過期

## 三層聯邦（違反 = secret-contract 違規）

SSOT: `_registry/secret-contract.json` → `federation.never_syncable` + `NO_BLANKET_COPY`

| 層 | 檔案 | 內容 | git |
|---|---|---|---|
| CATALOG | `_registry/api-capability-manifest.json` | 只有名稱／端點／schema | 同步 |
| SEAT | `_registry/api-availability/<seat>.json` | 只有數量／狀態 | 同步 |
| VALUES | `_secrets/api-matrix.json`、`_secrets/vault.json` | 真正的 key | **永不同步**（gitignored, ACL=SYSTEM+owner）|

所以 `api-matrix.json` **不在 `_registry/`**。任何把值寫進 `_registry/` 的動作都是違規。

## 值存在哪：看 recipe 的 `kind`

`_registry/token-onboard.json` 的 `kind` 決定 store，三者互斥：

| kind | store | 落點 |
|---|---|---|
| `llm` / `stt` | api-matrix | `_secrets/api-matrix.json` → `keys[]` |
| `env` | vault | `_secrets/vault.json` 的 `recipe.vault_path` |
| `cli` | cli-store | 工具自己的憑證庫（gh / flyctl / wrangler）— **我們刻意不持有值** |

判 `kind=cli` 的供應商「沒 key」是誤判：它的 token 在 gh/flyctl 裡面，用 `token-onboard.py list` 問工具本人。

## TR0 workflow（六步，缺一步就會有 orphan）

### 1 先查現況（別重複申請）

```powershell
python %AI_WORKSPACE%\_skill\engines\api-matrix-report.py --todo
```

只列不可用的。`--gaps` 看聯邦破洞（有值沒 console、有值沒 catalog、有 recipe 沒 key）。

### 2 找免費 tier

```powershell
python %AI_WORKSPACE%\_skill\engines\free_api_hunter.py --gaps
```

`--list` 全部候選、`--discover [--dry]` 掃新的。候選只會 **staged**，不會自動進 matrix。

### 3 開申請（**operator 的手**）

```powershell
python %AI_WORKSPACE%\_skill\engines\token-onboard.py request <provider>
```

印出 console URL + 需要的 scope。captcha / 手機驗證 / ToS 就是設計來擋機器人的，**agent 不繞過**。
console URL 的 SSOT 是 `_registry/api-console-map.json`（存 account/project/org id — 那是定址不是認證）。

> in-app Claude browser **沒有 profile**，任何 provider console 都是未登入狀態；要它按 Create key
> 必須 operator 先在那個 pane 登入。Claude-in-Chrome 禁用（前景干擾）。

### 4 收 key（值永不進 chat、永不進 argv）

**路徑 A — inbox（token-onboard 標準流程，operator 貼一行）**

```powershell
python %AI_WORKSPACE%\_skill\engines\token-onboard.py ingest
```

operator 把 `<provider>=<token>` 一行貼進 `_secrets/token-inbox.txt`（gitignored），ingest 後清空。

**路徑 B — LLM key 直接進 matrix**

```powershell
python %AI_WORKSPACE%\_skill\engines\key-onboard.py <provider> --key-stdin
```

`--key-stdin` 不是可選的偏好：command line 會被同 user 的任何 process 讀到
（Windows: `Win32_Process.CommandLine`）而且被 shell 存檔；stdin 兩者皆無。

### 5 驗活（兩個問題不同，別互相取代）

```powershell
python %AI_WORKSPACE%\_skill\engines\token-onboard.py list
python %AI_WORKSPACE%\_skill\engines\key-health.py --dry
```

- `token-onboard.py list` 問的是 **「這組憑證認得出身分嗎」**（打 identity endpoint，如 openrouter 的 `/api/v1/key`，expect 200）
- `key-health.py` 問的是 **「拿它真的叫得動模型嗎」**（真的送一次 completion）
- 額度用光的 key：前者 OK、後者 quota0。**兩個都是真的**，只是問題不同。

> ⚠ `key-health.py` **沒有 argparse**：`main()` 只看 `"--dry" in sys.argv[1:]`。
> 傳 `--help` 或任何別的參數 = 被忽略 = 它會**真的跑一輪 live probe 並改寫 matrix**。
> 要看行為請讀原始碼，不要用 `--help` 試探。

### 6 發布（names only）

```powershell
python %AI_WORKSPACE%\_skill\engines\api_registry.py sync --publish
python %AI_WORKSPACE%\_skill\engines\git_smart.py commit-push .
```

> `sync` **不加** `--publish` 也會寫 seat 檔 `_registry/api-availability/<seat>.json`；
> `--publish` 多做的是更新 fleet catalog。所以「dry run」這個直覺在這裡不成立。

驗收：`api-matrix-report.py` 的 CALLABLE NOW 應該多一個 provider，且 `--gaps` 不新增破洞。

## 禁止

- 把 key 貼進 chat、寫進 commit、放進 `_registry/`、放進 argv
- 幫 operator 註冊帳號、過 captcha、勾 ToS
- 用 `--help` 探測沒有 argparse 的 engine（見上面 key-health 警告）
- 拿 `token-onboard.py list` 的 OK 宣稱「模型可用」

## Reflect（ADUS 三問之一）

> 這串 hunt→signup→onboard→probe→publish 我今天跑第三次了嗎？→ 它已經是 **MTE**，照跑別重想。
> 又一個新 console／新 OAuth 形狀嗎？→ 那是 **VAR**，去 `_registry/token-onboard.json` 加一筆 recipe，不是改 code。

## References

- `references/api-matrix-schema.md` — `_secrets/api-matrix.json` 完整 schema、狀態字彙、怎麼補齊
- `references/current-inventory.md` — 本機目前申請成功的供應商、帳號、console 網址（無值）

## CITE

`_registry/secret-contract.json` · `_registry/token-onboard.json` · `_registry/api-console-map.json` ·
`_registry/api-capability-manifest.json` · `_registry/skill-taxonomy.json` · `token-onboarding-flow`
