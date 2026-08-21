#!/usr/bin/env python3
from __future__ import annotations
import importlib.util
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
HUB=Path(os.environ.get("AI_WORKSPACE",r"C:\ai_workspace")); STATUS=HUB/"_registry"/"token-preflight"/"claude-hook-status.json"; CODEX_STATUS=HUB/"_registry"/"token-preflight"/"codex-hook-status.json"


def _harness():
    path = HUB / "_harness" / "runtime" / "fames_session_harness.py"
    spec = importlib.util.spec_from_file_location("fames_session_harness", path)
    if not path.is_file() or spec is None or spec.loader is None:
        raise RuntimeError(f"missing FAMES harness: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    try: doc=json.load(sys.stdin)
    except Exception: doc={}
    cwd=str(doc.get("cwd") or os.getcwd()); agent="ai_"+Path(cwd).name[3:] if Path(cwd).name.startswith("ai_") else Path(cwd).name
    event=str(doc.get("hook_event_name") or "SessionStart")
    session_id=str(doc.get("session_id") or doc.get("conversation_id") or "")
    codex_marked=bool(doc.get("model") or doc.get("turn_id") or "permission_mode" in doc or "transcript_path" in doc)
    surface_id="open-agent-standard" if codex_marked else "claude"
    token_core=(f"TOKEN CORE {agent}: keep only outcome, verification, state, next action, blocker. "
                "Run token-preflight before broad reads. PFKT only for independent units; "
                "AEX only after verified residual. UNKNOWN is not clear.")
    try:
        harness=_harness()
        if event == "UserPromptSubmit":
            prompt=str(doc.get("prompt") or doc.get("user_message") or doc.get("message") or "")
            if surface_id == "open-agent-standard":
                runtime_event_observed=bool(
                    session_id.strip() and prompt.strip() and str(doc.get("turn_id") or "").strip()
                    and str(doc.get("model") or "").strip()
                    and str(doc.get("permission_mode") or "").strip()
                    and "transcript_path" in doc and str(doc.get("cwd") or "").strip()
                    and doc.get("fames_probe_mode") not in {"direct", "synthetic"}
                )
            else:
                runtime_event_observed=bool(
                    session_id.strip() and prompt.strip() and str(doc.get("cwd") or "").strip()
                    and doc.get("fames_probe_mode") not in {"direct", "synthetic"}
                )
            result=harness.turn_context(
                agent,
                Path(cwd),
                prompt=prompt,
                surface_id=surface_id,
                session_id=session_id,
                adapter_mode="same_turn_context_injection",
                adapter_path=Path(__file__),
                workspace=HUB,
                runtime_event_observed=runtime_event_observed,
                activation_evidence=("lifecycle_hook" if runtime_event_observed else "invalid_hook_payload"),
            )
            context=(token_core+"\n"+result.get("plan_text", "")).strip()
            state=result.get("state")
        else:
            result=harness.run_session(agent, Path(cwd), HUB)
            harness.hot_refresh(
                agent, Path(cwd), surface_id=surface_id, session_id=session_id,
                workspace=HUB, acknowledge=True,
            )
            context=(token_core+"\n"+result.get("plan_text", "")).strip()
            state=result.get("state")
    except Exception as exc:
        state="UNKNOWN"
        context=token_core+f"\nFAMES ALWAYS-ON — UNKNOWN — {type(exc).__name__}"
    status_path=CODEX_STATUS if surface_id == "open-agent-standard" else STATUS
    status_path.parent.mkdir(parents=True,exist_ok=True); status_path.write_text(json.dumps({"schema":3,"last_fired":datetime.now(timezone.utc).isoformat(),"event":event,"cwd":cwd,"agent":agent,"surface_id":surface_id,"runtime_event_observed":bool(locals().get("runtime_event_observed", False)),"fames_state":state},indent=2),encoding="utf-8")
    if context:
        # ASCII JSON keeps the hook envelope valid under Windows cp950 consoles;
        # Claude decodes the \u escapes back into the original context text.
        print(json.dumps({"hookSpecificOutput":{"hookEventName":event,"additionalContext":context}},ensure_ascii=True))
    else:
        print("{}")
    return 0
if __name__=="__main__": raise SystemExit(main())
