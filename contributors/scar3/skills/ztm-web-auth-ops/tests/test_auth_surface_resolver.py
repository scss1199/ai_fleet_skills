import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "auth-surface-resolver.py"
SPEC = importlib.util.spec_from_file_location("auth_surface_resolver", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


REQUIRED = ["authenticated_session", "dom_interaction", "provider_state_readback"]


def inventory(adapter_id="host-adapter"):
    return {
        "schema": 1,
        "requirements": {
            "capabilities": REQUIRED,
            "forbidden_capabilities": ["secret_to_chat"],
            "max_risk": 2,
        },
        "adapters": [{
            "id": adapter_id,
            "state": "available",
            "capabilities": REQUIRED + ["secure_stdin"],
            "risk": 1,
            "interaction_cost": 2,
            "priority": 50,
            "evidence_refs": ["receipt://adapter/live"],
        }],
    }


def test_each_host_label_can_satisfy_the_same_contract():
    for label in ("cursor-browser", "codex-browser", "claude-browser"):
        result = MODULE.resolve(inventory(label))
        assert result["state"] == "PASS"
        assert result["selected"]["id"] == label


def test_renaming_adapter_does_not_change_policy_score():
    first = MODULE.resolve(inventory("first-label"))
    renamed = MODULE.resolve(inventory("unrelated-label"))
    assert first["score"] == renamed["score"]
    assert first["selected"]["capabilities"] == renamed["selected"]["capabilities"]


def test_missing_capability_returns_named_handoff():
    document = inventory()
    document["adapters"][0]["capabilities"] = ["dom_interaction"]
    result = MODULE.resolve(document)
    assert result["state"] == "HANDOFF"
    assert result["reason"] == "NO_CAPABLE_ADAPTER"
    assert "authenticated_session" in result["missing_capabilities"]


def test_unsafe_adapter_is_rejected():
    document = inventory()
    document["adapters"][0]["capabilities"].append("agent_password_entry")
    result = MODULE.resolve(document)
    assert result["state"] == "HANDOFF"
    assert "FORBIDDEN_CAPABILITY" in result["rejected"][0]["reason"]


def test_unknown_availability_fails_closed():
    document = inventory()
    document["adapters"][0]["state"] = "unknown"
    result = MODULE.resolve(document)
    assert result["state"] == "UNKNOWN"
