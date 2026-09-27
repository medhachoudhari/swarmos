"""Memoise peer-state validation in _drain_round (performance only).

Profile at fleet 50 showed 38 percent of tick cost in pydantic
validate_python: 112610 model_validate calls over 200 ticks. The cause is
fan-out. One sender builds a single payload dict per tick, and every one of
its N in-range neighbours validates that SAME dict back into an AMRState.
The work is O(N^2) in fleet size and every repeat produces a bit-identical
object.

The cache is keyed on message_id, which is f"{rid}-{tick}-{seq}" and so is
unique per sender per tick. Validation is a pure function of the payload, so
returning the memoised object is semantically identical to revalidating. The
malformed-envelope drop still happens on first sight, and a negative result
is cached too, so a hostile payload is rejected for every recipient exactly
as before.

This changes NO behaviour. It is not a throughput fix. p95 tick cost was
95.5 ms against a 100 ms budget, which is a demo risk on its own.
"""
from __future__ import annotations

import ast
import pathlib

PATH = pathlib.Path("app/coordination/swarm_policy.py")
src = PATH.read_text()

# 1) A per-tick cache, cleared in _broadcast_round so it can never serve a
#    stale state across ticks.
old_bc = """        self.radio.tick_begin(tick)
        if self.integrity_enabled:"""
new_bc = """        self.radio.tick_begin(tick)
        # Fan-out validation cache, valid for THIS tick only. Cleared here
        # rather than in _drain_round because broadcast always precedes drain,
        # so clearing here makes a stale hit impossible by construction.
        self._state_cache = {}
        if self.integrity_enabled:"""
assert src.count(old_bc) == 1, f"broadcast anchor count={src.count(old_bc)}"
src = src.replace(old_bc, new_bc)

# 2) Serve the validated state from the cache.
old_val = """                payload = msg.payload
                try:
                    peer_state = AMRState.model_validate(payload["state"])
                except Exception:
                    # A malformed envelope is dropped, never trusted. This is
                    # also the seam the X-10 rogue-containment work plugs into.
                    continue"""
new_val = """                payload = msg.payload
                # Every in-range neighbour receives the identical payload dict
                # from this sender this tick, so validate it once and share the
                # result. None is cached as well, so a malformed envelope stays
                # rejected for every recipient.
                cache = self._state_cache
                key = msg.message_id
                if key in cache:
                    peer_state = cache[key]
                    if peer_state is None:
                        continue
                else:
                    try:
                        peer_state = AMRState.model_validate(payload["state"])
                    except Exception:
                        # A malformed envelope is dropped, never trusted. This
                        # is also the seam the X-10 rogue-containment work
                        # plugs into.
                        cache[key] = None
                        continue
                    cache[key] = peer_state"""
assert src.count(old_val) == 1, f"validate anchor count={src.count(old_val)}"
src = src.replace(old_val, new_val)

# 3) Initialise the attribute so a drain before any broadcast cannot AttributeError.
old_init = """        self._views: dict[str, dict[str, PeerView]] = {}"""
new_init = """        self._views: dict[str, dict[str, PeerView]] = {}
        # Per-tick peer-state validation cache. See _drain_round.
        self._state_cache: dict[str, object] = {}"""
assert src.count(old_init) == 1, f"init anchor count={src.count(old_init)}"
src = src.replace(old_init, new_init)

ast.parse(src)
PATH.write_text(src)
print("PATCHED + AST OK")
