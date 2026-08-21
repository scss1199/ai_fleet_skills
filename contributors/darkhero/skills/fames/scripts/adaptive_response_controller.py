#!/usr/bin/env python3
"""Provider-neutral, safety-preserving adaptive response and cost controller.

The controller may retry retryable transport or measured response-quality
residuals. It never retries a safety, authorization, policy, or capability
boundary in order to obtain a different answer.
"""
from __future__ import annotations

import hashlib
import inspect
import re
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable, Protocol


ACCEPT = "ACCEPT"
RETRY = "RETRY"
TERMINAL = "TERMINAL"

_BOUNDARY_PREFIX = re.compile(
    r"(?:\bi (?:can(?:not|'t)|am unable|won't)\b|"
    r"\b(?:cannot|can't|unable to) (?:assist|help|comply|provide|access)\b|"
    r"\b(?:authorization|permission|credential|access) (?:is|required|missing)\b)",
    re.IGNORECASE,
)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalized_prefix(value: str, size: int) -> str:
    return " ".join(value.split()).casefold()[:size]


@dataclass(frozen=True)
class StreamChunk:
    """A provider adapter's text or cumulative usage observation."""

    text: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class AttemptRequest:
    payload: str
    attempt: int
    temperature: float
    max_output_tokens: int
    repair_instruction: str | None


@dataclass(frozen=True)
class ResponseAssessment:
    decision: str
    category: str
    reason_code: str
    residual: str = ""

    def __post_init__(self) -> None:
        if self.decision not in {ACCEPT, RETRY, TERMINAL}:
            raise ValueError("assessment decision must be ACCEPT, RETRY, or TERMINAL")


class ResponseAdapter(Protocol):
    def stream(self, request: AttemptRequest) -> AsyncIterator[StreamChunk]: ...


Assessor = Callable[[str, AttemptRequest], ResponseAssessment | Awaitable[ResponseAssessment]]


class RetryableAdapterError(RuntimeError):
    """A sanitized adapter failure that may be retried within the attempt budget."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class TerminalAdapterError(RuntimeError):
    """A sanitized adapter failure that must not be retried."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def default_assessor(text: str, _request: AttemptRequest) -> ResponseAssessment:
    """Conservatively accept content, retry emptiness, and preserve boundaries."""

    if not text.strip():
        return ResponseAssessment(RETRY, "EMPTY_RESPONSE", "EMPTY_OUTPUT")
    if _BOUNDARY_PREFIX.search(text[:512]):
        return ResponseAssessment(
            TERMINAL,
            "BOUNDARY_RESPONSE",
            "SAFETY_AUTHORITY_OR_CAPABILITY_BOUNDARY_PRESERVED",
        )
    return ResponseAssessment(ACCEPT, "CONTENT", "NONEMPTY_RESPONSE")


