---
name: f1s-reverse-learning
description: >-
  F1S learns back from every cwd: harvests each seat's skills, memory lessons, tools and external APIs,
  compares them with what F1S already says, triages candidates on the free pool, and keeps a
  self-updating goal list (coverage + next goals) that a long-running session works through until
  nothing generalizable is left. Use when asked to absorb what the seats know into F1S, to keep a
  long task going with self-set goals, or before writing a new skill/engine (check what a seat already
  built). Curator seat runs it; other seats feed it automatically.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: low
parent_skill: mtm-mto-first
---

# f1s-reverse-learning — 從各 cwd 反向學習（F1S）

operator 2026-10-16：「把他們各自用到的所有技能 經驗 系統 api 整合會到f1s 使得f1s直接建立一個從各cwd反向學習的機制
… 讓這個對話的f1s能夠維持長任務自己找目標自己更新目標去把上面那件事情做到極致」。

## 三層

| 層 | 做什麼 | 指令（全部在 `_skill\engines\f1s-harvest.py`） |
|---|---|---|
| 收 | 每個 cwd（ai_* / jci_* / sdnext_a770，永不掃 fracdigi、quant）：技能（canonical／drifted／seat-local）、`~/.claude/projects/<cwd>/memory` 的經驗、`tools/ scripts/ _line/` 有 docstring 的工具、外部 API（只收變數名與主機名） | `scan` |
| 比 | 每筆對 F1S 單一文件（canonical 技能、hot directive、curator memory）算包含率；≥0.5 = 已在 F1S；其餘依種類、跨座位重複數、未覆蓋程度打分 | `scan` |
| 分 | 免費池（`chat_for("extract")`）逐批判定：generalize（附一句繁中規則）／seat-specific／noise；seat-specific 自動結案 | `triage` |
| 目標 | `_registry/f1s-harvest/goals.json`：coverage＝已結案／總數，`next`＝依分數排序的下一批目標（同服務、同名工具跨座位合併成一個目標） | `goals` |
| API | 全艦外部服務目錄（服務→類別、用到的座位、變數名、程式出處、是否已在免費池） | `catalog`、`api <service>` |

`cycle` 一次跑完收→比→分→API 目錄→重算目標。

## 長任務：自己找目標、自己更新目標

1. `python f1s-harvest.py cycle` → 讀 `goals.json` 的 `next`。
2. 取第一個目標，依種類整合（下表），做完立刻
   `python f1s-harvest.py mark <id> integrated --evidence "<commit 或路徑>"`（整組跨座位一起結案）；
   判定不該進 F1S 的寫 `rejected`／`duplicate`／`seat-specific` 並附理由。
3. 回到 1。每次 `cycle` 會重新收（新的 memory、新工具）、重算分數，目標清單自己往前推。
4. 停的條件：`open_goals` 為 0，或最高分低於 1.0（剩下都是低價值）。停時回報 coverage 前後數字。

| 種類 | 整合方式 |
|---|---|
| memory（generalize） | 規則寫進最相關的 canonical 技能（同主題 ≥3 條才新開技能）；用 triage 的 `rule` 當草稿，對照原 memory 修正，不帶專案名 |
| skill（local／drifted） | 通用的升為 `_skill/fleet-skills/` canonical；drifted 把座位的改進合回 canonical |
| system（generalize） | 與座位無關的工具搬進 `_skill/engines/`（附測試）；只在某類 repo 有用的寫成技能裡的參考路徑 |
| api | 由 `catalog` 一次整合，`cycle` 自動結案；接新外部服務前先 `api <service>` 看誰接過、參考哪段程式 |

出貨照 F1S：`f1s_audit.py` 加對應列（check_text 綁新文字）→ `ship-f1s.py`。

## 週期與上行

- 其他座位不用做事：它們寫的 memory、技能、工具，下次 `cycle` 就會被收到。
- `propose --n 5` 會把最高分目標用 `inbox.py send ai_darkhero <seat> --kind task "F1S: …"` 送進上行路徑，
  由 f1s-evolve 自動整合（T1 不可改、Lean 稽核與測試全綠才出貨）。
- 週期跑 `cycle` 要 HubClock rider，arming 是 operator 的；提案見 `_registry/f1s-harvest/` 的回報。

## 紅線

- 只收名稱與文字，不讀 `.env`／金鑰值；fracdigi、quant 整個不掃；`ai_ut` 的 UT.xlsx 不是文字來源。
- memory 內容含個資或帳戶資料的，整合時只取通用規則，不搬原文。
