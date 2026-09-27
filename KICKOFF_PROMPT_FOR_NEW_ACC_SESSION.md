# Kickoff prompt for a new ACC session

Paste the block below as the **first message** in a fresh ACC session on any
terminal. It orients the agent, forces it to verify the baseline before touching
anything, and points it at the full handoff.

---

```
I am continuing work on SWARMOS, a Smart India Hackathon project
(problem SIH26123, sponsored by Bharat Electronics Limited). It is a
distributed fleet-coordination system for autonomous mobile robots in a
smart warehouse: a 10 Hz Python simulation, a distributed safety arbiter,
an advisory-only ML layer, and a Vanilla JS + Canvas dashboard. There is
no framework, no network access and no pip - everything runs locally.

The repo is already complete and working. Before you change anything:

1. Read HANDOFF_20260922_1124_complete_session_state.md in the repo root,
   start to finish. It is the authoritative brief - architecture, the four
   invariants, all the environment landmines, the defect history and the
   open work. Do not skip section 2 (environment) or section 3 (the four
   laws); several past bugs came from violating them.

2. Then establish the baseline yourself, and tell me the numbers you get:

   PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. \
     /pkg/OSS-python-/3.12.0/x86_64-linux4.18-glibc2.28/bin/python3 \
     -m pytest tests/ -q
   # expect: 575 passed

   PYTHONPATH=. /pkg/OSS-python-/3.12.0/x86_64-linux4.18-glibc2.28/bin/python3 \
     tools/verify_ui_contract.py
   # expect: 22 pass, 1 warn, 0 FAIL

   If either differs, stop and tell me before making any change.

Key things to internalise from the handoff:

- Use the 3.12 interpreter at /pkg/OSS-python-/3.12.0/... The default
  python3 may be 3.4.1 and cannot parse this code.
- FastAPI is broken on this machine (version conflict with starlette).
  The API is raw Starlette on purpose. Do not reintroduce FastAPI.
- Your tool shell cannot reach my browser. curl to the dev server returns
  nothing from your side even while the page loads fine for me. So verify
  statically and in-process via starlette.testclient, never over live
  HTTP. That is what tools/verify_ui_contract.py does.
- Write files with a shell heredoc (cat > path <<'EOF'). Make inline edits
  by writing a tools/patch_*.py script that asserts each anchor matches
  exactly once, and have it buffer every edit in memory and write all
  files only at the end.
- Code comments are ASCII-only: no emoji, smart quotes, arrows or
  em-dashes in .py, .js or .css.
- Do not ask me for permission to save files. Just write them.
- Do not stop at a milestone boundary - keep going until the task is
  actually done, and write a session summary when you finish a milestone.

The honest status of the two success criteria, which must not be dressed
up in any slide or doc: C1 (zero collisions) is MET, with the caveat that
the baseline also scored zero so it is necessary but not differentiating.
C2 (20 pct throughput gain) is NOT MET - measured -19.3 pct, 95 pct CI
[-36.0, -2.6]. Two structural reasons are documented: task supply rather
than run length is the binding constraint, and avg_completion_s is
survivorship-biased across arms.

Once you have read the handoff and reported the two baseline numbers, tell
me what you think the highest-value next move is, and wait for me before
starting it.
```

---

## Notes for the repo owner

- Everything the agent needs is committed, so a plain
  `git clone <repo> && cd <repo>` is enough on the other machine.
- If the colleague's terminal shows ~250 files as modified with zero content
  changes, that is a permission-bit (644 vs 755) artefact, not real work. Fix it
  with `git config core.fileMode false` inside the clone. That setting is local
  to each clone and is not carried by the repo, so it may need repeating.
- The demo still launches with `./run.sh --demo` then `http://127.0.0.1:8770`.
- If you want the colleague's session to pick up a *specific* point rather than
  the tip, give them the commit hash as well - the handoff records the relevant
  history in section 11.
