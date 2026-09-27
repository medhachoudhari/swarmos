/* Formatting helpers. One rule: a value that does not exist renders as "--",
 * never as 0, never as "N/A", never as an invented placeholder. A zero that
 * means "no data" is a lie the operator cannot detect.
 */

export const DASH = "--";

export function num(v, digits = 0) {
  if (v == null || Number.isNaN(v)) return DASH;
  return Number(v).toFixed(digits);
}

export function int(v) {
  if (v == null || Number.isNaN(v)) return DASH;
  return Math.round(v).toLocaleString("en-US");
}

export function secs(v, digits = 1) {
  if (v == null || Number.isNaN(v)) return DASH;
  return Number(v).toFixed(digits);
}

export function metres(v, digits = 2) {
  if (v == null || Number.isNaN(v)) return DASH;
  return Number(v).toFixed(digits);
}

/** Heading in radians -> compass-ish degrees, 0 = +X, counter-clockwise. */
export function headingDeg(rad) {
  if (rad == null || Number.isNaN(rad)) return DASH;
  const deg = ((((rad * 180) / Math.PI) % 360) + 360) % 360;
  return deg.toFixed(0);
}

export function pct(v, digits = 0) {
  if (v == null || Number.isNaN(v)) return DASH;
  return Number(v).toFixed(digits);
}

/** Short hash for display; the full hash is always available on hover. */
export function shortHash(h) {
  if (!h) return DASH;
  return h.length <= 16 ? h : `${h.slice(0, 8)}...${h.slice(-8)}`;
}

export function titleCase(s) {
  if (!s) return DASH;
  return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
}
