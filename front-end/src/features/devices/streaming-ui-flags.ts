/**
 * Relay scrcpy H.264 is viewer-gated by default server-side.
 * Server can still override per-device via DB `relay_scrcpy_enabled`.
 *
 * `true` = hiện công tắc relay trên grid + màn Control (continuous mode).
 * MJPEG vẫn xem được khi relay tắt — chỉ tắt canvas H.264 + tải nhẹ hơn.
 */
export const SHOW_RELAY_SCRCPY_UI_TOGGLE = false;
