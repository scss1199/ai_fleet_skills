#!/usr/bin/env python3
"""leanctl -- one stable entry point to the hub's Lean 4 install for every local agent.

    python C:/ai_workspace/_lean/leanctl.py check --code "theorem t : 2 + 2 = 4 := by decide"
    python C:/ai_workspace/_lean/leanctl.py check --file proof.lean --mathlib
    python C:/ai_workspace/_lean/leanctl.py check --stdin --mathlib < proof.lean
    python C:/ai_workspace/_lean/leanctl.py info
    python C:/ai_workspace/_lean/leanctl.py selftest --require-mathlib
    python C:/ai_workspace/_lean/leanctl.py exec --cwd C:/path/to/project lake -- build

`check` prints one JSON document. The verdict is PROVED only when the file elaborated with
no error, no `sorry`, no locally declared axiom (private ones included), no declaration that
depends on an axiom outside {propext, Classical.choice, Quot.sound}, nothing in the text that
could hide a proof from that audit (`example`, `#guard_msgs`, `set_option debug.*`,
`native_decide`), the audit actually ran, and it found at least one proposition the caller
stated. `audit.theorems` lists every local proposition with the statement Lean elaborated, so
the caller can see WHAT was proved; what Lean generated on its own (`T.mk.injEq`) is marked
`synthetic` and never makes a file PROVED. A clean file that states no proposition (an `#eval`
run, a lone `structure`) is CHECKED. `cautions` names what a reader must not take from the
receipt: statements resting on the file's own definitions, local instances for imported types
(`instance : Add Nat`), printing extensions (their `statement` switches to a form the file cannot
influence), capped lists, cut statements.
Exit code 0 means PROVED or CHECKED, 1 any other verdict (fail closed), 2 that nothing was
checked (SETUP_ERROR, INPUT_ERROR, INTERNAL_ERROR). Every one of them prints JSON on stdout.
The source is piped through stdin, so no temp files are written. README.md has the contract
and its limits.

No PATH or environment variable is required or changed, no model is called, and child
processes never open a console window.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MATHLIB_PROJECT = ROOT / "hubmath"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
STANDARD_AXIOMS = ("propext", "Classical.choice", "Quot.sound")
AUDIT_TAG = "HUBLEAN_AUDIT"
DEFAULT_TIMEOUT_S = 600

# Appended after the caller's source. It lists what THIS file declared: local axioms, the
# non-standard axioms any local theorem/definition depends on, and the statement of each local
# proposition (a theorem, or a def/instance whose type is a Prop) as Lean printed it.
# Private and auxiliary (`_private.*`, `foo._proof_1`) constants are
# audited too -- skipping them once let `private axiom` + `private theorem` through as PROVED.
# The nonce ties the report to this run; a missing or duplicated report means the audit was
# skipped (`#exit`) or spoofed.
# What the receipt says was proved has to be the proposition itself, so the audit also reports
#   - `line`: where the caller declared it; 0 for what Lean generated on its own (`T.mk.injEq`,
#     `f.eq_1`), which must not turn a file without a proposition into PROVED;
#   - `local_deps`: declarations of this file the statement mentions (`def RH : Prop := True`, a
#     local `instance : Add T`), because such a statement means only what they say;
#   - `pp_extensions`: unexpanders / delaborators the file registered. Probing showed
#     `@[app_unexpander f]` printing `f 0` as `2 = 3` in a PROVED receipt, so with any of them
#     present each statement also comes without notation and as the raw kernel term.
# Statements are printed with default options, from the root namespace, with nothing opened: neither
# a `set_option pp.*` nor an `open` / unclosed `namespace` in the source changes what the receipt shows.
AUDIT_TEMPLATE = r'''
namespace HubLeanAudit_{nonce}
open Lean Elab Command in
elab "#hub_lean_audit_{nonce}" : command => do
  let env ← getEnv
  let std : Array Name := #[``propext, ``Classical.choice, ``Quot.sound]
  let ppKinds : Array (Name × String) := #[(``Lean.PrettyPrinter.Unexpander, "unexpander"),
    (``Lean.PrettyPrinter.Delaborator.Delab, "delab"), (``Lean.PrettyPrinter.Formatter, "formatter"),
    (``Lean.PrettyPrinter.Parenthesizer, "parenthesizer")]
  let mut localAxioms : Array String := #[]
  let mut deps : Array String := #[]
  let mut ppExts : Array Json := #[]
  let mut props : Array (Nat × String × Name × Bool × Array Name) := #[]
  let mut checked : Nat := 0
  for (n, ci) in env.constants.map₂.toList do
    let shown := Lean.privateToUserName n
    if shown.components.contains `HubLeanAudit_{nonce} then continue
    for (tyName, kind) in ppKinds do
      if ci.type.isConstOf tyName then
        ppExts := ppExts.push (Json.mkObj [("name", toJson shown.toString), ("kind", toJson kind)])
    let isThm := match ci with
      | .thmInfo _ => true
      | _ => false
    match ci with
    | .axiomInfo _ => localAxioms := localAxioms.push shown.toString
    | .thmInfo _ | .defnInfo _ | .opaqueInfo _ =>
      checked := checked + 1
      let axs ← Lean.collectAxioms n
      for a in axs do
        let s := (Lean.privateToUserName a).toString
        if !std.contains a && !deps.contains s then deps := deps.push s
      let propDef ← try
          liftTermElabM (Lean.Meta.isProp ci.type)
        catch _ => pure false
      if (isThm || propDef) && !shown.isInternal then
        let line := match (← findDeclarationRanges? n) with
          | some r => r.range.pos.line
          | none => 0
        props := props.push (line, shown.toString, n, isThm, axs)
    | _ => pure ()
  -- source order, generated declarations last, so the cap below drops those first
  let key := fun (p : Nat × String × Name × Bool × Array Name) => if p.1 == 0 then 1000000000 else p.1
  let sorted := props.qsort (fun a b => key a < key b || (key a == key b && a.2.1 < b.2.1))
  -- printed from the root namespace with nothing opened: inside an unclosed `namespace Foo` a local
  -- `Foo.Nat.Prime 4` came out as `Nat.Prime 4`
  let render : Expr → Options → CommandElabM String := fun e o => do
    try
      liftTermElabM <| withTheReader Core.Context
          (fun c => { c with currNamespace := .anonymous, openDecls := [] }) <|
        withOptions (fun _ => o) do return toString (← Lean.Meta.ppExpr e)
    catch _ => pure "<statement could not be printed>"
  let mut theorems : Array Json := #[]
  for (line, shownStr, n, isThm, axs) in sorted.extract 0 {max_theorems} do
    let some ci := env.find? n | continue
    let pretty ← render ci.type {}
    let localConsts := ci.type.getUsedConstants.filter fun c => env.constants.map₂.contains c && c != n
    let localDeps := localConsts.map fun c => (Lean.privateToUserName c).toString
    -- `instance : Add Nat` / `instance : OfNat Nat 2`: a data instance of this file for imported types
    -- is used without showing in the printed statement, and `2 + 2 = 0` came out PROVED with it
    let mut shadow : Array String := #[]
    for c in localConsts do
      let some dci := env.find? c | continue
      if Lean.Meta.isInstanceCore env c
          && dci.type.getUsedConstants.all (fun d => !env.constants.map₂.contains d) then
        let isProof ← try
            liftTermElabM (Lean.Meta.isProp dci.type)
          catch _ => pure false
        if !isProof then shadow := shadow.push (Lean.privateToUserName c).toString
    let mut fields : List (String × Json) := [("name", toJson shownStr),
      ("kind", toJson (if isThm then "theorem" else "def")), ("line", toJson line),
      ("statement", toJson pretty), ("local_deps", toJson localDeps), ("shadow_instances", toJson shadow),
      ("axioms", toJson (axs.map fun a => (Lean.privateToUserName a).toString))]
    if ppExts.isEmpty && shadow.isEmpty then
      -- `3 * 5 = 1` is a theorem of `ZMod 7`, and `2 ^ (1 / 2) = 1` holds in ℝ because that `1 / 2` is in ℕ
      let typed ← render ci.type (({} : Options).setBool `pp.numericTypes true)
      if typed != pretty then fields := fields ++ [("statement_typed", toJson typed)]
    else
      let noNotation ← render ci.type (({} : Options).setBool `pp.notation false)
      fields := fields ++ [("statement_no_notation", toJson noNotation),
        ("statement_kernel", toJson (toString ci.type))]
    theorems := theorems.push (Json.mkObj fields)
  let js := Json.mkObj [("nonce", "{nonce}"), ("local_axioms", toJson localAxioms),
    ("nonstandard_axioms", toJson deps), ("declarations_checked", toJson checked),
    ("pp_extensions", Json.arr ppExts), ("theorems_total", toJson props.size),
    ("theorems_stated", toJson (props.filter fun p => p.1 != 0).size),
    ("theorems", Json.arr theorems)]
  logInfo m!"{tag} {{js.compress}}"
end HubLeanAudit_{nonce}
#hub_lean_audit_{nonce}
'''
MAX_THEOREMS = 40
MAX_STATEMENT_CHARS = 2000

IMPORT_RE = re.compile(r"^\s*(?:public\s+|private\s+|meta\s+)*import\s+([A-Za-z_][\w.]*)", re.M)
HEADER_RE = re.compile(r"\s*(module|prelude)(?!\w)")
# Words looked up in the comment-stripped source. Some decide the verdict (see check_source), the
# rest are reported in `text_flags` so a reviewer sees that the file ships metaprograms and the like.
TEXT_FLAGS = ("sorry", "admit", "native_decide", "bv_decide", "example", "#exit", "#guard_msgs", "axiom",
              "unsafe", "implemented_by", "extern", "run_cmd", "run_elab", "run_meta", "elab", "elab_rules",
              "macro", "macro_rules", "syntax", "declare_syntax_cat", "notation", "notation3", "infix", "infixl",
              "infixr", "prefix", "postfix", "app_unexpander", "app_delab", "delab")
LEMMA_RE = re.compile(r"(?<![\w.])lemma(?![\w])")
PATTERN_FLAGS = {
    "set_option debug.*": re.compile(r"(?<![\w.])set_option\s+debug\."),
    "decide +native": re.compile(r"\+native(?!\w)|(?<![\w.])native\s*:=\s*true(?!\w)"),
}


class SetupError(Exception):
    pass


class InputError(Exception):
    """The caller's arguments or source could not be used; nothing was checked."""

    def __init__(self, message: str, *, receipt: bool = True):
        super().__init__(message)
        self.receipt = receipt      # False when the --out path itself is in doubt


