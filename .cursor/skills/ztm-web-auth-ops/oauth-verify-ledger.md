# Fracdigi / PSYNC OAuth · SSO verification ledger

> **Operator grant 2026-07-08:** Agent MAY use Cursor Edge with  
> `scss1199@gmail.com` · `sssc1219@gmail.com` · `raynor1219@gmail.com`  
> for **all 品數位 (fracdigi) OAuth/SSO verification**.  
> Every attempt (pass or fail) MUST append to `ledger.jsonl` and update this SUMMARY.

**HARD RULE:** This class of ops = **Cursor 內建 Edge (browser MCP) only**. Never Chrome.

Machine ledger: `GitHub/new.messages.fracdigi.com/runtime/oauth-verify-ledger.jsonl`  
Writer: `scripts/oauth-verify-log.mjs`

---

## Authorized accounts

| Email | Role | Typical use |
|-------|------|-------------|
| `scss1199@gmail.com` | L3 platform admin / Meta grantor | Meta pool OAuth, Console, prod admin |
| `sssc1219@gmail.com` | L2 clinic | Negative tests (must NOT reach Meta pool OAuth) |
| `raynor1219@gmail.com` | Clinic / AVOID for Meta Console | Product login only; **never** Meta Developers Console automation |

---

## Provider matrix (keep current)

| Provider | Cursor Edge | Chrome | Notes |
|----------|-------------|--------|-------|
| Meta / Facebook OAuth | **USE** | **AVOID** | Chrome = reCAPTCHA ↔ login loop (2026-07-08) |
| Meta Developers Console | **USE** | **AVOID** | business-login/settings + App Domains |
| Google SSO (psync product) | **USE** | AVOID for Meta path | `signInWithRedirect`; same Cursor Edge session |
| Google GCP Console | Cursor Edge first | CDP junction legacy | Prefer Cursor Edge when session already there |
| LINE Developers | Cursor Edge | — | Log each result |

---

## Known outcomes (rolling SUMMARY)

| Date | Provider | Account | Surface | Result | Evidence |
|------|----------|---------|---------|--------|----------|
| 2026-07-08 | Meta Console URI check | scss1199 | App `3843028145947505` redirect_uri meta-pool callback | **VALID** | Meta UI:「此重新導向 URI 對此應用程式有效」 |
| 2026-07-08 | Meta Console URI check | scss1199 | App `33551954441086090` same URI | **VALID** | Cursor Edge check URI |
| 2026-07-08 | Meta App Domains | scss1199 | `3843…` only had insights domain | **INVALID→FIXED** | Added `new.messages…` + vercel.app; Save Changes |
| 2026-07-08 | Meta OAuth (Chrome) | scss1199 | facebook login | **INVALID** | reCAPTCHA infinite loop |
| 2026-07-08 | Meta OAuth (Edge before App Domains) | scss1199 | 「網址已遭封鎖」 | **INVALID** | redirect URI blocked until domains fixed |
| 2026-07-08 | Meta redirect whitelist (probe script) | — | headless probe | **FALSE POSITIVE** | OK while Meta still blocked; prefer Console「檢查 URI」 |
| 2026-07-08 | Google SSO (psync) | scss1199 | Cursor Edge → accounts.google.com password | **BLOCKED / HANDOFF** | Agent **不輸入密碼**；UI 另顯 Too many failed attempts — operator 在 Cursor Edge 完成登入後再連 Meta |
| 2026-07-08 | Google SSO (psync) | scss1199 | Cursor Edge session after operator login | **PASS** | Landed `/admin/access` |
| 2026-07-08 | Meta pool OAuth | scss1199 | Cursor Edge connect → consent → all pages+businesses | **PASS** | `connected=true` grantor=scss1199 pages=8 |

---

## Password / secret boundary

| 可做 | 不可做 |
|------|--------|
| 點「使用 Google 登入」、選帳號磁磚、跟同意畫面 | **輸入 / 讀取 / 印出 /「記住」密碼、passkey、OTP、app secret、token 值** |
| Console 白名單、App Domains、檢查 URI | 把密碼寫進 chat / ledger / memory / Cursor rules |
| 沿用 operator 已登入的 Cursor Edge session | 要求 operator 在 chat 提供密碼 |

Operator 在 Cursor Edge 自己登入後說「已登入」→ agent **只沿用 session** 接 `/admin/access` Meta 池。  
**Agent NEVER stores passwords**（即便 operator 要求「記住」）。Password lives only in the operator’s browser password manager / head — never in agent memory, chat, ledger, or Cursor rules.

---

## How to log (agent)

```powershell
cd C:\ai_workspace\fracdigi\GitHub\new.messages.fracdigi.com
node scripts/oauth-verify-log.mjs --provider=meta --account=scss1199@gmail.com --surface=meta-pool-oauth --result=pass --browser=cursor-edge --note="connected=true"
```

Required fields: `provider`, `account`, `surface`, `result` (`pass`|`fail`|`blocked`|`fixed`), `browser` (`cursor-edge`).

| 2026-07-22 | Instagram phone login loop | scss1199 | Cursor IDE browser → Accounts Center → Add IG (ig_linking) | **BLOCKED / HANDOFF** | AC only had FB; IG not linked; email reset=No account; username prefilled scss1199; agent no password; operator enter IG password in Cursor browser then confirm link |

