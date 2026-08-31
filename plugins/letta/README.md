# zentinelle-letta

Zentinelle governance for [Letta](https://github.com/letta-ai/letta) (MemGPT).

`agent_type`: `letta`

## Read this first

Letta is not like the other harnesses here, and the difference is worth stating
plainly rather than discovering in production.

`letta-client` is a generated REST client for a Letta **server**. The agent
loop, the model call, tool execution and memory edits all happen on that
server, in another process. The client exposes no hook, middleware or
interceptor. By the time anything interesting happens, the client is waiting on
a socket.

So there is exactly one honest enforcement point, and it is the call site.

| Capability | Status |
|---|---|
| refuse a message before it is sent | **enforced** — the request genuinely does not leave the process |
| token usage | recorded, from the server's response |
| memory-tier changes | recorded after the fact, by diffing blocks around a call |
| block an individual tool call | **not possible client-side** |
| react to a memory edit as it happens | **not possible** — no event, webhook or stream |

## Install

```bash
pip install zentinelle-letta
```

## Use

```python
from letta_client import Letta
from zentinelle import ZentinelleClient
from zentinelle_letta import GovernedLetta

client = ZentinelleClient(api_key="sk_agent_...", agent_type="letta")
letta = GovernedLetta(Letta(api_key="..."), client, audit_memory=True)

response = letta.send_message(agent_id="agent-1", messages=[...])
```

Attribute access falls through to the wrapped client, so the rest of the SDK
still works. That fall-through is also the caveat: calling
`letta.agents.messages.create(...)` directly reaches the ungoverned path,
because there is no interceptor underneath to catch it. Use `send_message`.

## Memory auditing is a diff, not a hook

`audit_memory=True` snapshots the agent's core memory blocks before and after
a call and emits an event per block whose value changed. Two edits to one block
during a run look like one change, and a block edited and then reverted looks
like none. It is polling, and it is described as such because an audit trail
that quietly misses events is worse than one known to be coarse.

## Tool approval

`require_tool_approval()` sets Letta's own server-side `requires_approval` flag
on named tools, which makes the server pause and emit an approval request
before running them. That is Letta gating the tool, not Zentinelle deciding;
something still has to answer the request. It is exposed because it is the only
thing that stops a Letta tool call.

## Defaults

Checks fail closed; pass `fail_open=True` to prefer availability.
