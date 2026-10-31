"""Compute-only native adapters for the shared skill scope; no global settings.

DSH observes the adapter request. Claude observes CLI replay and native hooks;
its full provider request remains UNKNOWN. Neither proves arbitrary semantics.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import uuid

from skill_scope import ScopeStore, digest, encoded

HUB = Path(__file__).resolve().parents[2]


def load_runner():
    path = HUB / "ai_darkhero/line/ai101_dsh.py"
    spec = importlib.util.spec_from_file_location("scope_native_transport", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def result_json(text):
    value = text.strip()
    if value.startswith("```json\n") and value.endswith("```"):
        value = value[8:-3].strip()
    result = json.loads(value)
    if not isinstance(result, dict):
        raise ValueError("result_must_be_object")
    return result


def shape(value):
    """Constrain output type/structure, never substitute the expected answer."""
    if isinstance(value, dict):
        return {"type": "object", "properties": {k: shape(v) for k, v in value.items()},
                "required": list(value), "additionalProperties": False}
    if isinstance(value, list):
        variants = list({encoded(shape(v)): shape(v) for v in value}.values())
        return {"type": "array", "items": variants[0] if len(variants) == 1 else {"anyOf": variants} if variants else {}}
    return {"type": {str: "string", bool: "boolean", int: "integer", float: "number", type(None): "null"}[type(value)]}


def response_schema(frame):
    """A bound proposal schema does not replace the store's acceptance predicate."""
    example = frame.get("response_shape")
    if example is not None:
        if not isinstance(example, dict) or set(example) != {"result"}:
            raise ValueError("native_response_shape_invalid")
        return shape(example)
    obligations = frame["output_contract"]
    if len(obligations) != 1 or obligations[0]["parameters"]["pointer"] != "/result":
        raise ValueError("native_output_schema_capability_not_attested")
    return shape({"result": obligations[0]["parameters"]["expected"]})


def dsh(frame, output, runner, markers):
    config = {"timeout_seconds": 300, "mission_id": frame["task_id"]}
    gate = {"resident_api": runner.resident_api_gate(config), "local_compute": runner.local_compute_gate(config)}
    write(output / "route-gates.json", gate)
    # Observe only request content, never provider config or authentication fields.
    observer = runner.OBSERVER_JS.replace("import {writeFileSync}", "import {createHash} from 'node:crypto';\nimport {writeFileSync}")
    insertion = """
  state.requests = [];
  ctx.on('llm/stream', (options, next) => {
    const input = JSON.stringify({system:options.system, messages:options.messages});
    state.requests.push({sha256:createHash('sha256').update(input).digest('hex'),
      bytes:Buffer.byteLength(input), message_count:Array.isArray(options.messages)?options.messages.length:null,
      markers:Object.fromEntries(MARKERS.map(m => [m,input.includes(m)]))});
    save(); return next();
  });
""".replace("MARKERS", json.dumps(markers))
    observer = observer.replace("  ctx.on('session/event'", insertion + "  ctx.on('session/event'")
    # DSH compositions may shadow deployment persona. Carry the complete bound
    # projection in its explicit operator message so no parameter can disappear.
    prompt = frame["messages"][0]["content"] + "\nSKILL:\n" + frame["messages"][1]["content"]
    _, identity = runner._prepare_native({"item_id": frame["scope_id"]}, output, config,
        prompt=prompt, persona="Compute only the supplied bound task. Return requested JSON.", observer_js=observer,
        cwd=frame["cwd"])
    process = runner._run_native(output, config)
    usage = json.loads((output / "dsh-usage.json").read_text(encoding="utf-8"))
    lifecycle = runner._fames_evidence(output, usage, process, identity)
    if (not usage.get("completed") or usage.get("tool_events") != 0 or
            usage.get("request_models") != [{"provider": "local-ollama", "model": runner.MODEL}] or
            len(usage.get("requests", [])) != 1):
        raise ValueError("native_dsh_observation_failed")
    return result_json((output / "dsh-native/stdout.txt").read_text(encoding="utf-8")), {
        "process": process, "usage": usage, "lifecycle": lifecycle,
        "input_observation": "native_llm_stream_before_adapter", "native_identity": identity}


