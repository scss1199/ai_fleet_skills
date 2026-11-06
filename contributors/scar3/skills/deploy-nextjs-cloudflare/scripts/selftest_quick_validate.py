# -*- coding: utf-8 -*-
"""Negative controls for quick_validate.py.

"All checks passed" is worthless unless each check is capable of failing. Every case
below copies the real skill, mutates ONE thing, and asserts the validator rejects it;
the last case is the unmutated copy, which must pass. Nothing here touches the SSOT -
all work happens in a temp directory.

Case `missing_ref` is the one that matters: it reproduces the exact defect that produced
`quick_validate.py` - a SKILL.md naming a file that does not exist - which the upstream
skill-creator frontmatter contract passes without complaint.

Usage:
    python selftest_quick_validate.py
Exit 0 = every check still fires.
"""

import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SSOT = HERE.parent
sys.path.insert(0, str(HERE))

from quick_validate import validate_skill  # noqa: E402


def build(tmp: Path, case: str) -> Path:
    d = tmp / case / SSOT.name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_bytes((SSOT / "SKILL.md").read_bytes())
    for sub in ("scripts", "references", "assets"):
        if (SSOT / sub).is_dir():
            shutil.copytree(SSOT / sub, d / sub)
    return d


def mutate(d: Path, old: str, new: str) -> None:
    body = (d / "SKILL.md").read_text(encoding="utf-8")
    assert old in body, f"anchor not found in SKILL.md: {old!r}"
    (d / "SKILL.md").write_text(body.replace(old, new, 1), encoding="utf-8")


CASES = [
    ("missing_ref", False,
     lambda d: mutate(d, "`quick_validate.py`", "`totally_absent_script.py`")),
    ("deleted_script", False,
     lambda d: (d / "scripts" / "record_failure.py").unlink()),
    ("nested_skill_md", False,
     lambda d: (d / "references" / "SKILL.md").write_text("---\n---\n", encoding="utf-8")),
    ("bad_name_case", False,
     lambda d: mutate(d, "name: deploy-nextjs-cloudflare", "name: Deploy-Nextjs-Cloudflare")),
    ("angle_in_desc", False,
     lambda d: mutate(d, "description: Deploy existing", "description: Deploy <existing>")),
    ("unknown_key", False,
     lambda d: mutate(d, "metadata:", "flavour: banana\nmetadata:")),
    ("no_frontmatter", False,
     lambda d: (d / "SKILL.md").write_text("# no frontmatter\n", encoding="utf-8")),
    ("unmutated_control", True,
     lambda d: None),
]


def main() -> int:
    fails = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for case, expect_ok, mut in CASES:
            d = build(tmp, case)
            mut(d)
            ok, msg = validate_skill(d)
            if ok != expect_ok:
                fails += 1
            print(f"{'PASS' if ok == expect_ok else 'SELFTEST-FAIL':14} "
                  f"{case:18} ok={str(ok):5} {msg[:96]}")
    print(f"SELFTEST_RC={1 if fails else 0}  "
          f"({len(CASES) - fails}/{len(CASES)} cases behaved as specified)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
