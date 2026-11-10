// Display helpers. Exact amounts always come from integer paise; the compact
// forms are for axis ticks and summaries, never for tables or tooltips.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Group digits the Indian way: 12345678 -> "1,23,45,678". */
export function indianGrouping(n: number | bigint): string {
  const s = n.toString();
  if (s.length <= 3) return s;
  const head = s.slice(0, -3);
  const tail = s.slice(-3);
  return `${head.replace(/\B(?=(\d{2})+(?!\d))/g, ",")},${tail}`;
}

/** Exact rupees from integer paise: 4700000 -> "₹47,000.00". */
export function formatInr(paise: number): string {
  if (!Number.isSafeInteger(paise)) throw new Error("paise must be a safe integer");
  const sign = paise < 0 ? "-" : "";
  const abs = BigInt(Math.abs(paise));
  const rupees = abs / 100n;
  const rem = abs % 100n;
  return `${sign}₹${indianGrouping(rupees)}.${rem.toString().padStart(2, "0")}`;
}

/** Short rupee label for axes: ₹0, ₹500, ₹2K, ₹1.5L, ₹2.25Cr. */
export function formatInrAxis(paise: number): string {
  const rupees = paise / 100;
  const abs = Math.abs(rupees);
  const sign = rupees < 0 ? "-" : "";
  const trim = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(v < 10 ? 2 : 1).replace(/\.?0+$/, ""));
  if (abs >= 1e7) return `${sign}₹${trim(abs / 1e7)}Cr`;
  if (abs >= 1e5) return `${sign}₹${trim(abs / 1e5)}L`;
  if (abs >= 1e3) return `${sign}₹${trim(abs / 1e3)}K`;
  return `${sign}₹${trim(abs)}`;
}

export function formatCount(n: number): string {
  return indianGrouping(Math.trunc(n));
}

export function formatPercent(value: number | null): string {
  return value === null ? "n/a" : `${value.toFixed(1)}%`;
}

/** "2025-03-12" -> "12 Mar 2025". */
export function formatDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

/** "2026-11-12T10:05:00+00:00" -> "12 Nov, 3:35 pm" in local time. */
export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Nice round axis maximum and ticks for a value in paise. */
export function niceTicks(maxPaise: number, count = 4): number[] {
  if (maxPaise <= 0) return [0];
  const raw = maxPaise / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((f) => f * magnitude).find((s) => s >= raw) ?? raw;
  const ticks: number[] = [];
  for (let v = 0; v <= maxPaise + step * 0.001; v += step) ticks.push(Math.round(v));
  if (ticks[ticks.length - 1] < maxPaise) ticks.push(Math.round(ticks[ticks.length - 1] + step));
  return ticks;
}
