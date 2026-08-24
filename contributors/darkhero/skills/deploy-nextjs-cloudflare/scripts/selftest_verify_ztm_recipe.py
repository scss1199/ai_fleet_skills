#!/usr/bin/env python3
"""Negative controls for verify_ztm_recipe.py."""

from __future__ import annotations

import tempfile
from pathlib import Path

from verify_ztm_recipe import ORCHESTRATOR_MARKERS, verify


def write_good(root: Path) -> None:
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "ship.ps1").write_text(
        "param([switch]$Deploy)\npython scripts/ztm-cloudflare-ship.py\n",
        encoding="utf-8",
    )
    source = "\n".join(ORCHESTRATOR_MARKERS.values()) + "\n"
    (root / "scripts" / "ztm-cloudflare-ship.py").write_text(source, encoding="utf-8")


def main() -> int:
    checks = 0
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        write_good(root)
        assert verify(root, "ship.ps1", "scripts/ztm-cloudflare-ship.py")["ok"] is True
        checks += 1

        wrapper = root / "ship.ps1"
        wrapper.write_text("param([switch]$Deploy)\n", encoding="utf-8")
        assert verify(root, "ship.ps1", "scripts/ztm-cloudflare-ship.py")["ok"] is False
        checks += 1

        write_good(root)
        orchestrator = root / "scripts" / "ztm-cloudflare-ship.py"
        orchestrator.write_text(
            orchestrator.read_text(encoding="utf-8").replace("rollback(", "rollback_missing"),
            encoding="utf-8",
        )
        assert verify(root, "ship.ps1", "scripts/ztm-cloudflare-ship.py")["ok"] is False
        checks += 1

        write_good(root)
        with orchestrator.open("a", encoding="utf-8") as handle:
            handle.write("\nshell=True\n")
        assert verify(root, "ship.ps1", "scripts/ztm-cloudflare-ship.py")["ok"] is False
        checks += 1

    print(f"PASS verify_ztm_recipe selftest {checks}/4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
