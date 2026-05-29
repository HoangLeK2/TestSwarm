/** FastAPI/Pydantic `detail` from axios response — always a display string for UI. */
export function formatFarmApiError(err: unknown, fallback: string): string {
  const e = err as {
    response?: { data?: { detail?: unknown } };
    message?: string;
  };
  const d = e.response?.data?.detail;
  if (typeof d === 'string' && d.trim()) return d.trim();
  if (Array.isArray(d)) {
    const parts = d.map((x: { msg?: string }) =>
      typeof x?.msg === 'string' ? x.msg : JSON.stringify(x)
    );
    const joined = parts.filter(Boolean).join(' · ');
    return joined || fallback;
  }
  if (d != null && typeof d === 'object') {
    try {
      return JSON.stringify(d);
    } catch {
      return fallback;
    }
  }
  return typeof e.message === 'string' && e.message ? e.message : fallback;
}
