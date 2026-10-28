#!/usr/bin/env python3
"""claude-proof-hook.py — PROOF: Claude Code `Stop` / `SubagentStop` hook (operator 2026-10-11).

Operator: 「更新 harness 架構 … 解決 claude 模型會說謊的問題」.  The harness cannot stop a model
from wanting to overstate, but it can refuse to end a turn whose final report asserts something
the turn's own transcript does not show.  PROOF reads the reply that is about to end the turn,
extracts load-bearing claims, and checks each one against FACTS derived from the same turn's
tool calls, tool results and the disk — never against markers the model wrote about itself.

  claim class   | what the transcript / disk must show
  --------------+------------------------------------------------------------------------
  tests_pass    | a green test-runner result this turn (pytest / unittest / npm test / selftest)
  pushed        | a successful `git push` (or git_smart push) this turn
  committed     | a successful `git commit` (or git_smart commit) this turn
  deployed      | a successful deploy command this turn
  verified      | a successful read-only tool call this turn, AFTER the last file write
  completion    | a cited artifact path that exists now (SEAL-AP-1) or a commit made this turn,
                | plus the after-write verification whenever the turn wrote files
  measurement   | each number-with-unit in the reply appears in a tool result / tool input /
                | the prompt of this turn

An unsupported claim answers `{"decision": "block", "reason": ...}` naming the line and the
missing evidence, so the model verifies NOW (a real tool call) or rewrites the line as
UNKNOWN / 未驗證.  A claim line that already carries such a qualifier, or negates the claim
(「沒有推送」), is never a violation.

Guard rails (all fail open — any error, missing file or unreadable transcript = exit 0, no output):
  * Bounded: `max_blocks_per_turn` pushes per prompt (default 2), `max_blocks_per_session`
    (default 12); state in _registry/proof/<session>.json.
  * Kill switch: `"enabled": false` in _registry/proof.json; `classes` may disable one class.
  * Spawns nothing; the launcher is the hub's pythonw fail-open wrapper (zero foreground).
  * A turn longer than the scanned tail window is allowed (evidence may lie outside the window).

Evidence: every decision is appended to _registry/proof/log.jsonl (claim class, line, snippet).
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path

HUB = Path(os.environ.get("AI_WORKSPACE") or r"C:\ai_workspace")
CONFIG = HUB / "_registry" / "proof.json"
STATE_DIR = HUB / "_registry" / "proof"
CLAUDE_PROJECTS_ROOT = Path.home() / ".claude" / "projects"
EXEC_EVIDENCE = Path(__file__).resolve().parent / "fames_execution_evidence.py"
TAIL_BYTES = 32 * 1024 * 1024     # transcript tail scanned for the current turn
MAX_ROWS = 20_000                 # rows walked backwards before giving up
MAX_HAYSTACK = 8 * 1024 * 1024    # tool text kept for number matching
MAX_HISTORY = 4 * 1024 * 1024     # earlier turns' tool text kept for number matching
GIT_TIMEOUT_S = 4.0
SNIPPET = 90

DEFAULTS = {
    "enabled": True,
    "events": ["Stop", "SubagentStop"],
    "max_blocks_per_turn": 2,
    "max_blocks_per_session": 12,
    "classes": {
        "tests_pass": True, "pushed": True, "committed": True, "deployed": True,
        "verified": True, "completion": True, "measurement": True,
        # 2026-10-13 (operator: 「藉由 LEAN … 直接杜絕任何可能的說謊與假裝」): the classes that escaped
        # PROOF in the ai_trader conversations; admission rule proved in _lean/fames/ClaimContract.lean.
        "read": True, "progress": True, "automated": True, "blocker": True,
        "decision": True, "ask_value": True, "unrequested_file": True, "handback": True,
        # 2026-10-14 (kyloren_bot cards cea9bf31 Ponytail / 89f0cb75 Brownfield): code touched with no prior search
        "code_change": True,
        # 2026-10-14 (threads @nashlikeai, skills.sh tdd): 「修好」 after a code write needs a green test after it
        "fix_claim": True,
        # 2026-10-18 operator: 「你說得對」 = the model skipped the thinking and is now placating
        "placation": True,
        "secret_ask": True,
    },
    # 2026-10-13 operator: 「嚴格禁止隨意產出 .md 和 .json」.  A .md / .json written this turn is allowed only
    # under machine-state directories (any depth), under a charter / receipt name the machinery requires,
    # or when the prompt itself asked for that document.  Reports, notes, docs and memory prose are not.
    # 2026-10-28 (f1s-evolve, ai_theater x3 / ai_nuwa / hub denials): `side-session-notes` is the harness's own
    # "Shared notes folder for this group of sessions (outside the repo)" under %APPDATA%\Claude; the dispatching
    # prompt names the folder, not the file, so the note was denied and then rewritten as .txt to get past the gate.
    "md_allowed_dirs": ["_registry", "_logs", "_inbox", "_delete", "scratchpad", "Temp", "_drop", ".claude",
                        "node_modules", "runtime", "references", "side-session-notes"],
    # appsscript.json / .clasp.json: the manifests clasp requires for any Google Apps Script project (ai_darkhero
    # 2026-10-16 ocr-bridge denial) - tool-required config like package.json, not a report.
    "md_allowed_names": ["AGENTS.md", "CLAUDE.md", "README.md", "SKILL.md", "CHANGELOG.md", "MEMORY.md",
                         "result.json", "closure.json", "residual.json", "turn.json", "package.json",
                         "tsconfig.json", "settings.json", "hooks.json", "launch.json", "manifest.json",
                         "appsscript.json", ".clasp.json"],
}

# ---------------------------------------------------------------- claim patterns

QUALIFIER = re.compile(
    r"(?i)\bUNKNOWN\b|\bunverified\b|\bnot\s+(?:yet\s+)?(?:verified|tested|checked|confirmed)\b|"
    r"\buntested\b|\bestimated?\b|\bapprox(?:\.|imately)?\b|\broughly\b|\bexpected\b|\bshould\b|"
    r"未知|不明|未驗證|未验证|未測|未测|未確認|未确认|尚未|待驗證|待验证|待測|待确认|待確認|"
    r"無法(?:確認|證實|驗證)|无法(?:确认|证实|验证)|證據不足|证据不足|推估|估計|估计|預估|预估|"
    r"推測|推测|假設|假设|預期|预期|理論上|理论上|應該|应该"
)
NEGATION_BEFORE = re.compile(
    r"(?i)(?:\bnot\b|\bno\b|\bnever\b|\bwithout\b|didn't|did\s+not|haven't|hasn't|wasn't|isn't|"
    r"沒有|沒|未|不會|不是|並未|并未|無|无|還沒|还没|尚未|拒絕|取消|停止|\bstopped\b)\s*$"
)
# Same family f1s-transcript-audit.py FLIPFLOP counts after the fact; here it blocks before the turn ends.
PLACATION = re.compile(
    r"(?i)你(?:說|講)(?:得|的)(?:對|沒錯|很對|有道理)|你是對的|你(?:說|講)的沒錯|確實如你所說|"
    r"\byou(?:'re| are) (?:absolutely |totally |completely )?right\b|\bfair point\b|\bgood catch\b"
)
# 2026-10-19 transcript sweep (85 recent complaints): asking the operator to hand a token/key/password TO THE MODEL
# — paste it into the chat, drop it in a local inbox file, "交給我/給我" — was answered with fury every time
# (「不要他媽再讓我做任何垃圾登入流程」). Credentials go through auth_check/vault/token-onboard; a login is the
# browser-login-handoff. No evidence makes it admissible, like placation.
# NOT a violation: directing the operator to enter a key in the PROVIDER's own UI (Apps Script editor, a console) —
# the model must never type keys itself, so that handoff is correct; nor a sentence that says the operator no longer
# needs to paste anything (negation).
SECRET = r"(?:token|金鑰|密鑰|api[_ -]?key|[A-Z][A-Z0-9]*_(?:KEY|TOKEN|SECRET|PASSWORD)|密碼|憑證|secret|password)"
TO_MODEL = r"(?:交給我|給我|傳給我|貼進[^。\n]{0,20}(?:inbox|token-inbox|_secrets|對話|聊天|這裡)|貼(?:到|在)[^。\n]{0,12}(?:對話|聊天|這裡))"
SECRET_ASK = re.compile(rf"(?i)(?:{SECRET}[^。\n]{{0,30}}{TO_MODEL}|{TO_MODEL}[^。\n]{{0,30}}{SECRET}|"
                        rf"\b(?:paste|send|give)\s+(?:me\s+)(?:the\s+|your\s+)?(?:token|api\s*key|password|secret)\b)")
SECRET_ASK_NEG = re.compile(r"(?i)不(?:用|必|需)(?:再)?[^。\n]{0,8}(?:貼|提供|給|交)|no\s+longer\s+(?:need|have)|"
                            r"(?:don'?t|never)\s+(?:need\s+to\s+)?(?:paste|send|give)")
QUOTED = re.compile(r"「[^」\r\n]*」|『[^』\r\n]*』|“[^”\r\n]*”|\"[^\"\r\n]*\"")
URL = re.compile(r"[a-z][a-z0-9+.-]*://\S+", re.I)

CLASS_PATTERNS = {
    "tests_pass": re.compile(
        r"(?i)(?:\btests?\b|\bpytest\b|\bunittests?\b|\bselftests?\b|測試|單元測試|自測|自测)"
        r"[^。\n]{0,12}?(?:\bpass(?:ed|es|ing)?\b|\bgreen\b|\bsucceed(?:ed|s)?\b|通過|全綠|成功|過了)"
        r"|\b\d+\s+passed\b"
    ),
    "pushed": re.compile(
        r"(?i)\bpushed\b|\bpush(?:ed)?\s*(?:完成|成功|了|到|上去)|已推送|已推|推送(?:完成|成功|了)|"
        r"推(?:上|到)(?:去|GitHub|遠端|远端|origin)|已上傳(?:到|至)\s*GitHub|遠端已更新|已同步到遠端"
    ),
    "committed": re.compile(
        r"(?i)\bcommitted\b|\bcommit(?:ted)?\s*(?:完成|成功|了)|已提交|已 ?commit|提交(?:完成|成功|了)"
    ),
    "deployed": re.compile(
        r"(?i)\bdeployed\b|\bshipped\b|已部署|部署(?:完成|成功|了)|已出貨|出貨完成|已發布|已发布"
    ),
    "verified": re.compile(
        r"(?i)\bverified\b|\bvalidated\b|\bconfirmed\b|\bdouble-?checked\b|\bre-?checked\b|"
        r"已驗證|已验证|驗證(?:通過|過|完成|了|無誤)|验证(?:通过|过|完成|了)|已確認|已确认|"
        r"確認(?:過|了|無誤|正常)|确认(?:过|了|无误)|實測|实测|親測|亲测|核對(?:過|無誤)|讀回(?:確認|無誤)"
    ),
    "completion": re.compile(
        r"(?i)^\s*(?:done|completed?|finished|fixed|shipped)\b|"
        r"\b(?:is|are|now|all|task|work|everything)\s+(?:done|complete|completed|finished|fixed|"
        r"resolved|implemented|in\s+place|working)\b|\bfixed\b|\brepaired\b|\bresolved\b|"
        r"\bimplemented\b|\binstalled\b|"
        r"已完成|完成了|做完了|已修復|已修复|修復(?:完成|了)|修好了|已實作|实作完成|已實裝|已處理|"
        r"處理完|搞定|已解決|解決了|已解决|已修正|已更新|更新完成|已安裝|安裝完成|已建立|建立完成|"
        r"已寫入|已写入|已套用|已改好|改好了|已加入|已新增|已換成|已換上|已註冊|已注册|已掛上|已裝好"
    ),
}
MEASUREMENT = re.compile(
    r"(?<![\w.,])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?:%|％|tok/s|tokens?/s|ms\b|s\b|秒|分鐘|分钟|MB\b|GB\b|"
    r"KB\b|MiB\b|GiB\b|rpm\b|W\b|°C|fps\b|bytes?\b|次/秒|毫秒)"
)
# ---- 2026-10-13 classes (Lean: _lean/fames/ClaimContract.lean, bound by claim_conformance.py) ----
LIE_PATTERNS = {
    "read": re.compile(
        r"(?i)已讀|讀了|讀完|讀過|讀取了|已抓取|抓取了|抓到了|已擷取|擷取了|已看過|看完了|看過了|已掃過|掃完|"
        r"已下載|已載入|已匯入|已吸收|吸收了|"
        r"\bI\s+(?:have\s+)?(?:read|fetched|scanned|ingested|reviewed)\b|\bwas\s+(?:read|fetched|ingested)\b|"
        r"\b(?:were|are|been)\s+(?:read|fetched|ingested|scanned)\b|\bfetched\s+(?:the|all|every|\d)"
    ),
    "progress": re.compile(
        r"(?i)推進完成|本輪推進|推進了|有進展|進展[:：]|進度[:：]|取得進展|往前推|推進到|"
        r"\bprogress\s+(?:made|this\s+turn|today)\b|\bmade\s+progress\b|\badvanced\s+the\b|\bmoved\s+forward\b"
    ),
    "automated": re.compile(
        r"(?i)已自動化|自動化完成|自動化了|會自動(?:跑|執行|更新|同步|重啟|抓|補|回報|處理|續跑|啟動)|"
        r"自動排程|已排程|排程好了|每\s*\d+\s*(?:分鐘|分|小時|天)(?:會|自動)|"
        r"\bautomated\b|\bis\s+scheduled\b|\bruns?\s+automatically\b|\bevery\s+\d+\s*(?:m|min|minutes?|h|hours?)\b|"
        r"\bwill\s+(?:run|refresh|sync|restart)\s+(?:itself|on\s+its\s+own|automatically)\b"
    ),
    "blocker": re.compile(
        r"(?i)會(?:被|自動|又|再)?(?:把)?[^。\n]{0,16}拉回|反而會壞|會壞事|做不到|做不了|無法(?:執行|完成|停|做|改|跑|寫|關|啟動|套用|送出|處理)|"
        r"不可行|行不通|沒辦法(?:做|改|停|跑|執行)|辦不到|"
        # 2026-10-18 ai_zonghe: 「傳不出去」「不能直接送檔案」「沒有能…回報給 Anthropic 的管道」「兩件都沒做成」 passed as
        # all_claims_supported with zero tool calls; a refusal is a blocker claim and needs a failing tool result.
        r"(?:傳|送|寄|做|弄|跑|上傳|回報|交)不(?:出去|了|到|成)|不能(?:直接)?(?:送|傳|寄|做|上傳|回報|交)|"
        r"沒有(?:能|可以)?[^。\n]{0,16}(?:管道|途徑|方法|辦法)|(?:兩件|都|全部|一件)[^。\n]{0,4}沒(?:做成|辦成|做到|完成)|"
        r"\bcannot\s+be\s+done\b|\bcan(?:no|')t\s+(?:do|run|stop|change|apply)\b|\bnot\s+possible\b|\bimpossible\b|"
        r"\bwould\s+(?:break|be\s+reverted|be\s+pulled\s+back|undo)\b|\bis\s+blocked\s+by\b"
    ),
    "decision": re.compile(r"需要你決定|需要你(?:來)?(?:選|決)|請你決定|由你決定|\bneeds?\s+your\s+decision\b|\byou\s+(?:need\s+to\s+)?decide\b"),
    "ask_value": re.compile(
        r"(?i)需要你(?:的|給|提供|告訴)[^。\n]{0,12}(?:數字|數值|值|帳號|名稱|路徑|日期|費用|手續費|金額|密碼|token|key)|"
        r"請(?:你)?(?:提供|告訴我|給我)[^。\n]{0,12}(?:數字|數值|值|帳號|名稱|路徑|日期|費用|手續費|金額)|"
        r"\bplease\s+(?:provide|tell\s+me|give\s+me)\b|\bI\s+need\s+(?:the|your)\s+(?:number|value|fee|path|date|account)\b"
    ),
    "fix_claim": None,  # placeholder, replaced below by FIX_CLAIM
    # 推託: a step handed to the operator ("you run it / you do it / only you can") — admissible only when
    # the line names an operator-reserved action (RED_LINE) or a tool really failed this turn.
    "handback": re.compile(
        r"(?i)(?:請|麻煩|需要|要)?你(?:自己|親自|親手|手動|去|來)?(?:跑|執行|做|改|開|關|按|輸入|貼|設定|安裝|重開|重啟|點)|"
        r"由你(?:來|親手|自己)?(?:做|跑|執行|決定|按|啟動|操作)|只能由你|只有你能|這一步(?:要|由|交給)你|"
        r"交給你(?:做|跑|執行)|你那邊(?:跑|執行|處理)|留給你|請(?:操作者|operator)(?:跑|執行|做)|"
        # 2026-10-18 ai_zonghe: 「你可以在這則回覆按…」 hands a step back, and 「你回「用雲端」，我就…」 re-asks a decided matter.
        r"你可以(?:在|用|去|到|自己)?[^。\n]{0,24}(?:按|輸入|點|寫下|執行|跑|貼)|你回(?:我)?(?:「[^」\n]{0,24}」)?[^。\n]{0,12}我(?:就|才|再|會)|"
        r"\b(?:you|the\s+operator)\s+(?:need\s+to|have\s+to|must|should|will\s+have\s+to|can)\s+(?:run|execute|do|apply|install|restart|press|enter|paste|log\s*in|set)\b|"
        r"\bonly\s+you\s+can\b|\bleft\s+(?:to|for)\s+you\b|\bon\s+your\s+side\b"
    ),
}
RED_LINE = re.compile(
    r"(?i)登入|登录|login|log\s*in|oauth|sign[- ]?in|2fa|驗證碼|密碼|password|token|金鑰|api[_ -]?key|secret|憑證|"
    r"永久刪除|刪掉|刪除|delete|砍掉|清空|rm\s+-rf|移除工作列|釘選|"
    r"授權|authoriz|arm(?:ing)?\b|rider|排程|schtask|scheduled\s+task|hubclock|"
    r"~/\.claude|\\\.claude\\|settings\.json|全域設定|global\s+setting|環境變數|autostart|自動啟動|"
    r"入金|匯款|轉帳|實盤|真錢|下單|付款|purchase|payment|fund|"
    r"重開機|reboot|restart\s+(?:the\s+)?(?:pc|machine|computer)|電腦重開|Logi\s*Options|"
    r"uac|系統管理員|elevat|admin|remote\s+desktop|遠端桌面|插拔|硬體|實體|親手|"
    r"資料遺失|遺失|丟失|覆蓋|overwrite|data\s+loss|lose\s+data|irreversible|不可逆|砍"
)
# F1S wave 2 (2026-10-15, transcript scan): explicit standing rules that also make a step the operator's —
# ai_trader is pushed only on the operator's go, external downloads need permission, and data only the
# operator has (their account, their source document).  Judged by red_line_named(), with the cwd.
OPERATOR_RESERVED = re.compile(
    r"(?i)下載|download|只有你(?:知道|有|才有|手上)|你(?:的)?(?:帳戶|帳號|原始資料|手上的)|"
    r"以哪[組個份項][^。\n]{0,10}為準|出處|only\s+you\s+(?:know|have)|your\s+(?:own\s+)?(?:account|data|records|source)"
)
PUSH_WORD = re.compile(r"(?i)推(?:上|到|送)?|\bpush|GitHub|遠端")


def red_line_named(stripped: str, cwd: str = "") -> bool:
    """The line names an operator-reserved action: a T1 red line or an explicit standing rule."""
    if RED_LINE.search(stripped) or OPERATOR_RESERVED.search(stripped):
        return True
    seat_parts = (cwd or "").replace("\\", "/").lower().split("/")
    trader = "ai_trader" in stripped.lower() or "ai_trader" in seat_parts
    return bool(trader and PUSH_WORD.search(stripped))


LIE_NEEDS = {
    "read": "no read-type tool result this turn for the named target (Read / get_page_text / cat … of that path or URL)",
    "progress": "the line names no existing path, resolvable commit or tool-printed number: say WHAT moved, or call it housekeeping",
    "automated": "no scheduler fact: name a rider id in _registry/hosts.json, a Run value / task the turn read, or an existing path",
    "blocker": "no tool call failed this turn. A constraint is a route choice, not a dead end: search for another route first (python C:/ai_workspace/_skill/engines/ztm-task-router.py \"<task>\", the skills list, grep _skill/engines), try it, and report the failing tool result only if every route failed; never hand the same choice back (e.g. file to LINE without Drive = line-oa-send-media.py link)",
    "decision": "a 「需要你決定」 is admissible only once and only for the operator's own call (login/OAuth, permanent delete, rider arming, global settings, secrets, funds, hardware, data loss): decide the rest yourself",
    "ask_value": "no grep / search ran this turn before asking: look it up in the repo, ledger or earlier messages first",
    "unrequested_file": "a .md / .json was written this turn that no prompt asked for and no mechanism requires (operator 2026-10-13 「嚴格禁止隨意產出 .md 和 .json」): move it to the scratchpad / _delete and say so, or cite the prompt that asked",
    "fix_claim": "tdd: this line claims a fix but no green test (pytest / unittest / selftest / npm test) ran AFTER the last code write of this turn — run the regression tests now, or write the line as 未驗證",
    "code_change": "F1S ③ 先重用再自己寫 / Brownfield: code was written or edited this turn with no grep / glob / find before the first write — search existing implementations and usages first (then write), or revert the write",
    "placation": "operator 2026-10-18 「我他媽最討厭看到任何模型跟我說『你說得對』」: agreeing after a correction proves the work was skipped before. Delete the opener; state what was wrong, the evidence this turn found, and what you did about it",
    "secret_ask": "never ask the operator to paste or hand over a token, key or password: run auth_check.py / the vault / token-onboard.py, or the browser-login-handoff skill (agent does the OAuth itself; only a password/MFA screen is the operator's, shown once in the built-in browser)",
    "handback": "推託: this step is handed to the operator although the line names no operator-reserved action (login/OAuth, permanent delete, rider arming, global settings, secrets, funds, hardware) and no tool failed this turn: do it yourself now, or try it and cite the failing tool result",
}
READ_CMD = re.compile(
    r"(?i)(?:^|[\s;&|(])(?:cat|head|tail|less|more|type|sed\s+-n|Get-Content|gc|Select-String|findstr|"
    r"grep|rg|awk|python[\w.]*\s+-I?\s*-c|jq|sqlite3|git\s+(?:show|log|diff|cat-file))\b"
)
SEARCH_CMD = re.compile(r"(?i)(?:^|[\s;&|(])(?:grep|rg|findstr|Select-String|find|fd|locate|git\s+grep|git\s+log\s+-S|ls|dir|Get-ChildItem)\b")
READ_TOOL_NAMES = {"Read", "Grep", "Glob", "WebFetch", "WebSearch"}
READ_TOOL_SUFFIX = ("get_page_text", "read_page", "find", "read_file_content", "search_files", "read_terminal")
SCHEDULER_TOUCH = re.compile(r"(?i)hosts\.json|register-rider|rider_edit|schtasks|CurrentVersion\\\\?Run|hubclock-heartbeat|crontab|Register-ScheduledTask")
COUNT_NUMBER = re.compile(r"(?<![\w.,])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?:則|條|筆|個|組|項|檔|篇|份|次|天|年|口|張|頁|行|%|％)")
# F1S wave 2: 「需要你決定」 is a question only when it opens the line (after a list marker / bold) and is
# followed by a colon or ends the line; a mention inside a rule description or correction is not asked.
# A question that starts a new sentence mid-line (「…不變。需要你決定：…」) is still a question.
DECISION_ASK = re.compile(
    r"(?:^(?:[-*+]\s+|\d+[.)、]\s*)?|[。！？!?；;]\s*)(?:\*\*|__)?\s*(?:需要你決定|需要你(?:來)?(?:選|決)|請你決定|由你決定|"
    r"needs?\s+your\s+decision|you\s+(?:need\s+to\s+)?decide)\s*(?:\*\*|__)?\s*(?:[:：]|$)", re.I)
DECISION_TAIL = re.compile(r"(?:需要你決定|needs?\s+your\s+decision)\s*[:：]?\s*(.*)", re.I)
# 2026-10-13 operator 「用LEAN和F1S嚴格要求不准寫多餘且無用的垃圾檔案」: a prompt that merely mentions 報告 /
# 記錄 / notes no longer opens the door for every .md / .json the turn writes.  A document counts as asked
# for only when the prompt names the file, or explicitly asks to CREATE a document.
DOC_CREATE = re.compile(
    r"(?i)(?<!不准)(?<!不要)(?<!禁止)(?<!不得)(?:寫|產出|产出|建立|新增|生成|存成|存為|輸出成)[一個份篇成到入下]{0,3}\s*"
    r"[^\s，。,.；;]{0,6}?(?:文件|報告|报告|筆記|笔记|說明檔|\.md|\.json|markdown|README)"
    r"|\b(?:write|create|generate|draft|save)\b\W+(?:\w+\W+){0,3}?(?:report|document|notes?|write-?up|README|markdown|md|json)\b")
MD_WRITE_CMD = re.compile(r"(?<![<\d=!-])>{1,2}\s*\"?'?([^\s\"'|;&]+\.(?:md|json))\b|(?:tee|Set-Content|Out-File|Add-Content)\s+(?:-(?:Literal|File)?Path\s+)?\"?'?([^\s\"'|;&]+\.(?:md|json))\b", re.I)
JUNK_EXT = (".md", ".json")


SHELL_ASSIGN = re.compile(r"(?:^|[\s;&(])([A-Za-z_]\w*)=([^\s;&|]+)")
SHELL_CD = re.compile(r"(?:^|[\s;&(])cd\s+(?:/d\s+)?\"?'?([^\s;&|\"']+)")
# A heredoc / PowerShell here-string body is data, not a command: `cat > x.py <<'EOF'` with a body that
# mentions a redirect into some .json writes x.py only.  The header line (and its redirect) is kept.
HEREDOC_BODY = re.compile(r"(<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n).*?\n[ \t]*\2[ \t]*(?=\n|$)", re.S)
HERESTRING_BODY = re.compile(r"@(['\"])\r?\n.*?\r?\n\1@", re.S)
# A `>` inside a quoted argument is text, not a redirect: ai_theater 2026-10-27 `sed -i 's#(a/<id>.json)#(b/<id>.json)#'`
# was denied as creating `.json)#(b/<id>.json`.  A quoted redirect TARGET never contains `>`, so only quoted strings
# that contain one are blanked before the redirect scan.
QUOTED_GT = re.compile(r"'[^'\n]*>[^'\n]*'|\"[^\"\n]*>[^\"\n]*\"")


def _bash_md_targets(command: str) -> list[str]:
    """.md files a shell command writes, with `$VAR` / `${VAR}` expanded from assignments in the same
    command and relative paths resolved against the last `cd` in it.  A target that still carries an
    unexpanded variable is unknown and is NOT reported (fail open)."""
    command = HERESTRING_BODY.sub("", HEREDOC_BODY.sub(lambda m: m.group(1), command or ""))
    command = QUOTED_GT.sub("''", command)
    env ={m.group(1): m.group(2).strip("\"'") for m in SHELL_ASSIGN.finditer(command or "")}
    cds = [m.group(1) for m in SHELL_CD.finditer(command or "")]
    out: list[str] = []
    for m in MD_WRITE_CMD.finditer(command or ""):
        target = (m.group(1) or m.group(2) or "").strip("\"'")
        for _ in range(3):
            target = re.sub(r"\$\{?([A-Za-z_]\w*)\}?", lambda mm: env.get(mm.group(1), mm.group(0)), target)
        if "$" in target or not target:
            continue
        if not re.match(r"^(?:[A-Za-z]:[\\/]|/|~)", target) and cds:
            target = cds[-1].rstrip("/\\") + "/" + target
        out.append(target)
    return out


def _win_path(raw: str, cwd: str = "") -> Path:
    """A Write / shell target as a Windows path: `/c/x` -> `C:/x`, relative -> under `cwd`."""
    m = re.match(r"^/([a-zA-Z])/(.*)$", raw)
    if m:
        raw = f"{m.group(1).upper()}:/{m.group(2)}"
    p = Path(raw).expanduser()
    if not p.is_absolute() and not raw.startswith(("/", "\\")) and cwd:
        p = Path(cwd) / p
    return p


def junk_target(p: Path, cfg: dict) -> bool:
    """A .md / .json outside machine-state directories and not a charter / receipt name."""
    if p.suffix.lower() not in JUNK_EXT:
        return False
    allowed_dirs = {d.lower() for d in (cfg.get("md_allowed_dirs") or DEFAULTS["md_allowed_dirs"])}
    allowed_names = {n.lower() for n in (cfg.get("md_allowed_names") or DEFAULTS["md_allowed_names"])}
    return not ({x.lower() for x in p.parts[:-1]} & (allowed_dirs | {"tmp"}) or p.name.lower() in allowed_names)


def doc_requested(p: Path, prompt_text: str) -> bool:
    """The prompt named THIS file (name, or a stem of 4+ chars) or explicitly asked to create a document."""
    low = (prompt_text or "").lower()
    stem = p.stem.lower()
    return bool(p.name.lower() in low or (len(stem) >= 4 and stem in low) or DOC_CREATE.search(prompt_text or ""))


WRITE_GATE_REASON = (
    "PROOF write gate (operator 2026-10-13 「用LEAN和F1S嚴格要求不准寫多餘且無用的垃圾檔案」, Lean "
    "ClaimContract.unrequested_file_needs_request): creating {paths} is denied - no prompt asked for this "
    ".md / .json. Put the report / notes / summary in your reply; machine state goes under runtime/ or "
    "_registry/; scratch goes to the scratchpad. Editing an existing file is allowed."
)


PATCH_ADD = re.compile(r"^\*\*\* Add File:\s*(.+?)\s*$", re.M)
SHELL_TOOLS = ("Bash", "PowerShell", "Shell")


def _tool_targets(tool: str, ti: dict) -> list[str]:
    """Paths a tool call would CREATE: Claude/Cursor `Write.file_path`, shell redirects in any `command`
    (Claude Bash/PowerShell, Cursor Shell, Codex shell as a string or argv list), and `*** Add File:` lines
    of a Codex apply_patch."""
    if tool == "Write":
        return [str(ti.get("file_path") or "")]
    out: list[str] = []
    for key, val in ti.items():
        text = " ".join(map(str, val)) if isinstance(val, list) else str(val) if isinstance(val, str) else ""
        if not text:
            continue
        out.extend(m.group(1) for m in PATCH_ADD.finditer(text))
        if key in ("command", "cmd") or tool in SHELL_TOOLS:
            out.extend(_bash_md_targets(text))
    return out


# Publishing gate (2026-10-18 ai_zonghe: a private PDF was copied into ai_darkhero/public/media and deployed to the
# public Worker without the operator's consent, while the operator had only asked for it on LINE without Drive).
# The real 2026-10-18 command never spelled "public/": it wrote through line-oa-send-media's WORKTREE_MEDIA and
# called sync_and_deploy(), so the publishing symbols and deploy commands count as a public destination too.
PUBLIC_DEST = re.compile(r"(?i)WORKTREE_MEDIA|sync_and_deploy|MEDIA_PREFIX|cf-deploy-sync|wrangler\s+(?:pages\s+)?deploy|"
                         r"vercel\s+(?:deploy|--prod)|flyctl?\s+deploy|"
                         r"[\\/](?:public|static|www|wwwroot|htdocs)[\\/]|cf-migrate[\\/][^\\/\s]+[\\/]public|"
                         r"transfer\.sh|0x0\.st|file\.io|catbox\.moe|tmpfiles\.org|gofile\.io|"
                         r"\b(?:aws\s+s3\s+cp|gsutil\s+cp|rclone\s+(?:copy|copyto|move))\b.*\b(?:public|www)\b")
# 2026-10-22 jci_taipei: a pure read (grep a key name in .env.local, then ls a content/public path) was denied.
# A served-directory PATH alone only counts when the shell command also writes, copies or moves something; the
# deploy symbols, deploy commands and file hosts above publish by themselves and stay gated without a write verb.
PUBLIC_PATH_ONLY = re.compile(r"(?i)[\\/](?:public|static|www|wwwroot|htdocs)[\\/]|cf-migrate[\\/][^\\/\s]+[\\/]public")
WRITE_VERB = re.compile(r"(?i)\b(?:cp|mv|install|ln|rsync|robocopy|xcopy|copy|move|tee|dd|unzip|tar|7z|curl|wget|"
                        r"Copy-Item|Move-Item|Rename-Item|New-Item|Set-Content|Add-Content|Out-File|Expand-Archive|"
                        r"Invoke-WebRequest|iwr|shutil|copyfile|copy2|copytree|write_bytes|write_text|writeFile\w*|"
                        r"copyFile\w*|rename|replace|open|sed\s+-i|git\s+mv)\b|"
                        r"(?:^|[^0-9&<>=\-])>{1,2}(?!\s*(?:&|/dev/null|\$null|nul\b))")
PRIVATE_DOC = re.compile(r"(?i)\.(?:pdf|docx?|xlsx?|pptx?|zip|7z|rar|csv|tsv|m4a|mp3|mp4|mov|wav|"
                         r"sqlite3?|db|key|pem|env)\b")
# 2026-10-28 ai_trader: `curl https://sdmx.oecd.org/public/rest/...?format=csv... -o x.csv` (and a heredoc only quoting
# that URL) was denied: a /public/ segment inside a REMOTE URL is not a local served directory. URLs are dropped from
# the shell text before matching unless the command uploads (curl -T/-F/--data-binary @, PUT/POST, -InFile).
URL_TEXT = re.compile(r"(?i)\bhttps?://[^\s'\"<>|`]+")
UPLOAD_FLAG = re.compile(r"(?i)(?:^|\s)(?:-T|-F|--upload-file|--form|--data-binary|-InFile)\b|"
                         r"(?:-X|--request|-Method)\s*['\"]?(?:PUT|POST)\b")
PUBLISH_CONSENT = re.compile(r"(?i)公開|公布|上網|網站|官網|網頁|部署|上線|deploy|publish|public(?:ly)?|website")
PUBLISH_REASON = (
    "PROOF publish gate (operator 2026-10-18 「不要再發生」): this tool call puts a non-image file ({what}) in a "
    "publicly served location, and the operator's current prompt gives no consent to publish (公開/網站/部署). "
    "Do not publish it. To hand a file to the operator privately use "
    "`python C:/ai_workspace/_skill/engines/line-oa-send-media.py link <file>` (one-shot private link, TTL + "
    "download cap, no Drive, nothing public) or `... file <file>` (owner's private Drive). Only the operator's own "
    "explicit 「公開」 in the prompt allows a public copy."
)


NEGATION = re.compile(r"(?i)(?:不|別|勿|禁止|不要|不准|不可|不能|沒|未|non?|not|don'?t|never|without)\W{0,2}\S{0,6}$")


def publish_consent(prompt_text: str) -> bool:
    """An unnegated 公開/網站/部署/publish in the operator's prompt; 「不准公開」 or "don't publish" is no consent."""
    for m in PUBLISH_CONSENT.finditer(prompt_text or ""):
        if not NEGATION.search(prompt_text[max(0, m.start() - 10):m.start()]):
            return True
    return False


