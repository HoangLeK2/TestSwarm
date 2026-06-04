/** Bounded label for device Select (long model/serial otherwise breaks the top bar). */
export function formatDeviceSelectLabel(d: {
  brand: string;
  model: string;
  serial: string;
}) {
  const left = `${d.brand} ${d.model}`.trim().replace(/\s+/g, ' ');
  const s = d.serial;
  const serialShort = s.length > 16 ? `${s.slice(0, 7)}…${s.slice(-6)}` : s;
  if (!left) return serialShort;
  const maxLeft = 26;
  const leftShort =
    left.length > maxLeft ? `${left.slice(0, maxLeft - 1)}…` : left;
  return `${leftShort} — ${serialShort}`;
}

export function deviceSelectFullTitle(d: {
  brand: string;
  model: string;
  serial: string;
}) {
  const left = `${d.brand} ${d.model}`.trim();
  return left ? `${left} — ${d.serial}` : d.serial;
}
