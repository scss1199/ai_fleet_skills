#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# token-class: ZT
"""cursor_bootstrap_pack.py — embed rules_brief + pickup ritual in each ai_*/AGENTS.md (≤10KB).

Usage:
  python cursor_bootstrap_pack.py           # write all seats
  python cursor_bootstrap_pack.py --dry-run # print sizes only
  python cursor_bootstrap_pack.py ai_trader # one seat

CITE: ai_master/HUB_TODO.md · consolidate-master-directives.md · AGENT-BOOTSTRAP-PROMPT.md
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import COMMON as HUB, REGISTRY  # noqa: E402
from _hub_curator import HUB_CURATOR  # noqa: E402
import rules_brief  # noqa: E402

# Was 4096, but the shared bootstrap body is 4646-4986 bytes for all 20 seats (measured
# 2026-08-10), so the cap fired on every seat on every run and main() returned 1 forever.
# A byte-accurate cut at 4096 would have deleted load-bearing rules — 平行 / 零前景, the
# ztm-task-router path, the ztm-task-routes + workspace-seat-contract SSOT lines, the
# dual-agent charter and the whole `## Paths` section — from all 20 seats. So the budget is
# raised above the real content instead of the content being cut to fit the budget. Nothing
# external pins 4096: it is a local ritual, not a Cursor platform limit.
#
# Raised again 2026-09-14, from 5120, for the same reason. The body had grown to 5822-6196
# bytes, so write_one() cut every seat, and main() compared the already-cut size with the
# cap, so the warning never fired. The cut removed 路由, the SSOT line, the dual-agent charter and `## Paths` from every seat that had
# them, and the T1 brief was itself capped at 1250 bytes, leaving 3 of the 13
# hard lines verbatim. T1 now ships whole (4817 bytes) and first, the Obedience lines that T1 already states are gone, main()
# judges the uncut body, and the body measures 8364-8733 bytes across the 22 seats.
MAX_BYTES = 10240
ENG = os.path.dirname(os.path.abspath(__file__))
PICKUP = os.path.join(ENG, "inbox.py").replace("\\", "\\\\")
ASO = os.path.join(ENG, "agent-session-open.py").replace("\\", "\\\\")
RUN_STAMP = time.strftime("%Y%m%d_%H%M%S")


def _snapshot_prior(dest: str, prior: str) -> str:
    """Keep changed generated charters in manifested quarantine, never beside seats."""
    backup_root = os.path.join(HUB, "_delete", "cursor-bootstrap-backups")
    os.makedirs(backup_root, exist_ok=True)
    manifest = os.path.join(backup_root, "MANIFEST.md")
    if not os.path.isfile(manifest):
        with open(manifest, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(
                "# Cursor bootstrap backup quarantine\n\n"
                "- status: `GENERATED_CHANGE_BACKUPS`\n"
                "- source: generated `AGENTS.md` / `CLAUDE.md` before replacement\n"
                "- purge_eligible: `false`\n"
                "- permanent_deletion_authority: `operator_only`\n"
                "- content_verified: `false`\n\n"
                "Backups are grouped by generator run and preserve their workspace-relative path.\n"
            )
    relative = os.path.relpath(dest, HUB)
    target_dir = os.path.join(backup_root, RUN_STAMP, os.path.dirname(relative))
    os.makedirs(target_dir, exist_ok=True)
    base = os.path.basename(dest) + ".bak"
    target = os.path.join(target_dir, base)
    n = 0
    while os.path.exists(target):
        n += 1
        target = os.path.join(target_dir, base + ".%d" % n)
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(prior)
    return target


def _agents():
    import _projects
    out = []
    for name in _projects.hub_seats():
        meta = _projects.get(name) or {}
        path = meta.get("path")
        if path:
            out.append((name, path))
    # ai_master is the implicit identity when the hub root is opened, but it also has a
    # real seat directory and conversation surface.  It is intentionally absent from
    # project-matrix hub_seats(), so include it explicitly in the bootstrap invariant.
    master_path = os.path.join(HUB, "ai_master")
    if os.path.isdir(master_path):
        out.append(("ai_master", master_path))
    return sorted(set(out))


def _session_open(agent: str) -> str:
    if agent in ("ai_master", "ai_scar3", "ai_darkhero"):
        report = f"_registry/session-open-reports/{agent}.json"
        return f"""## Session open (hub curator — ZTM · {agent})

