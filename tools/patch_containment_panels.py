"""Lab toggle for the sentinel council, and an Inspector containment section.

The mechanism already works end to end and is proven over the live socket.
What is missing is the operator's side of it: a way to arm the council before
injecting a rogue, and a place that says WHO voted and WHY, in words, for the
robot currently selected.

The Inspector is deliberately the place for this. The map shows that a claim
and a body disagree; only the Inspector can name the witnesses. A containment
with no named witnesses is an accusation without evidence, which is exactly
what the quorum rule exists to prevent - so the UI must show the evidence or
it misrepresents the mechanism.
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def patch(rel, pairs):
    path = ROOT / rel
    src = path.read_text()
    for old, new in pairs:
        assert src.count(old) == 1, (rel, old[:70], src.count(old))
        src = src.replace(old, new)
    path.write_text(src)
    print("patched", rel)


# -- Lab: arm the council -------------------------------------------------
patch("web/js/panels/lab.js", [(
    """        <div class="field__hint">Same seed and same scenario must reproduce the same trace hash.</div>
      </div>""",
    """        <div class="field__hint">Same seed and same scenario must reproduce the same trace hash.</div>
      </div>
      <div class="field">
        <label class="field__label" for="lab-integrity">Message integrity</label>
        <select class="field__control" id="lab-integrity">
          <option value="off" selected>Off</option>
          <option value="on">Signed messages and sentinel council</option>
        </select>
        <div class="field__hint">When on, robots sign their broadcasts and neighbours
          cross-check position claims. Two independent witnesses are required before
          any robot is contained. Off by default, and off changes nothing: the trace
          hash is identical either way.</div>
      </div>""",
), (
    """      seed: Number(this.el.querySelector("#lab-seed").value),
    };""",
    """      seed: Number(this.el.querySelector("#lab-seed").value),
      integrity: this.el.querySelector("#lab-integrity").value === "on",
    };""",
)])

# -- Inspector: name the witnesses ---------------------------------------
patch("web/js/panels/inspector.js", [(
    """    const v = store.verdict(id);""",
    """    const ig = store.kpis && store.kpis.integrity ? store.kpis.integrity : null;
    const council = ig && ig.council ? ig.council : null;
    // The most recent council ruling about THIS robot, if any.
    const ruling = council && Array.isArray(council.events)
      ? [...council.events].reverse().find((e) => e.robot_id === id) || null
      : null;
    // Sub-quorum suspicion: accused, but not yet by enough witnesses. Showing
    // this matters - it is the difference between "under suspicion" and
    // "convicted", and collapsing the two would make the quorum meaningless.
    const pending = council && council.pending ? council.pending[id] || null : null;

    const v = store.verdict(id);""",
), (
    """      <div class="panel__section">
        <h2 class="panel__title">Movement intent</h2>""",
    """      ${ig ? `
      <div class="panel__section">
        <h2 class="panel__title">Integrity</h2>
        ${ruling ? `
          <div class="kv"><span class="kv__k">Ruling</span><span class="kv__v">
            <span class="chip" data-state="QUARANTINED">${ruling.action === "quarantine" ? "CONTAINED" : "RELEASED"}</span>
          </span></div>
          <div class="kv"><span class="kv__k">Reason</span><span class="kv__v">${ruling.reason || DASH}</span></div>
          <div class="kv"><span class="kv__k">Witnesses</span><span class="kv__v">${(ruling.witnesses || []).join(", ") || DASH}</span></div>
          <div class="kv"><span class="kv__k">At tick</span><span class="kv__v num">${int(ruling.tick)}</span></div>
          <div class="chain__note">${ruling.detail || ""}</div>
        ` : pending ? `
          <div class="kv"><span class="kv__k">Ruling</span><span class="kv__v">Under suspicion, not contained</span></div>
          <div class="chain__note">Accused by ${int(pending)} witness${pending === 1 ? "" : "es"};
            ${int(council.quorum)} are required. One robot's word is never enough.</div>
        ` : `
          <div class="kv"><span class="kv__k">Ruling</span><span class="kv__v">No accusation</span></div>
          <div class="chain__note">Signatures verified; position claims agree with what
            neighbours observed.</div>
        `}
        ${r.claimed ? `
          <div class="kv"><span class="kv__k">Claimed</span><span class="kv__v num">${metres(r.claimed.x)}, ${metres(r.claimed.y)} m</span></div>
          <div class="kv"><span class="kv__k">Actual</span><span class="kv__v num">${metres(r.position.x)}, ${metres(r.position.y)} m</span></div>
        ` : ""}
      </div>` : ""}

      <div class="panel__section">
        <h2 class="panel__title">Movement intent</h2>""",
)])
