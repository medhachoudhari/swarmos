# Session summary - 2026-09-22 00:40 - C1: two real defects, root-caused and fixed

## One-line

Running the C2 re-measurement the criteria document had left as a promise
exposed a genuine safety failure in C1; root-causing it found **two independent
defects**, both now fixed, both pinned by tests that fail on the old code, and
every document and slide that quoted the old numbers has been corrected.

## What triggered this

Block E was declared complete with only "explicit verification of the two stated
success criteria" outstanding. Acting on the standing instruction to complete the
whole project rather than stopping at milestone boundaries, I ran
`tools/verify_criteria_powered.py 9000 9` - the powered version of a measurement
that had previously only ever been run at 1800 ticks.

It returned `C1 zero collisions in the SwarmOS arm: 7 FAIL`, with **zero**
collisions in the stop-and-wait control. That is the exact inverse of the
project's central safety claim, and it had been invisible because the published
PASS came from a run too short to reach the first failure at tick 700.

## Defect 1 - free waypoint snap (app/sim/robot.py)

`SimRobot.step` snapped onto any waypoint within `WAYPOINT_TOLERANCE_M = 0.08` m
while charging **neither** `moved` nor `budget`. A robot therefore collected up to
0.08 m of unauthorised displacement per waypoint per tick on top of its granted
speed.

Evidence: at tick 699 of `blocked_aisle` seed 29 the monitor cleared `scale=0.25`
with a predicted closest approach of 0.7539 m - 0.0039 m of margin above the
0.750 m floor - authorising at most 0.055 m. The engine moved R007 **0.0777 m**
on a charged budget of 0.016 m.

Fix: `if leg <= WAYPOINT_TOLERANCE_M and leg <= budget:` plus `moved += leg;
budget -= leg`. Applied by `tools/patch_c1_waypoint_snap.py`. Result: **7
collisions -> 1**, `blocked_aisle 29` overlap_ticks 8301 -> 0.

Two probe bugs found along the way, both recorded in the criteria doc because
either would have produced a confident wrong answer: post-step `velocity` is
zeroed on arrival (24 phantom breaches), and `speed_scale` must be read **after**
`eng.step()` because `_apply_verdicts` assigns it inside the step (566 phantom
breaches).

## Defect 2 - truncated step envelope (app/coordination/swarm_policy.py)

One collision survived, and `diag_c1_stepbound` reported **zero** step-authority
breaches on it - so it was a different mechanism, not a residue of the first.

`_monitor` bounded its own next step with `project_step(me, MAX_STEP_M)`, which
walks the robot's published movement intent. When the remaining path is shorter
than a step, that projection stops at the end of the path. At tick 718 of
`blocked_aisle` seed 17 the projection was 0.0440 m, so every swept gap read back
as the standing-still gap 0.7520 m, the whole `MONITOR_SCALES` ladder looked
clear, and full speed was granted. The engine then moved R030 0.0540 m straight
into a stationary R040, crossing the 0.750 m floor and the 0.700 m collision
distance in one tick.

Fix: new module-level `_step_envelope(here, projected)` keeps the projection's
direction and extends the distance to `MAX_STEP_M`. A zero-length projection is
left alone - inventing a heading for a stationary robot would manufacture motion
nobody intends and wedge the aisle. Applied by
`tools/patch_c1_sound_envelope.py`; the change is strictly conservative, the
envelope only grows.

Deliberately **not** changed: the `granted` segments published for peers, which
also call `project_step`. Over-assuming peer motion was already measured to cost
31 percent of robot-ticks to phantom motion. Only the bound a robot applies to
*itself* was unsound.

Result: `blocked_aisle 17` collisions 1 -> 0, overlap_ticks 8282 -> 0; seeds 29
and 19 stay clean at 9000 ticks.

## Regression cover and gate

`tests/test_c1_step_authority.py` now carries four tests, all failing on pre-fix
code:

- `test_displacement_never_exceeds_granted_speed[blocked_aisle-29]`, `[rush_50-19]`
- `test_blocked_aisle_seed29_is_collision_free_past_tick_700` (defect 1)
- `test_blocked_aisle_seed17_is_collision_free_past_tick_719` (defect 2 - the
  step-authority test is structurally blind to this one)
- `test_step_envelope_never_understates_a_tick_of_motion` (unit cover on the new
  helper: short projections grow, long ones are untouched, stationary robots do
  not move, bearing is preserved)

Full suite: **575 passed in 91.81 s**.

## C2 - the honest result, and two findings worth more than the number

Post-defect-1 powered run, 27 paired runs: mean **-13.7 pct**, 95 pct CI
**[-26.6, -0.7]**, target >= 20 pct. **NOT MET, and the sign is negative** - the
entire interval sits below zero, so on this statistic we are slower than the
baseline. Reported as measured.