SessionStart 三層 hook 自動注入 fleet inbox + PLAN（`cursor-agent-session-open.py`）。  
Curator **不被 A2A hard-block**；scar3 維護 wallpaper / network / jci。

Report: `{report}`  
Debug: `python {ASO} --agent {agent}`
"""
    if agent in ("ai_master", "ai_darkhero_integration"):
        return f"""## Session open (SUPERSEDED — {agent})

此 seat 已肥料化。請改開 **`C:\\ai_workspace\\ai_darkhero`**。
"""
    return f"""## Session open (ZTM — SessionStart 三層 hook)

notice → inbox EXECUTE NOW → PLAN inject。**禁止等 operator 開口才 pickup。**

第一輪 **必須** `**本輪 PLAN**` → 執行 → verify → ack → SUBMIT。  
inbox>0：**禁止**建議下一步 · **禁止**盲 ack。

Report: `runtime/session_open/report.json` · `_registry/session-open-reports/{agent}.json`  
Debug: `python {ASO}`
"""


def _pilot_extra(agent: str) -> str:
    import json
    parts = []
    ec = os.path.join(REGISTRY, "extreme-confirm-pilot.json")
    try:
        pilots = set(json.load(open(ec, encoding="utf-8-sig")).get("pilot_agents") or [])
    except (OSError, json.JSONDecodeError):
        pilots = set()
    if agent in pilots:
        parts.append(
            "## 極致確認\n\n"
            "SSOT: `extreme-confirm-pilot.json`；未 pickup 前 portal 不可 ack task/directive/question。\n"
        )
    ac = os.path.join(REGISTRY, "accountability-enforce-pilot.json")
    try:
        ap = set(json.load(open(ac, encoding="utf-8-sig")).get("pilot_agents") or [])
    except (OSError, json.JSONDecodeError):
        ap = set()
    if agent in ap and agent != "ai_master":
        parts.append(
            "## 執法閘\n\n"
            "SSOT: `accountability-enforce-pilot.json`；inbox_lock/suspended HARD DENY；probation_lock 擋 ship。\n"
        )
    return "\n".join(parts)


def _dual_agent_fleet(agent: str) -> str:
    if agent == "fracdigi":
        return (
            "## 多 agent 並行 + 確認即上線\n\n"
            "SSOT: `GitHub/new.messages.fracdigi.com/AGENTS.md` · fleet: `_registry/fleet-dual-agent-charter.md`\n"
        )
    return (
        "## 多 agent 並行 + 確認即上線\n\n"
        "`_registry/fleet-dual-agent-charter.md` · psync 詳細見 fracdigi psync AGENTS.md。"
        " operator 確認→verify→push→prod→SHA+URL。**禁**問 push/deploy。\n"
    )


def _body(agent: str, rel_path: str) -> str:
    # T1 whole, never cut to a byte cap: rules_brief.charter_with_t1(), which decides whether
    # SessionStart must inject T1 itself, accepts only a charter that states every T1 rule
    # exactly. A body over MAX_BYTES fails main() instead.
    rules = rules_brief.format_rules(tiers=["T1"], max_bytes=1 << 30).strip()
    seat = os.path.join(HUB, rel_path).replace("\\", "/")
    pilot = _pilot_extra(agent)
    pilot_block = ("\n" + pilot + "\n") if pilot else "\n"
    # `## Paths` links every seat to ai_darkhero.html. That is NOT a per-seat path and not a
    # copy-paste bug: fleet-hub-html.json declares ONE fleet dashboard (authority ai_darkhero)
    # that "bakes all fleet entrances". Templating it to {agent}.html was tried 2026-08-03 and
    # reverted — it produced 19 dead links, since only ai_darkhero.html and ai_master.html
    # exist on disk. This note used to be an HTML comment inside the charter, where every seat
    # session paid for text that only a maintainer of this template needs.
    #
    # Obedience does not restate 禁止問 operator / 自己跑 / 週期工作 / PFKT work graph / 零前景 / the SSOT line:
    # T1, at the top of the charter, states each of them with the same commands and paths
    # (guarded by _skill/tests/test_standing_rules_delivery.py).
    return f"""<!-- DERIVED — regenerate: python %AI_WORKSPACE%\\_skill\\engines\\cursor_bootstrap_pack.py -->
