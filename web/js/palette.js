/* Command palette: eight commands, no more.
 *
 * Eight was a deliberate cut from a longer list. A palette with thirty entries
 * is a menu; a palette with eight is a set of things the operator actually does
 * during a demo. Ctrl/Cmd+K opens, typing filters, arrows move, Enter runs,
 * Escape closes and returns focus to whatever had it before.
 */
import { store } from "./store.js";

export class Palette {
  constructor({ scrim, input, list, commands }) {
    this.scrim = scrim;
    this.input = input;
    this.list = list;
    this.commands = commands;
    this.open = false;
    this.cursor = 0;
    this.filtered = commands.slice();
    this._prevFocus = null;

    this.input.addEventListener("input", () => { this.cursor = 0; this._filter(); });
    this.input.addEventListener("keydown", (e) => this._onKey(e));
    this.scrim.addEventListener("mousedown", (e) => { if (e.target === this.scrim) this.close(); });
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        this.toggle();
      } else if (e.key === "Escape" && this.open) {
        e.preventDefault();
        this.close();
      }
    });
  }

  toggle() { this.open ? this.close() : this.show(); }

  show() {
    this._prevFocus = document.activeElement;
    this.open = true;
    this.scrim.dataset.open = "true";
    this.input.value = "";
    this.cursor = 0;
    this._filter();
    this.input.focus();
  }

  close() {
    this.open = false;
    this.scrim.dataset.open = "false";
    if (this._prevFocus && this._prevFocus.focus) this._prevFocus.focus();
  }

  _onKey(e) {
    if (e.key === "ArrowDown") { e.preventDefault(); this._move(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); this._move(-1); }
    else if (e.key === "Enter") { e.preventDefault(); this._run(); }
  }

  _move(d) {
    if (this.filtered.length === 0) return;
    this.cursor = (this.cursor + d + this.filtered.length) % this.filtered.length;
    this._paint();
  }

  _filter() {
    const q = this.input.value.trim().toLowerCase();
    this.filtered = q
      ? this.commands.filter((c) => (c.name + " " + c.desc).toLowerCase().includes(q))
      : this.commands.slice();
    this._paint();
  }

  _paint() {
    if (this.filtered.length === 0) {
      this.list.innerHTML = `<div class="empty">
        <div class="empty__cause">No command matches that text.</div>
        <div class="empty__action">Clear the filter or press Escape to close.</div>
      </div>`;
      return;
    }
    this.list.innerHTML = this.filtered.map((c, i) => `
      <div class="palette__item" role="option" data-i="${i}" aria-selected="${i === this.cursor}">
        <span class="palette__name">${c.name}</span>
        <span class="palette__desc">${c.desc}</span>
        ${c.hint ? `<span class="palette__key">${c.hint}</span>` : ""}
      </div>`).join("");
    this.list.querySelectorAll(".palette__item").forEach((n) => {
      n.addEventListener("mouseenter", () => { this.cursor = Number(n.dataset.i); this._paint(); });
      n.addEventListener("click", () => { this.cursor = Number(n.dataset.i); this._run(); });
    });
    const sel = this.list.querySelector('[aria-selected="true"]');
    if (sel && sel.scrollIntoView) sel.scrollIntoView({ block: "nearest" });
  }

  _run() {
    const cmd = this.filtered[this.cursor];
    if (!cmd) return;
    this.close();
    try {
      cmd.run();
    } catch (err) {
      store.setLink(store.link, `Command "${cmd.name}" failed: ${err && err.message ? err.message : err}`);
    }
  }
}
