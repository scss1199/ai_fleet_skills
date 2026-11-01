# sync-cursor-hooks.py — propagate Cursor-native hub hooks to every hub seat + jci sub-roots.
# token-class: ZT
"""Install sessionStart inbox + a2a-read HARD DENY (Cursor JSON format) on all hub seats."""
from __future__ import annotations

import json
import hashlib
import importlib.util
import os
import sys
from pathlib import Path

ENG = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENG)
from _paths import COMMON, REGISTRY  # noqa: E402
import _projects  # noqa: E402
import hub_python  # noqa: E402

PYW = hub_python.resolve_pythonw()
RUN_HIDDEN = os.path.join(ENG, "hooks", "run_hidden.py")
FAMES_CONTEXT_HOOK = os.path.join(
    COMMON, "_skill", "fleet-skills", "token-preflight", "scripts", "claude_session_hook.py"
)
CLAUDE_CLAIM_INTEGRITY_HOOK = os.path.join(
    COMMON, "_skill", "engines", "claude-claim-integrity-hook.py"
)
# F1S Stop hooks (operator 2026-10-11 armed on the hub; 2026-10-13 「f1s 最新能力套用到所有對話與裝置」):
# wired on every host whose package carries the script, in this order after the claim-integrity gate.
CLAUDE_RUN_UNTIL_DONE_HOOK = os.path.join(COMMON, "_skill", "engines", "claude-run-until-done-hook.py")
CLAUDE_PROOF_HOOK = os.path.join(COMMON, "_skill", "engines", "claude-proof-hook.py")
# operator 2026-10-24 「一樣改 目的就是當任何對話一閒置後立刻套用」: the idle waiter runs as an asyncRewake Stop
# hook and exits 2 to wake the conversation, so it never takes the fail-open launcher (that launcher swallows
# SystemExit); f1s_live.py exits 0 on every error itself. Wired here so scar3 / altos get it from the package
# install (2026-10-28: scar3 had the script since 16:22 but no settings entry; only darkhero was hand-wired).
CLAUDE_LIVE_WAKE_HOOK = os.path.join(COMMON, "_skill", "engines", "f1s_live.py")
CLAUDE_LIVE_WAKE_TIMEOUT = 259200  # 72 h; f1s_live.LIFETIME_S (70 h) exits before the host kills it
CLAUDE_PLAIN_COMMANDS = {CLAUDE_LIVE_WAKE_HOOK: (("wait",), {"asyncRewake": True})}

# F1S auto-mode posture (operator 2026-10-31): the classifier rows Claude Code reads from ~/.claude/settings.json
# autoMode are rendered from _registry/fames-protocol.json#auto_mode_posture, so every host carries the T1 red lines
# and each seat's trust boundary as classifier rules. Claude Code reads autoMode from the user settings file (or
# managed settings) only - project settings are ignored (docs read 2026-10-31) - hence this writer. Operator rows stay
# in place; the rows F1S owns carry AUTO_MODE_TAG so a later render replaces them and nothing else.
PROTOCOL_PATH = os.path.join(REGISTRY, "fames-protocol.json")
AUTO_MODE_TAG = "[F1S]"
AUTO_MODE_KEYS = ("environment", "soft_deny")


def _am_norm(text) -> str:
    return " ".join(str(text).split()).strip()


def _am_untag(text) -> str:
    t = _am_norm(text)
    return t[len(AUTO_MODE_TAG):].strip() if t.startswith(AUTO_MODE_TAG) else t


def auto_mode_posture(protocol_path: str = PROTOCOL_PATH) -> dict:
    """The SSOT section; {} when the file or the section is missing or unreadable (nothing rendered, status ABSENT)."""
    try:
        with open(protocol_path, encoding="utf-8-sig") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return {}
    section = doc.get("auto_mode_posture") if isinstance(doc, dict) else None
    return section if isinstance(section, dict) else {}


def _am_rows(spec, key: str) -> list:
    out = []
    for row in (spec.get(key) or []) if isinstance(spec, dict) else []:
        text = row.get("rule") if isinstance(row, dict) else row
        if isinstance(text, str) and text.strip():
            out.append(_am_norm(text))
    return out


