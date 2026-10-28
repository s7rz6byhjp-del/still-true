# Aru Lite Context

A small adaptation of **Living Context** for an environment that already has long-term memory, source-chat retrieval, and structured tools.

## Conclusion first

Do not build another memory system. Add one short-lived ledger for **what is still true now**.

The ledger has two scopes:

- `today`: food, water, sleep, delivery, bowel movement, today's plan; expires at local midnight.
- `current`: temporary cross-day context; requires an explicit expiry/review time.

It deliberately does **not** store identity, relationship facts, preferences, project documentation, or durable memories. Those remain in Aru's existing memory layers.

## The four rules

1. **Plan is not fact.** `planned` never becomes `completed` merely because time passed.
2. **Evidence has a time.** Store when it was observed and, when known, when it occurred.
3. **Newer current evidence wins.** Reusing a key supersedes the previous value.
4. **Ended facts leave tombstones.** Old-chat retrieval must not revive something marked expired, completed, cancelled, corrected, or ended.

## Example

```python
import aru_lite_context as state

state.set_item(
    "KFC delivery",
    "paper-wrapped chicken has been ordered and has not arrived yet",
    scope="today",
    state="in_progress",
    source_ref="message:123",
    evidence="user_stated",
)

state.set_item(
    "dinner",
    "plans to cook tomato and mushroom noodles tonight",
    scope="today",
    state="planned",
)

# Delivery arrives and the temporary in-progress fact ends.
state.set_item(
    "KFC delivery",
    "paper-wrapped chicken arrived",
    scope="today",
    state="completed",
    evidence="user_stated",
)
```

The completed delivery is not kept in active context. It becomes a tombstone. If an old message later says “the chicken was just ordered”, the tombstone is evidence that this is no longer current.

## Integration boundary

Recommended request flow:

1. Read `render_context()` and attach the small block near the current user turn.
2. If semantic retrieval returns an old temporary fact, check tombstones for the same key.
3. Let explicit user statements or confirmed tool results update the ledger.
4. Do not write every conversational detail. Write only facts whose repetition or staleness would cause a noticeable mistake.

`tools_aru_lite.json` contains four proposed tool schemas: `state_set`, `state_get`, `state_drop`, and `state_tombstones`.

## Differences from upstream

Upstream remains intact. This adaptation adds:

- one combined JSON ledger instead of separate today/context/snapshot stores;
- explicit lifecycle states;
- ISO timestamps and timezone-aware expiry;
- source/evidence fields;
- tombstones for expiry, supersession, completion, cancellation, and manual removal;
- no snapshot receipt layer and no second long-term-memory path.

## Run tests

```bash
python -m unittest discover -s tests -v
```

No third-party dependencies are required.
