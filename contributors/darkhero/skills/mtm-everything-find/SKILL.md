---
name: mtm-everything-find
description: >-
  Machine-wide file locate via bundled voidtools Everything (es.exe) plus a non-file
  surface scan — firewall rules, accounts, services, tasks, Run keys, Appx, npm scopes.
  Everything indexes the FILESYSTEM ONLY, so a vendor/remnant audit must run BOTH halves.
  Use when locating any file on this machine, auditing leftovers of an uninstalled tool,
  or answering "I already scanned with everything.exe, is it really clean?".
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: on-demand
    token_budget: zero
    required: false
    engine: _skill/engines/mtm-everything-find.py
    companion_engine: _skill/engines/mtm-system-remnant.py
    registry: _registry/mtm-audit/
    seat: ai_darkhero
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# mtm-everything-find

> **One-liner:** `python %AI_WORKSPACE%\_skill\engines\mtm-everything-find.py name "<query>" -n 50`
> **殘留稽核（兩半都要跑）:** file 半 = `mtm-everything-find.py` · 非 file 半 = `mtm-system-remnant.py scan <keyword>`

## 何時用（強制）

- 要在整台機器找檔案 / 副檔名 / 目錄 → **先用本技能，禁止 Grep 全盤掃**（TRN token 黑洞）
- 卸載某工具後要證明「清乾淨了」→ 必須跑**兩半**，只跑 Everything 不算證據
- 有人（含 operator）說「我用 everything.exe 掃過了，乾淨」→ 那句話只覆蓋檔案系統，見下方紅線
- 找 hub 內檔案 → 一樣用本技能（`-path C:\ai_workspace` 收窄）

## TR0 開局

```powershell
cd C:\ai_workspace\ai_darkhero
python %AI_WORKSPACE%\_skill\engines\prework.py "everything file find" --agent ai_darkhero
python %AI_WORKSPACE%\_skill\engines\ztm-task-router.py "find file everything"
python %AI_WORKSPACE%\_skill\engines\mtm-everything-find.py doctor
```

`doctor` 綠燈 = `Everything.exe` + `es.exe` + tray process 都在。紅燈就別掃，先修索引。

## 一鍵管線（優選）

```powershell
# file 半：Everything query syntax（ext: / folder: / path: 都吃）
python %AI_WORKSPACE%\_skill\engines\mtm-everything-find.py name "ext:py verify" -n 50
python %AI_WORKSPACE%\_skill\engines\mtm-everything-find.py name "folder:codex_" --write

# 非 file 半：12 個 Everything 看不到的表面
python %AI_WORKSPACE%\_skill\engines\mtm-system-remnant.py scan codex --brief --write --emit-script
python %AI_WORKSPACE%\_skill\engines\mtm-system-remnant.py surfaces
```

輸出全部落 cold JSON 到 `_registry/mtm-audit/`（`everything-find-*.json` / `system-remnant-<kw>-*.json`），
下一輪讀 JSON，**不要重掃**。

## 分步引擎

| Step | Engine | 成功準則 |
|------|--------|----------|
| Health | `mtm-everything-find.py doctor` | `[OK] es.exe` + tray running |
| File locate | `mtm-everything-find.py name "<q>" [-path] [-n] [--write]` | 路徑列表；0 hit 且 doctor 綠 = 真的沒有 |
| File remnant (Claude) | `mtm-everything-find.py claude-audit --brief --write` | `verdict: ABSORBED` |
| Non-file remnant | `mtm-system-remnant.py scan <kw> --brief --write` | `verdict: CLEAN`、`errors: {}` |
| Removal plan | `mtm-system-remnant.py scan <kw> --emit-script` | `.ps1` dry-run 可未提權跑過 |
| grep/edit 內容 | `local-find.py grep\|replace\|edit` | 內容層才用；檔名層一律 Everything |

## 12 個非 file 表面（Everything 結構性看不到）

按安全移除順序：`firewall_rules` → `scheduled_tasks` → `services` → `run_keys` →
`uninstall_entries` → `appx_packages` → `local_users` → `local_groups` → `env_vars` →
`npm_scopes` → `credentials` → `prefetch`。

`surfaces` 子命令印出權威清單，勿在別處另抄一份。

## 紅線

- **「everything 掃過 = 乾淨」是假結論。** Everything 只索引檔案系統；帳號、群組、防火牆規則、
  服務、排程、登錄機碼、Appx、npm scope、憑證管理員一律看不到。實測案例：codex 檔案全清後
  仍留 11 條 enabled 防火牆規則（3 條 block 規則 SDDL 綁已刪除 SID、8 條 Query User 指向已卸載
  的 `openai.codex_*` 路徑）+ 1 個空 `node_modules\@openai`。CITE
  `_registry/mtm-audit/system-remnant-codex-*.json`（2026-08-13）。
- **關鍵字掃不到「相關但不叫該關鍵字」的殘留。** `npm rm -g @vendor/tool` 留下的是以 **scope**
  命名的 `node_modules\@vendor`，不是產品名 → 引擎對「空 scope 目錄」做 keyword-independent 回報。
  防火牆規則同理：block 規則的 `Name` 是 GUID，關鍵字只出現在 `DisplayName`，**兩個欄位都要比對**。
- **`mtm-system-remnant.py` READ-ONLY BY CONTRACT，沒有也不准加 `--apply`。** 帳號 / 群組 /
  防火牆 / 服務變更 = 修改系統與安全設定 = operator-gated：引擎**產生指令**，人類提權執行。
  這條**優先於**「禁止問 operator 機械活」——交付方式是「這是確切指令，需要 admin」，不是問許可。
- **防火牆一定查預設 store（PersistentStore），不要 `-PolicyStore ActiveStore`。** ActiveStore 是
  唯讀合併執行檢視，`Remove-NetFirewallRule` 打它會失敗 → 用 ActiveStore 產的計畫是跑不動的指令。
  ActiveStore 只用來 diff 出 GPO 注入規則，標 `removable=false`。
- **fail closed：探針沒吐 envelope = UNKNOWN，不是 clean。** 每個 PowerShell 探針必須回
  `{probe:'ok', rows:[...]}`；配上 `$ErrorActionPreference='SilentlyContinue'`，壞掉的 cmdlet 會
  exit 0 且靜默，空 stdout 若當成 0 hit 就是假交付。
- **生成的 .ps1：ASCII-only 註解 + UTF-8 BOM（`utf-8-sig`）。** PS 5.1 把無 BOM 的 .ps1 當 ANSI 讀，
  中文/em-dash/`·` 會變 mojibake。且**不准放 `#requires -RunAsAdministrator`**——它會連未提權的
  dry-run 都拒跑，提權檢查要放在 `-Apply` 分支內。
- 檔案清除走 hub 慣例：**move 進 `_delete/<date>-<topic>/` + manifest，禁止 hard delete。**
- 不碰 `_secrets`、fracdigi vault、`~/.claude`（operator-gated）。

## 全艦套用（curator）

```powershell
python %AI_WORKSPACE%\_skill\engines\fleet-skill-sync.py deploy --seats-only
python %AI_WORKSPACE%\_skill\engines\sync-cursor-hooks.py
```

## CITE

`_skill/engines/mtm-everything-find.py` · `_skill/engines/mtm-system-remnant.py` ·
`_skill/engines/local-find.py` · bundled CLI `_skill/engines/bin/es.exe` ·
輸出 `_registry/mtm-audit/` · 姊妹技能 `mtm-claude-remnant-cleanup`
