# SESSION SUMMARY — 2026-09-20 20:44 IST

**Project**: SWARMOS — Edge-AI Based Distributed Fleet Coordination for Autonomous
Mobile Robots in Smart Warehouses
**Event**: Smart India Hackathon 2026 | Problem ID **SIH26123** | Sponsor **Bharat
Electronics Limited (BEL)** | Theme Robotics & Drones
**Repo**: `/home/fdipglob_ai_tools/nxp60742/acc_id_work/chin_20260920`
(remote `https://github.com/adithyad-cs/swarmos-member4-coordination.git`)

---

## 1. Objective of this session

1. Produce a detailed blueprint Word document describing the whole project so it could be
   submitted to external AI tools for an independent gap review.
2. Author the adversarial review prompt to drive those external reviews.
3. Ingest the returned reviews, cross-compare them, and freeze the final scope.
4. Begin implementation of all six modules.

---

## 2. Artefacts produced

| Artefact | Purpose |
|---|---|
| `docs/gen_project_blueprint_docx.py` | Reproducible generator, 18 sections |
| `SWARMOS_Project_Blueprint_and_Feature_Inventory.docx` | 184 paragraphs, 9 tables, 55 KB — the document sent out for review |
| `docs/AI_REVIEW_PROMPT.md` | Four-voice adversarial review prompt (JUDGE / PROFESSOR / DESIGNER / RIVAL), 10 numbered asks, explicit do-NOT list |
| This session summary | Decision record |

---

## 3. External reviews received

| Tool | File | Character |
|---|---|---|
| 1 | `SWARMOS_Blueprint_Addendum_A_New_Features.docx` (868 lines) | The normative delta. 22 X-series features, re-adjudicated novelty register N1-N10, 10-row cut list, 10 UI/UX corrections, 22-row ranked action list with cut line at rank 14 |
| 2 | `SWARMOS_Final_Adversarial_Review_and_New_Features_Chat.docx` (1314 lines) | Re-organises Tool 1 into the 10 asks. Adds problem-statement coverage matrix, 12-question hostile Q&A, 10-beat 5-minute demo script |
| 3 | `gem1.docx` (636 lines) | Same 22 X-series. Adds mechanism-level detail and exact numeric thresholds |
| 4 | `chat2.docx` | Same 22 X-series plus 4 appendices and a final panel consensus. Promotes the Decision Inspector to headline surface |

### Key cross-comparison finding

**All four reviews independently converged on the same 22 features.** Tool 2 restates
Tool 1. Tools 3 and 4 arrived at the same list from a different starting point, which is
strong corroboration rather than new information. **No fifth major idea appeared in any
review. The feature set is therefore treated as closed.**

The genuine value of Tools 3 and 4 is mechanism-level specificity that Tools 1 and 2 left
abstract.

---

## 4. What the review changed about the project

The review's central finding, accepted in full: **three of the eight original novelty
claims were soft and two were indefensible.**

| Claim | Original status | Final decision |
|---|---|---|
| N1 decentralised auction | claimed novel | INCREMENTAL — it is Contract Net Protocol (Smith 1980), ST-SR-IA in the Gerkey-Mataric taxonomy. Strengthened, not dropped |
| N2 intent + space-time reservation | claimed novel | **Demoted to table stakes** — this is WHCA* (Silver 2005) and Kiva-class practice |
| N3 deterministic replay | claimed novel | GENUINE as engineering |
| N4 deadlock detection | claimed novel | INCREMENTAL — Coffman conditions, Knapp 1987, Kim & Tanchoco, Reveliotis |
| N5 ML behind safety firewall | claimed novel | **GENUINE** — restated openly as the Simplex runtime-assurance architecture (Sha 2001). Naming the prior art makes it stronger because the contribution is the enforcement and its measurement |
| N6 degradation ladder | claimed novel | INCREMENTAL until degradation is *measured* rather than declared |
| N7 digital-twin command centre | claimed novel | **Reclassified as differentiation, not novelty.** Claiming a UI as a technical contribution invites a professor to discount the entire list |
| N8 closed-loop analytics | claimed novel | **DELETED.** As specified it was offline parameter tuning with a feedback arrow drawn on a slide |
| **N9 adversarial robot containment** | — | **NEW, GENUINE.** Most BEL-relevant claim in the deck |
| **N10 counterfactual co-simulation** | — | **NEW, GENUINE, impact 10.** Hardest single thing for a rival to copy |

Result: **9 claims, every one defensible, each with a number on screen behind it.**

---

## 5. The five items where Tools 3 and 4 beat the earlier proposals

Accepted because each closes a real hole rather than adding surface:

1. **X-23 Failure detector + gossip reservation GC** — 10 Hz heartbeats, >200 ms miss means
   adjacent peers declare failure, gossip-invalidate the dead agent's space-time
   reservations, reroute around last known coordinate.
   *Why it matters*: X-01 killed a process but never said who cleans up its reservations.
   Without this, the on-stage `kill -9` leaves ghost reservations and the fleet deadlocks.
   This is the item that makes the staged failure actually recover.