def claude(frame, output, runner, markers):
    seats = [row for row in runner.registered_agents(native=True) if Path(row["cwd"]).resolve() == Path(frame["cwd"]).resolve()]
    if len(seats) != 1:
        raise ValueError("unregistered_native_cwd")
    executable = Path(os.environ["APPDATA"]) / "npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe"
    if not executable.is_file():
        raise ValueError("native_claude_missing")
    hook = HUB / "_skill/fleet-skills/token-preflight/scripts/claude_session_hook.py"
    command = f'"{sys.executable}" "{hook}"'
    write(output / "settings.json", {"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": command, "timeout": 25}]}]}})
    write(output / "mcp.json", {"mcpServers": {}})
    system = output / "system.private.txt"
    system.write_text(frame["messages"][0]["content"], encoding="utf-8")
    session = str(uuid.uuid4())
    prompt = frame["messages"][1]["content"]
    request = {"type": "user", "message": {"role": "user", "content": prompt}}
    argv = [str(executable), "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
        "--replay-user-messages", "--include-hook-events", "--tools", "", "--disable-slash-commands",
        "--system-prompt-file", str(system), "--setting-sources", "", "--settings", str(output / "settings.json"),
        "--strict-mcp-config", "--mcp-config", str(output / "mcp.json"), "--permission-mode", "dontAsk",
        "--session-id", session, "--no-session-persistence", "--max-budget-usd", "0.50"]
    argv += ["--json-schema", encoded(response_schema(frame))]
    # Use existing native first-party authentication. Inherited API placeholders
    # must not override it; this changes only the owned child's environment.
    env = {k: v for k, v in os.environ.items() if not k.startswith("ANTHROPIC_") and k not in {
        "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"}}
    env.update(NO_COLOR="1", DISABLE_AUTOUPDATER="1", PYTHONUTF8="1")
    process = runner.run_hidden(argv, cwd=frame["cwd"], timeout=180, env=env,
        stdout_path=output / "stdout.private.jsonl", stderr_path=output / "stderr.private.log",
        input_bytes=(encoded(request) + "\n").encode())
    write(output / "process.json", process)
    if process["timed_out"] or process["returncode"]:
        raise ValueError("native_claude_process_failed")
    rows = [json.loads(line) for line in (output / "stdout.private.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    results = [r for r in rows if r.get("type") == "result"]
    replay = [r for r in rows if r.get("type") == "user" and r.get("message", {}).get("content") == prompt]
    if len(results) != 1 or results[0].get("is_error") or not replay:
        raise ValueError("native_claude_result_or_replay_missing")
    result = results[0]
    path = HUB / "_registry/fames-turn/claude" / (digest(("claude\0" + session).encode()) + ".json")
    raw = path.read_bytes()
    turn = json.loads(raw)
    if (turn.get("state") != "PASS" or turn.get("agent") != seats[0]["seat"]
            or turn.get("prompt_identity") != digest(prompt.encode())
            or not turn.get("runtime_event_observed") or turn.get("adapter_identity") != digest(hook.read_bytes())
            or result.get("session_id") != session):
        raise ValueError("native_claude_lifecycle_mismatch")
    write(output / "fames-turn.json", turn)
    init = next((r for r in rows if r.get("type") == "system" and r.get("subtype") == "init"), {})
    if init.get("tools") not in ([], ["StructuredOutput"]) or init.get("mcp_servers") != []:
        raise ValueError("native_claude_tool_boundary_unknown")
    observed = {"process": process, "session_id": session,
        "native_executable_sha256": digest(executable.read_bytes()), "model": init.get("model"),
        "usage": result.get("usage"), "model_usage": result.get("modelUsage"),
        "lifecycle": {"state": "PASS_ACTUAL_NATIVE_LIFECYCLE", "receipt_sha256": digest(raw), "path": str(path)},
        "input_observation": "native_cli_replay_plus_hook", "provider_request": "UNKNOWN",
        "replay_sha256": digest(prompt.encode()), "markers": {m: m in prompt for m in markers},
        "tools": init.get("tools"), "mcp_servers": init.get("mcp_servers")}
    write(output / "observation.json", observed)
    structured = result.get("structured_output")
    if not isinstance(structured, dict) or set(structured) != {"result"}:
        raise ValueError("native_structured_output_missing")
    return structured, observed


def run(store, scope_id, host, output, *, markers=()):
    output = Path(output).resolve()
    receipt = {"schema": 1, "host": host, "scope_id": scope_id, "state": "UNKNOWN", "paid_fallback": False}
    try:
        store.admit(scope_id, "compute", str(output))
    except (ValueError, OSError, KeyError, TypeError) as error:
        receipt["reason"] = str(error)[:180] if isinstance(error, ValueError) else type(error).__name__
        return receipt
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("output_not_empty")
    admitted = True
    try:
        frame = store.input_for(scope_id)
        write(output / "scope-input.private.json", frame)
        receipt.update({"input_sha256": frame["input_sha256"], "input_bytes": frame["input_bytes"],
                        "task_id": frame["task_id"], "goal_hash": frame["goal_hash"]})
        if host not in {"dsh", "claude"}:
            raise ValueError("unregistered_host")
        result, observed = {"dsh": dsh, "claude": claude}[host](frame, output, load_runner(), list(markers))
        receipt["observed"] = observed
        admitted = False
        store.admit(scope_id, "compute", str(output / "result.json"))
        admitted = True
        write(output / "result.json", result)
        evidence = {k: frame[k] for k in ("schema", "scope_id", "task_id", "task_revision", "goal_hash")}
        evidence["artifacts"] = [{"path": str(output / "result.json"), "sha256": digest((output / "result.json").read_bytes())}]
        receipt["verification"] = store.complete(scope_id, evidence)
        receipt["state"] = receipt["verification"]["verification"]
    except (ValueError, OSError, KeyError, TypeError) as error:
        receipt["reason"] = str(error)[:180] if isinstance(error, ValueError) else type(error).__name__
        if admitted and (output / "observation.json").is_file():
            receipt["observed"] = json.loads((output / "observation.json").read_text(encoding="utf-8"))
    finally:
        if admitted:
            receipt["release"] = store.release(scope_id)
            write(output / "native-scope.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=["dsh", "claude"], required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    store = ScopeStore(args.root)
    try:
        result = run(store, args.scope, args.host, args.output)
        print(encoded({k: result.get(k) for k in ("state", "reason", "scope_id")}))
        return 0 if result["state"] == "VERIFIED" else 2
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