def auto_mode_expected(posture: dict) -> dict:
    """{key: [tagged rows]} in render order: the fleet rows, then every seat section sorted by seat name."""
    fleet = posture.get("fleet") or {}
    env = _am_rows(fleet, "environment")
    deny = _am_rows(fleet, "soft_deny")
    for seat, spec in sorted((posture.get("seats") or {}).items()):
        seat_env = _am_rows(spec, "environment")
        if seat_env:
            env.append(f"### Seat {seat} (F1S)")
            env += seat_env
        deny += _am_rows(spec, "soft_deny")
    return {"environment": [f"{AUTO_MODE_TAG} {r}" for r in env], "soft_deny": [f"{AUTO_MODE_TAG} {r}" for r in deny]}


def render_auto_mode(doc: dict, expected: dict) -> bool:
    """Merge the F1S rows into doc["autoMode"]; True when the document changed. Untagged operator rows stay in
    place, an untagged duplicate of an F1S row is adopted (dropped in favour of the tagged row), $defaults is kept
    where the operator put it (or added first) in soft_deny, and allow / hard_deny are never touched. An empty
    expectation leaves the document alone."""
    if not any(expected.get(k) for k in AUTO_MODE_KEYS):
        return False
    auto = doc.get("autoMode")
    if not isinstance(auto, dict):
        auto = {}
    changed = False
    for key in AUTO_MODE_KEYS:
        want = list(expected.get(key) or [])
        current = auto.get(key) if isinstance(auto.get(key), list) else []
        wanted = {_am_untag(w) for w in want}
        kept = [r for r in current
                if not (isinstance(r, str) and (_am_norm(r).startswith(AUTO_MODE_TAG) or _am_untag(r) in wanted))]
        if key == "soft_deny":
            if "$defaults" in kept:
                at = kept.index("$defaults") + 1
                new = kept[:at] + want + kept[at:]
            else:
                new = ["$defaults"] + want + kept
        else:
            new = kept + want
        if new != current:
            auto[key] = new
            changed = True
    if changed:
        doc["autoMode"] = auto
    return changed


def auto_mode_status(settings_path: str | None = None, protocol_path: str = PROTOCOL_PATH) -> dict:
    """ABSENT (no SSOT section), UNWRITTEN (SSOT present, the settings carry no F1S row yet), DRIFT (rows missing
    or stale tagged rows left behind) or IN_SYNC. Report only; never raises."""
    settings_path = settings_path or os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
    posture = auto_mode_posture(protocol_path)
    expected = auto_mode_expected(posture)
    total = sum(len(v) for v in expected.values())
    fleet = posture.get("fleet") or {}
    base = {"expected": total, "missing": 0, "stale": 0, "seats": sorted((posture.get("seats") or {}).keys()),
            "fleet_environment": len(fleet.get("environment") or []), "fleet_soft_deny": len(fleet.get("soft_deny") or [])}
    if not total:
        return {"state": "ABSENT", **base}
    try:
        with open(settings_path, encoding="utf-8-sig") as fh:
            auto = (json.load(fh) or {}).get("autoMode") or {}
    except (OSError, ValueError, AttributeError):
        auto = {}
    if not isinstance(auto, dict):
        auto = {}
    missing = stale = present = 0
    for key in AUTO_MODE_KEYS:
        have = [_am_norm(r) for r in (auto.get(key) or []) if isinstance(r, str)]
        have_set, want = set(have), expected[key]
        want_set = set(want)
        missing += sum(1 for w in want if w not in have_set)
        present += sum(1 for w in want if w in have_set)
        stale += sum(1 for h in have if h.startswith(AUTO_MODE_TAG) and h not in want_set)
    state = "UNWRITTEN" if present == 0 else ("DRIFT" if missing or stale else "IN_SYNC")
    return {"state": state, **base, "missing": missing, "stale": stale}


