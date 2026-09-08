"""Optional Anthropic SDK adapter for FAMES adaptive response control.

The policy remains provider-neutral. This file only translates the current
Anthropic async streaming boundary into the canonical StreamChunk contract.
Pass an already-configured client; never pass or log an API key here.
"""
from __future__ import annotations
import hashlib

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, AsyncIterator


try:
    from scripts.adaptive_response_controller import (
        AttemptRequest,
        RetryableAdapterError,
        StreamChunk,
        TerminalAdapterError,
    )
except ModuleNotFoundError:
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    package = sys.modules.get("scripts")
    if package is None:
        package = ModuleType("scripts")
        package.__path__ = [str(scripts_dir)]
        sys.modules["scripts"] = package
    spec = importlib.util.spec_from_file_location(
        "scripts.adaptive_response_controller",
        scripts_dir / "adaptive_response_controller.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the FAMES adaptive response controller")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    AttemptRequest = module.AttemptRequest
    RetryableAdapterError = module.RetryableAdapterError
    StreamChunk = module.StreamChunk
    TerminalAdapterError = module.TerminalAdapterError


class AnthropicAsyncMessagesAdapter:
    def __init__(self, client: Any, *, model: str) -> None:
        if not model.strip():
            raise ValueError("model is required")
        self.client = client
        self.model = model

    @staticmethod
    def _content(request: AttemptRequest) -> str:
        if request.repair_instruction is None:
            return request.payload
        return request.payload + "\n\n[Measured response repair]\n" + request.repair_instruction

    async def stream(self, request: AttemptRequest) -> AsyncIterator[StreamChunk]:
        try:
            async with self.client.messages.stream(
                model=self.model,
                max_tokens=request.max_output_tokens,
                temperature=request.temperature,
                system=(
                    "Give a concise, evidence-bounded technical response. Preserve all applicable "
                    "safety, authorization, privacy, and higher-priority policy boundaries. "
                    "Never claim access, execution, or evidence that was not observed."
                ),
                messages=[{"role": "user", "content": self._content(request)}],
            ) as stream:
                async for text in stream.text_stream:
                    yield StreamChunk(text=text)
                message = await stream.get_final_message()
                usage = getattr(message, "usage", None)
                stop_reason = str(getattr(message, "stop_reason", "") or "").strip()
                stop_code = stop_reason.upper() if stop_reason else None
                boundary_state = None
                boundary_category = None
                boundary_reason_code = None
                if stop_reason == "refusal":
                    boundary_state = "BOUNDARY"
                    boundary_category = "SAFETY_BOUNDARY"
                    boundary_reason_code = "PROVIDER_STOP_REASON_REFUSAL"
                elif stop_reason in {
                    "end_turn",
                    "max_tokens",
                    "stop_sequence",
                    "tool_use",
                    "pause_turn",
                    "model_context_window_exceeded",
                }:
                    boundary_state = "CLEAR"
                    boundary_category = "PROVIDER_COMPLETION"
                    boundary_reason_code = f"PROVIDER_STOP_REASON_{stop_code}"
                message_id = str(getattr(message, "id", "") or "")
                yield StreamChunk(
                    input_tokens=getattr(usage, "input_tokens", None),
                    output_tokens=getattr(usage, "output_tokens", None),
                    boundary_state=boundary_state,
                    boundary_category=boundary_category,
                    boundary_reason_code=boundary_reason_code,
                    provider_request_id_sha256=(
                        hashlib.sha256(message_id.encode("utf-8")).hexdigest()
                        if message_id else None
                    ),
                    provider_stop_reason=stop_code,
                    provider_model_sha256=hashlib.sha256(self.model.encode("utf-8")).hexdigest(),
                    temperature_applied=True,
                )
        except Exception as exc:
            name = exc.__class__.__name__
            if name in {"APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError"}:
                raise RetryableAdapterError("PROVIDER_TRANSIENT") from exc
            if name in {"AuthenticationError", "PermissionDeniedError", "BadRequestError", "NotFoundError"}:
                raise TerminalAdapterError("PROVIDER_REQUEST_REJECTED") from exc
            raise
