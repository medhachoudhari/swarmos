# SWARMOS — Team Member Status Collection Prompt

**Purpose:** collect an accurate, honest snapshot of every member's actual
progress so the six modules can be integrated without late surprises.

**Why this matters:** the most common way hackathon teams fail is not bad
code — it is six working modules that have never run together, discovered
too late. Section 5 (data contracts) of the prompt below is specifically
designed to surface those mismatches now instead of in the final week.

---

## Part A — Message to send to each team member

> Team — before we lock the final architecture I need a written snapshot of
> where each of us actually is, so we don't discover integration problems in
> the last week.
>
> Please paste the prompt in Part B into whichever AI tool you have been using
> for SWARMOS (ChatGPT / Claude / Copilot / Cursor). Ideally use the same
> session where you did the work so it has context.
>
> Send me back the full output as a .md file or plain text. Not a screenshot.
>
> Be honest about what is NOT built yet. I need reality, not a good
> impression. Guessing is worse than saying "not started".
>
> IMPORTANT: do not paste any passwords, API keys or GitHub tokens into the
> output.
>
> Deadline: <fill in>

---

## Part B — The prompt for them to paste (send verbatim)

```
You are acting as a technical session-summary generator for a Smart India
Hackathon project called SWARMOS (Problem ID SIH26123, Bharat Electronics
Limited, theme: Robotics and Drones — "Edge-AI Based Distributed Fleet
Coordination for Autonomous Mobile Robots in Smart Warehouses").

I am ONE member of a 6-member team. Another member is consolidating the
whole system architecture and needs an accurate written snapshot of MY
part so the modules can be integrated without surprises.

Produce a structured handoff document using EXACTLY the section headings
below. This document will be read by another engineer and another AI tool,
so it must be precise and factual.

CRITICAL RULES:
- Do NOT invent, assume, or exaggerate anything. If something is not built,
  write "NOT STARTED" or "NOT BUILT".
- Clearly separate WHAT ACTUALLY EXISTS as working code from WHAT IS ONLY
  PLANNED. This distinction matters more than anything else in this document.
- Do NOT include any passwords, API keys, tokens, or credentials.
- If you are unsure whether something works, say "UNVERIFIED" rather than
  guessing.
- Inspect the actual files/workspace if you have access to them, rather than
  relying on memory of our conversation.
- Be concise. Use bullet points and tables. No marketing language.

=== SECTION 1: MY ROLE ===
- My name and which of these roles I own:
  M1 Frontend/UI-UX | M2 Backend/Integration | M3 AI-ML |
  M4 Robotics/Multi-Agent | M5 Simulation + Path Planning |
  M6 Database/Analytics
- One-sentence description of what I believe my module is responsible for.

=== SECTION 2: WHAT IS ACTUALLY BUILT (WORKING CODE) ===
For each item: file/folder path, approximate line count, what it does, and
whether it RUNS today (yes / partially / no). Only list things that exist.

=== SECTION 3: WHAT IS NOT BUILT YET ===
Everything I have planned or discussed but have NOT implemented.

=== SECTION 4: TECH STACK I AM USING ===
Languages, frameworks, libraries with versions, build/run commands, OS,
Python/Node version. Include the exact command used to start or test my part.

=== SECTION 5: MY DATA CONTRACTS (MOST IMPORTANT SECTION) ===
This is what the integration depends on. Be very specific.
5a. INPUTS — what data does my module need FROM other members?
    For each: the data, which member should provide it, and the exact
    expected format (JSON schema, field names, types, units). If I have
    only assumed a format, mark it "ASSUMED — needs confirmation".
5b. OUTPUTS — what data does my module produce FOR other members?
    For each: the data, its exact format/schema with field names and types,
    and how it is exposed (REST endpoint, WebSocket, function call, DB table,
    file). Include a real example payload if one exists.
5c. Any place where I am currently guessing what another member's data looks
    like. List these explicitly — they are the highest integration risk.

=== SECTION 6: MY KEY ALGORITHMS / DESIGN DECISIONS ===
For each significant choice: what I chose, why, what alternatives I rejected,
and any known limitation. If I made a choice arbitrarily, say so honestly.

=== SECTION 7: MY IDEAS AND FEATURE PROPOSALS ===
Features or novelty ideas I think would help us win, including ones I have
not started. Mark each as: must-have / nice-to-have / stretch.

=== SECTION 8: PROBLEMS, BLOCKERS AND RISKS ===
- What is blocking me right now.
- What I am waiting on from another member.
- What I am worried will break or not finish in time.
- Anything I do not know how to do yet. (Be honest — this is the most useful
  part of the whole document.)

=== SECTION 9: MY TESTS ===
Do I have automated tests? How many, what do they cover, do they pass, and
what is the command to run them? If none, write "NO TESTS".

=== SECTION 10: WHAT I NEED DECIDED BY THE TEAM ===
Open questions requiring a group decision (shared formats, units,
coordinate system, robot ID naming convention, tech choices, who owns X).

=== SECTION 11: TIME AVAILABLE ===
Realistically how many hours per week I can commit until the deadline,
and any exam/travel/work conflicts.

=== SECTION 12: DEMO VIEW ===
What will MY part look like in the final live demo? What will a judge
actually see or be able to click?

Output the whole thing as clean Markdown so it can be pasted into a file.
```

---

## Part C — Where to save the replies

Save each reply into this repository so it is version controlled and all in
one place:

```
docs/team_inputs/M1_frontend_summary.md
docs/team_inputs/M2_backend_summary.md
docs/team_inputs/M3_aiml_summary.md
docs/team_inputs/M5_simulation_summary.md
docs/team_inputs/M6_database_summary.md
```

M4 (Robotics/Multi-Agent) is already documented by:
- `SWARMOS_Complete_Session_Handoff_and_Master_Prompt.docx`
- `docs/member4_step4_checkpoint.md`
- `docs/member4_step4a_design_decisions.md`
- `docs/member4_step4a_learning_map.md`

---

## Part D — What happens after the replies arrive

1. Build a contract-conflict matrix: every mismatch between what one member
   emits and what another member expects. This is the single highest-value
   artefact for the team.
2. Revise `SWARMOS_Team_Plan_SIH26123.pptx` from v1 to v2 using real member
   capabilities instead of assumptions.
3. Reassign scope based on actual available hours per member (Section 11).
4. Merge their feature ideas into the novelty shortlist.

---

## Rationale for each section (for your own reference)

| Section | Why it is in the prompt |
|---|---|
| 2 vs 3 | AI tools are optimistic and describe planned work as done. Forcing an explicit NOT BUILT list is the only way to get a real baseline. |
| 5a / 5b | Catches the classic failure: one member emits metres, another expects grid cells. |
| 5c | "Where am I guessing" is the highest-signal question in the whole document. |
| 6 | Feeds the per-member Q&A Defence slides for the judges' round. |
| 8 | Blockers surfaced early are cheap; surfaced late they are fatal. |
| 10 | Shared decisions (units, coordinate system, robot ID format) must be made once, by the group, early. |
| 11 | Plans fail on capacity, not ideas. Scope must match real available hours. |
| 12 | Anything that cannot be seen by a judge does not score. |
