#!/usr/bin/env python3
"""_secrets.py — single accessor for the central secret vault (all projects).

Vault: 00-meta/.secrets/vault.json (gitignored). LLM keys stay in api-matrix.json.
Usage:
    import _secrets
    key = _secrets.get("fathom.api_key")          # dotted path
    _secrets.set("social.instagram.password","x") # write (persists to disk)

SECURITY: never print returned values into an LLM/agent context. Read -> use in a
script -> keep on disk. List names with _secrets.keys() (paths only, no values).
"""
import os,sys,json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import VAULT  # resolves to %AI_WORKSPACE%\_secrets\vault.json (default C:\ai_workspace)

def _load():
    if not os.path.exists(VAULT): return {}
    return json.loads(open(VAULT,encoding="utf-8-sig").read())

def _save(d):
    os.makedirs(os.path.dirname(VAULT),exist_ok=True)
    open(VAULT,"w",encoding="utf-8").write(json.dumps(d,ensure_ascii=False,indent=2))

def get(path,default=None):
    cur=_load()
    for k in path.split("."):
        if isinstance(cur,dict) and k in cur: cur=cur[k]
        else: return default
    return cur

def set(path,value):
    d=_load(); cur=d
    parts=path.split(".")
    for k in parts[:-1]:
        cur=cur.setdefault(k,{})
    cur[parts[-1]]=value; _save(d); return True

def keys(prefix=""):
    """Return dotted paths to leaf values (NAMES only, never values)."""
    out=[]
    def walk(node,pfx):
        if isinstance(node,dict):
            for k,v in node.items():
                if k.startswith("_"): continue
                walk(v,f"{pfx}.{k}" if pfx else k)
        else:
            out.append(pfx)
    walk(_load(),"")
    return sorted(p for p in out if p.startswith(prefix))

if __name__=="__main__":
    import sys
    if len(sys.argv)>1 and sys.argv[1]=="--list":
        print("vault paths (names only):")
        for p in keys(): print("  "+p)
    else:
        print(__doc__)
