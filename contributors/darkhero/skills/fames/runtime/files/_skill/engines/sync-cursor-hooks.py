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
                "failClosed": True,
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
    fames_scripts = {"cursor-agent-session-open.py", "cursor-fames-hot-refresh.py"}
    for event, entries in HOOKS["hooks"].items():
        wanted = [entry for entry in entries if not fames_only or any(
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
    return f'{exe} "{script}"'


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


def write_codex_fames_hook(path: str) -> dict:
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


def _claude_command_group(script: str, timeout: int) -> dict:
    return {
        "hooks": [{
            "type": "command",
            "command": f'"{PYW}" "{script}"',
            "timeout": timeout,
        }]
    }


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

    wanted = {
        "SessionStart": (FAMES_CONTEXT_HOOK, 10),
        "UserPromptSubmit": (FAMES_CONTEXT_HOOK, 20),
        "Stop": (CLAUDE_CLAIM_INTEGRITY_HOOK, 15),
        "SubagentStop": (CLAUDE_CLAIM_INTEGRITY_HOOK, 15),
    }
    for event, (script, timeout) in wanted.items():
        current = hooks.get(event)
        if current is not None and not isinstance(current, list):
            raise RuntimeError(f"Claude hook event is not a list: {target}: {event}")
        groups = list(current) if isinstance(current, list) else []
        hooks[event] = [
            _claude_command_group(script, timeout),
            *_without_managed_handlers(groups, script),
        ]

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    read_back = json.loads(target.read_text(encoding="utf-8-sig"))
    for event, (script, _timeout) in wanted.items():
        installed = [
            group for group in (read_back.get("hooks") or {}).get(event) or []
            if _contains_script(group, script)
        ]
        if len(installed) != 1:
            raise RuntimeError(f"Claude FAMES hook read-back mismatch: {target}: {event}")
    data = target.read_bytes()
    return {"path": str(target), "sha": hashlib.sha256(data).hexdigest(), "read_back": True}


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
    codex_global.update(write_codex_fames_hook(os.path.join(os.path.expanduser("~"), ".codex", "hooks.json")))
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
