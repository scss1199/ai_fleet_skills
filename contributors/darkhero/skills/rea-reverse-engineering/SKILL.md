---
name: rea-reverse-engineering
description: >-
  F1S route for understanding software the operator owns or is authorised to analyse when there is no
  source to read: Electron/JavaScript apps, websites, .NET, Android APKs, Go/WASM artifacts and native
  binaries, through REA (morluto/rea, MIT, npm rea-agents). Runs on demand with npx (no global install,
  no ~/.claude.json change). Use when a task needs to know how a closed tool or app behaves (config format,
  IPC, endpoints, a calculation) and no documentation or source exists. Never for third-party software
  without authorisation, protected tools, or vault material.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: on-demand
    token_budget: low
parent_skill: mtm-mto-first
---

# rea-reverse-engineering — 逆向分析（F1S 按需元件）

來源：operator 2026-10-16 轉來的 kyloren IG reel（REA：把 Hopper／Ghidra／IDA 等逆向工具接給 Claude Code、
Codex、Cursor 的開源 MCP）。原始專案 `github.com/morluto/rea`（MIT），npm 套件 `rea-agents`
（2026-10-16 核對：6.5.0，repository = morluto/rea，maintainer = morluto）。

## 先問三件事（不符就不用）

1. **有沒有原始碼或文件？** 有就讀原始碼，不逆向（先重用，技能 mtm-mto-first）。
2. **授權**：只分析 operator 自己的程式，或 operator 明確授權分析的軟體。REA 官方也只允許這個範圍。
   第三方商業軟體、破解授權、繞過保護一律不做。
3. **紅線**：Logi Options+（受保護輸入裝置）不碰；fracdigi、quant 的檔案不碰；`ai_ut` 的 UT.xlsx 這類
   專有資料不當成分析目標，也不放進輸出。

## 怎麼跑（不安裝、不改全域設定）

```bash
npx -y rea-agents@6.5.0 analyze-javascript-application "<absolute path to app or folder>" --json > <scratchpad>/rea.json
```

- 這條 JavaScript／Electron 路線不需要 Ghidra／Hopper；2026-10-16 在 `_skill/fleet-fly-hooks` 實測：
  rc=0，20 個 JS 檔、196 個 finding，`~/.claude.json` 與 `~/.claude/skills` 都沒有被改。
- 輸出很大（上例 21 MB）：**寫到 scratchpad，不要整份讀進對話**。只讀 `normalized_result.summary`、
  `normalized_result.statistics` 與最上層的 `limitations`，需要細節再用 jq／Python 撈特定節點。
- 其他目標（原生執行檔、APK、網站、HAR）的指令看 `npx -y rea-agents@6.5.0 --help` 與 repo 的 `docs/cli.md`。
  原生分析要 Ghidra／Hopper／IDA；在 Windows 上 Ghidra 仍是實驗性支援。安裝這些工具前先跟 operator 說明。
- **不跑 `rea-agents setup`**：它會寫 `~/.claude.json` 的 `mcpServers.rea` 並把技能裝進 `~/.claude/skills`，
  屬於全域設定變更，要 operator 明確授權（T1 授權）。要常駐 MCP 時才提出。
- 版本固定寫 `@6.5.0`；要升級先 `npm view rea-agents version repository.url` 確認還是官方 repo，
  再改這裡的版本號。名字相近的套件或複製來的 README 不算官方。

## 讀結果的規矩

- REA 是**靜態分析**：它不執行程式，`limitations` 會說明哪些關係只是推測。結論引用 finding 的路徑，
  並寫出 limitations；沒有執行驗證的行為寫 UNKNOWN。
- 加殼的程式和伺服器端邏輯通常拆不出來，這時照實寫 UNKNOWN，不要用猜的補。
- 分析在本機跑，但結果一旦貼進對話就會送到模型供應商：只把需要的片段帶進對話。
