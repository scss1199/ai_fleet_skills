#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# token-class: ZT
"""beforeSubmitPrompt: read back the always-applied FAMES RB/Ti rule every turn.

Cursor's event can allow or block but cannot inject context.  The project rule is the
injection path; this hook is its fail-closed freshness and receipt gate.
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
        turn = _harness().turn_context(
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
                "FAMES RB/Ti turn gate is UNKNOWN. The prompt was not sent because the "
                "active package, parity, session identity, or always-applied rule did not read back. "
                f"Receipt: {turn.get('state_path') or 'UNKNOWN'}"
            )
    except Exception as exc:
        cio.emit_deny(
            f"FAMES RB/Ti turn gate failed closed ({type(exc).__name__}). "
            "The prompt was not sent; repair the on-disk gate before retrying."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