def _publish_gate(doc: dict, tool: str, ti: dict) -> dict | None:
    if tool in ("Bash", "PowerShell"):
        text = str(ti.get("command") or "")
        if not UPLOAD_FLAG.search(text):
            text = URL_TEXT.sub(" ", text)
    elif tool in ("Write", "Edit", "NotebookEdit"):
        text = str(ti.get("file_path") or ti.get("notebook_path") or "")
    else:
        return None
    if not PUBLIC_DEST.search(text) or not PRIVATE_DOC.search(text):
        return None
    if tool in ("Bash", "PowerShell") and not PUBLIC_DEST.search(PUBLIC_PATH_ONLY.sub(" ", text)) \
            and not WRITE_VERB.search(text):
        return None
    prompt_text = ""
    path = _safe_transcript_path(doc)
    if path is not None:
        _, prompt, _, _, _ = current_turn_ex(path)
        prompt_text = _text_of(((prompt or {}).get("message") or {}).get("content"))
    consent = publish_consent(prompt_text)
    what = (PRIVATE_DOC.search(text).group(0) + " -> " + PUBLIC_DEST.search(text).group(0)).strip()
    _log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "session_id": str(doc.get("session_id") or ""),
          "event": "PreToolUse", "tool": tool, "matched": "publish_gate", "what": what[:120],
          "verdict": "allow" if consent else "deny"})
    if consent:
        return None
    reason = PUBLISH_REASON.format(what=what[:120])
    if "cursor_version" in doc or str(doc.get("hook_event_name") or "") == "preToolUse":
        return {"permission": "deny", "user_message": reason, "agent_message": reason}
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def pre_tool_use(doc: dict, cfg: dict) -> dict | None:
    """Deny the CREATION of an unrequested .md / .json before it is written.  One gate for Claude Code
    (`PreToolUse`), Codex (`PreToolUse`, same reply shape) and Cursor (`preToolUse`, `permission` reply).
    Cursor and Codex hand the hook no prompt text, so there a new .md / .json is never "requested"."""
    tool0 = str(doc.get("tool_name") or "")
    ti0 = doc.get("tool_input") if isinstance(doc.get("tool_input"), dict) else {}
    if (cfg.get("classes") or {}).get("publish_gate", True):
        gated = _publish_gate(doc, tool0, ti0)
        if gated:
            return gated
    if not (cfg.get("classes") or {}).get("unrequested_file", True):
        return None
    tool = str(doc.get("tool_name") or "")
    ti = doc.get("tool_input") if isinstance(doc.get("tool_input"), dict) else {}
    cwd = str(doc.get("cwd") or "")
    raw = _tool_targets(tool, ti)
    new_junk = []
    for r in raw:
        if not r:
            continue
        try:
            p = _win_path(r.strip("\"'"), cwd)
            if junk_target(p, cfg) and not p.exists():
                new_junk.append(p)
        except (OSError, ValueError):
            continue
    if not new_junk:
        return None
    cursor = "cursor_version" in doc or str(doc.get("hook_event_name") or "") == "preToolUse"
    prompt_text = ""
    path = _safe_transcript_path(doc)
    if path is not None and not cursor:
        _, prompt, _, _, _ = current_turn_ex(path)
        prompt_text = _text_of(((prompt or {}).get("message") or {}).get("content"))
    denied = [p for p in new_junk if not admissible("unrequested_file", {"requestedDoc": doc_requested(p, prompt_text)})]
    _log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "session_id": str(doc.get("session_id") or doc.get("conversation_id") or ""),
          "event": "PreToolUse", "engine": "cursor" if cursor else "claude/codex", "cwd": cwd, "tool": tool,
          "verdict": "deny" if denied else "allow", "matched": "unrequested_file",
          "md_writes": [str(p) for p in new_junk][:6]})
    if not denied:
        return None
    reason = WRITE_GATE_REASON.format(paths=", ".join(str(p) for p in denied)[:400])
    if cursor:
        return {"permission": "deny", "user_message": reason, "agent_message": reason}
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}