<!-- Cursor reads AGENTS.md at session start. Open cwd MUST be {seat} (not hub root). -->

# {agent} — Cursor bootstrap (≤{MAX_BYTES}B)

> Identity + mandate load only when **cwd = `{seat}`**. Hub root `C:\\ai_workspace` silently makes you this machine's curator seat (`_registry/machine.json`; default `{HUB_CURATOR}`).
> **THIS file is the seat charter.** `CLAUDE.md` starts with `@AGENTS.md`, so every engine reads the same bytes.
> (T1 hard lines come first on purpose: a body over {MAX_BYTES} bytes fails this generator, and the cut it still writes loses only the tail.)

## Standing rules (portal rules tab = this source)

{rules}

{_session_open(agent)}
{pilot_block}
## FAMES complete-contract trigger

FAMES 是預設契約，不是一次叫全部（operator 2026-10-08）：每次對話照 T1 `f1s`（F1S＝FAMES 一套系統）。FP、MTM 每個任務都做；SCF 要有已驗證結果，AEX 要有可比較的量測差距，SEAL 在宣稱完成時；Lean、Jev、HubClock、GitHub 只在各自條件成立時啟用。使用者單說「FAMES」＝在回報列出各階段狀態。SSOT：`_registry/fames-protocol.json`；Skill：`fames`。

## Milestone handoff

- SUBMIT: `_inbox/from_projects/{agent}/<topic>.md`
- Task to curator: `python {PICKUP} send {HUB_CURATOR} {agent} --kind task "…"`
- Park at milestone: `python %AI_WORKSPACE%\\_skill\\engines\\goal_compact.py park {agent}`

## Obedience (operator 2026-06-24 — 違反=P=0)

**MTM/MTO（SessionStart+每 session 1x remind 已注入）**：任務前 `prework.py`+`ztm-task-router.py` · Skill `mtm-mto-first` · 禁 TRN Read/Shell 迴圈 · `mtm-token-waste-scan.py --brief`  
**AGC（auto-goal-compact 已注入）**：長 session 讀 `_registry/agc-compact/{agent}.md` 勿重讀 chat · Skill `agc-auto-goal-compact` · `agc-should-compact.py --agent {agent}`  
**平行**：獨立 ZTM 葉 → Multitask/Task 同 wave 全開；禁止無 merge 就宣稱完成  
路由：`python %AI_WORKSPACE%\\_skill\\engines\\ztm-task-router.py "<keywords>"`

{_dual_agent_fleet(agent)}
## Paths

- Shared engines/KB: `%AI_WORKSPACE%\\_skill\\`
- Portal truth: file:///C:/ai_workspace/ai_darkhero.html (_registry/fleet-hub-html.json)

