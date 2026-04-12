/**
 * Relay scrcpy H.264 stays **on by default** server-side
 * (`streaming.auto_attach_scrcpy_on_connect` / `auto_attach_scrcpy_on_relay_online`,
 * DB `relay_scrcpy_enabled` default true).
 *
 * `true` = hiện công tắc relay trên grid + màn Control (continuous mode).
 * MJPEG vẫn xem được khi relay tắt — chỉ tắt canvas H.264 + tải nhẹ hơn.
 */
export const SHOW_RELAY_SCRCPY_UI_TOGGLE = false;
