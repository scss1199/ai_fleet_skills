"""Produce the approved minimal task projection the Jev turn router requires.

Defect this closes: ``jev_turn_router.advisory_for_turn`` reads an approved
projection from ``_registry/jev-task-projections/<agent>/<prompt_identity>.json``
and no producer existed end-to-end, so the shared host surfaces could never pass
``missing_approved_projection``.

Privacy is structural, not editorial. The emitted ``task_projection`` is built
only from a CLOSED VOCABULARY: fixed shape terms declared in this module plus
registered canonical skill IDs. A prompt substring cannot appear in the output
unless it is already a member of that vocabulary, so raw text, secrets, market
data, file contents and account details cannot leak by construction. The
producer verifies that invariant against its own output before writing and
fails closed when it does not hold.

This module grants no authority. It never calls a provider, never reads a
credential, never executes a skill and never deletes a file.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path

SCHEMA = 1
MODEL = "jev-1.13.0"
SURFACES = ("dsh", "claude", "open-agent-standard")
MAX_TASK_CHARS = 1600
MAX_ALLOWED_SKILLS = 32
MAX_STORE_FILES = 512
TTL_SECONDS = 900

# Closed vocabulary, part 1: task-shape terms. Matching is substring on the
# case-folded prompt; only the term itself is ever emitted.
SHAPE_TERMS_ASCII = (
    "audit", "authorize", "benchmark", "browser", "build", "cache", "commit",
    "compare", "compile", "config", "credential", "deploy", "deterministic",
    "diagnose", "document", "evaluate", "evidence", "execute", "explain",
    "fix", "github", "inbox", "install", "inventory", "latency", "lean",
    "login", "measure", "migrate", "monitor", "oauth", "parallel", "plan",
    "probe", "proof", "publish", "push", "refactor", "regression", "release",
    "report", "research", "review", "rollback", "schedule", "search",
    "secret", "skill", "summarize", "test", "token", "trade", "translate",
    "upgrade", "verify", "wiki", "workflow",
)
# Closed vocabulary, part 2: Traditional-Chinese shape terms. A character-class
# signal alone cannot distinguish task shapes in a Han-script prompt, and the
# evaluation families require mixed-language coverage, so the terms are declared
# here as data. They are emitted verbatim or not at all.
SHAPE_TERMS_HAN = (
    "上線", "交付", "佈署", "修正", "停用", "報告", "復原", "多語", "審查",
    "工作流", "建置", "排程", "推送", "提案", "撤銷", "測試", "研究", "稽核",
    "編譯", "翻譯", "自動化", "藍圖", "證據", "註冊", "評估", "說明", "調查",
    "部署", "重啟", "驗證",
)
NEGATION_TERMS = (
    "do not", "don't", "never", "without", "no need", "skip", "avoid",
    "不要", "不需", "不得", "嚴禁", "禁止", "勿", "無須",
)
LENGTH_BUCKETS = ("xs", "s", "m", "l", "xl")
LANGUAGE_TOKENS = ("han", "latin", "han_latin", "other")
KEYS = ("shape", "skills", "len", "lang", "multi", "neg", "mand")


def _bucket(n: int) -> str:
    for limit, name in ((80, "xs"), (400, "s"), (1600, "m"), (6400, "l")):
        if n <= limit:
            return name
    return "xl"


def _language(text: str) -> str:
    han = any("㐀" <= ch <= "鿿" for ch in text)
    latin = any(("a" <= ch <= "z") or ("A" <= ch <= "Z") for ch in text)
    if han and latin:
        return "han_latin"
    if han:
        return "han"
    if latin:
        return "latin"
    return "other"


def vocabulary(skill_ids) -> tuple[str, ...]:
    """The complete set of strings this module is permitted to emit."""
    return tuple(sorted(set(
        SHAPE_TERMS_ASCII + SHAPE_TERMS_HAN + LENGTH_BUCKETS
        + LANGUAGE_TOKENS + KEYS + tuple(skill_ids))))


def _matched_terms(folded: str) -> tuple[str, ...]:
    return tuple(t for t in SHAPE_TERMS_ASCII + SHAPE_TERMS_HAN if t in folded)


def _ranked_skills(folded: str, candidates) -> list[str]:
    """Deterministic local prefilter. Not a selection and not an authority call."""
    def score(skill_id: str) -> tuple[int, str]:
        parts = [p for p in skill_id.replace("_", "-").split("-") if len(p) > 2]
        hits = sum(1 for p in parts if p in folded) + (2 if skill_id in folded else 0)
        return (-hits, skill_id)
    ordered = sorted(candidates, key=score)
    return ordered[:MAX_ALLOWED_SKILLS]


def compile_task_projection(prompt_text: str, allowed_skill_ids, mandatory_skill_ids) -> str:
    """Return the closed-vocabulary descriptor string. No prompt text is copied."""
    folded = (prompt_text or "").casefold()
    body = {
        "shape": list(_matched_terms(folded)),
        "skills": list(allowed_skill_ids),
        "len": _bucket(len(prompt_text or "")),
        "lang": _language(prompt_text or ""),
        "multi": "\n" in (prompt_text or ""),
        "neg": any(t in folded for t in NEGATION_TERMS),
        "mand": list(mandatory_skill_ids),
    }
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def verify_closed(task_projection: str, allowed: tuple[str, ...]) -> bool:
    """Total structural check: every string in the output is a vocabulary member."""
    permitted = set(allowed)
    try:
        parsed = json.loads(task_projection)
    except ValueError:
        return False

    def walk(node) -> bool:
        if isinstance(node, str):
            return node in permitted
        if isinstance(node, bool) or node is None or isinstance(node, (int, float)):
            return True
        if isinstance(node, list):
            return all(walk(v) for v in node)
        if isinstance(node, dict):
            return all(isinstance(k, str) and k in permitted and walk(v)
                       for k, v in node.items())
        return False

    return walk(parsed)


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_bound(path: Path):
    with path.open("rb") as stream:
        raw = stream.read(128 * 1024 + 1)
    if len(raw) > 128 * 1024:
        raise ValueError("oversized local routing input")
    return json.loads(raw.decode("utf-8-sig")), _sha_bytes(raw)


def build_projection(workspace, agent, *, prompt_text, prompt_identity,
                     session_identity, surface_id, now=None, catalog_loader=None) -> dict:
    """Write the bound projection when local policy approves it; else write nothing.

    Returns a bounded receipt. The receipt carries the emitted descriptor because
    the descriptor is closed-vocabulary and auditable; it never carries prompt text.
    """
    receipt = {"state": "NOT_WRITTEN", "reason": "missing_configuration",
               "path": None, "projection_sha256": None, "task_projection": None,
               "raw_prompt_copied": False, "provider_calls": 0,
               "closed_vocabulary_verified": None, "vocabulary_sha256": None}
    try:
        workspace = Path(workspace).resolve()
        if surface_id not in SURFACES:
            receipt["reason"] = "unsupported_surface"
            return receipt
        if any(not isinstance(v, str) or len(v) != 64
               or any(c not in "0123456789abcdef" for c in v)
               for v in (prompt_identity or "", session_identity or "")):
            receipt["reason"] = "invalid_identity"
            return receipt
        config_path = workspace / "_registry" / "jev-advisor.json"
        if not config_path.is_file():
            return receipt
        config, config_sha = _read_bound(config_path)
        if (config.get("schema") != SCHEMA or config.get("enabled") is not True
                or config.get("mode") not in {"shadow", "advisory"}
                or config.get("model") != MODEL):
            receipt["reason"] = "disabled_or_unsupported_config"
            return receipt
        if agent not in config.get("allowed_agents", []):
            receipt["reason"] = "agent_not_enabled"
            return receipt
        if config.get("provider_authorized") is not True:
            # Nothing downstream can use a projection while the provider is
            # unauthorized, so do not create registry state for it.
            receipt["reason"] = "provider_not_authorized"
            return receipt
        if config.get("projection_auto_approve") is not True:
            receipt["reason"] = "projection_approval_not_granted"
            return receipt
        policy_path = workspace / "_registry" / "web-api-routing-policy.json"
        if not policy_path.is_file():
            receipt["reason"] = "missing_provider_policy"
            return receipt
        _policy, policy_sha = _read_bound(policy_path)

        loader = catalog_loader
        if loader is None:
            import importlib.util
            import sys
            path = Path(__file__).with_name("jev_skill_advisor.py")
            spec = importlib.util.spec_from_file_location("_jev_projection_advisor", path)
            module = importlib.util.module_from_spec(spec)
            sys.modules["_jev_projection_advisor"] = module
            spec.loader.exec_module(module)
            loader = module.load_catalog
        catalog = loader(workspace)
        mandatory = sorted(s.id for s in catalog.skills if s.installation_required)
        candidates = [s.id for s in catalog.skills if not s.installation_required]
        if not candidates:
            receipt["reason"] = "no_optional_candidates"
            return receipt
        allowed = _ranked_skills((prompt_text or "").casefold(), candidates)

        vocab = vocabulary(allowed + mandatory)
        task = compile_task_projection(prompt_text, allowed, mandatory)
        verified = verify_closed(task, vocab)
        receipt["closed_vocabulary_verified"] = verified
        receipt["vocabulary_sha256"] = _sha_bytes(
            json.dumps(vocab, ensure_ascii=False).encode("utf-8"))
        if not verified or not 1 <= len(task) <= MAX_TASK_CHARS:
            receipt["state"] = "REFUSED"
            receipt["reason"] = "closed_vocabulary_self_check_failed"
            return receipt

        root = (workspace / "_registry" / "jev-task-projections" / agent)
        root.mkdir(parents=True, exist_ok=True)
        root = root.resolve()
        target = root / f"{prompt_identity}.json"
        if not target.is_file():
            existing = sum(1 for _ in root.iterdir())
            if existing >= MAX_STORE_FILES:
                # Bounded store without deletion: deletion is operator-only.
                receipt["state"] = "REFUSED"
                receipt["reason"] = "projection_store_full"
                return receipt
        moment = now or dt.datetime.now(dt.timezone.utc)
        document = {
            "schema": SCHEMA,
            "approved_for_provider": True,
            "approval_basis": "closed_vocabulary_producer_and_local_policy",
            "producer": "jev_task_projection.build_projection",
            "producer_sha256": _sha_bytes(Path(__file__).read_bytes()),
            "generated_at": moment.isoformat(),
            "expires_at": (moment + dt.timedelta(seconds=TTL_SECONDS)).isoformat(),
            "agent": agent,
            "surfaces": [surface_id],
            "prompt_identity": prompt_identity,
            "session_identity": session_identity,
            "config_sha256": config_sha,
            "provider_policy_sha256": policy_sha,
            "catalog_sha256": catalog.registry_sha256,
            "task_projection": task,
            "allowed_skill_ids": list(allowed),
            "mandatory_skill_ids": list(mandatory),
            "vocabulary_sha256": receipt["vocabulary_sha256"],
            "raw_prompt_included": False,
        }
        raw = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")
        temp = target.with_suffix(f".{os.getpid()}.tmp")
        temp.write_bytes(raw)
        os.replace(temp, target)
        receipt.update(state="WRITTEN", reason="approved_closed_vocabulary_projection",
                       path=str(target), projection_sha256=_sha_bytes(raw),
                       task_projection=task, allowed_skill_count=len(allowed),
                       mandatory_skill_count=len(mandatory),
                       expires_at=document["expires_at"])
        return receipt
    except Exception as exc:  # noqa: BLE001 - reason codes only, never content
        receipt["state"] = "ERROR"
        receipt["reason"] = "producer_error:" + type(exc).__name__
        return receipt