"""


_SEAT_SPEC_RE = re.compile(
    r"<!--\s*SEAT-SPEC:BEGIN.*?<!--\s*SEAT-SPEC:END\s*-->",
    re.S | re.I,
)


def _preserve_seat_spec(dest: str) -> str:
    """Keep SEAT-SPEC block across bootstrap rewrites (Outcome SSOT for SCF g / SEAL-FP)."""
    if not os.path.isfile(dest):
        return ""
    try:
        old = open(dest, encoding="utf-8").read()
    except OSError:
        return ""
    m = _SEAT_SPEC_RE.search(old)
    return m.group(0).strip() if m else ""


_IMPORT_LINE = "@AGENTS.md"
_IMPORT_NOTE = (
    "\n<!-- The line above imports the seat charter so every engine reads the SAME bytes.\n"
    "     Claude Code reads CLAUDE.md; Cursor and the AGENTS.md convention read AGENTS.md.\n"
    "     Anything below is Claude-specific. Windows: `ln -s` needs admin, so @import. -->\n"
)


def _has_live_import(body: str) -> bool:
    """True only if CLAUDE.md carries an import Claude Code will actually act on.

    Three ways a present-looking @AGENTS.md is dead, all of which a naive check accepts:
      - indented 4+ spaces  -> Markdown code block, and import parsing skips code blocks
      - inside a ``` fence  -> same
      - a longer token      -> "@AGENTS.mdX" is not the file
    So: an unindented line that is exactly the import, outside any fence. Position in the
    file does not matter — Claude Code honours an import anywhere.
    """
    open_char, open_len = "", 0
    for raw in body.splitlines():
        # CommonMark: a fence opens with 3+ ` or ~ indented <4 spaces, and closes ONLY on
        # the SAME character at >= the opening length. Toggling on any ```/~~~ lets
        # "~~~ / @AGENTS.md / ``` / @AGENTS.md / ~~~" read as closed, so a dead import
        # inside a fence would be reported live and the gate would wrongly pass.
        probe = raw.lstrip(" ")
        indent = len(raw) - len(probe)
        ch = probe[:1]
        if indent < 4 and ch in ("`", "~"):
            run = len(probe) - len(probe.lstrip(ch))
            if run >= 3:
                if not open_char:
                    # An opening fence may carry an info string, but CommonMark forbids a
                    # backtick inside a BACKTICK fence's info string — "```js`x" is an
                    # ordinary paragraph, not a fence. Opening on it would swallow every
                    # following line and report a live import as dead.
                    if ch == "`" and "`" in probe[run:]:
                        continue
                    open_char, open_len = ch, run
                    continue
                if ch == open_char and run >= open_len and not probe[run:].strip():
                    open_char, open_len = "", 0
                    continue
        if open_char:
            continue
        if raw.rstrip() == _IMPORT_LINE:  # no leading whitespace allowed
            return True
    return False