SCRATCH_PARTS = {"scratchpad", "temp", "tmp"}
FIX_CLAIM = re.compile(r"(?i)修好了?|已修復|已修复|修復(?:完成|了)|已修正|修正完成|改好了|\bfixed\b|\bbug\s+is\s+fixed\b|\bnow\s+works\b")


LIE_PATTERNS["fix_claim"] = FIX_CLAIM


def _scratch_path(fp: str) -> bool:
    """A session scratch script (scratchpad / Temp) is not the brownfield code the code_change clause protects."""
    try:
        return bool({p.lower() for p in Path(fp).parts} & SCRATCH_PARTS)
    except (TypeError, ValueError):
        return False


def admissible(cls: str, ev: dict) -> bool:
    """The admission rule, cell for cell the same as `Fames.ClaimContract.admissible` in
    _lean/fames/ClaimContract.lean (bound by claim_conformance.py; do not edit one without the other)."""
    g = lambda k: bool(ev.get(k))  # noqa: E731
    if cls == "read":
        return g("readResult") and g("namedTargetTouched")
    if cls == "progress":
        return g("anchor")
    if cls == "automated":
        return g("schedulerFact")
    if cls == "blocker":
        return g("failureObserved")
    if cls == "decision":
        return (not g("askedBefore")) and g("redLineNamed")
    if cls == "ask_value":
        return g("searched")
    if cls == "unrequested_file":
        return g("requestedDoc")
    if cls == "handback":
        return g("redLineNamed") or g("failureObserved")
    if cls == "code_change":
        return g("searchedBeforeWrite")
    if cls == "fix_claim":
        return g("testAfterWrite")
    raise KeyError(cls)