def claude_managed_hooks() -> list:
    """(event, script, timeout) rows in wiring order; a Stop hook whose script is absent on this host is
    skipped (the package has not delivered it yet), never wired to a missing file."""
    rows = [
        ("SessionStart", FAMES_CONTEXT_HOOK, 10),
        ("UserPromptSubmit", FAMES_CONTEXT_HOOK, 20),
        # operator 2026-10-15: F1S upgrades reach a long task mid-turn; a stat()-only fast path when unchanged.
        ("PostToolUse", FAMES_CONTEXT_HOOK, 10),
    ]
    if os.path.isfile(CLAUDE_RUN_UNTIL_DONE_HOOK):
        rows.append(("Stop", CLAUDE_RUN_UNTIL_DONE_HOOK, 10))
    if os.path.isfile(CLAUDE_PROOF_HOOK):
        rows.append(("Stop", CLAUDE_PROOF_HOOK, 15))
        rows.append(("SubagentStop", CLAUDE_PROOF_HOOK, 15))
        # 2026-10-13 operator 「用LEAN和F1S嚴格要求不准寫多餘且無用的垃圾檔案」: deny an unrequested .md / .json
        # before it is created (CLAUDE_MATCHERS limits it to the tools that write files).
        rows.append(("PreToolUse", CLAUDE_PROOF_HOOK, 10))
    if os.path.isfile(CLAUDE_LIVE_WAKE_HOOK):
        rows.append(("Stop", CLAUDE_LIVE_WAKE_HOOK, CLAUDE_LIVE_WAKE_TIMEOUT))
    return rows


CLAUDE_MATCHERS = {("PreToolUse", CLAUDE_PROOF_HOOK): "Write|Bash|PowerShell"}
# F1S wave 2 (2026-10-15): the advisory claim-integrity Stop hook blocked 48 times, all on 2026-10-08,
# and never since; PROOF covers the claims. The script stays (Lean conformance imports it); only the
# Stop/SubagentStop wiring is removed from the settings file on the next write.
CLAUDE_RETIRED_HOOKS = [("Stop", CLAUDE_CLAIM_INTEGRITY_HOOK), ("SubagentStop", CLAUDE_CLAIM_INTEGRITY_HOOK)]


