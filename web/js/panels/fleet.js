/* Fleet panel: state distribution plus a sortable roster.
 * The roster is the keyboard path to selection, so it must stay in sync with
 * the map at all times -- two views of one selection, never two selections.
 */
import { store, STATES } from "../store.js";
import { DASH, int, metres, pct } from "../format.js";

export class FleetPanel {
  constructor(el, mapView) {
    this.el = el;
    this.map = mapView;
    this.sort = "id";
    this._built = false;
  }

  render() {
    if (!store.hasData) {
      this.el.innerHTML = `
        <h2 class="panel__title">Fleet</h2>
        <div class="empty">
          <div class="empty__cause">No robots are reporting.</div>
          <div class="empty__action">Start a scenario in the Lab tab to populate the fleet.</div>
        </div>`;
      this._built = false;
      return;
    }
    if (!this._built) this._build();
    this._update();
  }

  _build() {
    const counts = store.countByState();
    this.el.innerHTML = `
      <h2 class="panel__title">Fleet composition</h2>
      <div class="statebar" id="statebar"></div>
      <div id="state-counts"></div>
      <div class="panel__section">
        <h2 class="panel__title">Resilience</h2>
        <div id="resilience"></div>
      </div>
      <div class="panel__section">
        <h2 class="panel__title">Roster</h2>
        <div class="field">
          <select class="field__control" id="roster-sort">
            <option value="id">Sort by id</option>
            <option value="state">Sort by state</option>
            <option value="battery">Sort by battery</option>
          </select>
        </div>
        <div class="roster" id="roster" role="listbox" aria-label="Robot roster"></div>
      </div>`;
    this.el.querySelector("#roster-sort").addEventListener("change", (e) => {
      this.sort = e.target.value;
      this._update();
    });
    this._built = true;
    void counts;
  }

  _update() {
    const counts = store.countByState();
    const total = store.robots.size || 1;

    const bar = this.el.querySelector("#statebar");
    bar.innerHTML = STATES
      .filter((s) => counts[s] > 0)
      .map((s) => `<div class="statebar__seg" style="width:${(counts[s] / total) * 100}%;background:var(--state-${s.toLowerCase()})" title="${s}: ${counts[s]}"></div>`)
      .join("");

    this.el.querySelector("#state-counts").innerHTML = STATES
      .filter((s) => counts[s] > 0)
      .map((s) => `<div class="kv"><span class="kv__k">${s}</span><span class="kv__v num">${int(counts[s])}</span></div>`)
      .join("");

    // Resilience counters come from the arbiter's KPIs, not from the robot
    // states, so they are reported even when the count is zero: 'zero robots
    // contained' is a real and reassuring reading, unlike a missing value,
    // which renders as a dash and never as a fabricated zero.
    const k = store.kpis || {};
    const shown = (v) => (v === null || v === undefined ? DASH : int(v));
    this.el.querySelector("#resilience").innerHTML = `
      <div class="kv"><span class="kv__k">Sovereign (radio lost)</span>
        <span class="kv__v num">${shown(k.robots_sovereign)}</span></div>
      <div class="kv"><span class="kv__k">Contained (rogue)</span>
        <span class="kv__v num">${shown(k.robots_rogue)}</span></div>
      <div class="kv"><span class="kv__k">Failed</span>
        <span class="kv__v num">${shown(k.robots_failed)}</span></div>
      <span class="chain__note">A sovereign robot lost contact with every peer and is
        navigating on a tightened envelope at half speed. It is still working.</span>
`;

    const rows = [...store.robots.values()];
    if (this.sort === "state") rows.sort((a, b) => a.status.localeCompare(b.status) || a.robot_id.localeCompare(b.robot_id));
    else if (this.sort === "battery") rows.sort((a, b) => (a.battery ?? 0) - (b.battery ?? 0));
    else rows.sort((a, b) => a.robot_id.localeCompare(b.robot_id));

    const roster = this.el.querySelector("#roster");
    roster.innerHTML = rows.map((r) => {
      const v = store.verdict(r.robot_id);
      const low = (r.battery ?? 100) < 25;
      // A sovereign or quarantined robot is named as such first; its verdict
      // alone ("SLOW") would hide the mode the operator most needs to see.
      const mode = (r.status === "SOVEREIGN" || r.status === "QUARANTINED") && v ? `${r.status} &middot; ` : "";
      return `<div class="roster__row" role="option" data-id="${r.robot_id}"
                   data-state="${r.status}" aria-selected="${r.robot_id === store.selectedRobot}"
                   data-selected="${r.robot_id === store.selectedRobot}">
        <span class="roster__id">${r.robot_id}</span>
        <span class="roster__meta">${mode}${v ? v.kind : r.status} &middot; ${metres(r.velocity, 2)} m/s${r.current_task_id ? ` &middot; ${r.current_task_id}` : ""}</span>
        <span class="roster__battery" title="Battery ${pct(r.battery)}%">
          <span class="roster__battery-fill" data-low="${low}" style="width:${Math.max(0, Math.min(100, r.battery ?? 0))}%"></span>
        </span>
      </div>`;
    }).join("");

    roster.querySelectorAll(".roster__row").forEach((row) => {
      row.addEventListener("click", () => store.select(row.dataset.id));
    });
  }
}
