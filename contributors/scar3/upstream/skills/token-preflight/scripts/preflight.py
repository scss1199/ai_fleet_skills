#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, re, uuid
from datetime import datetime, timezone
from pathlib import Path
HUB=Path(os.environ.get("AI_WORKSPACE",r"C:\ai_workspace")); OUT=HUB/"_registry"/"token-preflight"
def classify(task,outcome,verification):
    t=" ".join(task.split()); low=t.casefold()
    if len(t)<8 or len(t.split())<2: return "UNKNOWN",False,"task lacks a concrete action and object"
    if not outcome.strip(): return "UNKNOWN",False,"missing outcome"
    if not verification.strip(): return "UNKNOWN",False,"missing verification"
    explicit=bool(re.search(r"\b(parallel|subagents?|fan[- ]?out|concurrently)\b|平行|並行",low))
    multi=explicit or len(re.findall(r"\b(and|then|also)\b|以及|並且|然後",low))>=2
    return "READY",multi,""
def main():
    p=argparse.ArgumentParser(); p.add_argument("--agent",required=True); p.add_argument("--task",required=True); p.add_argument("--session",default=""); p.add_argument("--outcome",default=""); p.add_argument("--verification",default=""); p.add_argument("--artifact",action="append",default=[])
    a=p.parse_args(); fp=hashlib.sha256(a.task.strip().encode()).hexdigest()[:16]; status,graph,blocker=classify(a.task,a.outcome,a.verification)
    hashes={}
    for raw in a.artifact:
        q=Path(raw); hashes[str(q)]=hashlib.sha256(q.read_bytes()).hexdigest() if q.is_file() else None
    seal=status=="READY" and bool(a.outcome.strip()) and bool(a.verification.strip())
    doc={"schema":1,"ts":datetime.now(timezone.utc).isoformat(),"agent":a.agent,"session":a.session,"task_fingerprint":fp,"artifact_hashes":hashes,"outcome":a.outcome.strip(),"verification":a.verification.strip(),"skill_id":"token-preflight","skill_version":"2","status":status,"hot_context":["outcome","verification","state","next_action","blocker"],"activate":{"FP":True,"MTM":True,"PFKT":graph,"SCF":False,"SEAL":seal,"AEX":False},"read_budget":"TR1 before TRN","blocker":blocker}
    OUT.mkdir(parents=True,exist_ok=True); sid=re.sub(r"[^A-Za-z0-9_.-]+","_",a.session)[:40] or uuid.uuid4().hex[:12]; path=OUT/f"{a.agent}-{fp}-{sid}.json"; path.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding="utf-8"); doc["receipt_path"]=str(path); print(json.dumps(doc,ensure_ascii=False)); return 2 if status=="UNKNOWN" else 0
if __name__=="__main__": raise SystemExit(main())