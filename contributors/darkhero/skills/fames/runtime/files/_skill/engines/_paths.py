#!/usr/bin/env python3
"""_paths.py — single shared-zone path resolver for all hub engines.

Resolves every shared R/W surface from AI_WORKSPACE (default: inferred from this
file's own location — the hub root two levels up from _skill\engines). One
import replaces scattered hardcoded absolute literals, so engines are
location-portable and the whole shared zone can move by setting one env var.

    from _paths import VAULT, BUS, DOWNLOADS, MATRIX, ROUTING, LOGS, TECHNIQUE_OUTPUT

Resolution order:
  1. env AI_WORKSPACE   (set by `setx AI_WORKSPACE C:\ai_workspace` for future sessions)
  2. env CLAUDE_COMMON  (legacy fallback during transition)
  3. inferred from __file__ (this file at <WORKSPACE>\_skill\engines\_paths.py)
"""
import os
import sys

# Windows consoles default to cp950/cp1252 — fleet JSON/hooks are UTF-8.
if sys.platform == "win32":
    for _stream in (getattr(sys, "stdout", None), getattr(sys, "stderr", None)):
        if _stream is not None and hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

ENGINES = os.path.dirname(os.path.abspath(__file__))            # <WORKSPACE>\_skill\engines
SKILL   = os.path.dirname(ENGINES)                              # <WORKSPACE>\_skill
COMMON  = (os.environ.get("AI_WORKSPACE")
           or os.environ.get("CLAUDE_COMMON")
           or os.path.dirname(SKILL))                           # <WORKSPACE>

# --- neutral shared surfaces (underscore-prefixed, never committed) ---
SECRETS          = os.path.join(COMMON, "_secrets")
VAULT            = os.path.join(SECRETS, "vault.json")
API_MATRIX       = os.path.join(SECRETS, "api-matrix.json")
BUS              = os.path.join(COMMON, "_bus")
DOWNLOADS        = os.path.join(COMMON, "_downloads")
REGISTRY         = os.path.join(COMMON, "_registry")
MATRIX           = os.path.join(REGISTRY, "project-matrix.json")
ROUTING          = os.path.join(REGISTRY, "insight-routing.json")
LOGS             = os.path.join(COMMON, "_logs")
INBOX            = os.path.join(COMMON, "_inbox")
TEMP             = os.path.join(COMMON, "_temp")
TECHNIQUE_OUTPUT = os.path.join(SKILL, "technique_output")
STATE            = os.path.join(BUS, "STATE.md")

if __name__ == "__main__":
    for k in ("COMMON","SECRETS","VAULT","API_MATRIX","BUS","DOWNLOADS","REGISTRY",
              "MATRIX","ROUTING","LOGS","INBOX","TEMP","TECHNIQUE_OUTPUT","STATE"):
        v = globals()[k]; print(f"{k:16} {v:50} {'OK' if os.path.exists(v) else 'MISSING'}")