def claude_hooks_missing(settings_path: str) -> list:
    """Managed (event, script basename) pairs that the Claude settings file does not wire yet."""
    try:
        doc = json.loads(Path(settings_path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        doc = {}
    hooks = doc.get("hooks") if isinstance(doc, dict) and isinstance(doc.get("hooks"), dict) else {}
    missing = []
    for event, script, _timeout in claude_managed_hooks():
        groups = hooks.get(event) if isinstance(hooks.get(event), list) else []
        if not any(_contains_script(group, script) for group in groups):
            missing.append((event, os.path.basename(script)))
    return missing

# Extra workspace roots (user opens subfolder as Cursor workspace — hooks must exist there).
# 2026-08-13 (operator: 一個 cwd 一個 surface): only a sub-path that is a real cwd —
# its own AGENTS.md + git repo + a project-matrix entry — earns a surface here.
# jci_taipei_website / jci_taipei_70 were dropped: neither has AGENTS.md, both are
# worked on from the jci_taipei seat root. Re-adding one recreates a surplus
# .cursor on every sync, so do not re-add without those three artifacts.
EXTRA_HOOK_ROOTS = {
    "fracdigi": ["GitHub/new.messages.fracdigi.com"],
}

HOOKS = {
    "version": 1,
    "hooks": {
        "sessionStart": [
            {
                "command": f"{PYW} {RUN_HIDDEN} {os.path.join(ENG, 'hooks', 'session-start-notice.ps1')}",
                "timeout": 20,
            },
            {
                "command": f"{PYW} {os.path.join(ENG, 'cursor-session-inbox.py')}",
                "timeout": 20,
            },
            {
                "command": f'"{PYW}" "{os.path.join(ENG, "cursor-agent-session-open.py")}"',
                "timeout": 90,
            },
            {
                "command": f"{PYW} {os.path.join(ENG, 'cursor-mtm-session-inject.py')}",
                "timeout": 15,
            },
            {
                "command": f"{PYW} {os.path.join(ENG, 'cursor-agc-session-inject.py')}",
                "timeout": 15,
            },
            {
                "command": f"{PYW} {os.path.join(ENG, 'cursor-adus-session-hint.py')}",
                "timeout": 10,
            },
            {
                "command": f"{PYW} {os.path.join(ENG, 'cursor-seal-session-open.py')}",
                "timeout": 15,
            },
        ],
        # 2026-10-13 operator 「Codex 和 Cursor 也擋 所有CWD都要做到」: the PROOF write gate denies an
        # unrequested .md / .json before it is created (same engine and Lean-bound rule as Claude Code).
        "preToolUse": [
            {
                "command": f"{PYW} {os.path.join(ENG, 'claude-proof-hook.py')}",
                "timeout": 10,
            },
        ],
        "postToolUse": [
            {
                "command": f"{PYW} {os.path.join(ENG, 'cursor-seal-post-tool.py')}",
                "timeout": 12,
            },
        ],
        "afterShellExecution": [
            {
                "command": f"{PYW} {os.path.join(ENG, 'cursor-seal-after-shell.py')}",
                "timeout": 12,
            },
        ],
        "beforeSubmitPrompt": [
            {
                "command": f'"{PYW}" "{os.path.join(ENG, "cursor-fames-hot-refresh.py")}"',
                "timeout": 20,
            },
            {
                "command": f"{PYW} {os.path.join(ENG, 'cursor-fleet-inbox-auto.py')}",
                "timeout": 15,
            },
            {
                "command": f"{PYW} {os.path.join(ENG, 'cursor-mtm-mto-remind.py')}",
                "timeout": 12,
            },
            {
                "command": f"{PYW} {os.path.join(ENG, 'cursor-mtm-hot-inject.py')}",
                "timeout": 20,
            },
            {
                "command": f"{PYW} {os.path.join(ENG, 'cursor-agc-auto-compact.py')}",
                "timeout": 18,
            },
            {
                "command": f"{PYW} {os.path.join(ENG, 'cursor-auto-gate-unblock.py')}",
                "timeout": 18,
            },
            {
                "command": f"{PYW} {os.path.join(ENG, 'cursor-a2a-read-gate.py')}",
                "timeout": 12,
            },
            {
                "command": f"{PYW} {os.path.join(ENG, 'cursor-accountability-gate.py')}",
                "timeout": 12,
            },
            {
                "command": f"{PYW} {RUN_HIDDEN} {os.path.join(ENG, 'hooks', 'prework-gate.ps1')}",
                "timeout": 15,
            },
            {
                "command": f"{PYW} {RUN_HIDDEN} {os.path.join(ENG, 'hooks', 'claim-linter-gate.ps1')}",
                "timeout": 12,
            },
            {
                "command": f"{PYW} {os.path.join(ENG, 'cursor-seal-claim-check.py')}",
                "timeout": 12,
            },
            {
                "command": f"{PYW} {os.path.join(ENG, 'cursor-ztm-broad-gate.py')}",
                "timeout": 12,
            },
            {
                "command": f"{PYW} {os.path.join(ENG, 'cursor-pfkt-gate.py')}",
                "timeout": 12,
            },
        ],
        "preCompact": [
            {
                "command": f"{PYW} {RUN_HIDDEN} {os.path.join(ENG, 'hooks', 'compaction-guard.ps1')}",
                "timeout": 12,
            },
        ],
        "stop": [
            {"command": f"{PYW} {RUN_HIDDEN} {os.path.join(ENG, 'hooks', 'claim-linter-gate.ps1')}", "timeout": 15},
            {"command": f"{PYW} {os.path.join(ENG, 'log_session.py')}", "timeout": 25},
            {"command": f"{PYW} {os.path.join(ENG, 'cursor-seal-finalize.py')}", "timeout": 20},
        ],
        "subagentStop": [
            {"command": f"{PYW} {RUN_HIDDEN} {os.path.join(ENG, 'hooks', 'claim-linter-gate.ps1')}", "timeout": 15},
            {"command": f"{PYW} {os.path.join(ENG, 'log_session.py')}", "timeout": 25},
            {"command": f"{PYW} {os.path.join(ENG, 'cursor-seal-finalize.py')}", "timeout": 20},
        ],
    },
}


def hook_roots():
    import _projects
    seen = set()
    out = []
    for name in _projects.hub_seats():
        meta = _projects.get(name) or {}
        full = meta.get("path")
        if not full or not os.path.isdir(full):
            continue
        if full not in seen:
            seen.add(full)
            out.append((name, full))
        seat_root = full
        for sub in EXTRA_HOOK_ROOTS.get(name) or []:
            p = os.path.join(seat_root, sub.replace("/", os.sep))
            if os.path.isdir(p) and p not in seen:
                seen.add(p)
                out.append((name + "/" + sub.replace("\\", "/").replace("/", "/"), p))
    master = os.path.join(COMMON, "ai_master")
    if os.path.isdir(master) and master not in seen:
        out.append(("ai_master", master))
    return out


def _read_hook_document(target: Path) -> dict:
    doc = json.loads(target.read_text(encoding="utf-8-sig")) if target.is_file() else {}
    if not isinstance(doc, dict) or not isinstance(doc.get("hooks", {}), dict):
        raise RuntimeError(f"Hook configuration is not an object: {target}")
    return doc


def _without_managed_handlers(groups: list, script: str) -> list:
    """Keep unrelated handlers even when sharing a group with a managed hook."""
    kept = []
    for group in groups:
        if not _contains_script(group, script):
            kept.append(group)
            continue
        remaining = [handler for handler in group.get("hooks", [])
                     if not (isinstance(handler, dict) and
                             script.lower() in str(handler.get("command") or "").lower())]
        if remaining:
            kept.append({**group, "hooks": remaining})
    return kept


def write_hooks(path, *, fames_only=False):
    target = Path(path)
    doc = _read_hook_document(target)
    hooks = doc.setdefault("hooks", {})
    doc.setdefault("version", HOOKS["version"])
    fames_scripts = {"cursor-agent-session-open.py", "cursor-fames-hot-refresh.py", "claude-proof-hook.py"}
    for event, entries in HOOKS["hooks"].items():
        wanted = [_fail_open_entry(entry) for entry in entries if not fames_only or any(
            os.path.join(ENG, script).lower() in entry["command"].lower()
            for script in fames_scripts)]
        if not wanted:
            continue
        current = hooks.get(event, [])
        if not isinstance(current, list):
            raise RuntimeError(f"Hook event is not a list: {target}: {event}")
        managed_scripts = [entry["command"].rsplit(ENG, 1)[1].strip('" ')
                           for entry in wanted]
        preserved = [entry for entry in current if not (isinstance(entry, dict) and any(
            (ENG + script).lower() in str(entry.get("command") or "").lower()
            for script in managed_scripts))]
        hooks[event] = [*wanted, *preserved]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if _read_hook_document(target) != doc:
        raise RuntimeError(f"Cursor hook read-back mismatch: {target}")
    return {"hook_sha": hashlib.sha256(target.read_bytes()).hexdigest(), "hook_read_back": True}


def _turn_rule() -> str:
    harness_path = Path(COMMON) / "_harness" / "runtime" / "fames_session_harness.py"
    spec = importlib.util.spec_from_file_location("fames_session_harness_rule", harness_path)
    if not harness_path.is_file() or spec is None or spec.loader is None:
        raise RuntimeError(f"missing FAMES session harness: {harness_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fames_script = Path(COMMON) / "_skill" / "fleet-skills" / "fames" / "scripts" / "fames_fleet.py"
    rule, contract, diagnostic = module.render_turn_rule(fames_script)
    if not rule or contract.get("state") != "PASS":
        raise RuntimeError(diagnostic or "FAMES RB/Ti turn rule is UNKNOWN")
    return rule


def write_turn_rule(root: str, rule: str) -> dict:
    path = Path(root) / ".cursor" / "rules" / "fames-rb-ti.mdc"
    path.parent.mkdir(parents=True, exist_ok=True)
    current = path.read_text(encoding="utf-8-sig") if path.is_file() else None
    if current != rule:
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(rule)
    read_back = path.read_text(encoding="utf-8-sig")
    if read_back != rule:
        raise RuntimeError(f"FAMES RB/Ti rule read-back mismatch: {path}")
    return {
        "rule_path": str(path),
        "rule_sha": hashlib.sha256(read_back.encode("utf-8")).hexdigest(),
        "rule_read_back": True,
    }


def _codex_hook_command(exe: str, script: str) -> str:
    # Codex never started a hook command that opens with a quote: `"pythonw.exe" "hook.py"` fails
    # under both `cmd /C` (outer quotes stripped) and `powershell -Command` (two bare strings),
    # while the SessionStart shape `python "hook.py"` runs. Keep the first token unquoted.
    if not exe or '"' in exe or any(ch.isspace() for ch in exe):
        raise RuntimeError(f"Codex hook launcher must be an unquoted path without whitespace: {exe!r}")
    return fail_open_command(f"{exe} {script}")


def _codex_fames_group() -> dict:
    return {
        "hooks": [{
            "type": "command",
            "command": _codex_hook_command(PYW, FAMES_CONTEXT_HOOK),
            "timeout": 20,
            "additionalContextLimit": 5000,
        }]
    }


def _contains_fames_context_hook(group: object) -> bool:
    if not isinstance(group, dict):
        return False
    return any(
        isinstance(handler, dict)
        and FAMES_CONTEXT_HOOK.lower() in str(handler.get("command") or "").lower()
        for handler in group.get("hooks") or []
    )


def write_codex_fames_hook(path: str, write_gate: bool = False) -> dict:
    target = Path(path)
    try:
        doc = json.loads(target.read_text(encoding="utf-8-sig")) if target.is_file() else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Codex hooks are unreadable: {target}: {exc}") from exc
    if not isinstance(doc, dict):
        raise RuntimeError(f"Codex hooks root is not an object: {target}")
    hooks = doc.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise RuntimeError(f"Codex hooks field is not an object: {target}")
    current = hooks.get("UserPromptSubmit")
    if current is not None and not isinstance(current, list):
        raise RuntimeError(f"Codex UserPromptSubmit is not a list: {target}")
    groups = list(current) if isinstance(current, list) else []
    hooks["UserPromptSubmit"] = [
        _codex_fames_group(),
        *_without_managed_handlers(groups, FAMES_CONTEXT_HOOK),
    ]
    pre = hooks.get("PreToolUse")
    if pre is not None and not isinstance(pre, list):
        raise RuntimeError(f"Codex PreToolUse is not a list: {target}")
    # The PROOF write gate lives only in ~/.codex/hooks.json: it already applies in every cwd, and Codex
    # makes the operator review each new handler per file, so one copy means one review.
    kept = _without_managed_handlers(list(pre or []), CLAUDE_PROOF_HOOK)
    if write_gate and os.path.isfile(CLAUDE_PROOF_HOOK):
        kept = [{"hooks": [{"type": "command", "command": _codex_hook_command(PYW, CLAUDE_PROOF_HOOK),
                            "timeout": 10}]}, *kept]
    if kept:
        hooks["PreToolUse"] = kept
    else:
        hooks.pop("PreToolUse", None)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    read_back = json.loads(target.read_text(encoding="utf-8-sig"))
    installed = [
        group for group in (read_back.get("hooks") or {}).get("UserPromptSubmit") or []
        if _contains_fames_context_hook(group)
    ]
    if len(installed) != 1:
        raise RuntimeError(f"Codex FAMES hook read-back mismatch: {target}")
    data = target.read_bytes()
    return {"path": str(target), "sha": hashlib.sha256(data).hexdigest(), "read_back": True}


# A hook must never lock a session (operator 2026-10-08). `python "hook.py"` exits 2
# when the script is missing, and Claude Code reads exit 2 as a block. This launcher
# runs the script in-process and turns a missing file, a crash or any SystemExit into
# exit 0; whatever the script printed before that still reaches Claude. -P keeps the
# session cwd off sys.path, and the script's own folder takes its usual sys.path[0].
CLAUDE_FAIL_OPEN = (
    "with __import__('contextlib').suppress(Exception,SystemExit):"
    "import os,runpy,sys;sys.argv=sys.argv[1:];"
    "sys.path.insert(0,os.path.dirname(sys.argv[0]));"
    "runpy.run_path(sys.argv[0],run_name='__main__')"
)


def claude_hook_command(script: str) -> str:
    return f'"{PYW}" -P -c "{CLAUDE_FAIL_OPEN}" "{script}"'


def fail_open_command(command: str) -> str:
    """Cursor/Codex form of the same launcher: `<exe> <script> [args]` -> fail-open, first token unquoted.

    Codex never starts a command that opens with a quote, and none of these paths contain whitespace.
    """
    exe, *args = [part.strip('"') for part in command.split()]
    if not args or any(ch.isspace() for ch in exe):
        raise RuntimeError(f"cannot wrap hook command: {command!r}")
    return f'{exe} -P -c "{CLAUDE_FAIL_OPEN}" ' + " ".join(f'"{arg}"' for arg in args)


def _fail_open_entry(entry: dict) -> dict:
    """No hook is failClosed, and a missing or broken script exits 0 (operator 2026-10-08)."""
    out = {key: value for key, value in entry.items() if key != "failClosed"}
    out["command"] = fail_open_command(entry["command"])
    return out


def _claude_command_group(script: str, timeout: int, event: str = "") -> dict:
    plain = CLAUDE_PLAIN_COMMANDS.get(script)
    if plain:
        args, extra = plain
        handler = {"type": "command",
                   "command": f'"{PYW}" -P "{script}" ' + " ".join(args),
                   **extra, "timeout": timeout}
    else:
        handler = {"type": "command", "command": claude_hook_command(script), "timeout": timeout}
    group = {"hooks": [handler]}
    matcher = CLAUDE_MATCHERS.get((event, script))
    return {"matcher": matcher, **group} if matcher else group


def _contains_script(group: object, script: str) -> bool:
    if not isinstance(group, dict):
        return False
    return any(
        isinstance(handler, dict)
        and script.lower() in str(handler.get("command") or "").lower()
        for handler in group.get("hooks") or []
    )


def write_claude_fames_hooks(path: str) -> dict:
    """Merge context injection and claim gates without deleting user hooks."""
    target = Path(path)
    try:
        doc = json.loads(target.read_text(encoding="utf-8-sig")) if target.is_file() else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Claude settings are unreadable: {target}: {exc}") from exc
    if not isinstance(doc, dict):
        raise RuntimeError(f"Claude settings root is not an object: {target}")
    hooks = doc.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise RuntimeError(f"Claude hooks field is not an object: {target}")

    for event, script in CLAUDE_RETIRED_HOOKS:
        if isinstance(hooks.get(event), list):
            hooks[event] = _without_managed_handlers(hooks[event], script)
            if not hooks[event]:
                del hooks[event]
    wanted = claude_managed_hooks()
    by_event: dict = {}
    for event, script, timeout in wanted:
        by_event.setdefault(event, []).append((script, timeout))
    for event, scripts in by_event.items():
        current = hooks.get(event)
        if current is not None and not isinstance(current, list):
            raise RuntimeError(f"Claude hook event is not a list: {target}: {event}")
        groups = list(current) if isinstance(current, list) else []
        for script, _timeout in scripts:
            groups = _without_managed_handlers(groups, script)
        hooks[event] = [
            *(_claude_command_group(script, timeout, event) for script, timeout in scripts),
            *groups,
        ]

    # F1S auto-mode posture rides the same write: the classifier rows every host must carry (operator 2026-10-31).
    expected_auto = auto_mode_expected(auto_mode_posture())
    render_auto_mode(doc, expected_auto)

    target.parent.mkdir(parents=True, exist_ok=True)
    staged = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    with staged.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(staged, target)
    read_back = json.loads(target.read_text(encoding="utf-8-sig"))
    for event, script, _timeout in wanted:
        installed = [
            group for group in (read_back.get("hooks") or {}).get(event) or []
            if _contains_script(group, script)
        ]
        if len(installed) != 1:
            raise RuntimeError(f"Claude FAMES hook read-back mismatch: {target}: {event}")
    auto_back = read_back.get("autoMode") or {}
    for key in AUTO_MODE_KEYS:
        have = {_am_norm(r) for r in (auto_back.get(key) or []) if isinstance(r, str)}
        if any(w not in have for w in expected_auto.get(key) or []):
            raise RuntimeError(f"Claude autoMode read-back mismatch: {target}: {key}")
    data = target.read_bytes()
    return {"path": str(target), "sha": hashlib.sha256(data).hexdigest(), "read_back": True,
            "stop_hooks": [os.path.basename(s) for e, s, _t in wanted if e == "Stop"],
            "auto_mode": {k: len(v) for k, v in expected_auto.items()}}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["--claude-only"]:
        claude_global = write_claude_fames_hooks(
            os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
        )
        print("sync-cursor-hooks: Claude FAMES context + claim gates -> %s" % claude_global["path"])
        return 0
    fames_only = argv == ["--fames-only"]
    if argv and not fames_only:
        raise SystemExit("usage: sync-cursor-hooks.py [--claude-only|--fames-only]")
    written = []
    codex_written = []
    rule = _turn_rule()
    roots = hook_roots()
    for label, root in roots:
        path = os.path.join(root, ".cursor", "hooks.json")
        row = {"agent": label, "path": path}
        row.update(write_hooks(path, fames_only=fames_only))
        row.update(write_turn_rule(root, rule))
        written.append(row)
        codex_row = {"agent": label}
        codex_row.update(write_codex_fames_hook(os.path.join(root, ".codex", "hooks.json")))
        codex_written.append(codex_row)
    user_hooks = os.path.join(os.path.expanduser("~"), ".cursor", "hooks.json")
    global_cursor = {"agent": "~/.cursor (global)", "path": user_hooks}
    global_cursor.update(write_hooks(user_hooks, fames_only=fames_only))
    written.append(global_cursor)
    codex_root = {"agent": "workspace-root"}
    codex_root.update(write_codex_fames_hook(os.path.join(COMMON, ".codex", "hooks.json")))
    codex_written.append(codex_root)
    codex_global = {"agent": "~/.codex (global)"}
    codex_global.update(write_codex_fames_hook(os.path.join(os.path.expanduser("~"), ".codex", "hooks.json"),
                                               write_gate=True))
    codex_written.append(codex_global)
    claude_global = write_claude_fames_hooks(
        os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
    )
    reg = os.path.join(REGISTRY, "cursor-hooks-sync.json")
    doc = {
        "generated": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "scope": "fames-only" if fames_only else "all-managed-hooks",
        "configuration_read_back": True,
        "runtime_activation": "UNKNOWN_REQUIRES_ACTUAL_HOST_EVENT",
        "cursor_unregistered_cwd": "UNKNOWN_REQUIRES_CURRENT_TURN_RULE",
        "seats": written,
        "count": len(written),
        "format": "cursor-native (continue/user_message)",
        "pythonw": PYW,
        "turn_rule_sha": hashlib.sha256(rule.encode("utf-8")).hexdigest(),
        "turn_rule_count": sum(1 for row in written if row.get("rule_read_back") is True),
        "codex_user_prompt_submit": codex_written,
        "codex_hook_count": sum(1 for row in codex_written if row.get("read_back") is True),
        "claude_fames_hooks": claude_global,
    }
    with open(reg, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    hub_python.write_stamp()
    print("sync-cursor-hooks: pythonw=%s" % PYW)
    print("sync-cursor-hooks: %d hook.json paths (Cursor-native)" % len(written))
    for w in written:
        print("  ", w["agent"], "->", w["path"])
    print("sync-cursor-hooks: %d Codex UserPromptSubmit paths" % len(codex_written))
    print("sync-cursor-hooks: Claude FAMES context + claim gates -> %s" % claude_global["path"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
