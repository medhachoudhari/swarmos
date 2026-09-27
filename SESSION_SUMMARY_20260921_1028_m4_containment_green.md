# Session summary - 2026-09-21 10:28 - M4 adversarial containment complete and green

## Milestone

X-10 / novelty claim **N9 (adversarial robot containment)** is implemented, wired
end to end in the simulation loop, and fully tested.

**Full suite: 503 passed** (458 before this feature + 45 new integrity tests),
97 s. This was the predicted number exactly, which matters: it means the new
layer added behaviour without perturbing any existing behaviour.

## What was built

| File | State |
| --- | --- |
| `app/coordination/integrity.py` | NEW. `MessageAuthenticator` (HMAC-SHA256, per-robot derived keys, side-band signatures), `SentinelCouncil` (quorum accusation), `canonical_bytes`, `AuthStats`, `ContainmentEvent`. |
| `app/sim/robot.py` | `spoof_x/spoof_y/quarantined` fields, `claimed_x/claimed_y` properties, `"cl"` render key, quarantine excluded from `is_available_for_work`. |
| `app/sim/engine.py` | `observations()` (ground-truth sightings), `apply_containment()`, `_fault_rogue` now spoofs position, `_plan` skips quarantined robots, containment emitted via `_emit`. |
| `app/coordination/swarm_policy.py` | `integrity=` flag, sign on broadcast, verify on drain, claim/traffic/signature audits, `_enforce_containment`, `_drop_peer_everywhere`, `_reclaim_space`, `observe()`, `stats()["integrity"]`. |
| `tests/test_integrity.py` | NEW, 45 tests, all passing. |

## The three defects the tests caught (all mine)

The first run of `tests/test_integrity.py` was **43 passed / 2 failed**, and both
failures were genuine product defects rather than test bugs. Fixed by
`tools/patch_containment_teeth.py`:

1. **Containment was invisible.** `apply_containment` appended straight to
   `_events_this_tick`, bypassing `_emit()`, so the event never reached
   `self.events` - the feed the UI and the operator read. A containment nobody
   can see in the feed is exactly the silent mechanism this project rejects
   everywhere else.
2. **A contained robot was re-dispatched.** `_dispatch` gates on
   `is_available_for_work`, which knew nothing about `quarantined`, so the
   robot was handed fresh work on the very next tick.
3. **A contained robot was re-planned.** `_plan` regenerated its path, and
   `robot.step()` then drove it at v=1.2 m/s.

Taken together, containment was a label that lasted exactly one tick - which is
precisely what its own docstring promised it would not be. Worth recording
plainly: the mechanism *looked* finished, the diagnostic showed a rogue robot
being correctly identified and quarantined, and it was still broken. The
diagnostic proved detection worked; only the test asked whether the robot had
actually stopped.

## Two earlier near-misses, kept for the record

- **`_requeue_task` does not exist.** My first `apply_containment` called it.
  The real helper is `_release_task(robot, reason=...)`. This would have raised
  `AttributeError` the first time a quorum was ever reached - the path least
  likely to be hit by accident.
- **The enrolment self-destruct.** With integrity on and nobody calling
  `auth.enrol()`, every sender is `UNKNOWN_SENDER`, so every robot accuses
  every peer of impersonation, quorum is met for all of them, and the whole
  fleet quarantines itself on tick one. The containment mechanism would have
  destroyed the fleet it exists to protect. Fixed by enrolling from the
  reported fleet at the top of every `_broadcast_round`.

## Measured evidence

```
integrity OFF hash: cd8b8db047d5555f    contained: ()   rejected: 0
integrity ON, honest fleet: signed 6000, verified 66028, rejected 0,
                            accusations 0, contained []
rogue injected at tick 20 -> contained at tick 21
  witnesses ['R008', 'R020']
  claimed (5.45, -1.00) but observed at (5.50, 1.50), error 2.50 m
  against a 1.50 m tolerance
  R017 quarantined=True  v=0.00  task=None   false positives: []
```

**False positives are the question that decides whether this is usable at all.**
With `SENSING_REALISTIC` over 900 ticks, `max|drift|` reached only **0.016 m**
against the 1.50 m tolerance - a ~90x margin - with 0 accusations and 0
containments. Stated honestly: odometry drift is unbounded in principle, so
this margin is an empirical finding about runs of this length, not a guarantee.

**Integrity is inert when off:** the trace hash with `integrity=False` is
byte-identical to the pre-feature hash. That is the property that lets this
ship without invalidating any previously recorded trace.

## Remaining work

1. **UI wiring for containment** (next): `store.js` `adaptRobot` must carry the
   `cl` claimed-position key; `map.js` must draw the claim as a ghost marker
   linked to the true position; the Inspector should surface
   `stats()["integrity"]` and sub-quorum `council.pending()`. `QUARANTINED` is
   already a known state in `store.js:16` and `map.js:51`.