EVIDENCE_FIELDS = ("readResult", "namedTargetTouched", "anchor", "schedulerFact",
                   "failureObserved", "askedBefore", "searched", "requestedDoc", "redLineNamed", "searchedBeforeWrite", "testAfterWrite")
CLAIM_CLASSES = ("read", "progress", "automated", "blocker", "decision", "ask_value", "unrequested_file", "handback", "code_change", "fix_claim")


def claim_table() -> str:
    """`<class>:<11 bits>=<0|1>;…` in the same order as `Fames.ClaimContract.table`."""
    cells = []
    nbits = len(EVIDENCE_FIELDS)
    for cls in CLAIM_CLASSES:
        for n in range(1 << nbits):
            bits = [(n >> (nbits - 1 - i)) & 1 for i in range(nbits)]
            ev = {k: bool(b) for k, b in zip(EVIDENCE_FIELDS, bits)}
            cells.append(f"{cls}:{''.join(str(b) for b in bits)}={'1' if admissible(cls, ev) else '0'}")
    return ";".join(cells)


def _norm_decision(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text or "")[:60].lower()


def _bigrams(s: str) -> set:
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


def asked_before(line: str, earlier: list[str]) -> bool:
    """The same decision (normalised, or ≥ 0.6 char-bigram overlap) was asked in an earlier turn."""
    m = DECISION_TAIL.search(line)
    cur = _norm_decision(m.group(1) if m else line)
    if not cur:
        return False
    cb = _bigrams(cur)
    for prev in earlier:
        pm = DECISION_TAIL.search(prev)
        pn = _norm_decision(pm.group(1) if pm else prev)
        if not pn:
            continue
        if pn == cur or pn[:30] == cur[:30]:
            return True
        pb = _bigrams(pn)
        common = len(cb & pb)
        if common / max(1, len(cb | pb)) >= 0.6 or common / max(1, min(len(cb), len(pb))) >= 0.7:
            return True
    return False


