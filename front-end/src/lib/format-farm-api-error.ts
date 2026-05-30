/** FastAPI/Pydantic `detail` from axios response — always a display string for UI. */
export function formatFarmApiError(err: unknown, fallback: string): string {
  const e = err as {
    response?: { data?: { detail?: unknown; code?: string } };
    message?: string;
  };
  const d = e.response?.data?.detail;
  if (typeof d === 'string' && d.trim()) return d.trim();
  if (d != null && typeof d === 'object' && !Array.isArray(d)) {
    const code = (d as { code?: string }).code;
    if (code === 'INVALID_CREDENTIALS') return 'Sai thông tin đăng nhập';
    if (code === 'ACCOUNT_LOCKED') return 'Tài khoản tạm khóa. Thử lại sau.';
    if (code === 'ORG_DISABLED') return 'Tổ chức đã bị vô hiệu hóa.';
    if (code === 'TOO_MANY_REQUESTS') {
      return 'Bạn đang gửi yêu cầu quá nhanh. Vui lòng đợi vài giây rồi thử lại.';
    }
    if (code === 'SERVICE_DEGRADED') {
      return 'Hệ thống đang ở chế độ giới hạn. Vui lòng thử lại sau.';
    }
    try {
      return JSON.stringify(d);
    } catch {
      return fallback;
    }
  }
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