2. Expose `integrity` in `app/api/runner.py` `RunConfig` so the Lab panel can
   switch it on (the `rogue_agent` command is already there).
3. **X-12 counterfactual co-simulation (N10)** - the last genuine novelty claim.

## Environment reminders

- Python: `/pkg/OSS-python-/3.12.0/x86_64-linux4.18-glibc2.28/bin/python3`
- Suite: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. ... -m pytest tests/ -q`
- `FaultKind` values are UPPERCASE: `inject("ROGUE_ROBOT")`, not `rogue_robot`.
  The lowercase `rogue_agent` is a UI alias mapped at `app/api/runner.py:387`.
- `app/coordination/swarm_policy.py` is untracked by git - no revert path, so
  every patch script gates on `ast.parse` and asserts `src.count(old) == 1`.
- Never `pkill -f uvicorn` - it kills my own shell. Use a PID file.

---

# Addendum - 10:43 - the operator's side is now wired too

X-10 / N9 is complete **end to end**, not just in the engine.

## Added after the summary above

| File | Change |
| --- | --- |
| `web/js/store.js` | `adaptRobot` carries the compact `cl` key into a canonical `claimed` field (null for honest robots). |
| `web/js/map.js` | The lie is drawn: a hollow ring at the claimed position, joined to the true body by a dashed line. The gap IS the evidence, and its length is the error the quorum voted on. |
| `web/js/panels/lab.js` | `#lab-integrity` selector arms signing and the sentinel council before a rogue is injected. Off by default. |
| `web/js/panels/inspector.js` | New Integrity section: the ruling, the reason, **the named witnesses**, the tick, the full detail sentence, and claimed-vs-actual. Sub-quorum suspicion renders distinctly as "Under suspicion, not contained". |
| `app/sim/engine.py` | New `_integrity_stats()`; `kpis()` now carries an `integrity` block. |
| `app/api/runner.py`, `app/api/server.py` | `integrity` flows POST body -> `RunConfig` -> `_make_policy`. |

## Two further gaps found by probing rather than by reading

1. **`kpis()` never surfaced the integrity block.** The policy computed
   `stats()["integrity"]` every tick and nothing downstream could see it. The
   KPI method's whole promise is that the number on screen and the number in
   the report cannot drift apart; a metric that never leaves the policy object
   was outside that guarantee. It returns **None**, not a dict of zeros, when
   the layer is off - the operator must be able to tell "nothing was rejected"
   from "nothing was watching", and a zero in place of an unknown is the one
   lie a dashboard about detecting lies cannot tell.
2. **The switch was wired at one end only.** `RunConfig.integrity` and the
   `_make_policy(..., integrity=)` parameter both existed, but the single call
   site still built the policy without it. The operator would have armed the
   council, seen nothing happen, and had no way to tell whether the feature or
   the fleet was at fault. Found by grepping the call site rather than trusting
   the patch.

Also worth recording: my first live probe reported `kpis.integrity: null` and
looked like a third defect. It was not - `/api/status` deliberately carries no
`robots`/`kpis`/`events`; those live on the WebSocket frame. **The probe was
wrong, not the product.** Re-probed over the real channel before changing
anything.

## Verified over the live WebSocket (port 8793)

```
config:            {... 'policy': 'swarmos', 'integrity': True}
inject:            ROGUE_ROBOT applied to R017, spoof 2.5 m, tick 31
WS kpis.integrity: enabled=true, messages_rejected=0, accusations=8,
                   robots_contained=1, reservations_reclaimed=0
WS council:        contained ['R017']
WS robot R017:     cl=[5.453, -1.0], s="QUARANTINED"
```

The containment *event* did not appear in that capture only because the socket
attached after tick 31 and frames carry that tick's events; the event itself is
covered by `test_containment_is_recorded_as_an_event`, which passes.

## Gates, after all of the above

- **Full suite: 503 passed** (107 s) - unchanged by the UI and API work.
- **Frontend contract gate: 0 errors, 0 warnings** - 10 js files, 43 html ids,
  88 tokens. The new `#lab-integrity` control lives in the Lab panel's own
  template, so the html-id count is untouched.

## The demo script this unlocks

1. Start `rush_50` with **Message integrity: on**.
2. Inject **Rogue agent (adversarial robot)**.
3. Within a tick or two, one robot grows a ghost ring and a dashed tether,
   turns `QUARANTINED`, stops, and gives up its task.
4. Select it: the Inspector names the two witnesses and states the error in
   metres against the tolerance.
5. The honest-fleet and realistic-noise runs are the answer to the obvious
   judge's question - "what stops it accusing a robot that is merely drifting?"
   Measured margin: 0.016 m of drift against a 1.5 m tolerance, 0 false
   positives over 900 ticks.

## Next

**X-12 counterfactual co-simulation (N10)** - the last genuine novelty claim
and the only remaining Wave 2 item.