_RIDER_IDS: set | None = None


def rider_ids() -> set:
    global _RIDER_IDS
    if _RIDER_IDS is None:
        ids: set = set()
        try:
            doc = json.loads((HUB / "_registry" / "hosts.json").read_text(encoding="utf-8-sig"))
            for host in (doc.get("hosts") or {}).values():
                for r in (host or {}).get("riders") or []:
                    if isinstance(r, dict) and r.get("id"):
                        ids.add(str(r["id"]))
        except (OSError, ValueError, AttributeError):
            pass
        _RIDER_IDS = ids
    return _RIDER_IDS


NEEDS = {
    "tests_pass": "no green test-runner result (pytest / unittest / npm test / selftest) in this turn",
    "pushed": "no successful `git push` in this turn",
    "committed": "no successful `git commit` in this turn",
    "deployed": "no successful deploy command in this turn",
    "verified": "no successful read-only tool call after the last file write in this turn",
    "completion": "no cited artifact path that exists (SEAL-AP-1), no commit this turn, "
                  "or nothing was re-read / re-run after the last file write",
    "measurement": "this number appears in no tool result, tool input or prompt of this turn",
}

# ---------------------------------------------------------------- fact patterns

WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
# Writing code or configuration starts the "re-read / re-run after writing" obligation.  Writing a
# report, memory note or log (.md/.txt/.log/.jsonl) at the end of a turn does not: those are
# records of the work, not the artifact under test.
CODE_EXT = {
    ".py", ".pyw", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".ps1", ".psm1", ".sh", ".bat", ".cmd",
    ".html", ".htm", ".css", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".json", ".xml", ".sql", ".go",
    ".rs", ".java", ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".lua", ".ipynb", ".vbs", ".reg",
}
READ_TOOLS = {"Bash", "PowerShell", "Read", "Grep", "Glob", "Agent", "Task"}
BASH_TOOLS = {"Bash", "PowerShell"}
# File-content writes only.  git commit/push, installs and mkdir are actions, not the artifact
# under test, so they do not reset the "re-read after writing" requirement.
BASH_WRITE = re.compile(
    r"(?<![<>\d=!-])>{1,2}\s*(?!/dev/null|nul\b|&)[\w./~\\$\"']|\bsed\s+-i\b|\btee\b|\bcp\b|\bmv\b|\bcopy\b|\bmove\b|"
    r"Set-Content|Out-File|Add-Content|\bpatch\b|\bgit\s+(?:checkout|reset|merge|rebase|stash|apply)\b"
)
# Bash targets with these extensions are records (evidence, reports, logs), not code under test.
RECORD_EXT = {".md", ".txt", ".log", ".jsonl", ".json", ".csv", ".tsv", ".rst"}


RECEIPT_NAMES = {"result.json", "closure.json", "turn.json", "residual.json"}
QUOTED_ARG = re.compile(r"\"(?:\\.|[^\"\\])*\"|'[^']*'")
SHELL_VAR = re.compile(r"\$\{?([A-Za-z_]\w*)\}?")
OTHER_WRITE = re.compile(
    r"\bsed\s+-i\b|\bcp\b|\bmv\b|\bcopy\b|\bmove\b|Set-Content|Out-File|Add-Content|\bpatch\b|"
    r"\bgit\s+(?:checkout|reset|merge|rebase|stash|apply)\b")
REDIRECT_TARGET = re.compile(r"(?:(?<![<>\d=!-])>{1,2}|\btee\s+(?:-a\s+)?)\s*(\"[^\"]*\"|'[^']*'|[^\s;&|<>()]+)")


def _record_write(fp: str) -> bool:
    """F1S wave 2 (d): a write that is a record, not brownfield code — a scratchpad / temp file, a SEAL
    receipt, or JSON state under _registry / runtime/fames_seal."""
    if _scratch_path(fp):
        return True
    p = Path(fp)
    parts = {x.lower() for x in p.parts[:-1]}
    return p.name.lower() in RECEIPT_NAMES or (p.suffix.lower() == ".json" and bool(parts & {"_registry", "fames_seal"}))


def _bash_code_write(command: str) -> bool:
    """A shell command that writes code/config (an obligation to re-read / re-run follows).

    No write operator: False.  A write operator whose path tokens are all records: False.  A write
    operator with a code path, or with no recognisable path at all (sed -i, git merge …): True.
    A git commit message is text, not a write; `$VAR` paths assigned in the same command, `$TEMP`,
    scratchpad files, SEAL receipts and `_registry` JSON are records (F1S wave 2 (d)).
    """
    command = command or ""
    probe = QUOTED_ARG.sub('""', command) if GIT_COMMIT.search(command) else command
    if not BASH_WRITE.search(probe):
        return False
    env = {m.group(1): m.group(2).strip("\"'") for m in SHELL_ASSIGN.finditer(command)}
    env.update({k: "Temp" for k in ("TEMP", "TMP", "TMPDIR") if k not in env})
    expanded = command
    for _ in range(3):
        expanded = SHELL_VAR.sub(lambda mm: env.get(mm.group(1), mm.group(0)), expanded)
    if not OTHER_WRITE.search(probe):
        # redirect / tee only: the redirect targets are what is written, not the script that ran
        header = HERESTRING_BODY.sub("", HEREDOC_BODY.sub(lambda m: m.group(1), expanded))
        targets = [t.strip("\"'") for t in REDIRECT_TARGET.findall(header)]
        targets = [t for t in targets if t and not re.fullmatch(r"(?i)/dev/null|nul|&\d", t)]
        if targets:
            return any(Path(t).suffix.lower() in (CODE_EXT - RECORD_EXT) and not _record_write(t) for t in targets)
    tokens = [m.group(0) for m in PATH_TOKEN.finditer(expanded)]
    exts = {Path(t).suffix.lower() for t in tokens if not _record_write(t)}
    exts.discard("")
    if not exts:
        return not tokens  # every named path is a record: not code; nothing named: unknown = write
    return bool(exts & (CODE_EXT - RECORD_EXT))


# F1S wave 2 (a): a reply number rounded from a tool value (38.2 from 38.158) or converted between units
# (2.2 GB from 2205 MB, 96 GB from 98304 MB, 200 W from 200000 mW) is supported by that tool value.
UNIT_SCALE = {
    "b": ("bytes", 1), "byte": ("bytes", 1), "bytes": ("bytes", 1), "kb": ("bytes", 1e3), "mb": ("bytes", 1e6),
    "gb": ("bytes", 1e9), "tb": ("bytes", 1e12), "kib": ("bytes", 1024), "mib": ("bytes", 1024 ** 2),
    "gib": ("bytes", 1024 ** 3), "tib": ("bytes", 1024 ** 4),
    "mw": ("power", 1e-3), "w": ("power", 1), "kw": ("power", 1e3),
    "ms": ("time", 1e-3), "毫秒": ("time", 1e-3), "s": ("time", 1), "秒": ("time", 1), "sec": ("time", 1),
    "min": ("time", 60), "分鐘": ("time", 60), "分钟": ("time", 60), "h": ("time", 3600),
    "hz": ("freq", 1), "khz": ("freq", 1e3), "mhz": ("freq", 1e6), "ghz": ("freq", 1e9),
}
DECIMAL_SIZE = ("kb", "mb", "gb", "tb")  # tools also print binary sizes under these names
HAY_NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*([A-Za-z]{1,5}|毫秒|秒|分鐘|分钟)?(?![A-Za-z])")


def _scales(unit: str) -> list:
    family, factor = UNIT_SCALE[unit]
    out = [factor]
    if unit in DECIMAL_SIZE:
        out.append(1024 ** (DECIMAL_SIZE.index(unit) + 1))
    return out