def ensure_claude_md(rel_path: str, *, dry_run: bool = False) -> str:
    """Guarantee CLAUDE.md imports AGENTS.md, every run.

    Without this the SSOT is only ever a SNAPSHOT: this generator rewrites AGENTS.md but
    never looked at CLAUDE.md, so a new seat — or one whose import line got dropped —
    silently re-diverges and nothing notices. Enforcing it here makes the property
    maintained rather than merely true today.

    Never destructive: creates when absent, PREPENDS when a real charter is already there
    (twelve seats had substantive CLAUDE.md bodies), and leaves a correct file untouched
    so byte-stability — and therefore the prompt cache — is preserved.
    """
    dest = os.path.join(HUB, rel_path, "CLAUDE.md")
    if os.path.isfile(dest):
        with open(dest, encoding="utf-8-sig") as fh:
            body = fh.read()
        if _has_live_import(body):
            return "ok"
        if dry_run:
            return "would-prepend"
        _snapshot_prior(dest, body)
        new = _IMPORT_LINE + "\n" + _IMPORT_NOTE + "\n" + body
        with open(dest, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(new)
        return "prepended"
    if dry_run:
        return "would-create"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(_IMPORT_LINE + "\n" + _IMPORT_NOTE)
    return "created"


def write_one(agent: str, rel_path: str, *, dry_run: bool = False) -> dict:
    dest = os.path.join(HUB, rel_path, "AGENTS.md")
    seat_spec = _preserve_seat_spec(dest)
    body = _body(agent, rel_path)
    boot_enc = body.encode("utf-8")
    body_bytes = len(boot_enc)  # uncut size, the one main() must judge: the cut below always fits
    if body_bytes > MAX_BYTES:
        # Truncate bootstrap only — never drop preserved SEAT-SPEC (goal/FP coupling).
        # Cut on the ENCODED bytes: the budget is bytes, and the body is mostly CJK at 3
        # bytes/char, so slicing the str by MAX_BYTES kept ~3x the budget and the guard
        # below never converged. `errors="ignore"` drops the partial char at the boundary.
        body = boot_enc[: MAX_BYTES - 80].decode("utf-8", "ignore").rsplit("\n", 1)[0]
        # The cut can land inside an HTML comment. An unterminated `<!--` swallows
        # everything appended below it — including the SEAT-SPEC block — so close it.
        if body.count("<!--") > body.count("-->"):
            body += "\n-->"
        body += "\n\n<!-- truncated to %d bytes -->\n" % MAX_BYTES
        boot_enc = body.encode("utf-8")
    if seat_spec:
        body = body.rstrip() + "\n\n" + seat_spec + "\n"
    enc = body.encode("utf-8")
    if not dry_run:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        # This rewrites AGENTS.md for EVERY seat in one run, and the bootstrap body is
        # truncated at MAX_BYTES — so anything a human added below the cut and outside the
        # SEAT-SPEC block is gone with no way back. Snapshot before overwriting; O_EXCL so
        # two runs in the same second cannot collide and destroy the older snapshot.
        if os.path.isfile(dest):
            with open(dest, encoding="utf-8-sig") as fh:
                prior = fh.read()
            if prior == body:
                claude_md = ensure_claude_md(rel_path, dry_run=dry_run)
                return {
                    "agent": agent,
                    "path": dest,
                    "claude_md": claude_md,
                    "bytes": len(enc),
                    "body_bytes": body_bytes,
                    "bootstrap_bytes": len(boot_enc),
                    "seat_spec": bool(seat_spec),
                    "unchanged": True,
                }
            _snapshot_prior(dest, prior)
        with open(dest, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
    claude_md = ensure_claude_md(rel_path, dry_run=dry_run)
    return {
        "agent": agent,
        "path": dest,
        "claude_md": claude_md,
        "bytes": len(enc),
        "body_bytes": body_bytes,
        "bootstrap_bytes": len(boot_enc),
        "seat_spec": bool(seat_spec),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("agents", nargs="*", help="optional agent names; default all matrix seats")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    all_seats = _agents()
    seats, want = all_seats, set()
    if a.agents:
        want = set(a.agents)
        # A misspelled seat name used to filter down to zero targets and still print
        # "0 seats" and return 0 — a green run that regenerated nothing. Fail loudly
        # instead, so a typo in a scripted fleet run cannot pass for success.
        unknown = sorted(want - {s[0] for s in all_seats})
        if unknown:
            print("ERROR: unknown seat(s): %s" % unknown, file=sys.stderr)
            return 2
        seats = [s for s in all_seats if s[0] in want]
    rows = [write_one(ag, rel, dry_run=a.dry_run) for ag, rel in seats]
    # The CLAUDE.md -> AGENTS.md import is a FLEET invariant, so heal it for every seat
    # even on a filtered run. Otherwise `--agents ai_foo` would leave the rest of the
    # fleet diverged while the run still reports success, and the property would hold
    # only for whoever happened to be regenerated last. This is a one-line file check
    # per seat and rewrites nothing that is already correct.
    if a.agents:
        healed = [(ag, ensure_claude_md(rel, dry_run=a.dry_run))
                  for ag, rel in all_seats if ag not in want]
        changed = [ag for ag, st in healed if st != "ok"]
        if changed:
            print("fleet CLAUDE.md invariant healed outside filter:", changed)
    # The cap is bootstrap ritual only; SEAT-SPEC may push total file larger (SCF/FP SSOT).
    # Judge the UNCUT body: write_one() cuts an oversized body to fit before writing it, so
    # the post-cut size never exceeds the cap. Measured there, this check stayed silent while
    # every seat lost its tail (found 2026-09-14).
    over = [r for r in rows if r["body_bytes"] > MAX_BYTES]
    print("cursor_bootstrap_pack: %d seats, max_body=%d max_boot=%d max_file=%d bytes%s" % (
        len(rows),
        max((r["body_bytes"] for r in rows), default=0),
        max((r.get("bootstrap_bytes", 0) for r in rows), default=0),
        max((r["bytes"] for r in rows), default=0),
        " [dry-run]" if a.dry_run else "",
    ))
    if over:
        print("WARN: bootstrap over %d bytes:" % MAX_BYTES, [r["agent"] for r in over])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
