#!/usr/bin/env python3
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
HUB=Path(os.environ.get("AI_WORKSPACE",r"C:\ai_workspace")); STATUS=HUB/"_registry"/"token-preflight"/"claude-hook-status.json"
def main():
    try: doc=json.load(sys.stdin)
    except Exception: doc={}
    cwd=str(doc.get("cwd") or os.getcwd()); agent="ai_"+Path(cwd).name[3:] if Path(cwd).name.startswith("ai_") else Path(cwd).name
    text=(f"TOKEN CORE {agent}: keep only outcome, verification, state, next action, blocker. "
          "Run token-preflight before broad reads. PFKT only for independent units; AEX only after verified residual. UNKNOWN is not clear.")
    STATUS.parent.mkdir(parents=True,exist_ok=True); STATUS.write_text(json.dumps({"schema":1,"last_fired":datetime.now(timezone.utc).isoformat(),"event":"SessionStart","cwd":cwd,"agent":agent},indent=2),encoding="utf-8")
    print(json.dumps({"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":text}},ensure_ascii=False)); return 0
if __name__=="__main__": raise SystemExit(main())