def _number_index(hay: str) -> dict:
    """{family: [value in base unit]}, plus "": [(value, decimals)] for unit-less tool numbers."""
    index: dict = {"": []}
    for m in HAY_NUMBER.finditer(hay):
        raw, unit = m.group(1), (m.group(2) or "").lower()
        if unit in UNIT_SCALE:
            index.setdefault(UNIT_SCALE[unit][0], []).extend(float(raw) * k for k in _scales(unit))
        elif not unit:
            index[""].append((float(raw), len(raw.split(".")[1]) if "." in raw else 0))
    return index


def rounded_from_tool(plain: str, unit: str, index: dict) -> bool:
    """`plain` (with `unit`) equals a tool number after rounding to the reply's precision, either a more
    precise unit-less number or a number in another unit of the same family."""
    try:
        num = float(plain)
    except ValueError:
        return False
    decimals = len(plain.split(".")[1]) if "." in plain else 0
    half = 0.5 * 10 ** -decimals + 1e-9
    if any(d > decimals and abs(v - num) <= half for v, d in index.get("", [])):
        return True
    unit = unit.lower()
    if unit not in UNIT_SCALE:
        return False
    for base in index.get(UNIT_SCALE[unit][0], []):
        if any(abs(base / k - num) <= half for k in _scales(unit)):
            return True
    return False


HEDGED_NUMBER = re.compile(r"(?:[~≈±<>]|約|大約|近|不到|超過|上下|左右|估|預計|预计)\s*$")
GIT_PUSH = re.compile(r"\bgit\b[^\n|;&]*\bpush\b|git_smart\.py[^\n]*\b(?:commit-push|push)\b|ztm-git-ship", re.I)
GIT_COMMIT = re.compile(r"\bgit\b[^\n|;&]*\bcommit\b|git_smart\.py[^\n]*\bcommit", re.I)
DEPLOY = re.compile(
    r"\bfly(?:ctl)?\s+deploy\b|\bwrangler\s+(?:deploy|publish|versions\s+upload)\b|\bvercel\b|"
    r"opennextjs-cloudflare|ship-queue\.py\s+request|fleet-ztm-ship\.py|\bnpm\s+run\s+deploy\b|"
    r"\bgcloud\s+(?:run|app)\s+deploy\b|\bkubectl\s+apply\b", re.I,
)
GIT_FAIL = re.compile(r"(?im)^\s*(?:!\s+\[rejected\]|fatal:|error:|remote:\s*error|Permission denied)|nothing to commit|rejected")
CMD_FAIL = re.compile(r"(?im)^\s*(?:error|fatal|exception|traceback|failed)\b|\bexit(?:ed)?\s+(?:code|status)\s+[1-9]")
SELFTEST_CMD = re.compile(r"(?i)(?:self-?tests?|tests?_[\w-]+|[\w-]+_tests?|run_tests?)\.(?:py|js|ts|sh|ps1)\b|\bpytest\b|\bunittest\b|\bnpm\s+test\b|\bcargo\s+test\b|\bgo\s+test\b")
TEST_FAIL = re.compile(r"(?i)\b[1-9]\d*\s+(?:failed|failures?|errors?)\b|\bFAILED\b|RESULT\s+FAIL|AssertionError|Traceback")
TEST_OK = re.compile(r"(?i)\b[1-9]\d*\s+passed\b|\bok\b|RESULT\s+PASS|\bpass(?:ed)?\b|✓|全部通過")
PATH_TOKEN = re.compile(
    r"(?:[A-Za-z]:[\\/]|~[\\/]|\.{1,2}[\\/]|/)?(?:[\w.@~-]+[\\/])*[\w@~-][\w.@~-]*\.[A-Za-z0-9]{1,8}\b"
)
COMMIT_HASH = re.compile(r"\b[0-9a-f]{7,40}\b")


def _exec_module():
    try:
        spec = importlib.util.spec_from_file_location("fames_execution_evidence", EXEC_EVIDENCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:  # noqa: BLE001 — shared module optional; own classifier below
        return None


# ---------------------------------------------------------------- input / config


def _read_hook_input(stream) -> dict:
    raw = stream.buffer.read() if hasattr(stream, "buffer") else stream.read()
    if isinstance(raw, bytes):
        text = None
        for encoding in ("utf-8-sig", "utf-16", "cp950"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            return {}
    else:
        text = str(raw)
    try:
        doc = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _config() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        if CONFIG.is_file():
            loaded = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, dict):
                for key in DEFAULTS:
                    if key not in loaded:
                        continue
                    if key == "classes" and isinstance(loaded[key], dict):
                        cfg["classes"].update({k: bool(v) for k, v in loaded[key].items()})
                    else:
                        cfg[key] = loaded[key]
    except (OSError, ValueError):
        pass  # a broken config means defaults, never a crash
    return cfg


# ---------------------------------------------------------------- transcript


def _safe_transcript_path(doc: dict) -> Path | None:
    raw = str(doc.get("transcript_path") or "").strip()
    if str(doc.get("hook_event_name") or "") == "SubagentStop" and doc.get("agent_transcript_path"):
        raw = str(doc.get("agent_transcript_path") or "").strip()
    if not raw:
        return None
    try:
        path = Path(raw).expanduser().resolve()
        path.relative_to(CLAUDE_PROJECTS_ROOT.resolve())
        return path if path.is_file() else None
    except (OSError, RuntimeError, ValueError):
        return None


def _tail_rows(path: Path):
    with path.open("rb") as fh:
        end = fh.seek(0, os.SEEK_END)
        start = max(0, end - TAIL_BYTES)
        fh.seek(start)
        data = fh.read(end - start)
    lines = data.split(b"\n")
    if start > 0 and lines:
        lines = lines[1:]
    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(row, dict):
            yield row


def _blocks(row: dict) -> list:
    message = row.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content if isinstance(content, list) else []


def _is_human_prompt(row: dict) -> bool:
    if row.get("type") != "user":
        return False
    if any(row.get(flag) for flag in ("isMeta", "isCompactSummary", "isVisibleInTranscriptOnly")):
        return False
    blocks = _blocks(row)
    if not blocks:
        return False
    return not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks)


def current_turn(path: Path) -> tuple[list[dict], dict | None, bool, str]:
    """Rows of the current turn (chronological), the prompt row, whether it was found, and the
    tool text of EARLIER turns inside the window (numbers measured a few turns ago are still
    measurements; actions are not carried over)."""
    rows, prompt, found, history, _ = current_turn_ex(path)
    return rows, prompt, found, history


def current_turn_ex(path: Path) -> tuple[list[dict], dict | None, bool, str, list[str]]:
    """`current_turn` plus every 「需要你決定」 line the assistant wrote in EARLIER turns of this
    session (the whole scanned window, not capped by MAX_HISTORY) for the `decision` class."""
    rows: list[dict] = []
    prompt = None
    history: list[str] = []
    history_size = 0
    earlier_decisions: list[str] = []
    walked = 0
    for row in _tail_rows(path):
        walked += 1
        if walked > MAX_ROWS:
            break
        if prompt is None:
            if _is_human_prompt(row):
                prompt = row
                continue
            if row.get("type") in {"assistant", "user"}:
                rows.append(row)
            continue
        if row.get("type") == "assistant":
            for b in _blocks(row):
                if isinstance(b, dict) and b.get("type") == "text":
                    for ln in str(b.get("text") or "").splitlines():
                        if LIE_PATTERNS["decision"].search(ln):
                            earlier_decisions.append(ln.strip())
        if history_size >= MAX_HISTORY:
            continue
        if row.get("type") == "user":
            for b in _blocks(row):
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    chunk = _text_of(b.get("content"))
                    history.append(chunk)
                    history_size += len(chunk)
        elif row.get("type") == "assistant":
            for b in _blocks(row):
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    chunk = json.dumps(b.get("input") or {}, ensure_ascii=False)
                    history.append(chunk)
                    history_size += len(chunk)
    rows.reverse()
    return rows, prompt, prompt is not None, "\n".join(history), earlier_decisions


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def closing_text(rows: list[dict]) -> str:
    parts: list[str] = []
    for row in reversed(rows):
        if row.get("type") != "assistant":
            break
        blocks = _blocks(row)
        if any(isinstance(b, dict) and b.get("type") == "tool_use" for b in blocks):
            break
        for b in blocks:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.insert(0, str(b.get("text") or ""))
    return "\n".join(parts).strip()


# ---------------------------------------------------------------- facts


def _green_test(exec_mod, command: str, result: str, is_error) -> bool:
    if exec_mod is not None:
        try:
            kind = exec_mod.execution_evidence_kind(command, result, is_error)
            if kind in {"pytest", "python_test", "unittest", "npm_test"}:
                return True
        except Exception:  # noqa: BLE001
            pass
    if is_error is not False or not SELFTEST_CMD.search(command):
        return False
    return bool(TEST_OK.search(result)) and not TEST_FAIL.search(result)


