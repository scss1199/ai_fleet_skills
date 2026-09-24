"""Thin DSH lifecycle adapter; no provider calls or persisted prompt content."""
import json
import hashlib
import sys
from pathlib import Path

from fames_session_harness import turn_context

WORKSPACE = Path(__file__).resolve().parents[2]


def agent_for_cwd(cwd):
    """Keep workspace seat identity; isolate external roots without name collisions."""
    try:
        relative = cwd.relative_to(WORKSPACE.resolve())
    except ValueError:
        return "external-" + hashlib.sha256(str(cwd).encode("utf-8")).hexdigest()[:16]
    if not relative.parts:
        return "ai_master"
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in relative.parts[0])


def handle(doc):
    if not isinstance(doc, dict):
        raise ValueError("invalid hook payload")
    raw_cwd = doc.get("cwd")
    if not isinstance(raw_cwd, str) or not raw_cwd.strip() or not Path(raw_cwd).is_absolute():
        raise ValueError("hook requires an absolute cwd")
    cwd = Path(raw_cwd).resolve(strict=True)
    if not cwd.is_dir():
        raise ValueError("hook cwd must be an existing directory")
    observed = bool(doc.get("hook_event_name") == "UserPromptSubmit"
                    and doc.get("session_id") and doc.get("turn_id")
                    and doc.get("prompt") and doc.get("activation_source") == "dsh-agent-pre-step"
                    and doc.get("probe_mode") not in {"direct", "synthetic"})
    result = turn_context(agent_for_cwd(cwd), cwd, prompt=str(doc.get("prompt") or ""),
        surface_id="dsh", session_id=str(doc.get("session_id") or ""),
        adapter_mode="same_turn_context_injection", adapter_path=Path(__file__),
        workspace=WORKSPACE, runtime_event_observed=observed,
        activation_evidence="lifecycle_hook" if observed else "direct_probe")
    return {"state": result["state"], "context": result["plan_text"],
            "receipt_path": result["state_path"], "raw_prompt_persisted": False}


if __name__ == "__main__":
    try:
        raw = sys.stdin.buffer.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("oversized payload")
        print(json.dumps(handle(json.loads(raw)), ensure_ascii=True))
    except Exception:
        print(json.dumps({"state": "UNKNOWN", "context": "FAMES DSH intake UNKNOWN: lifecycle adapter failed; do not claim completion."}))
        sys.exit(2)