class AdaptiveResponseController:
    """Run at most three bounded attempts without expanding authority or safety."""

    def __init__(
        self,
        *,
        temperatures: tuple[float, ...] = (0.5, 0.2, 0.0),
        max_output_tokens: int = 1024,
        max_output_chars: int = 16_384,
        repeat_prefix_chars: int = 96,
    ) -> None:
        if not temperatures or len(temperatures) > 3:
            raise ValueError("temperatures must contain one to three attempts")
        if any(value < 0.0 or value > 1.0 for value in temperatures):
            raise ValueError("temperature must be within 0.0..1.0")
        if max_output_tokens <= 0 or max_output_chars <= 0 or repeat_prefix_chars < 32:
            raise ValueError("output budgets and repeat prefix must be positive")
        self.temperatures = temperatures
        self.max_output_tokens = max_output_tokens
        self.max_output_chars = max_output_chars
        self.repeat_prefix_chars = repeat_prefix_chars

    @staticmethod
    def _repair_instruction(attempt: int, prior: ResponseAssessment | None) -> str | None:
        if attempt == 1:
            return None
        category = prior.category if prior else "RETRYABLE_RESIDUAL"
        reason = prior.reason_code if prior else "RETRYABLE_RESIDUAL"
        base = (
            "Address only the measured retryable residual "
            f"({category}/{reason}). Preserve every higher-priority policy, safety, "
            "authorization, privacy, and evidence boundary. Do not invent access, actions, "
            "sources, or results."
        )
        if attempt == 3:
            return (
                base
                + " Return a concise technical result with status PASS, HANDOFF, UNKNOWN, "
                "or FAIL; include evidence, blockers, and the smallest lawful next action."
            )
        return base

    @staticmethod
    async def _assess(assessor: Assessor, text: str, request: AttemptRequest) -> ResponseAssessment:
        result = assessor(text, request)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, ResponseAssessment):
            raise TypeError("assessor must return ResponseAssessment")
        return result

    @staticmethod
    async def _close_stream(iterator: AsyncIterator[StreamChunk]) -> bool:
        close = getattr(iterator, "aclose", None)
        if close is None:
            return False
        await close()
        return True

    @staticmethod
    def _receipt(
        payload: str,
        *,
        state: str,
        category: str,
        attempts: list[dict],
    ) -> dict:
        usage_known = bool(attempts) and all(
            isinstance(item.get("input_tokens"), int)
            and isinstance(item.get("output_tokens"), int)
            for item in attempts
        )
        return {
            "schema": 1,
            "controller": "fames-adaptive-response-v1",
            "payload_sha256": _sha256_text(payload),
            "payload_chars": len(payload),
            "state": state,
            "category": category,
            "attempt_count": len(attempts),
            "attempts": attempts,
            "cost_state": "KNOWN" if usage_known else "UNKNOWN",
            "savings_claim": "UNMEASURED",
            "raw_payload_persisted": False,
            "raw_output_persisted": False,
        }

    async def execute(
        self,
        payload: str,
        adapter: ResponseAdapter,
        *,
        assessor: Assessor = default_assessor,
    ) -> dict:
        if not isinstance(payload, str) or not payload.strip():
            receipt = self._receipt(payload if isinstance(payload, str) else "", state="UNKNOWN", category="EMPTY_PAYLOAD", attempts=[])
            return {"state": "UNKNOWN", "category": "EMPTY_PAYLOAD", "text": "", "receipt": receipt}

        attempts: list[dict] = []
        prior_text = ""
        prior_assessment: ResponseAssessment | None = None

        for attempt, temperature in enumerate(self.temperatures, start=1):
            request = AttemptRequest(
                payload=payload,
                attempt=attempt,
                temperature=temperature,
                max_output_tokens=self.max_output_tokens,
                repair_instruction=self._repair_instruction(attempt, prior_assessment),
            )
            iterator = adapter.stream(request)
            parts: list[str] = []
            input_tokens: int | None = None
            output_tokens: int | None = None
            closed_early = False
            early_category: str | None = None

            try:
                async for chunk in iterator:
                    if not isinstance(chunk, StreamChunk):
                        raise TerminalAdapterError("INVALID_STREAM_CHUNK")
                    if chunk.input_tokens is not None:
                        input_tokens = chunk.input_tokens
                    if chunk.output_tokens is not None:
                        output_tokens = chunk.output_tokens
                    if chunk.text:
                        parts.append(chunk.text)
                    current = "".join(parts)
                    if len(current) > self.max_output_chars:
                        parts = [current[: self.max_output_chars]]
                        early_category = "OUTPUT_BUDGET_EXHAUSTED"
                        closed_early = await self._close_stream(iterator)
                        break
                    if prior_text and len(_normalized_prefix(current, self.repeat_prefix_chars)) >= self.repeat_prefix_chars:
                        if _normalized_prefix(current, self.repeat_prefix_chars) == _normalized_prefix(prior_text, self.repeat_prefix_chars):
                            early_category = "REPEATED_NON_PROGRESS"
                            closed_early = await self._close_stream(iterator)
                            break
            except RetryableAdapterError as exc:
                assessment = ResponseAssessment(RETRY, "ADAPTER_RETRYABLE", exc.reason_code)
                attempts.append({
                    "attempt": attempt,
                    "temperature": temperature,
                    "state": "RETRY",
                    "category": assessment.category,
                    "reason_code": assessment.reason_code,
                    "output_sha256": _sha256_text(""),
                    "output_chars": 0,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "closed_early": False,
                })
                prior_assessment = assessment
                continue
            except TerminalAdapterError as exc:
                attempts.append({
                    "attempt": attempt,
                    "temperature": temperature,
                    "state": "FAIL",
                    "category": "ADAPTER_TERMINAL",
                    "reason_code": exc.reason_code,
                    "output_sha256": _sha256_text(""),
                    "output_chars": 0,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "closed_early": False,
                })
                receipt = self._receipt(payload, state="FAIL", category="ADAPTER_TERMINAL", attempts=attempts)
                return {"state": "FAIL", "category": "ADAPTER_TERMINAL", "text": "", "receipt": receipt}
            except Exception as exc:  # fail closed without persisting exception text
                attempts.append({
                    "attempt": attempt,
                    "temperature": temperature,
                    "state": "UNKNOWN",
                    "category": "UNCLASSIFIED_ADAPTER_ERROR",
                    "reason_code": exc.__class__.__name__,
                    "output_sha256": _sha256_text(""),
                    "output_chars": 0,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "closed_early": False,
                })
                receipt = self._receipt(payload, state="UNKNOWN", category="UNCLASSIFIED_ADAPTER_ERROR", attempts=attempts)
                return {"state": "UNKNOWN", "category": "UNCLASSIFIED_ADAPTER_ERROR", "text": "", "receipt": receipt}

            text = "".join(parts)
            if early_category == "OUTPUT_BUDGET_EXHAUSTED":
                attempts.append({
                    "attempt": attempt,
                    "temperature": temperature,
                    "state": "HANDOFF",
                    "category": early_category,
                    "reason_code": "LOCAL_CHARACTER_LIMIT",
                    "output_sha256": _sha256_text(text),
                    "output_chars": len(text),
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "closed_early": closed_early,
                })
                receipt = self._receipt(payload, state="HANDOFF", category=early_category, attempts=attempts)
                return {"state": "HANDOFF", "category": early_category, "text": text, "receipt": receipt}

            if early_category == "REPEATED_NON_PROGRESS":
                assessment = ResponseAssessment(RETRY, early_category, "IDENTICAL_NORMALIZED_PREFIX")
            else:
                try:
                    boundary_assessment = default_assessor(text, request)
                    if boundary_assessment.decision == TERMINAL:
                        assessment = boundary_assessment
                    else:
                        assessment = await self._assess(assessor, text, request)
                except Exception as exc:  # assessor failure is evidence failure, not permission to accept
                    attempts.append({
                        "attempt": attempt,
                        "temperature": temperature,
                        "state": "UNKNOWN",
                        "category": "ASSESSOR_ERROR",
                        "reason_code": exc.__class__.__name__,
                        "output_sha256": _sha256_text(text),
                        "output_chars": len(text),
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "closed_early": closed_early,
                    })
                    receipt = self._receipt(payload, state="UNKNOWN", category="ASSESSOR_ERROR", attempts=attempts)
                    return {"state": "UNKNOWN", "category": "ASSESSOR_ERROR", "text": text, "receipt": receipt}

            attempt_state = {ACCEPT: "PASS", RETRY: "RETRY", TERMINAL: "HANDOFF"}[assessment.decision]
            attempts.append({
                "attempt": attempt,
                "temperature": temperature,
                "state": attempt_state,
                "category": assessment.category,
                "reason_code": assessment.reason_code,
                "output_sha256": _sha256_text(text),
                "output_chars": len(text),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "closed_early": closed_early,
            })
            if assessment.decision == ACCEPT:
                receipt = self._receipt(payload, state="PASS", category=assessment.category, attempts=attempts)
                return {"state": "PASS", "category": assessment.category, "text": text, "receipt": receipt}
            if assessment.decision == TERMINAL:
                receipt = self._receipt(payload, state="HANDOFF", category=assessment.category, attempts=attempts)
                return {"state": "HANDOFF", "category": assessment.category, "text": text, "receipt": receipt}
            prior_text = text
            prior_assessment = assessment

        receipt = self._receipt(payload, state="HANDOFF", category="ATTEMPT_BUDGET_EXHAUSTED", attempts=attempts)
        return {"state": "HANDOFF", "category": "ATTEMPT_BUDGET_EXHAUSTED", "text": prior_text, "receipt": receipt}