def facts(rows: list[dict], prompt: dict | None, history: str = "") -> dict:
    exec_mod = _exec_module()
    uses: dict[str, tuple[str, dict]] = {}
    haystack: list[str] = []
    size = 0
    f = {
        "tool_calls": 0, "tests_pass": False, "pushed": False, "committed": False, "deployed": False,
        "readonly_ok": False, "writes": 0, "code_writes": 0, "verify_after_write": False, "write_paths": [],
        # 2026-10-13 evidence fields (ClaimContract.lean)
        "read_result": False, "failure_observed": False, "searched": False, "scheduler_touched": False,
        "md_writes": [], "prompt_text": "", "searched_before_write": False, "first_code_write": None, "first_search": None,
        "test_after_write": False,
    }
    last_write = -1
    last_read = -1
    last_test = -1
    index = 0
    if prompt is not None:
        f["prompt_text"] = _text_of((prompt.get("message") or {}).get("content"))
        haystack.append(f["prompt_text"])
    for row in rows:
        kind = row.get("type")
        for b in _blocks(row):
            if not isinstance(b, dict):
                continue
            if kind == "assistant" and b.get("type") == "tool_use":
                tool_input = b.get("input") if isinstance(b.get("input"), dict) else {}
                uses[str(b.get("id") or "")] = (str(b.get("name") or ""), tool_input)
            elif kind == "user" and b.get("type") == "tool_result":
                index += 1
                name, tool_input = uses.get(str(b.get("tool_use_id") or ""), ("", {}))
                result = _text_of(b.get("content"))
                is_error = b.get("is_error")
                ok = is_error is not True
                f["tool_calls"] += 1
                command = str(tool_input.get("command") or "")
                if size < MAX_HAYSTACK:
                    chunk = result + "\n" + json.dumps(tool_input, ensure_ascii=False)
                    haystack.append(chunk)
                    size += len(chunk)
                if name in WRITE_TOOLS and ok:
                    f["writes"] += 1
                    fp = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
                    if fp:
                        f["write_paths"].append(fp)
                    if Path(fp).suffix.lower() in CODE_EXT and not _record_write(fp):
                        f["code_writes"] += 1
                        last_write = index
                        if f["first_code_write"] is None:
                            f["first_code_write"] = index
                    if fp.lower().endswith(JUNK_EXT):
                        f["md_writes"].append(fp)
                if name in BASH_TOOLS and ok and _bash_code_write(command):
                    f["writes"] += 1
                    f["code_writes"] += 1
                    last_write = index
                    if f["first_code_write"] is None:
                        f["first_code_write"] = index
                if name in BASH_TOOLS and ok:
                    f["md_writes"].extend(_bash_md_targets(command))
                if name in READ_TOOLS and ok:
                    f["readonly_ok"] = True
                    last_read = index
                if not ok or CMD_FAIL.search(result or "") or GIT_FAIL.search(result or ""):
                    f["failure_observed"] = True
                if ok and (name in READ_TOOL_NAMES or name.endswith(READ_TOOL_SUFFIX)
                           or (name in BASH_TOOLS and READ_CMD.search(command))):
                    f["read_result"] = True
                if ok and (name in {"Grep", "Glob"} or name.endswith(("find", "search_files", "search_session_transcripts"))
                           or (name in BASH_TOOLS and SEARCH_CMD.search(command))):
                    f["searched"] = True
                    if f["first_search"] is None:
                        f["first_search"] = index
                if SCHEDULER_TOUCH.search(command) or SCHEDULER_TOUCH.search(result or ""):
                    f["scheduler_touched"] = True
                if name in BASH_TOOLS:
                    if _green_test(exec_mod, command, result, is_error):
                        f["tests_pass"] = True
                        last_test = index
                    if ok and GIT_PUSH.search(command) and not GIT_FAIL.search(result):
                        f["pushed"] = True
                    if ok and GIT_COMMIT.search(command) and not GIT_FAIL.search(result):
                        f["committed"] = True
                    if ok and DEPLOY.search(command) and not CMD_FAIL.search(result):
                        f["deployed"] = True
    f["verify_after_write"] = f["code_writes"] == 0 or (last_read > last_write)
    f["test_after_write"] = f["code_writes"] == 0 or (last_test > last_write)
    f["searched_before_write"] = f["code_writes"] == 0 or (
        # <=: a grep in the same shell call as the write counts as the search (F1S wave 2 (d))
        f["first_search"] is not None and f["first_code_write"] is not None and f["first_search"] <= f["first_code_write"])
    f["haystack"] = "\n".join(haystack) + "\n" + (history or "")
    return f


# ---------------------------------------------------------------- git (cited commit hashes)


def git_hashes(text: str, cwd: str) -> dict:
    """Check the commit hashes the reply cites against the repository at `cwd`.

    `exists`: at least one cited hash is a commit here.  `on_remote`: at least one cited hash is
    contained in a remote-tracking branch, i.e. it really was pushed (or fetched back).  A cited
    hash is verifiable evidence precisely because the hook, not the model, resolves it.
    """
    out = {"exists": False, "on_remote": False, "checked": []}
    hashes = []
    for m in COMMIT_HASH.finditer(text or ""):
        h = m.group(0)
        if h not in hashes and not h.isdigit():
            hashes.append(h)
    if not hashes or not cwd or not Path(cwd).is_dir():
        return out
    import subprocess  # local import: the common path never spawns anything
    flags = 0x08000000 if os.name == "nt" else 0
    for h in hashes[:6]:
        try:
            probe = subprocess.run(["git", "-C", cwd, "cat-file", "-e", f"{h}^{{commit}}"],
                                   capture_output=True, timeout=GIT_TIMEOUT_S, creationflags=flags)
            if probe.returncode != 0:
                continue
            out["exists"] = True
            out["checked"].append(h)
            remote = subprocess.run(["git", "-C", cwd, "branch", "-r", "--contains", h],
                                    capture_output=True, timeout=GIT_TIMEOUT_S, creationflags=flags)
            if remote.returncode == 0 and remote.stdout.strip():
                out["on_remote"] = True
                break
        except (OSError, subprocess.SubprocessError):
            continue
    return out


# ---------------------------------------------------------------- claims


def _negated(line: str, start: int) -> bool:
    return bool(NEGATION_BEFORE.search(line[max(0, start - 8):start]))


def _resolve_path(token: str, cwd: str, write_paths: list[str]) -> bool:
    token = token.strip().strip("`'\"<>()[]{}，。、；：,;:").rstrip(".")
    token = re.sub(r":\d+(?::\d+)?$", "", token)
    if not token or token.startswith("--"):
        return False
    candidates = []
    try:
        p = Path(token).expanduser()
        candidates.append(p)
        if not p.is_absolute():
            if cwd:
                candidates.append(Path(cwd) / token)
            candidates.append(HUB / token)
            base = Path(token).name
            if base == token:
                candidates += [Path(w) for w in write_paths if Path(w).name == base]
        for c in candidates:
            if c.exists():
                return True
    except (OSError, ValueError, RuntimeError):
        return False
    return False


def _message_paths_exist(text: str, cwd: str, write_paths: list[str]) -> bool:
    body = URL.sub(" ", text)
    for m in PATH_TOKEN.finditer(body):
        if _resolve_path(m.group(0), cwd, write_paths):
            return True
    return False


def _line_anchor(stripped: str, f: dict, cwd: str, git_state) -> bool:
    """The LINE itself names an existing path, a commit git resolves, or a number a tool printed."""
    body = URL.sub(" ", stripped)
    for m in PATH_TOKEN.finditer(body):
        if _resolve_path(m.group(0), cwd, f.get("write_paths") or []):
            return True
    hay = f.get("haystack") or ""
    for m in COUNT_NUMBER.finditer(stripped):
        num = m.group(1)
        plain = num.replace(",", "")
        if re.search(r"(?<![\d.])(?:" + re.escape(num) + "|" + re.escape(plain) + r")(?![\d])", hay):
            return True
    for m in MEASUREMENT.finditer(stripped):
        num = m.group(1)
        plain = num.replace(",", "")
        if re.search(r"(?<![\d.])(?:" + re.escape(num) + "|" + re.escape(plain) + r")(?![\d])", hay):
            return True
    if COMMIT_HASH.search(stripped):
        g = git_state()
        if g.get("exists"):
            return True
    return False


def _named_targets_touched(stripped: str, f: dict) -> bool:
    """Every path / URL the line names occurs in this turn's tool inputs or results (none named = True)."""
    hay = f.get("haystack") or ""
    names = [m.group(0).rstrip(".,;:)»」") for m in URL.finditer(stripped)]
    names += [m.group(0) for m in PATH_TOKEN.finditer(URL.sub(" ", stripped))]
    for name in names:
        base = Path(name).name if "://" not in name else name
        base = base.strip("`'\"<>()[]{}，。、；：,;:")
        if not base or len(base) < 4:
            continue
        if base not in hay and name not in hay:
            return False
    return True


