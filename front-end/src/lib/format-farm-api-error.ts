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
    if (code === 'ACCOUNT_NOT_BOUND') {
      const hint = (d as { hint?: string }).hint;
      return hint
        ? `Kịch bản cần tài khoản nhưng chiến dịch chưa gắn. ${hint}`
        : 'Kịch bản cần tài khoản nhưng chiến dịch chưa gắn tài khoản.';
    }
    if (code === 'ACCOUNT_NOT_FOUND') {
      return 'Tài khoản hoặc nhóm tài khoản không thuộc tổ chức này.';
    }
    if (code === 'ACCOUNT_UNAVAILABLE') {
      return 'Tài khoản không khả dụng (bị treo hoặc đang cooldown).';
    }
    if (code === 'INVALID_TRANSITION') {
      const msg = (d as { message?: string }).message;
      return msg || 'Chuyển trạng thái campaign không hợp lệ.';
    }
    if (code === 'CAMPAIGN_LOCKED') {
      const msg = (d as { message?: string }).message;
      return msg || 'Campaign không thể sửa nội dung ở trạng thái hiện tại.';
    }
    if (code === 'SCENARIO_REQUIRED') {
      const msg = (d as { message?: string }).message;
      return msg?.trim() || 'Chiến dịch phải gắn ít nhất một kịch bản từ thư viện.';
    }
    if (code === 'SCENARIO_NAME_DUPLICATE') {
      return 'Tên kịch bản đã tồn tại trong thư viện — hãy chọn tên khác.';
    }
    if (code === 'NO_ORGANIZATION') {
      return 'Tài khoản chưa thuộc tổ chức — không thể tạo chiến dịch theo thư viện kịch bản.';
    }
    if (code === 'CAMPAIGN_RUNNING') {
      return 'Campaign đang chạy — hãy hủy trước khi xóa.';
    }
    if (code === 'CAMPAIGN_ALREADY_RUNNING') {
      return 'Campaign đang chạy — không thể dispatch lại.';
    }
    if (code === 'EMPTY_DISPATCH_TARGET') {
      return 'Chưa chọn thiết bị hoặc nhóm thiết bị hợp lệ để chạy.';
    }
    if (code === 'DEVICE_OFFLINE') {
      const ids = (d as { details?: { device_ids?: string[] } }).details
        ?.device_ids;
      if (ids?.length) {
        return `Thiết bị offline: ${ids.length} thiết bị không sẵn sàng.`;
      }
      return 'Một hoặc nhiều thiết bị đang offline.';
    }
    if (code === 'DEVICE_NOT_FOUND') {
      return 'Không tìm thấy thiết bị trong tổ chức.';
    }
    if (code === 'DISPATCH_TARGET_TOO_LARGE') {
      return 'Số thiết bị vượt giới hạn cho phép.';
    }
    if (code === 'OVERRIDE_PAYLOAD_TOO_LARGE') {
      return 'Dữ liệu override theo thiết bị vượt giới hạn cho phép.';
    }
    if (code === 'TOO_MANY_REQUESTS') {
      return 'Bạn đang gửi yêu cầu quá nhanh. Vui lòng đợi vài giây rồi thử lại.';
    }
    if (code === 'SERVICE_DEGRADED') {
      return 'Hệ thống đang ở chế độ giới hạn. Vui lòng thử lại sau.';
    }
    const issues = (d as { errors?: Array<{ message?: string }> }).errors;
    if (Array.isArray(issues) && issues.length > 0) {
      const joined = issues
        .map((issue) => issue.message?.trim())
        .filter(Boolean)
        .join(' · ');
      if (joined) return joined;
    }
    const message = (d as { message?: string }).message;
    if (typeof message === 'string' && message.trim()) return message.trim();
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
