#!/usr/bin/env python3
"""Persistent, secret-free circuit state for shared free API providers."""
import argparse,json,os,re,tempfile,threading,time
from pathlib import Path
DEFAULT=Path(os.environ.get("AI_WORKSPACE",r"C:\ai_workspace"))/"_registry"/"free-api-health.json"
BILLING=re.compile(r"402|budget exhausted|insufficient[_ ]quota|credit balance|payment required",re.I)
class CircuitStore:
 def __init__(self,path=DEFAULT,threshold=2,cooldown=900,base=60,billing_cooldown=86400): self.path=Path(path); self.threshold=threshold; self.cooldown=cooldown; self.base=base; self.billing_cooldown=billing_cooldown; self.data=self._load()
 def _load(self):
  try:
   x=json.loads(self.path.read_text(encoding="utf-8")); return x if isinstance(x,dict) else {"version":1,"providers":{}}
  except (OSError,ValueError): return {"version":1,"providers":{}}
 def _refresh(self):
  """Re-read before a write: every Pool process loads the file once and saved its WHOLE dict, so a long-lived
  process put back other providers' stale entries (2026-10-27: an old open window outlived a later `ok`)."""
  disk=self._load().get("providers",{})
  if disk: self.data.setdefault("providers",{}).update(disk)
 def _entry(self,p): return self.data.setdefault("providers",{}).setdefault(p,{"failures":0,"open_until":0})
 def allowed(self,p,now=None): return float(self._entry(p).get("open_until",0)) <= (time.time() if now is None else now)
 _lock=threading.RLock()   # Pool.fan_out records from worker threads; json.dump must not see a dict mid-update
 def record(self,p,ok,detail="",now=None):
  with self._lock:
   self._refresh()
   now=time.time() if now is None else now; e=self._entry(p); e.update(last_checked=int(now),last_result="ok" if ok else "error",detail=detail[:160])
   if ok: e.update(failures=0,open_until=0)
   else:
    e["failures"]=int(e.get("failures",0))+1
    # 2026-10-27: a flat 900 s window shut gemini (the one steady provider) for 15 min after two 503 "high demand"
    # replies that cleared within seconds. Back off exponentially instead: 60 s, 120 s, ... capped at `cooldown`.
    if e["failures"]>=self.threshold: e["open_until"]=int(now+min(self.cooldown,self.base*2**(e["failures"]-self.threshold)))
    # 2026-11-01: mistral answered 402 "API budget exhausted" 380 times at the 15-min cap. An account budget does not
    # clear in minutes, so billing-class refusals hold the circuit open for a day instead of re-probing ~96x/day.
    if BILLING.search(detail or ""): e["open_until"]=int(now+self.billing_cooldown)
   self.save()
 def note(self,p,result,detail="",now=None):
  """Record a state that is not a call failure (e.g. `no-credentials`): never counts toward the threshold and
  never opens the circuit, so an empty key pool stops masquerading as a failing provider (2026-10-27 audit)."""
  with self._lock:
   self._refresh()
   now=time.time() if now is None else now; e=self._entry(p); e.update(last_checked=int(now),last_result=result,detail=detail[:160],failures=0,open_until=0)
   self.save()
 def save(self):
  self.path.parent.mkdir(parents=True,exist_ok=True); fd,name=tempfile.mkstemp(prefix=self.path.name,suffix=".tmp",dir=self.path.parent)
  try:
   with os.fdopen(fd,"w",encoding="utf-8") as f: json.dump(self.data,f,ensure_ascii=False,indent=2,sort_keys=True)
   os.replace(name,self.path)
  finally:
   if os.path.exists(name): os.unlink(name)
 def report(self):
  now=time.time(); ps={}
  for p,e in sorted(self.data.get("providers",{}).items()): ps[p]={"state":"open" if e.get("open_until",0)>now else "closed","failures":e.get("failures",0),"retry_after_seconds":max(0,int(e.get("open_until",0)-now)),"last_checked":e.get("last_checked"),"last_result":e.get("last_result","unknown"),"detail":e.get("detail","")}
  status="UNKNOWN" if not ps else ("DEGRADED" if any(x["last_result"]!="ok" or x["state"]=="open" for x in ps.values()) else "OK")
  return {"status":status,"providers":ps}
def main():
 p=argparse.ArgumentParser(); p.add_argument("status",nargs="?",default="status"); p.add_argument("--state",type=Path,default=DEFAULT); a=p.parse_args(); print(json.dumps(CircuitStore(a.state).report(),ensure_ascii=False,indent=2)); return 0
if __name__=="__main__": raise SystemExit(main())
