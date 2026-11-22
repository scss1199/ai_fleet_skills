# Authentication surface adapter contract

The canonical workflow consumes names-only JSON. No field may contain a credential, cookie,
authorization header, password, recovery code, payment value, or DOM text containing a secret.

## Request

```json
{
  "schema": 1,
  "requirements": {
    "capabilities": ["authenticated_session", "dom_interaction", "provider_state_readback"],
    "forbidden_capabilities": ["agent_password_entry", "secret_to_chat"],
    "max_risk": 2
  },
  "adapters": [
    {
      "id": "local-adapter-label",
      "state": "available",
      "capabilities": ["authenticated_session", "dom_interaction", "provider_state_readback"],
      "risk": 1,
      "interaction_cost": 2,
      "priority": 50,
      "evidence_refs": ["receipt://session/probe"]
    }
  ]
}
```

`id` is opaque output metadata. Policy must not inspect or score it. `state` is one of `available`,
`unavailable`, or `unknown`. Risk and interaction cost are non-negative integers. Priority is an
integer where higher is preferred after risk and cost.

## Result

- `PASS`: one adapter satisfies every required capability, contains none of the forbidden
  capabilities, is within the risk ceiling, and carries evidence.
- `HANDOFF / NO_CAPABLE_ADAPTER`: inventory is valid but no available adapter satisfies the
  request. The result lists missing capabilities and rejections without exposing values.
- `UNKNOWN / INVALID_INVENTORY`: the request or inventory is malformed, an adapter's state is
  unknown, or required evidence is absent.

## Safe secret egress capabilities

- `provider_store_direct`: value moves between provider-controlled stores without agent exposure.
- `secure_stdin`: value is supplied to a local consumer over standard input without argv or logs.
- `download_to_dropfile`: provider download lands in a watched, access-controlled file that is
  ingested and wiped without printing its contents.
- `operator_external_paste`: the operator copies from the provider UI directly into the declared
  secure ingress; the agent never sees the value.

Adapter-specific limitations and host names belong in adapter packages or dated ledgers, not this
contract.
