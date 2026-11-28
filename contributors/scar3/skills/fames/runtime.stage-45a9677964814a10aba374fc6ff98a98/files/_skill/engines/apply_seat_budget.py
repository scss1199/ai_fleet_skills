#!/usr/bin/env python3
r"""apply_seat_budget.py -- what a seat's conversations pay for without using it, cut in the seat's own project files.

Measured 2026-11-03 over the 2.5 days after the 300K window (weighted, deduplicated by message id): 257M in all, of
which 103M was one ai_nuwa conversation's general-purpose subagents, all on Opus. Every call also re-reads a floor of
about 97K tokens, 36K system tools and 20-31K MCP tools among them, and most seats never call several of those tools.

Three project-level edits, nothing under ~/.claude:
  .claude/agents/general-purpose.md   the default subagent runs on Sonnet; a caller passes model "opus" for judgment.
  .claude/agents/<other>.md           a `model: opus` / `model: fable` pin becomes `model: sonnet` (2026-11-16: ai_trader's
                                      10.4M of 14.5M in two days ran in five named agents pinned to Opus, called with no
                                      model). The caller still passes model "opus" for judgment; an agent that must stay
                                      pinned carries the frontmatter comment `# seat-budget: keep`.
  .claude/settings.json               permissions.deny lists each DENIABLE tool with no call from this seat in 30 days.

A seat that needs a denied tool again: delete its row from permissions.deny. Reruns keep rows the engine did not write.
Takes effect at each session's next process start.
usage: python apply_seat_budget.py [--dry-run]
"""
import argparse
import glob
import json
import os
import re
import time

HUB = r"C:\ai_workspace"
PROJECTS = os.path.expanduser(r"~\.claude\projects")
SKIP = {"fracdigi", "quant", "kyloren_quant"}
DAYS = 30
DENIABLE = ("Artifact", "SearchPlugins", "SuggestPluginInstall", "SuggestSkills",
            "ScheduleWakeup", "mcp__visualize", "mcp__terminal", "mcp__1a59c906-04da-521d-bda7-7f71b9f9e01c")
AGENT = """---
name: general-purpose
description: General-purpose agent for research and multi-step tasks; runs on Sonnet. Pass model "opus" when the task is design or judgment rather than carrying out a clear brief.
model: sonnet
---

You carry out the brief you were given, completely, with the tools you have. Search before you change code, change only
the lines the task needs, and run the check the brief names. Your final message is your report: what is now true, the
evidence for it (paths, test output), and anything you could not verify, marked UNKNOWN. Keep it short; the conversation
that called you pays for every line.
"""


def seats(hub):
    for path in sorted(glob.glob(os.path.join(hub, "*", "CLAUDE.md"))):
        name = os.path.basename(os.path.dirname(path))
        if name not in SKIP:
            yield name


def used_tools(seat, projects=PROJECTS, now=None):
    """Tool names this seat called in DAYS days, or None when it has no transcript in that time (no evidence, no edit)."""
    since = (now or time.time()) - DAYS * 86400
    stamp = time.strftime("%Y-%m-%d", time.gmtime(since))
    used, seen = set(), False
    for path in glob.glob(os.path.join(projects, "C--ai-workspace-" + seat.replace("_", "-"), "**", "*.jsonl"), recursive=True):
        try:
            if os.path.getmtime(path) < since:
                continue
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"tool_use"' not in line:
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if str(row.get("timestamp") or "") < stamp or row.get("type") != "assistant":
                        continue
                    seen = True
                    for block in (row.get("message") or {}).get("content") or []:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            used.add(str(block.get("name")))
        except OSError:
            continue
    return used if seen else None


def deny_rows(used):
    return [rule for rule in DENIABLE if not any(name == rule or name.startswith(rule + "__") for name in used)]


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


PIN = re.compile(r"^(model:[ \t]*)[\"']?[\w.\-]*(?:opus|fable)[\w.\-]*[\"']?[ \t]*(?=\r?$)", re.M | re.I)
KEEP = "# seat-budget: keep"


def unpin_text(text):
    """An agent file's text with its Opus/Fable pin set to Sonnet, or None when the frontmatter has no such pin or keeps it."""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    head = text[:end] if end > 0 else ""
    if KEEP in head or not PIN.search(head):
        return None
    return PIN.sub(lambda m: m.group(1) + "sonnet", head, count=1) + text[end:]


def unpin_agents(root, dry=False):
    """Names of this seat's agent files whose pin was (or would be) moved to Sonnet."""
    moved = []
    for path in sorted(glob.glob(os.path.join(root, "agents", "*.md"))):
        try:
            with open(path, encoding="utf-8", newline="") as fh:
                new = unpin_text(fh.read())
        except (OSError, UnicodeDecodeError):
            continue
        if new is None:
            continue
        moved.append(os.path.basename(path)[:-3])
        if not dry:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="") as fh:
                fh.write(new)
            os.replace(tmp, path)
    return moved


def apply_seat(hub, seat, used, dry=False):
    """Returns the deny rows added and whether the agent file was written; a settings file that does not parse is left alone."""
    root = os.path.join(hub, seat, ".claude")
    settings = os.path.join(root, "settings.json")
    try:
        with open(settings, encoding="utf-8-sig") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        doc = {}
    except ValueError:
        print(f"KEPT {settings}: not valid JSON")
        return [], False
    deny = doc.setdefault("permissions", {}).setdefault("deny", [])
    added = [rule for rule in deny_rows(used) if rule not in deny]
    agent = os.path.join(root, "agents", "general-purpose.md")
    wrote_agent = not os.path.exists(agent)
    if not dry:
        if added:
            deny.extend(added)
            write_text(settings, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
        if wrote_agent:
            write_text(agent, AGENT)
    return added, wrote_agent


def main(hub=HUB, projects=PROJECTS, dry=False, stats=None):
    """{seat: deny rows added}; a caller that wants more passes `stats`, filled with {"pins": {seat: [agent names moved]}}."""
    out = {}
    pins = stats.setdefault("pins", {}) if stats is not None else {}
    for seat in seats(hub):
        used = used_tools(seat, projects)
        if used is None:
            print(f"SKIP {seat}: no transcript in {DAYS} days")
            continue
        added, agent = apply_seat(hub, seat, used, dry)
        moved = unpin_agents(os.path.join(hub, seat, ".claude"), dry)
        out[seat] = added
        if moved:
            pins[seat] = moved
        print(f"{'WOULD' if dry else 'DID'} {seat}: deny +{len(added)} {added} agent={'new' if agent else 'kept'}"
              + (f" opus pins -> sonnet: {moved}" if moved else ""))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    main(dry=ap.parse_args().dry_run)
