#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quick validation for this skill's SKILL.md.

Why this file exists: SKILL.md has named `quick_validate.py` in its MTM completion
evidence since the skill was created, and Rule 13 requires running "the skill quick
validation" after every material change - but the script was never shipped with the
skill. Measured 2026-08-08: the only `quick_validate.py` on this machine sat inside
`_delete\\claude-pre0513-20260711\\...\\skills\\skill-creator\\scripts\\`, i.e. a
quarantined copy of the upstream skill-creator plugin, and every live hit was the same
evidence line copied into per-agent SKILL.md mirrors. A completion checklist that cites
an absent script cannot be discharged, only asserted.

Two groups of checks:

  1. the upstream skill-creator frontmatter contract (exactly one SKILL.md, parseable
     YAML frontmatter, allowed keys only, kebab-case name <= 64 chars, description
     <= 1024 chars with no angle brackets);

  2. reference resolution - every `*.py` / `*.md` file named in a backtick code span in
     SKILL.md must actually exist somewhere reachable. This is the check that catches
     the failure above: a skill whose own instructions point at a missing script is
     broken whether or not its frontmatter is perfect.

SSOT is `%AI_WORKSPACE%\\_skill\\fleet-skills\\<skill>`. The per-agent `.cursor/skills`
copies are discovery mirrors (SKILL.md "Hard gates"); validate the SSOT, then let
`_skill/engines/fleet-skill-sync.py` propagate.

Usage:
    python quick_validate.py [skill_directory]      # defaults to this script's parent skill
Exit 0 = valid.
"""

import os
import re
import sys
from pathlib import Path

import yaml

EXCLUDED_DIR_PARTS = {"__pycache__", "node_modules"}
ROOT_EXCLUDED_DIR_PARTS = {"evals"}
ALLOWED_PROPERTIES = {
    "name", "description", "license", "allowed-tools", "metadata", "compatibility",
}
# Backtick code spans only. Prose that merely mentions a filename is not a reference
# the skill asks anyone to run.
CODE_SPAN = re.compile(r"`([^`\n]+)`")


def _counts_as_skill_md(rel_path: Path) -> bool:
    dir_parts = rel_path.parts[:-1]
    if any(part in EXCLUDED_DIR_PARTS for part in dir_parts):
        return False
    if dir_parts and dir_parts[0] in ROOT_EXCLUDED_DIR_PARTS:
        return False
    return True


def _search_roots(skill_path: Path) -> list[Path]:
    roots = [
        skill_path,
        skill_path / "scripts",
        skill_path / "references",
        skill_path / "assets",
    ]
    ws = os.environ.get("AI_WORKSPACE") or r"C:\ai_workspace"
    roots += [Path(ws) / "_skill" / "engines", Path(ws)]
    return roots


def _referenced_files(content: str) -> list[str]:
    """Basenames of *.py / *.md referenced in code spans, deduped, order preserved."""
    out, seen = [], set()
    for span in CODE_SPAN.findall(content):
        for token in re.split(r"[\s\"'()<>,;]+", span):
            if "*" in token or "?" in token:
                continue
            name = re.split(r"[\\/]", token)[-1]
            if not name.lower().endswith((".py", ".md")):
                continue
            # A bare extension is a description of a file class, not a file: SKILL.md
            # legitimately writes `.py` and `.md` when saying which files this check
            # covers. Require a non-empty stem - and split it by hand, because
            # `Path(".py").stem` is ".py", not "": pathlib reads a leading dot as a
            # dotfile name with no suffix, so a pathlib-based guard silently never fires.
            if not name.rsplit(".", 1)[0]:
                continue
            if name not in seen:
                seen.add(name)
                out.append(name)
    return out


def validate_skill(skill_path) -> tuple[bool, str]:
    skill_path = Path(skill_path)

    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        return False, f"SKILL.md not found under {skill_path}"

    packaged = [
        p for p in skill_path.rglob("SKILL.md")
        if _counts_as_skill_md(p.relative_to(skill_path))
    ]
    if len(packaged) > 1:
        extras = sorted(
            str(p.relative_to(skill_path)) for p in packaged
            if p.resolve() != skill_md.resolve()
        )
        return False, (
            f"Found {len(packaged)} SKILL.md files; a skill must contain exactly one at "
            f"<folder>/SKILL.md. Extra: {', '.join(extras)}"
        )

    content = skill_md.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return False, "No parseable YAML frontmatter at the top of SKILL.md"

    try:
        frontmatter = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        return False, f"Invalid YAML in frontmatter: {exc}"
    if not isinstance(frontmatter, dict):
        return False, "Frontmatter must be a YAML mapping"

    unexpected = set(frontmatter) - ALLOWED_PROPERTIES
    if unexpected:
        return False, (
            f"Unexpected frontmatter key(s): {', '.join(sorted(unexpected))}. "
            f"Allowed: {', '.join(sorted(ALLOWED_PROPERTIES))}"
        )
    for field in ("name", "description"):
        if field not in frontmatter:
            return False, f"Missing '{field}' in frontmatter"
        if not isinstance(frontmatter[field], str):
            return False, f"'{field}' must be a string, got {type(frontmatter[field]).__name__}"

    name = frontmatter["name"].strip()
    if not re.match(r"^[a-z0-9-]+$", name):
        return False, f"Name '{name}' must be kebab-case (lowercase, digits, hyphens)"
    if name.startswith("-") or name.endswith("-") or "--" in name:
        return False, f"Name '{name}' cannot start/end with a hyphen or contain '--'"
    if len(name) > 64:
        return False, f"Name is {len(name)} characters; maximum is 64"
    if name != skill_path.resolve().name:
        return False, f"Name '{name}' does not match its directory '{skill_path.resolve().name}'"

    description = frontmatter["description"].strip()
    if "<" in description or ">" in description:
        return False, "Description cannot contain angle brackets"
    if len(description) > 1024:
        return False, f"Description is {len(description)} characters; maximum is 1024"

    compatibility = frontmatter.get("compatibility")
    if compatibility is not None:
        if not isinstance(compatibility, str):
            return False, f"Compatibility must be a string, got {type(compatibility).__name__}"
        if len(compatibility) > 500:
            return False, f"Compatibility is {len(compatibility)} characters; maximum is 500"

    roots = _search_roots(skill_path)
    missing = [
        ref for ref in _referenced_files(content)
        if not any((root / ref).is_file() for root in roots)
    ]
    if missing:
        return False, (
            "SKILL.md references file(s) that do not exist in the skill, in "
            f"%AI_WORKSPACE%\\_skill\\engines, or at the workspace root: {', '.join(missing)}. "
            "Ship the file or correct the reference; an instruction pointing at a missing "
            "script cannot be followed."
        )

    return True, (
        f"Skill is valid: {skill_path.resolve().name} "
        f"({len(_referenced_files(content))} referenced file(s) all resolved)"
    )


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
    ok, message = validate_skill(target)
    print(message)
    sys.exit(0 if ok else 1)