class _Parser(argparse.ArgumentParser):
    def error(self, message):       # argparse would print usage to stderr and exit without any JSON
        raise InputError(f"{message} (see `leanctl.py --help`)", receipt=False)


def decode_source(data: bytes, origin: str) -> tuple[str, str]:
    """UTF-8 is the contract. A UTF-16 BOM is decoded too: Windows PowerShell 5.1 writes UTF-16 for
    `>` and `Out-File`, and the BOM makes it unambiguous. Anything else is refused, because guessing
    a legacy code page could silently change what a theorem says."""
    utf16 = data[:2] in (b"\xff\xfe", b"\xfe\xff")
    try:
        text = data.decode("utf-16" if utf16 else "utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InputError(f"{origin} is not valid {'UTF-16' if utf16 else 'UTF-8'} (byte "
                         f"0x{data[exc.start:exc.start + 1].hex()} at offset {exc.start}). Save the source as "
                         "UTF-8, e.g. in PowerShell `Set-Content -Encoding utf8`") from None
    if "\x00" in text:
        raise InputError(f"{origin} contains NUL characters (UTF-16 or UTF-32 without a byte order mark?). "
                         "Save the source as UTF-8")
    return text, "utf-16" if utf16 else "utf-8"


def toolchain_dir() -> Path:
    current = ROOT / "state" / "current.json"
    if current.is_file():
        try:
            rel = json.loads(current.read_text(encoding="utf-8")).get("toolchain", "")
        except (OSError, ValueError, AttributeError):
            rel = ""                # unreadable pointer: fall back to the newest installed toolchain
        cand = (ROOT / rel).resolve()
        if rel and (cand / "bin" / "lean.exe").is_file():
            return cand
    found = sorted(p.parent.parent for p in (ROOT / "toolchains").glob("*/bin/lean.exe"))
    if not found:
        raise SetupError(f"no Lean toolchain under {ROOT / 'toolchains'}; run install_lean.py")
    return found[-1]


def mathlib_lean_path() -> list[str]:
    """LEAN_PATH entries of the prebuilt Mathlib project (computed, so no lake call per check)."""
    libs = [p for p in sorted((MATHLIB_PROJECT / ".lake" / "packages").glob("*/.lake/build/lib/lean"))
            if p.is_dir()]
    own = MATHLIB_PROJECT / ".lake" / "build" / "lib" / "lean"
    if own.is_dir():
        libs.append(own)
    return [str(p) for p in libs]


def mathlib_ready() -> bool:
    return (MATHLIB_PROJECT / ".lake" / "packages" / "mathlib" / ".lake" / "build" / "lib" / "lean"
            / "Mathlib.olean").is_file()


def run(cmd: list[str], *, stdin_text: str | None = None, env: dict | None = None,
        timeout: float = DEFAULT_TIMEOUT_S, cwd: Path | None = None) -> tuple[int | None, str, str]:
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=cwd,
                            creationflags=NO_WINDOW)
    try:
        out, err = proc.communicate(stdin_text.encode("utf-8") if stdin_text is not None else None,
                                    timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        return None, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
    return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def strip_comments(src: str) -> str:
    """Blank `--` comments and (nested) `/- -/` comments. Line breaks and string literals stay, so a
    `--` inside a string cannot hide the rest of its line from the text rules."""
    out, i, n, depth = [], 0, len(src), 0
    while i < n:
        two = src[i:i + 2]
        if depth:
            if two == "/-":
                depth, i = depth + 1, i + 2
            elif two == "-/":
                depth, i = depth - 1, i + 2
            else:
                if src[i] == "\n":
                    out.append("\n")
                i += 1
        elif two == "/-":
            out.append(" ")
            depth, i = 1, i + 2
        elif two == "--":
            out.append(" ")
            while i < n and src[i] != "\n":
                i += 1
        elif src.startswith("'\"'", i):      # the character literal '"' does not open a string
            out.append("'\"'")
            i += 3
        elif src[i] == '"':
            j = i + 1
            while j < n and src[j] != '"':
                j += 2 if src[j] == "\\" else 1
            out.append(src[i:j + 1])
            i = j + 1
        else:
            out.append(src[i])
            i += 1
    return "".join(out)


def parse_messages(stdout: str) -> tuple[list[dict], list[str]]:
    messages, stray = [], []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except ValueError:
            stray.append(line)
            continue
        if isinstance(doc, dict) and "severity" in doc:
            pos = doc.get("pos") or {}
            messages.append({"severity": doc.get("severity"), "line": pos.get("line"),
                             "column": pos.get("column"), "text": str(doc.get("data", ""))})
        else:
            stray.append(line)
    return messages, stray


def render_audit(nonce: str) -> str:
    return AUDIT_TEMPLATE.replace("{nonce}", nonce).replace("{tag}", AUDIT_TAG) \
        .replace("{max_theorems}", str(MAX_THEOREMS)).replace("{{", "{").replace("}}", "}")


def check_source(source: str, *, mathlib: bool | None = None, timeout: float = DEFAULT_TIMEOUT_S,
                 memory_mb: int | None = None, audit: bool = True) -> dict:
    started = time.time()
    tc = toolchain_dir()
    lean = tc / "bin" / "lean.exe"
    source = source.replace("\r\n", "\n").lstrip("\ufeff")
    bare = strip_comments(source)
    imports = IMPORT_RE.findall(bare)
    if mathlib is None:
        mathlib = any(m.split(".")[0] in ("Mathlib", "Aesop", "Batteries", "Qq", "Plausible",
                                          "ProofWidgets", "LeanSearchClient", "ImportGraph")
                      for m in imports)
    if mathlib and not mathlib_ready():
        raise SetupError("Mathlib is not built yet; run setup_mathlib.py (or pass --no-mathlib)")

    body, line_offset = source, 0
    if audit and "Lean" not in imports:
        # the audit is a small metaprogram, so the file must import Lean (a narrower import such as
        # Lean.Data.Json or Mathlib.Logic.Basic is not enough); imports come first, so one line is
        # prepended and subtracted again from every reported position
        body, line_offset = "import Lean\n" + source, 1
    # a `module` / `prelude` header must be the first token, so nothing can be prepended to it
    header = HEADER_RE.match(bare)
    unsupported = bool(audit and header)
    nonce = secrets.token_hex(8)
    tail = render_audit(nonce) if audit else ""
    user_lines = body.count("\n") + 1
    full = body + "\n" + tail

    env = dict(os.environ)
    env.pop("LEAN_PATH", None)
    if mathlib:
        env["LEAN_PATH"] = os.pathsep.join(mathlib_lean_path())
    cmd = [str(lean), "--json", "--stdin"]
    if memory_mb:
        cmd += ["-M", str(int(memory_mb))]
    try:
        rc, out, err = (None, "", "") if unsupported else run(cmd, stdin_text=full, env=env, timeout=timeout,
                                                              cwd=ROOT)
    except OSError as exc:
        raise SetupError(f"could not start {lean}: {exc}") from None

    messages, stray = parse_messages(out)
    audit_reports, audit_messages, user_messages = [], [], []
    for m in messages:
        if (m["line"] or 0) > user_lines:       # emitted by the appended audit, not by the caller's text
            if m["text"].startswith(AUDIT_TAG + " "):
                try:
                    audit_reports.append(json.loads(m["text"][len(AUDIT_TAG) + 1:]))
                except ValueError:
                    audit_reports.append({"nonce": None})
            else:
                audit_messages.append(m)
            continue
        if m["line"] is not None:
            m["line"] = max(m["line"] - line_offset, 0)
        user_messages.append(m)

    errors = [m for m in user_messages if m["severity"] == "error"]
    sorry = any("declaration uses 'sorry'" in m["text"] or "declaration uses `sorry`" in m["text"]
                for m in user_messages)
    flags = sorted({f for f in TEXT_FLAGS if re.search(rf"(?<![\w.]){re.escape(f)}(?![\w])", bare)}
                   | {name for name, pattern in PATTERN_FLAGS.items() if pattern.search(bare)})
    report = audit_reports[0] if len(audit_reports) == 1 else None
    audit_ok = bool(report) and report.get("nonce") == nonce
    local_axioms = (report or {}).get("local_axioms", [])
    nonstandard = [a for a in (report or {}).get("nonstandard_axioms", []) if a != "sorryAx"]
    if report and "sorryAx" in report.get("nonstandard_axioms", []):
        sorry = True
    # A file that registers its own unexpander or delaborator decides how its statements are printed, so
    # `statement` switches to a form those hooks cannot touch and `statement_pretty` keeps the file's view.
    pp_exts = [e for e in (report or {}).get("pp_extensions", []) if isinstance(e, dict)]
    form = "pretty"
    if pp_exts:
        form = "no_notation" if all(e.get("kind") == "unexpander" for e in pp_exts) else "kernel"
    theorems = []
    for t in (report or {}).get("theorems", []):
        pretty = str(t.get("statement", ""))
        # a data instance this file declares for imported types (`instance : Add Nat`) is invisible in the
        # pretty form and changes what `+` or a numeral means: only the kernel term shows it
        shadow = [str(s) for s in t.get("shadow_instances", [])]
        t_form = "kernel" if shadow else form
        shown = pretty if t_form == "pretty" else str(t.get("statement_" + t_form,
                                                            "<statement could not be printed>"))
        line = t.get("line") or None        # 0: Lean generated it, the caller did not write it
        entry = {"name": t.get("name"), "kind": t.get("kind", "theorem"),
                 "line": line - line_offset if line else None, "synthetic": line is None,
                 "statement": shown[:MAX_STATEMENT_CHARS], "statement_form": t_form,
                 "local_deps": t.get("local_deps", []), "shadow_instances": shadow,
                 "axioms": t.get("axioms", [])}
        if t_form != "pretty":
            entry["statement_pretty"] = pretty[:MAX_STATEMENT_CHARS]
        elif t.get("statement_typed"):      # same statement, every numeral with its type
            entry["statement_typed"] = str(t["statement_typed"])[:MAX_STATEMENT_CHARS]
        if len(shown) > MAX_STATEMENT_CHARS:
            entry["statement_truncated"] = True
        theorems.append(entry)
    stated = [t for t in theorems if not t["synthetic"]]
    theorems_total = max(int((report or {}).get("theorems_total") or 0), len(theorems))

    reasons = []
    if unsupported:
        verdict = "UNSUPPORTED"
        reasons.append(f"the source starts with `{header.group(1)}`; `check` has to put `import Lean` in front "
                       "of the file for its audit, which such a header forbids. Drop the header, or build the "
                       "file in a Lake project with `leanctl.py exec lake` (no verdict, no audit)")
    elif rc is None:
        verdict = "TIMEOUT"
        reasons.append(f"lean did not finish within {timeout}s")
    elif errors:
        verdict = "FAILED"
        reasons.append(f"{len(errors)} error message(s), lean exit code {rc}")
        if LEMMA_RE.search(bare) and not any(m.split(".")[0] == "Mathlib" for m in imports):
            reasons.append("hint: `lemma` is a Mathlib command; write `theorem`, or add `import Mathlib`")
    elif sorry:
        verdict = "INCOMPLETE"
        reasons.append("a declaration uses `sorry`: nothing was proved")
    elif audit and not audit_ok:
        verdict = "UNVERIFIED"
        audit_errors = [f"audit: {m['text'][:300]}" for m in audit_messages if m["severity"] == "error"]
        if rc != 0 and not audit_errors:
            reasons.append(f"lean exited with code {rc} (0x{rc & 0xFFFFFFFF:08X}) before the axiom audit reported: "
                           "a crash, e.g. a stack overflow in `#eval` or the memory limit; fail closed")
        else:
            reasons.append("the axiom audit did not run exactly once (a `#exit` skips it); fail closed")
        reasons += audit_errors[:3]
    elif rc != 0:
        verdict = "FAILED"
        reasons.append(f"lean exit code {rc} without an error message")
    elif local_axioms or nonstandard:
        verdict = "UNSOUND_AXIOMS"
        # Lean 4.34 records compiled-code trust as a per-declaration axiom `<decl>._native.<tactic>.ax_*`.
        native = [a for a in dict.fromkeys(local_axioms + nonstandard) if "._native." in a]
        declared = [a for a in local_axioms if a not in native]
        if native:
            reasons.append("trusts compiled code instead of the kernel (`native_decide`, `decide +native`, or a "
                           "SAT-backed `bv_decide`): " + ", ".join(native))
        if declared:
            reasons.append("the source declares its own axiom(s): " + ", ".join(declared))
        if nonstandard:
            reasons.append("depends on non-standard axiom(s): " + ", ".join(nonstandard))
    # The audit only sees what stays in the environment and only what Lean reported. The text rules
    # below refuse what can get around that: an `example` leaves nothing behind (probing showed it
    # accepted with `decide +native`, `sorryAx`, `debug.byAsSorry`, `unsafe`), `#guard_msgs` can
    # swallow an error, and a `debug.*` option can skip the kernel or turn a proof into `sorry`.
    elif "sorry" in flags or "admit" in flags:
        verdict = "INCOMPLETE"
        reasons.append("the source text contains `sorry`/`admit` (its warning can be silenced); fail closed")
    elif "set_option debug.*" in flags:
        verdict = "UNVERIFIED"
        reasons.append("the source sets a `debug.*` option; those can switch kernel checking off "
                       "(debug.skipKernelTC) or replace proofs with `sorry` (debug.byAsSorry). Remove it")
    elif "native_decide" in flags or "decide +native" in flags:
        verdict = "UNSOUND_AXIOMS"
        reasons.append("`native_decide` / `decide +native` trusts the compiler instead of the kernel")
    elif "#guard_msgs" in flags:
        verdict = "UNVERIFIED"
        reasons.append("`#guard_msgs` can swallow the error of a failed declaration. Remove it")
    elif "example" in flags:
        verdict = "UNVERIFIED"
        reasons.append("an `example` leaves nothing in the environment, so its proof cannot be audited or "
                       "cited. State it as a named `theorem` (`theorem my_claim : … := …`) and check again")
    elif not audit:
        verdict = "ELABORATED"
        reasons.append("no error and no sorry, but the axiom audit was disabled")
    elif stated:
        verdict = "PROVED"
    else:
        verdict = "CHECKED"
        reasons.append("the file elaborated cleanly but states no proposition: nothing was proved "
                       "(fine for `#eval`/`#check` runs)")
        if theorems:
            reasons.append(f"the {len(theorems)} listed proposition(s) are marked `synthetic`: Lean generated them "
                           f"for the file's definitions (e.g. `{theorems[0]['name']}`), the caller stated none")

    # Cautions never change the verdict; they say what a reader must not take from the receipt.
    cautions = []
    if theorems and verdict != "PROVED":
        cautions.append(f"the verdict is {verdict}: `audit.theorems` lists what the file declares, "
                        "none of it counts as proved")
    local = [t for t in stated if t["local_deps"]]
    if local:
        named = "; ".join(f"`{t['name']}` ({', '.join(t['local_deps'][:6])}{', ...' if len(t['local_deps']) > 6 else ''})"
                          for t in local[:5])
        cautions.append(f"{len(local)} statement(s) mention declarations made in this file and mean only what those "
                        f"declarations say; quote them with the claim: {named}"
                        + (f"; and {len(local) - 5} more" if len(local) > 5 else ""))
    shadowed = [t for t in stated if t["shadow_instances"]]
    if shadowed:
        cautions.append(f"{len(shadowed)} statement(s) rely on an instance this file declares for imported types, so "
                        "notation such as `+` or a numeral does not have its usual meaning there: "
                        + "; ".join(f"`{t['name']}` ({', '.join(t['shadow_instances'][:6])})" for t in shadowed[:5])
                        + "; their `statement` is the raw kernel term, `statement_pretty` the usual rendering")
    if pp_exts:
        how = "without notation (`pp.notation false`)" if form == "no_notation" else "as the raw kernel term"
        cautions.append("the source registers its own printing extensions ("
                        + ", ".join(f"{e.get('name')} [{e.get('kind')}]" for e in pp_exts[:6])
                        + f"), which decide how a statement is displayed; `statement` is printed {how}, "
                        "`statement_pretty` keeps the file's own rendering")
    if theorems_total > len(theorems):
        cautions.append(f"the file declares {theorems_total} propositions; `audit.theorems` lists the first "
                        f"{len(theorems)} in source order (the axiom audit covered all of them)")
    cut = [str(t["name"]) for t in theorems if t.get("statement_truncated")]
    if cut:
        cautions.append(f"statement(s) cut at {MAX_STATEMENT_CHARS} characters, so their conclusion is not in this "
                        "receipt: " + ", ".join(cut[:5]))

    return {
        "schema": "hub-lean-check/1",
        "ok": verdict in ("PROVED", "CHECKED"),
        "verdict": verdict,
        "reasons": reasons,
        "cautions": cautions,
        "messages": user_messages,
        "stderr": err.strip()[-2000:],
        "stray_stdout": stray[-20:],
        "audit": {"ran": audit_ok, "local_axioms": local_axioms, "nonstandard_axioms": nonstandard,
                  "declarations_checked": (report or {}).get("declarations_checked"),
                  "theorems": theorems,
                  "theorems_total": theorems_total,
                  "theorems_stated": (report or {}).get("theorems_stated", len(stated)),
                  "theorems_truncated": theorems_total > len(theorems),
                  "pp_extensions": pp_exts,
                  "standard_axioms_allowed": list(STANDARD_AXIOMS),
                  "messages": audit_messages},
        "text_flags": flags,
        "mathlib": bool(mathlib),
        "imports": imports,
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "lean_exit_code": rc,
        "toolchain": str(tc),
        "elapsed_s": round(time.time() - started, 2),
    }


def hub_env(tc: Path) -> dict:
    """Process-local environment for lake: toolchain first on PATH, caches kept under _lean/."""
    env = dict(os.environ)
    env["PATH"] = str(tc / "bin") + os.pathsep + env.get("PATH", "")
    env["MATHLIB_CACHE_DIR"] = str(ROOT / "cache" / "mathlib")
    env["LAKE_CACHE_DIR"] = str(ROOT / "cache" / "lake")
    for key in ("LEAN_PATH", "LEAN_SYSROOT", "ELAN_TOOLCHAIN"):
        env.pop(key, None)
    return env


def exec_tool(tool: str, args: list[str], cwd: str | None) -> int:
    """Run lean/lake/... from the current toolchain with inherited stdio (version-independent path)."""
    tc = toolchain_dir()
    exe = tc / "bin" / (tool if tool.lower().endswith(".exe") else tool + ".exe")
    if not exe.is_file():
        raise SetupError(f"no such toolchain binary: {exe}")
    if args and args[0] == "--":
        args = args[1:]
    # A piped or windowless caller must not get a new console, so CREATE_NO_WINDOW is always set.
    # Windows does not propagate standard handles into such a child on its own, hence the
    # explicit pass-through (a stream without a file descriptor, as under pythonw, maps to NUL).
    def std(stream):
        try:
            stream.flush()
            stream.fileno()
            return stream
        except (AttributeError, OSError, ValueError):
            return subprocess.DEVNULL

    return subprocess.run([str(exe), *args], env=hub_env(tc), cwd=cwd or None, creationflags=NO_WINDOW,
                          stdin=std(sys.stdin), stdout=std(sys.stdout), stderr=std(sys.stderr)).returncode


def info() -> dict:
    tc = toolchain_dir()
    rc, out, _ = run([str(tc / "bin" / "lean.exe"), "--version"], timeout=120)
    rc2, out2, _ = run([str(tc / "bin" / "lake.exe"), "--version"], timeout=120)
    manifest = MATHLIB_PROJECT / "lake-manifest.json"
    packages = {}
    if manifest.is_file():
        for pkg in json.loads(manifest.read_text(encoding="utf-8")).get("packages", []):
            packages[pkg.get("name")] = {"rev": pkg.get("rev"), "inputRev": pkg.get("inputRev")}
    return {
        "schema": "hub-lean-info/1",
        "root": str(ROOT),
        "toolchain": str(tc),
        "lean_exe": str(tc / "bin" / "lean.exe"),
        "lake_exe": str(tc / "bin" / "lake.exe"),
        "lean_version": out.strip() if rc == 0 else None,
        "lake_version": out2.strip() if rc2 == 0 else None,
        "mathlib_project": str(MATHLIB_PROJECT),
        "mathlib_ready": mathlib_ready(),
        "mathlib_packages": packages,
        "lean_path": mathlib_lean_path() if mathlib_ready() else [],
    }


# (name, needs_mathlib, source, expected verdict)
SELFTEST_CASES = [
    ("core_true_theorem", False, "theorem hub_t1 : 2 + 2 = 4 := by decide", "PROVED"),
    ("core_omega", False, "theorem hub_t2 (a b : Nat) (h : a < b) : a + 1 ≤ b := by omega", "PROVED"),
    ("core_false_statement_rejected", False, "theorem hub_bad : 2 + 2 = 5 := by decide", "FAILED"),
    ("core_sorry_rejected", False, "theorem hub_s (p : Prop) : p := by sorry", "INCOMPLETE"),
    ("core_axiom_rejected", False, "axiom hub_cheat : False\ntheorem hub_a : 1 = 2 := hub_cheat.elim",
     "UNSOUND_AXIOMS"),
    ("core_exit_skips_audit_rejected", False, "theorem hub_e : 1 = 1 := rfl\n#exit", "UNVERIFIED"),
    ("core_eval_output", False, "#eval (2 : Nat) ^ 100", "CHECKED"),
    ("core_statement_reported", False, "theorem hub_comm (a b : Nat) : a + b = b + a := Nat.add_comm a b",
     "PROVED"),
    ("core_prop_def_reported", False, "def hub_pd : 2 + 3 = 5 := rfl", "PROVED"),
    ("core_lean_submodule_import", False, "import Lean.Data.Json\ntheorem hub_j : 1 = 1 := rfl", "PROVED"),
    ("core_example_rejected", False, "example : 1 + 1 = 2 := rfl", "UNVERIFIED"),
    ("core_compiler_axiom_rejected", False, "theorem hub_n : 2 ^ 10 = 1024 := by decide +native",
     "UNSOUND_AXIOMS"),
    ("core_guard_msgs_rejected", False,
     "#guard_msgs (drop all) in\ntheorem hub_g : (1 : Nat) = \"a\" := rfl\ntheorem hub_g2 : 1 = 1 := rfl",
     "UNVERIFIED"),
    ("core_by_as_sorry_rejected", False,
     "set_option debug.byAsSorry true in\ntheorem hub_b : 1 = 2 := by simp", "INCOMPLETE"),
    ("core_module_header_unsupported", False, "module\ntheorem hub_mod : 1 = 1 := rfl", "UNSUPPORTED"),
    ("core_private_axiom_rejected", False,
     "private axiom hub_pc : False\nprivate theorem hub_pt : 1 = 2 := hub_pc.elim", "UNSOUND_AXIOMS"),
    ("core_silenced_sorry_example_rejected", False,
     "set_option warn.sorry false\nexample : 1 = 2 := by sorry", "INCOMPLETE"),
    ("core_native_decide_example_rejected", False, "example : 2 ^ 10 = 1024 := by native_decide",
     "UNSOUND_AXIOMS"),
    ("core_kernel_check_disabled_rejected", False,
     "set_option debug.skipKernelTC true in\ntheorem hub_k : 1 = 1 := rfl", "UNVERIFIED"),
    # statement fidelity: the receipt has to show the proposition that was proved, not what the file prints
    ("core_unexpander_spoof_unmasked", False,
     "def hub_f (_n : Nat) : Prop := True\n"
     "@[app_unexpander hub_f] def hub_unexp : Lean.PrettyPrinter.Unexpander := fun _ => `(2 = 3)\n"
     "theorem hub_spoof : hub_f 0 := trivial", "PROVED"),
    ("core_delab_spoof_unmasked", False,
     "def hub_g (_n : Nat) : Prop := True\nopen Lean.PrettyPrinter.Delaborator in\n"
     "@[delab app.hub_g] def hub_delab : Delab := do `(3 = 4)\ntheorem hub_spoof2 : hub_g 0 := trivial",
     "PROVED"),
    ("core_structure_only_not_proved", False, "structure HubFoo where\n  a : Nat\n  b : Nat", "CHECKED"),
    ("core_local_definition_flagged", False, "def HubRH : Prop := True\ntheorem hub_rh : HubRH := trivial",
     "PROVED"),
    ("core_theorem_cap_signalled", False,
     "\n".join(f"theorem hub_c{i} : {i} = {i} := rfl" for i in range(MAX_THEOREMS + 5)), "PROVED"),
    ("core_lemma_hint", False, "lemma hub_l : 1 = 1 := rfl", "FAILED"),
    ("core_unclosed_namespace_full_names", False,
     "namespace HubNs\ndef Nat.Prime (_n : Nat) : Prop := True\ntheorem hub_four : Nat.Prime 4 := trivial",
     "PROVED"),
    ("core_shadow_instance_unmasked", False,
     "instance hubBadAdd : Add Nat := ⟨fun _ _ => 0⟩\ntheorem hub_sh : (2 : Nat) + 2 = 0 := rfl\n"
     "theorem hub_ok (a b : Nat) : a * b = b * a := Nat.mul_comm a b", "PROVED"),
    ("mathlib_numeral_types_shown", True,
     "import Mathlib\ntheorem hub_m4 : (2 : ℝ) ^ (1 / 2) = 1 := by norm_num", "PROVED"),
    ("mathlib_ring", True,
     "import Mathlib\ntheorem hub_m1 (a b : ℝ) : (a + b) ^ 2 = a ^ 2 + 2 * a * b + b ^ 2 := by ring",
     "PROVED"),
    ("mathlib_nlinarith", True,
     "import Mathlib\ntheorem hub_m2 (x y : ℝ) : 2 * x * y ≤ x ^ 2 + y ^ 2 := by nlinarith [sq_nonneg (x - y)]",
     "PROVED"),
    ("mathlib_false_statement_rejected", True,
     "import Mathlib\ntheorem hub_m3 (x : ℝ) : x ^ 2 < 0 := by nlinarith [sq_nonneg x]", "FAILED"),
]


def _thm(res: dict, name: str) -> dict:
    return next((t for t in res["audit"]["theorems"] if t["name"] == name), {})


# what a case has to show beyond its verdict
SELFTEST_EXTRA = {
    "core_eval_output": lambda r: any("1267650600228229401496703205376" in m["text"] for m in r["messages"]),
    "core_statement_reported": lambda r: ("a + b = b + a" in _thm(r, "hub_comm").get("statement", "")
                                          and _thm(r, "hub_comm").get("line") == 1 and r["cautions"] == []),
    "core_prop_def_reported": lambda r: _thm(r, "hub_pd").get("kind") == "def",
    # the audit itself must see it, not only the text rule. Lean 4.34 records `decide +native` as a
    # per-theorem axiom (`hub_n._native.decide.ax_1_1`); older releases used `Lean.ofReduceBool`.
    "core_compiler_axiom_rejected": lambda r: any("native" in a or a == "Lean.ofReduceBool"
                                                  for a in r["audit"]["nonstandard_axioms"]),
    "core_unexpander_spoof_unmasked": lambda r: (
        _thm(r, "hub_spoof").get("statement") == "hub_f 0" and _thm(r, "hub_spoof").get("statement_pretty") == "2 = 3"
        and _thm(r, "hub_spoof").get("statement_form") == "no_notation"
        and _thm(r, "hub_spoof").get("local_deps") == ["hub_f"]
        and any("printing extensions" in c for c in r["cautions"])),
    "core_delab_spoof_unmasked": lambda r: (
        _thm(r, "hub_spoof2").get("statement_form") == "kernel"
        and _thm(r, "hub_spoof2").get("statement", "").startswith("hub_g ")
        and "3 = 4" not in _thm(r, "hub_spoof2").get("statement", "")
        and _thm(r, "hub_spoof2").get("statement_pretty") == "3 = 4"),
    "core_structure_only_not_proved": lambda r: (
        bool(r["audit"]["theorems"]) and all(t["synthetic"] for t in r["audit"]["theorems"])
        and r["audit"]["theorems_stated"] == 0 and any("synthetic" in x for x in r["reasons"])),
    "core_local_definition_flagged": lambda r: (_thm(r, "hub_rh").get("local_deps") == ["HubRH"]
                                                and any("`hub_rh` (HubRH)" in c for c in r["cautions"])),
    "core_theorem_cap_signalled": lambda r: (
        r["audit"]["theorems_total"] == MAX_THEOREMS + 5 and len(r["audit"]["theorems"]) == MAX_THEOREMS
        and r["audit"]["theorems_truncated"] and r["audit"]["theorems"][0]["name"] == "hub_c0"
        and any(f"declares {MAX_THEOREMS + 5} propositions" in c for c in r["cautions"])),
    "core_lemma_hint": lambda r: any("`lemma` is a Mathlib command" in x for x in r["reasons"]),
    "core_unclosed_namespace_full_names": lambda r: (
        _thm(r, "HubNs.hub_four").get("statement") == "HubNs.Nat.Prime 4"
        and _thm(r, "HubNs.hub_four").get("local_deps") == ["HubNs.Nat.Prime"]),
    "core_shadow_instance_unmasked": lambda r: (
        _thm(r, "hub_sh").get("shadow_instances") == ["hubBadAdd"]
        and _thm(r, "hub_sh").get("statement_form") == "kernel" and "hubBadAdd" in _thm(r, "hub_sh")["statement"]
        and _thm(r, "hub_sh").get("statement_pretty") == "2 + 2 = 0"
        and _thm(r, "hub_ok").get("statement_form") == "pretty" and _thm(r, "hub_ok").get("shadow_instances") == []
        and any("usual meaning" in c for c in r["cautions"])),
    # that `1 / 2` is natural-number division, so the theorem says 2 ^ 0 = 1; the typed form has to show it
    "mathlib_numeral_types_shown": lambda r: (
        _thm(r, "hub_m4").get("statement") == "2 ^ (1 / 2) = 1"
        and "(1 / 2 : ℕ)" in _thm(r, "hub_m4").get("statement_typed", "")),
}


def selftest(require_mathlib: bool, timeout: float) -> dict:
    have_mathlib = mathlib_ready()
    results = []
    for name, needs_mathlib, source, expected in SELFTEST_CASES:
        if needs_mathlib and not have_mathlib:
            results.append({"case": name, "status": "SKIPPED", "reason": "Mathlib not built"})
            continue
        res = check_source(source, mathlib=needs_mathlib, timeout=timeout)
        ok = res["verdict"] == expected
        if ok and name in SELFTEST_EXTRA:
            try:
                ok = bool(SELFTEST_EXTRA[name](res))
            except (KeyError, IndexError, TypeError):      # a result without the field is a failed case
                ok = False
        results.append({"case": name, "status": "PASS" if ok else "FAIL", "expected": expected,
                        "verdict": res["verdict"], "elapsed_s": res["elapsed_s"],
                        "detail": None if ok else res})
    failed = [r for r in results if r["status"] == "FAIL"]
    skipped = [r for r in results if r["status"] == "SKIPPED"]
    ok = not failed and not (require_mathlib and skipped)
    return {"schema": "hub-lean-selftest/1", "ok": ok, "passed": sum(r["status"] == "PASS" for r in results),
            "failed": len(failed), "skipped": len(skipped), "require_mathlib": require_mathlib,
            "info": info(), "results": results}


def emit(doc: dict, out: str | None, ascii_only: bool = False) -> bool:
    """stdout is UTF-8 (Lean output is full of ∀ ℝ ≤); --ascii escapes it for hosts that decode
    a child's output with a legacy code page. The --out receipt is always plain UTF-8.

    Returns False when the receipt could not be written. The caller then exits 2: an older receipt
    may still sit at that path, and a reader must not take it for this run's."""
    written = True
    if out:
        try:
            path = Path(out)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        except OSError as exc:
            written = False
            doc = dict(doc, receipt_error=f"could not write --out {out}: {exc}")
    text = json.dumps(doc, indent=2, ensure_ascii=ascii_only)
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()
    return written


def read_source(args: argparse.Namespace) -> tuple[str, str]:
    if args.code is not None:
        try:
            args.code.encode("utf-8")
        except UnicodeEncodeError:      # a Windows command line can carry a lone surrogate
            raise InputError("--code holds characters that are not valid Unicode; save the source as a UTF-8 "
                             "file and pass it with --file") from None
        return args.code, "argv"
    if args.file:
        path = Path(args.file)
        if args.out and Path(args.out).resolve() == path.resolve():
            raise InputError("--out points at the --file source; the receipt would overwrite the proof",
                             receipt=False)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise InputError(f"cannot read --file {args.file}: {exc.strerror or exc}") from None
        return decode_source(data, f"--file {args.file}")
    return decode_source(sys.stdin.buffer.read(), "stdin")


def mangled_pipe_hint(source: str) -> str | None:
    """Windows PowerShell 5.1 pipes text to a native program as ASCII and turns ∀ ℝ ≤ ⟨ into `?`;
    a legacy-code-page command line does the same to --code."""
    if source.isascii() and re.search(r"(?<![\w?\]])\?(?![\w_?])", source):
        return ("the source is pure ASCII and has stray `?` characters: if it went through a Windows PowerShell "
                "pipe or a --code argument, its non-ASCII symbols were replaced by `?`. Save it as a UTF-8 "
                "file and pass it with --file")
    return None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    receipt = True
    try:
        return _main(argv)
    except SetupError as exc:
        verdict, error = "SETUP_ERROR", str(exc)
    except InputError as exc:
        verdict, error, receipt = "INPUT_ERROR", str(exc), exc.receipt
    except Exception as exc:        # noqa: BLE001 -- the contract is JSON on stdout, never a bare traceback
        frames = traceback.extract_tb(exc.__traceback__)[-3:]
        where = " <- ".join(f"{Path(f.filename).name}:{f.lineno}" for f in reversed(frames))
        verdict, error = "INTERNAL_ERROR", f"{type(exc).__name__}: {exc} ({where})"
    # The error also replaces the receipt, so an older PROVED at that path cannot pass for this run.
    out = None
    own = argv[:argv.index("exec")] if "exec" in argv else argv     # what follows `exec` belongs to the tool
    for i, arg in enumerate(own):
        if arg == "--out" and i + 1 < len(own):
            out = own[i + 1]
        elif arg.startswith("--out="):
            out = arg[len("--out="):]
    emit({"schema": "hub-lean-error/1", "ok": False, "verdict": verdict, "error": error},
         out if receipt else None, "--ascii" in argv)
    return 2


def _main(argv: list[str]) -> int:
    ap = _Parser(prog="leanctl", description="Hub Lean 4 checker (JSON in, JSON out).")
    ap.add_argument("--ascii", action="store_true",
                    help="escape non-ASCII in the JSON on stdout (for hosts that do not read UTF-8)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ck = sub.add_parser("check", help="elaborate Lean source and return a fail-closed verdict")
    src = ck.add_mutually_exclusive_group(required=True)
    src.add_argument("--code", help="Lean source as one argument")
    src.add_argument("--file", help="path to a .lean file")
    src.add_argument("--stdin", action="store_true", help="read Lean source from stdin")
    ml = ck.add_mutually_exclusive_group()
    ml.add_argument("--mathlib", dest="mathlib", action="store_true", default=None,
                    help="make Mathlib importable (auto-detected from the imports by default)")
    ml.add_argument("--no-mathlib", dest="mathlib", action="store_false")
    ck.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S, help="wall-clock seconds")
    ck.add_argument("--memory-mb", type=int, default=None, help="lean -M memory limit")
    ck.add_argument("--no-audit", action="store_true",
                    help="skip the axiom audit; the best possible verdict becomes ELABORATED")
    ck.add_argument("--out", help="also write the JSON result to this path (a re-checkable receipt)")

    sub.add_parser("info", help="print versions and paths").add_argument("--out")

    st = sub.add_parser("selftest", help="positive and negative controls; exit 0 only if all pass")
    st.add_argument("--require-mathlib", action="store_true", help="a skipped Mathlib case is a failure")
    st.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    st.add_argument("--out")

    ex = sub.add_parser("exec", help="run a toolchain binary, e.g. `exec lake build` or `exec lean --version`")
    ex.add_argument("--cwd", help="working directory for the tool")
    ex.add_argument("tool", help="lean, lake, leanc, ...")
    ex.add_argument("args", nargs=argparse.REMAINDER)

    args = ap.parse_args(argv)
    if args.cmd == "exec":
        return exec_tool(args.tool, args.args, args.cwd)
    timeout = getattr(args, "timeout", DEFAULT_TIMEOUT_S)
    if not (0 < timeout < float("inf")):        # also refuses nan, which would wait forever
        raise InputError(f"--timeout must be a positive number of seconds, got {timeout}")
    if args.cmd == "check":
        if args.memory_mb is not None and args.memory_mb <= 0:
            raise InputError(f"--memory-mb must be positive, got {args.memory_mb}")
        source, encoding = read_source(args)
        doc = check_source(source, mathlib=args.mathlib, timeout=timeout,
                           memory_mb=args.memory_mb, audit=not args.no_audit)
        doc["source_encoding"] = encoding
        hint = mangled_pipe_hint(source) if doc["verdict"] == "FAILED" else None
        if hint:
            doc["reasons"].append(hint)
    elif args.cmd == "info":
        return 0 if emit(info(), args.out, args.ascii) else 2
    else:
        doc = selftest(args.require_mathlib, timeout)
    if not emit(doc, args.out, args.ascii):
        return 2
    return 0 if doc["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