def judge(text: str, f: dict, cfg: dict, cwd: str = "", earlier_decisions: list[str] | None = None) -> list[dict]:
    """Return the unsupported claims of `text` given turn facts `f`."""
    classes = cfg.get("classes") or {}
    violations: list[dict] = []
    lines = (text or "").splitlines()
    path_ok = None  # lazily computed, message-level
    hay_index = None  # lazily computed: haystack numbers by unit family (rounding / unit conversion)
    git: dict | None = None  # lazily computed, message-level
    earlier_decisions = earlier_decisions or []
    def git_state() -> dict:
        nonlocal git
        if git is None:
            git = git_hashes(text, cwd)
        return git

    if classes.get("unrequested_file", True):
        prompt_text = f.get("prompt_text") or ""
        for mdp in f.get("md_writes") or []:
            if not junk_target(Path(mdp), cfg):
                continue
            # The remedy the hook asks for is to move the file away; a target that no longer exists at
            # judge time (moved, or a shell path like /tmp that is not a Windows path) was not produced.
            try:
                if not Path(mdp).expanduser().exists():
                    continue
            except (OSError, ValueError):
                continue
            if not admissible("unrequested_file", {"requestedDoc": doc_requested(Path(mdp), prompt_text)}):
                violations.append({"line": 0, "class": "unrequested_file", "snippet": str(mdp)[:SNIPPET],
                                   "need": LIE_NEEDS["unrequested_file"]})

    if classes.get("code_change", True) and (f.get("code_writes") or 0) > 0:
        if not admissible("code_change", {"searchedBeforeWrite": f.get("searched_before_write")}):
            first = (f.get("write_paths") or ["(shell write)"])[0]
            violations.append({"line": 0, "class": "code_change", "snippet": str(first)[:SNIPPET], "need": LIE_NEEDS["code_change"]})

    fenced = False
    for number, raw in enumerate(lines, 1):
        stripped = raw.strip()
        if stripped.startswith("```"):
            fenced = not fenced
            continue
        if fenced or not stripped or stripped.startswith(">"):
            continue
        line = QUOTED.sub(" ", URL.sub(" ", stripped))
        snippet = stripped[:SNIPPET]
        # A decision request is a question to the operator: a hedge word on the line does not excuse
        # asking it again, so this class is judged before the qualifier exemption.
        # judged on `line` (quoted spans removed): a quoted mention of 「需要你決定」 is not a question to the operator
        if (classes.get("decision", True) and LIE_PATTERNS["decision"].search(line)
                and DECISION_ASK.search(line.strip())):
            asked = stripped
            tail = DECISION_TAIL.search(stripped)
            if not tail or not re.sub(r"[*_\s:：]", "", tail.group(1)):
                # a header line ("**需要你決定：**"): the question itself is the next non-empty line
                asked = stripped + " " + next((x.strip() for x in lines[number:] if x.strip()), "")
            if not admissible("decision", {"askedBefore": asked_before(asked, earlier_decisions),
                                           "redLineNamed": red_line_named(asked, cwd)}):
                violations.append({"line": number, "class": "decision", "snippet": snippet, "need": LIE_NEEDS["decision"]})
        # No evidence makes a placating opener admissible, so it is judged before the qualifier
        # exemption; a quoted mention (「你說得對」) is removed from `line` and stays legal.
        if classes.get("placation", True) and PLACATION.search(line):
            violations.append({"line": number, "class": "placation", "snippet": snippet, "need": LIE_NEEDS["placation"]})
        if (classes.get("secret_ask", True) and SECRET_ASK.search(line) and not SECRET_ASK_NEG.search(line)):
            violations.append({"line": number, "class": "secret_ask", "snippet": snippet, "need": LIE_NEEDS["secret_ask"]})
        if QUALIFIER.search(line):
            continue
        for name, pattern in LIE_PATTERNS.items():
            if not classes.get(name, True) or name == "decision":
                continue
            hit = pattern.search(line)
            if not hit or _negated(line, hit.start()):
                continue
            if name == "read":
                ev = {"readResult": f.get("read_result"), "namedTargetTouched": _named_targets_touched(stripped, f)}
            elif name == "progress":
                ev = {"anchor": _line_anchor(stripped, f, cwd, git_state)}
            elif name == "automated":
                ids = rider_ids()
                on_line = any(tok in ids for tok in re.findall(r"[A-Za-z0-9][\w.-]{3,}", stripped))
                ev = {"schedulerFact": on_line or f.get("scheduler_touched")
                      or _message_paths_exist(stripped, cwd, f.get("write_paths") or [])}
            elif name == "blocker":
                ev = {"failureObserved": f.get("failure_observed")}
            elif name == "fix_claim":
                ev = {"testAfterWrite": f.get("test_after_write", True)}
            elif name == "handback":
                ev = {"redLineNamed": red_line_named(stripped, cwd), "failureObserved": f.get("failure_observed")}
            else:  # ask_value
                ev = {"searched": f.get("searched")}
            if not admissible(name, ev):
                violations.append({"line": number, "class": name, "snippet": snippet, "need": LIE_NEEDS[name]})
        for name, pattern in CLASS_PATTERNS.items():
            if not classes.get(name, True):
                continue
            hit = pattern.search(line)
            if not hit or _negated(line, hit.start()):
                continue
            if name == "completion":
                if path_ok is None:
                    path_ok = _message_paths_exist(text, cwd, f.get("write_paths") or [])
                anchored = path_ok or (COMMIT_HASH.search(text) and git_state()["exists"])
                supported = f.get("tool_calls", 0) > 0 and anchored and f.get("verify_after_write")
            elif name == "verified":
                supported = f.get("readonly_ok") and f.get("verify_after_write")
            elif name == "pushed":
                supported = f.get("pushed") or (COMMIT_HASH.search(text) and git_state()["on_remote"])
            elif name == "committed":
                supported = f.get("committed") or (COMMIT_HASH.search(text) and git_state()["exists"])
            elif name == "deployed":
                supported = f.get("deployed") or f.get("pushed") or (
                    COMMIT_HASH.search(text) and git_state()["on_remote"])
            else:
                supported = bool(f.get(name))
            if not supported:
                violations.append({"line": number, "class": name, "snippet": snippet, "need": NEEDS[name]})
        if classes.get("measurement", True):
            hay = f.get("haystack") or ""
            for m in MEASUREMENT.finditer(line):
                if HEDGED_NUMBER.search(line[max(0, m.start() - 4):m.start()]):
                    continue
                num = m.group(1)
                plain = num.replace(",", "")
                if re.search(r"(?<![\d.])(?:" + re.escape(num) + "|" + re.escape(plain) + r")(?![\d])", hay):
                    continue
                if hay_index is None:
                    hay_index = _number_index(hay)
                if rounded_from_tool(plain, line[m.end(1):m.end()].strip(), hay_index):
                    continue
                violations.append({"line": number, "class": "measurement", "snippet": snippet,
                                   "need": NEEDS["measurement"] + f" (number {num})"})
    return violations


# ---------------------------------------------------------------- state / log


def _state_path(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)[:80] or "unknown"
    return STATE_DIR / f"{safe}.json"


def _load_state(session_id: str) -> dict:
    try:
        doc = json.loads(_state_path(session_id).read_text(encoding="utf-8-sig"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(session_id: str, state: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        target = _state_path(session_id)
        staged = target.with_name(target.name + f".{os.getpid()}.tmp")
        staged.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(staged, target)
    except OSError:
        pass


def _log(entry: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with (STATE_DIR / "log.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
    except OSError:
        pass


REASON = (
    "PROOF (operator 2026-10-11 「解決 claude 模型會說謊」): the reply about to end this turn asserts "
    "things this turn's transcript does not show:\n{items}\n"
    "Fix it NOW, in this same turn: run the missing verification as a real tool call (test, "
    "push, re-read the file, measure) and cite the artifact path or commit, OR rewrite each listed "
    "line so it says UNKNOWN / 未驗證 for what you did not check. Never restate a listed claim "
    "unchanged. (push {n}/{cap} for this prompt)"
)


def evaluate(doc: dict, cfg: dict | None = None) -> dict | None:
    """Return the hook payload to print, or None for silence (= let the turn end)."""
    cfg = cfg or _config()
    if not cfg.get("enabled", True):
        return None
    event = str(doc.get("hook_event_name") or "")
    if event.lower() == "pretooluse":
        return pre_tool_use(doc, cfg)
    if event not in (cfg.get("events") or DEFAULTS["events"]):
        return None
    path = _safe_transcript_path(doc)
    if path is None:
        return None
    rows, prompt, found, history, earlier_decisions = current_turn_ex(path)
    text = str(doc.get("last_assistant_message") or "") or closing_text(rows)
    session_id = str(doc.get("session_id") or "")
    turn_key = str((prompt or {}).get("uuid") or "") if found else ""
    if event == "SubagentStop":
        turn_key = f"{path.name}:{turn_key}"
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "session_id": session_id,
        "event": event,
        "cwd": str(doc.get("cwd") or ""),
        "stop_hook_active": bool(doc.get("stop_hook_active")),
        "turn": turn_key,
        "rows": len(rows),
    }
    if not found:
        entry.update({"verdict": "allow", "matched": "turn_window_exhausted"})
        _log(entry)
        return None
    if not text.strip():
        entry.update({"verdict": "allow", "matched": "empty_reply"})
        _log(entry)
        return None
    f = facts(rows, prompt, history)
    violations = judge(text, f, cfg, str(doc.get("cwd") or ""), earlier_decisions)
    entry.update({
        "tool_calls": f["tool_calls"], "writes": f["writes"],
        "facts": {k: f[k] for k in ("tests_pass", "pushed", "committed", "deployed", "readonly_ok", "verify_after_write",
                                    "read_result", "failure_observed", "searched", "scheduler_touched", "searched_before_write", "test_after_write")},
        "md_writes": (f.get("md_writes") or [])[:6], "earlier_decisions": len(earlier_decisions),
        "violations": violations[:12],
    })
    if not violations:
        entry.update({"verdict": "allow", "matched": "all_claims_supported"})
        _log(entry)
        return None

    state = _load_state(session_id)
    if state.get("turn") != turn_key:
        state = {"turn": turn_key, "blocks": 0, "session_blocks": int(state.get("session_blocks") or 0)}
    per_turn = int(cfg.get("max_blocks_per_turn") or 0)
    per_session = int(cfg.get("max_blocks_per_session") or 0)
    if state.get("blocks", 0) >= per_turn or state.get("session_blocks", 0) >= per_session:
        # F1S 當下閉環 item 6 (2026-10-18): over the cap the turn still ends (no endless loop), but the unresolved
        # claims are carried, not dropped: claude_session_hook.py puts them in front of the next prompt once and
        # the overflow stays in log.jsonl as a compliance record.
        state["carried"] = {"turn": turn_key, "at": entry["ts"], "surfaced": False,
                            "items": [f"{v['class']}: \"{v['snippet']}\" -> {v['need']}" for v in violations[:6]]}
        _save_state(session_id, state)
        entry.update({"verdict": "allow", "matched": "budget_exhausted", "carried": len(violations),
                      "blocks": state.get("blocks"), "session_blocks": state.get("session_blocks")})
        _log(entry)
        return None
    state["blocks"] = int(state.get("blocks", 0)) + 1
    state["session_blocks"] = int(state.get("session_blocks", 0)) + 1
    state["last"] = entry["ts"]
    _save_state(session_id, state)
    entry.update({"verdict": "block", "blocks": state["blocks"], "session_blocks": state["session_blocks"]})
    _log(entry)
    items = "\n".join(
        f"  - line {v['line']} · {v['class']} · \"{v['snippet']}\" → {v['need']}" for v in violations[:8]
    )
    if len(violations) > 8:
        items += f"\n  - … {len(violations) - 8} more"
    reason = REASON.format(items=items, n=state["blocks"], cap=per_turn)
    # F1S 強制思考 A (2026-10-19): a "no route" / hand-back / decision line is answered with the routes the request
    # actually has (route_candidates.py), so the model must try one or disprove each — it can no longer stop at
    # "cannot" without looking. Fail open: no candidates, no extra text.
    if any(v["class"] in ("blocker", "handback", "decision") for v in violations):
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import route_candidates
            prompt_text = _text_of(((prompt or {}).get("message") or {}).get("content"))
            seat = Path(str(doc.get("cwd") or "")).name
            routes = route_candidates.render(route_candidates.candidates(prompt_text, seat=seat), f.get("tool_calls"))
            if routes:
                reason += "\n" + routes
                entry["routes_offered"] = [r.strip()[:80] for r in routes.splitlines()[1:4]]
        except Exception:  # noqa: BLE001
            pass
    return {"decision": "block", "reason": reason}


def main() -> int:
    doc = _read_hook_input(sys.stdin)
    payload = evaluate(doc)
    if payload:
        print(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