Two structural findings changed what the criterion can even mean:

1. **Task supply, not run length, is the binding constraint.** At 9000 ticks the
   `blocked_aisle` baseline is byte-identical to the 1800-tick run (85.19 /
   74.54 / 90.27 s, 16 / 14 / 14 done). Five times the horizon, zero extra
   completions. This **refutes** the old document's own top recommendation
   ("run 18000 ticks") and confirms its fourth.
2. **`avg_completion_s` across arms is survivorship-biased.**
   `narrow_aisle_deadlock` seed 11: baseline 112.74 s with 12 done vs swarmos
   83.57 s with 3 done, scored "+25.9 pct better". We looked faster only because
   we finished a quarter as many tasks - the easy ones.

The sound replacement is specified: equal-completion-count time, or
`tasks_per_min` over a fixed horizon. Neither needs new simulation for the first
pass - the paired runs are on disk.

## Documents and deck corrected

- `docs/SUCCESS_CRITERIA_VERIFICATION.md` fully rewritten (308 lines). The old
  version's "C1 PASS" and "the baseline is also collision-free" claims are gone,
  replaced by the 7-collision failure, both root causes with their traces, both
  fixes, the re-verification, the honest C2 number and the two structural
  findings. Backup at `/tmp/SUCCESS_CRITERIA_VERIFICATION.before_c1_rewrite.md`.
- `docs/gen_master_spec_pptx.py`: slide 18 rewritten to the measured truth, a
  **new slide 19 "How C1 was actually won"** added telling the two-defect story
  (this is stronger evidence of engineering discipline than a green tick would
  have been), old slide 23's roadmap rewritten since its top two items are now
  answered. Patched by `tools/patch_deck_criteria_truth.py` then
  `tools/patch_deck_trim_1819.py` to hold the 1400-char density budget.
- Deck regenerated and verified by reading it back with python-pptx:
  **25 slides, char counts 309 to 1319, flagged=0, non-ascii chars []**.

## Environment notes worth keeping

- `_step_envelope` lives immediately before `class SwarmPolicy` in
  `swarm_policy.py`; `math` is imported at line 50.
- `swarm_policy.py` is **not** git-tracked. Backups in /tmp, newest first:
  `swarm_policy.before_envelope.py`, `...before_c1_fix.py`, `...before_prune.py`,
  `...before_sovereign.py`, `...with_cache.py`, `...before_planner.py`.
- The powered run takes ~2260 s. Poll with a bounded `for j in $(seq 1 52); do
  kill -0 <PID> || break; sleep 5; done` loop using an **absolute** log path;
  `&`-detached `while` loops lose the `cd`, and `sleep 290` exceeds the 300 s
  command timeout.
- Deck density standard is flagged=0 against a 1400-char-per-slide check.

## Closed: the confirmation measurement

`reports/criteria_after_envelope_fix.log` finished in 2319.9 s (9000 ticks,
9 seeds, 3 scenarios, both arms, 27 pairs):

```
C1 zero collisions in the SwarmOS arm: 0  PASS
   baseline arm collisions (control, expected > 0): 0
C2 paired reduction in avg_completion_s, n=27 paired runs
  mean            : -19.3 pct
  std dev         :  42.2 pct
  95 pct CI       : [-36.0, -2.6] pct
  target          : >= 20 pct
  verdict         : NOT MET - the whole interval sits below the bar
```

- **C1 PASS.** 7 collisions -> 0, and no `SwarmOS collision run:` line anywhere
  in the log. Both defects are pinned by tests that fail on the old code.
- **C2 still NOT MET, and the mean moved from -13.7 pct to -19.3 pct.** That is
  the expected direction: defect 2 was the arbiter under-estimating a robot's own
  one-tick reach and therefore granting speed it should have withheld, so a sound
  bound costs throughput. A C2 that had *improved* after this fix would have been
  evidence the fix was inert.
- The statistic itself remains unsound across arms (survivorship bias in
  `avg_completion_s`); re-scoring C2 on an unbiased measure is roadmap item 1.

Everything is now consistent: `docs/SUCCESS_CRITERIA_VERIFICATION.md` carries the
final numbers in its "Final powered result" section, and slide 18 of the master
spec deck shows -19.3 pct / [-36.0, -2.6] (deck re-verified at 25 slides,
flagged=0, non-ascii []).

## Remaining work, unchanged

1. Re-score C2 on an equal-completion-count or `tasks_per_min` statistic.
2. Raise task supply so `blocked_aisle` is not exhausted inside the run window.
3. Consider whether the peer `granted` segments should also use `_step_envelope`
   - they intentionally do not today, because over-assuming peer motion already
   costs 31 percent of robot-ticks to phantom motion.
