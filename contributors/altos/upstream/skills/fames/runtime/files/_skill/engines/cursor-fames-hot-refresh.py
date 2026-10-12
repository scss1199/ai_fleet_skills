#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# token-class: ZT
"""beforeSubmitPrompt: read back the always-applied FAMES RB/Ti rule every turn.

Cursor's event can allow or block but cannot inject context.  The project rule is the
injection path; this hook is its freshness and receipt check, advisory only since 2026-10-08
(operator): an UNKNOWN turn is reported to the user and the prompt still goes through.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ENG = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENG)

import cursor_hook_io as cio
from _paths import COMMON as HUB


def _harness():
    path = Path(HUB) / "_harness" / "runtime" / "fames_session_harness.py"
    spec = importlib.util.spec_from_file_location("fames_session_harness", path)
    if not path.is_file() or spec is None or spec.loader is None:
        raise RuntimeError(f"missing FAMES harness: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    doc = cio.read_input()
    cwd = cio.workspace_cwd(doc)
    agent = cio.resolve_agent(cwd)
    session_id = str(
        doc.get("session_id") or doc.get("conversation_id") or doc.get("chat_id")
        or ""
    )
    prompt = cio.prompt_text(doc)
    runtime_event_observed = bool(
        session_id.strip() and prompt.strip()
        and doc.get("fames_probe_mode") not in {"direct", "synthetic"}
    )
    try:
        harness = _harness()
        rule_path = Path(cwd) / ".cursor" / "rules" / "fames-rb-ti.mdc"
        try:  # self-heal a stale rule (never raises; the read-back below still reports the result)
            script = Path(HUB) / "_skill" / "fleet-skills" / "fames" / "scripts" / "fames_fleet.py"
            expected, _contract, _diag = harness.render_turn_rule(script)
            current = rule_path.read_text(encoding="utf-8-sig") if rule_path.is_file() else ""
            if expected and rule_path.parent.is_dir() and current != expected:
                stage = rule_path.with_name(rule_path.name + ".tmp")
                stage.write_text(expected, encoding="utf-8", newline="\n")
                os.replace(stage, rule_path)
        except Exception:
            pass
        turn = harness.turn_context(
            agent,
            Path(cwd),
            prompt=prompt,
            surface_id="cursor",
            session_id=session_id,
            adapter_mode="always_apply_rule_with_pre_submit_read_back",
            adapter_path=Path(__file__),
            workspace=Path(HUB),
            rule_path=Path(cwd) / ".cursor" / "rules" / "fames-rb-ti.mdc",
            runtime_event_observed=runtime_event_observed,
            activation_evidence=(
                "always_apply_rule_gate" if runtime_event_observed else "invalid_hook_payload"
            ),
        )
        if turn.get("state") == "PASS":
            cio.emit_allow()
        else:
            cio.emit_deny(
                "FAMES RB/Ti turn check is UNKNOWN: the active package, parity, session identity, "
                "or always-applied rule did not read back. The prompt still goes through; do not claim completion. "
                f"Receipt: {turn.get('state_path') or 'UNKNOWN'}"
            )
    except Exception as exc:
        cio.emit_deny(
            f"FAMES RB/Ti turn check failed ({type(exc).__name__}). "
            "The prompt still goes through; repair the on-disk check when convenient."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