2. **X-24 Deterministic lock arbitration** — concurrent claims on one cell tie-break on the
   immutable multi-attribute utility score U_i, then unique agent sequence ID. Higher U
   takes the lock, lower yields. Backed by `tests/test_race_condition.py`.
3. **X-25 Bounded radio range R_comm = 15 m** — intent broadcast reaches neighbours within
   15 m only, giving O(k) message complexity with k much less than N.
   *Why it matters*: this is what makes "Edge" honest, because a real robot has finite
   radio, and it converts the X-03 scaling chart from a rising slope into a flat line.
   Single best technical detail across all four reviews.
4. **Decision Inspector promoted to the headline surface** — pinned rail card carrying
   intent, reservation, per-term utility stack, verdict, and the numeric winning margin
   over the runner-up. N7 is re-pitched as "we render the reasoning, not the robots."
5. **The real SIH26123 success criteria** — **zero collisions** and **at least 20%
   task-completion-time reduction versus a stop-and-wait baseline**. No earlier document
   had the published numbers. These become the two headline figures the whole build and
   demo exist to prove, and the X-12 ghost baseline is specified as *stop-and-wait* so the
   20% is measured against the correct control.

---

## 6. Decisions held against the reviewers' advice

| Item | Decision | Reason |
|---|---|---|
| X-07 bounded windowed CBS | **REJECT for this build** | All four rank it last (score 1.6); Tool 1 explicitly says do not half-build it. We describe the design and expose the escalation hook, and answer the question verbally |
| X-19 UCB1 bandit | **DEFER**, and therefore delete N8 | Nine airtight claims beat ten with one soft claim. Half-measures here are the most attackable item in the deck |
| X-05, X-06, X-08, X-11, X-15, X-21 | **DEFER** to a stretch list | All correct, none load-bearing for the demo. X-05 auto-promotes if X-20 lands early, since the forecaster needs a consumer |
| X-01 Sovereign Agent Mode | **ACCEPT with a hedge** | Built as a swappable transport behind the existing `transport.py` interface, single-process tick loop first. If process mode runs long we still have a working demo and lose exactly one claim instead of the whole system |

---

## 7. Frozen scope

- 6 items already DONE (M4 Step 4A, unit-tested)
- **27 accepted additions** (the accepted X-series subset plus X-23, X-24, X-25, the
  Decision Inspector promotion, and the success-criteria instrumentation)
- **10 cuts applied** — global search U-08, focus mode as a separate mode U-06, palette
  trimmed to 8 real commands, Analytics cut to 4 charts, scenarios 6 to 3
  (`rush_50`, `narrow_aisle_deadlock`, `blocked_aisle`; the other two become fault
  injections), ARIA audit, `GET /api/report`, decorative congestion heatmap, the
  RandomForest action classifier A-02 deleted outright, and N8 as written
- **10 UI/UX corrections** with concrete tokens: surface `#0F1419`, three-level ink
  `#E8EDF2` / `#9AA7B4` / `#63707D`, saturated colour reserved for state only, level-of-
  detail rendering above and below 0.6 zoom, one 400 ms conflict pulse then a static 2 px
  ring, one hero metric at 40 px tabular, empty states that name cause and next action
  inline, degraded banners instead of red toasts, fixed 68/22/10 three-zone layout that
  never moves
- **9 novelty claims**

---

## 8. Build order agreed

M5 simulation (+X-15 hooks, X-14) → M6 database and analytics (+X-13, X-03, X-22) →
M4 Step 4B (X-09, X-18, X-17, X-16, X-24, X-25, X-02, X-23, then X-01, X-10) →
M2 API and 10 Hz tick loop → M1 web (tokens and fixed layout first, then Live Map,
Decision Inspector, Simulation Lab, Analytics) → M3 ML (X-20, X-04) →
X-12 ghost fleet versus stop-and-wait → verification of the two success criteria →
`run.sh` and README → master specification deck.

The system is kept runnable at the end of every step rather than integrated once at the
end.

---

## 9. Environment note

All Python must run under
`/pkg/OSS-python-/3.12.0/x86_64-linux4.18-glibc2.28/bin/python3`.
The default `python3` on this host is 3.4.1 and unusable.
Verified available: pydantic 2.13.5, fastapi 0.104.1, uvicorn 0.52.4, websockets 17.1,
numpy 1.26.2, pandas 2.1.3, scikit-learn 1.3.2, python-pptx 1.0.2, python-docx 1.1.0,
pytest 9.1.1, sqlite3 (stdlib).

---

## 10. Next actions

1. Generate `SWARMOS_Final_Implementation_Feature_List.docx` from
   `docs/gen_implementation_list_docx.py`.
2. Begin implementation at M5.
