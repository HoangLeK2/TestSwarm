package jp.co.cyberagent.stf;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.KeyguardManager;
import android.content.ComponentName;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.drawable.GradientDrawable;
import android.media.projection.MediaProjectionManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.telephony.TelephonyManager;
import android.util.Log;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.result.ActivityResult;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.localbroadcastmanager.content.LocalBroadcastManager;

import android.content.BroadcastReceiver;
import android.content.IntentFilter;

import com.google.android.material.button.MaterialButton;
import com.journeyapps.barcodescanner.ScanContract;
import com.journeyapps.barcodescanner.ScanOptions;

import org.json.JSONObject;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.util.Enumeration;

import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;

public class IdentityActivity extends AppCompatActivity {

    private static final String TAG        = "IdentityActivity";
    private static final int CAMERA_PERMISSION_CODE = 100;
    private static final String PREFS_NAME = "stf_prefs";
    private static final String PREF_WS_URL = "ws_url";
    private static final String PREF_REGISTER_URL = "adb_register_url";
    private static final String PREF_DEVICE_KEY  = "adb_device_key";

    public static final String ACTION_IDENTITY = "jp.co.cyberagent.stf.ACTION_IDENTIFY";
    public static final String EXTRA_SERIAL = "serial";

    // UI states
    private static final int STATE_DISCONNECTED = 0;
    private static final int STATE_CONNECTING = 1;
    private static final int STATE_CONNECTED = 2;
    private static final int STATE_ERROR = 3;

    private MaterialButton btnScan;
    private TextView tvStatus;
    private View viewStatusDot;

    // WS URL waiting for projection permission
    private String pendingWsUrl;
    private boolean serviceRunning = false;

    private ActivityResultLauncher<ScanOptions> barcodeLauncher;
    private ActivityResultLauncher<Intent> projectionLauncher;

    /**
     * Handles the service asking us to re-request the screen-capture permission.
     */
    private final BroadcastReceiver reAuthReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(android.content.Context context, Intent intent) {
            if (WsAgentService.ACTION_NEED_REAUTH.equals(intent.getAction())) {
                // Guard: if another thread already refreshed the token, skip.
                if (WsAgentService.sSharedProjection != null) return;
                Log.i(TAG, "Received NEED_REAUTH — re-requesting MediaProjection permission");
                if (pendingWsUrl != null) {
                    applyState(STATE_CONNECTING, "Re-requesting screen permission…");
                    MediaProjectionManager mpm = (MediaProjectionManager) getSystemService(MEDIA_PROJECTION_SERVICE);
                    if (mpm != null) {
                        projectionLauncher.launch(mpm.createScreenCaptureIntent());
                    }
                }
            } else if (WsAgentService.ACTION_SERVER_ERROR.equals(intent.getAction())) {
                String message = intent.getStringExtra("message");
                if (message == null) message = "Mã QR không hợp lệ";
                getSharedPreferences(PREFS_NAME, MODE_PRIVATE).edit().remove(PREF_WS_URL).apply();
                pendingWsUrl = null;
                serviceRunning = false;
                applyState(STATE_DISCONNECTED, "Scan QR to connect");
                Toast.makeText(IdentityActivity.this, message, Toast.LENGTH_LONG).show();
            } else if (WsAgentService.ACTION_CONNECTION_FAILED.equals(intent.getAction())) {
                String message = intent.getStringExtra("message");
                if (message == null) message = "Connection failed";
                applyState(STATE_ERROR, "Lỗi kết nối: " + message);
                Toast.makeText(IdentityActivity.this, message, Toast.LENGTH_LONG).show();
            } else if (WsAgentService.ACTION_CONNECTED.equals(intent.getAction())) {
                String url = intent.getStringExtra("url");
                applyState(STATE_CONNECTED, url != null ? "Streaming: " + url : "Streaming");
            }
        }
    };

    // ──────────────────────────────────────────────────────────────────────
    // Lifecycle
    // ──────────────────────────────────────────────────────────────────────

    @SuppressLint("MissingPermission")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_identity);

        // ── Views ──────────────────────────────────────────────────────
        TextView tvSerial = findViewById(R.id.tv_serial);
        TextView tvModel = findViewById(R.id.tv_model);
        TextView tvVersion = findViewById(R.id.tv_version);
        TextView tvOperator = findViewById(R.id.tv_operator);
        TextView tvPhone = findViewById(R.id.tv_phone);
        View rowImei = findViewById(R.id.row_imei);
        View divImei = findViewById(R.id.divider_imei);
        TextView tvImei = findViewById(R.id.tv_imei);

        btnScan = findViewById(R.id.btn_scan);
        tvStatus = findViewById(R.id.tv_status);
        viewStatusDot = findViewById(R.id.view_status_dot);

        // ── Device info ────────────────────────────────────────────────
        Intent intent = getIntent();
        TelephonyManager tm = (TelephonyManager) getSystemService(TELEPHONY_SERVICE);

        String serial = intent.getStringExtra(EXTRA_SERIAL);
        if (serial == null)
            serial = getDisplaySerial();
        tvSerial.setText(serial);
        tvModel.setText(Build.BRAND + " " + Build.MODEL);
        tvVersion.setText(Build.VERSION.RELEASE + "  (SDK " + Build.VERSION.SDK_INT + ")");

        if (tm != null) {
            tvOperator.setText(emptyOrUnknown(tm.getSimOperatorName()));
            tvPhone.setText(getSecuredId(tm::getLine1Number));
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                rowImei.setVisibility(View.VISIBLE);
                divImei.setVisibility(View.VISIBLE);
                tvImei.setText(getSecuredId(tm::getImei));
            }
        } else {
            tvOperator.setText("—");
            tvPhone.setText("—");
        }

        // ── MediaProjection launcher ───────────────────────────────────
        projectionLauncher = registerForActivityResult(
                new ActivityResultContracts.StartActivityForResult(),
                result -> {
                    if (result.getResultCode() == Activity.RESULT_OK
                            && result.getData() != null
                            && pendingWsUrl != null) {
                        // Save URL for auto-reconnect across WiFi networks
                        getSharedPreferences(PREFS_NAME, MODE_PRIVATE).edit()
                                .putString(PREF_WS_URL, pendingWsUrl).apply();
                        WsAgentService.start(this,
                                pendingWsUrl,
                                result.getResultCode(),
                                result.getData());
                        serviceRunning = true;
                        String hostPort = formatHostPort(pendingWsUrl);
                        applyState(STATE_CONNECTING, hostPort != null ? "Đang kết nối " + hostPort + "…" : "Đang kết nối tới server…");
                    } else {
                        applyState(STATE_ERROR, "Screen capture permission denied");
                    }
                });

        // ── QR launcher ────────────────────────────────────────────────
        barcodeLauncher = registerForActivityResult(new ScanContract(), result -> {
            String content = result.getContents();
            if (content == null) {
                // User cancelled or closed scanner → stay on IdentityActivity, clear connecting state
                if (!isFinishing() && !isDestroyed())
                    applyState(STATE_DISCONNECTED, "Not connected");
                return;
            }
            if (isFinishing() || isDestroyed())
                return;

            Log.d(TAG, "QR result received, connecting: " + content.substring(0, Math.min(content.length(), 60)) + "...");
            if (content.startsWith("ws://") || content.startsWith("wss://")) {
                pendingWsUrl = content;
                applyState(STATE_CONNECTING, "Requesting screen permission…");
                MediaProjectionManager mpm = (MediaProjectionManager) getSystemService(MEDIA_PROJECTION_SERVICE);
                if (mpm != null) {
                    projectionLauncher.launch(mpm.createScreenCaptureIntent());
                } else {
                    pendingWsUrl = null;
                    applyState(STATE_ERROR, "Screen capture not available");
                    Toast.makeText(this, "Screen capture not available on this device", Toast.LENGTH_LONG).show();
                }
            } else if (content.trim().startsWith("{")) {
                // ADB connect-by-QR: payload { "registerUrl": "http://..." } → POST device IP to backend
                handleAdbRegisterQr(content);
            } else {
                Toast.makeText(this,
                        "Invalid QR — expected ws:// or wss:// or JSON with registerUrl",
                        Toast.LENGTH_LONG).show();
            }
        });

        // ── Button ─────────────────────────────────────────────────────
        btnScan.setOnClickListener(v -> {
            if (serviceRunning) {
                WsAgentService.stop(this);
                serviceRunning = false;
                pendingWsUrl = null;
                // Clear saved URL so it doesn't auto-reconnect
                getSharedPreferences(PREFS_NAME, MODE_PRIVATE).edit()
                        .remove(PREF_WS_URL).apply();
                applyState(STATE_DISCONNECTED, "Disconnected");
            } else {
                checkCameraAndScan();
            }
        });

        ensureVisibility();
        // Disabled: do not auto-enable accessibility; we rely on minitouch.
        // autoEnableA11y();

        // Auto-reconnect with saved URL (works across different WiFi networks).
        // If the service already holds a valid MediaProjection token (same process lifetime),
        // skip the system dialog — just restart the service with the stored URL.
        String savedUrl = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
                .getString(PREF_WS_URL, null);
        if (savedUrl != null && !savedUrl.isEmpty()) {
            pendingWsUrl = savedUrl;
            if (WsAgentService.sSharedProjection != null) {
                // Token is still valid — no dialog needed.
                WsAgentService.start(this, savedUrl, 0, null);
                serviceRunning = true;
                applyState(STATE_CONNECTED, "Reconnecting to " + savedUrl + "…");
            } else {
                applyState(STATE_CONNECTING, "Requesting screen permission…");
                MediaProjectionManager mpm = (MediaProjectionManager) getSystemService(MEDIA_PROJECTION_SERVICE);
                if (mpm != null) {
                    projectionLauncher.launch(mpm.createScreenCaptureIntent());
                } else {
                    applyState(STATE_DISCONNECTED, "Tap to connect");
                }
            }
        } else {
            applyState(STATE_DISCONNECTED, "Scan QR to connect");
        }

        // Auto ADB connect (cloud farm style):
        // Nếu app đã từng quét QR JSON ADB (registerUrl + deviceKey) thì mỗi lần mở app
        // sẽ tự động gửi IP WiFi hiện tại lên backend để server ADB-connect mà không cần quét lại.
        String savedRegisterUrl = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
                .getString(PREF_REGISTER_URL, null);
        String savedDeviceKey = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
                .getString(PREF_DEVICE_KEY, null);
        if (savedRegisterUrl != null && !savedRegisterUrl.isEmpty()) {
            // Không block UI; chạy nền.
            final String jsonPayload = buildAdbRegisterPayload(savedRegisterUrl, savedDeviceKey);
            if (jsonPayload != null) {
                handleAdbRegisterQr(jsonPayload);
            }
        }
    }

    /**
     * Programmatically enable TouchAccessibilityService via WRITE_SECURE_SETTINGS.
     * This requires the permission to be granted once via ADB:
     *   adb shell pm grant jp.co.cyberagent.stf android.permission.WRITE_SECURE_SETTINGS
     */
    private void autoEnableA11y() {
        // Disabled in ADB-first builds; Accessibility-based touch is optional.
    }

    @Override
    protected void onResume() {
        super.onResume();
        IntentFilter filter = new IntentFilter();
        filter.addAction(WsAgentService.ACTION_NEED_REAUTH);
        filter.addAction(WsAgentService.ACTION_SERVER_ERROR);
        filter.addAction(WsAgentService.ACTION_CONNECTION_FAILED);
        filter.addAction(WsAgentService.ACTION_CONNECTED);
        LocalBroadcastManager.getInstance(this).registerReceiver(reAuthReceiver, filter);
    }

    @Override
    protected void onPause() {
        super.onPause();
        LocalBroadcastManager.getInstance(this).unregisterReceiver(reAuthReceiver);
    }

    // ──────────────────────────────────────────────────────────────────────
    // UI state
    // ──────────────────────────────────────────────────────────────────────

    private void applyState(int state, String message) {
        tvStatus.setText(message);
        GradientDrawable dot = new GradientDrawable();
        dot.setShape(GradientDrawable.OVAL);
        switch (state) {
            case STATE_CONNECTED:
                dot.setColor(0xFF22C55E);
                tvStatus.setTextColor(0xFF22C55E);
                btnScan.setText("Disconnect");
                btnScan.setIcon(null);
                btnScan.setBackgroundTintList(
                        android.content.res.ColorStateList.valueOf(0xFFEF4444));
                break;
            case STATE_CONNECTING:
                dot.setColor(0xFFF59E0B);
                tvStatus.setTextColor(0xFFF59E0B);
                break;
            case STATE_ERROR:
                dot.setColor(0xFFEF4444);
                tvStatus.setTextColor(0xFFEF4444);
                resetScanButton();
                break;
            default:
                dot.setColor(0xFF64748B);
                tvStatus.setTextColor(0xFF64748B);
                resetScanButton();
                break;
        }
        viewStatusDot.setBackground(dot);
    }

    private void resetScanButton() {
        btnScan.setText("Scan QR Code");
        btnScan.setIconResource(R.drawable.ic_qr_scan);
        btnScan.setBackgroundTintList(
                android.content.res.ColorStateList.valueOf(0xFF6366F1));
    }

    /**
     * ADB connect-by-QR: QR payload is JSON { "registerUrl": "http://host:port/api/connect/register" }.
     * Get this device's WiFi IP and POST it to registerUrl so the backend can connect via ADB.
     */
    private String buildAdbRegisterPayload(String registerUrl, String deviceKey) {
        try {
            JSONObject obj = new JSONObject();
            obj.put("registerUrl", registerUrl);
            if (deviceKey != null && !deviceKey.isEmpty()) {
                obj.put("deviceKey", deviceKey);
            }
            return obj.toString();
        } catch (Exception e) {
            Log.w(TAG, "buildAdbRegisterPayload failed", e);
            return null;
        }
    }

    private void handleAdbRegisterQr(String jsonContent) {
        String registerUrl;
        String deviceKey = null;
        try {
            JSONObject obj = new JSONObject(jsonContent);
            registerUrl = obj.optString("registerUrl", null);
            deviceKey = obj.optString("deviceKey", null);
            if (registerUrl == null || registerUrl.isEmpty()) {
                runOnUiThread(() -> Toast.makeText(this, "QR thiếu registerUrl", Toast.LENGTH_LONG).show());
                return;
            }
            // Persist for future auto-connects
            getSharedPreferences(PREFS_NAME, MODE_PRIVATE).edit()
                    .putString(PREF_REGISTER_URL, registerUrl)
                    .putString(PREF_DEVICE_KEY, deviceKey)
                    .apply();
        } catch (Exception e) {
            Log.w(TAG, "Invalid JSON from QR", e);
            runOnUiThread(() -> Toast.makeText(this, "Mã QR không hợp lệ (JSON)", Toast.LENGTH_LONG).show());
            return;
        }
        applyState(STATE_CONNECTING, "Đang gửi IP lên server…");
        final String registerUrlFinal = registerUrl;
        final String deviceKeyFinal   = deviceKey;
        new Thread(() -> {
            String ip = getWifiIpAddress();
            if (ip == null || ip.isEmpty()) {
                runOnUiThread(() -> {
                    applyState(STATE_ERROR, "Không lấy được IP WiFi");
                    Toast.makeText(IdentityActivity.this, "Bật WiFi và thử lại", Toast.LENGTH_LONG).show();
                });
                return;
            }
            int port = 5555;
            try {
                OkHttpClient client = new OkHttpClient.Builder()
                        .connectTimeout(15, java.util.concurrent.TimeUnit.SECONDS)
                        .writeTimeout(10, java.util.concurrent.TimeUnit.SECONDS)
                        .readTimeout(15, java.util.concurrent.TimeUnit.SECONDS)
                        .build();
                StringBuilder body = new StringBuilder();
                body.append("{\"ip\":\"").append(ip).append("\",\"port\":").append(port);
                if (deviceKeyFinal != null && !deviceKeyFinal.isEmpty()) {
                    body.append(",\"device_key\":\"").append(deviceKeyFinal).append("\"");
                }
                body.append("}");
                Request request = new Request.Builder()
                        .url(registerUrlFinal)
                        .post(RequestBody.create(body.toString(), MediaType.parse("application/json")))
                        .build();
                try (Response response = client.newCall(request).execute()) {
                    final int code = response.code();
                    final String bodyStr = response.body() != null ? response.body().string() : "";
                    runOnUiThread(() -> {
                        if (code >= 200 && code < 300) {
                            applyState(STATE_DISCONNECTED, "Đã gửi IP. Backend đang kết nối…");
                            Toast.makeText(IdentityActivity.this, "Kết nối thành công. Xem dashboard.", Toast.LENGTH_LONG).show();
                        } else {
                            applyState(STATE_ERROR, "Server lỗi: " + code);
                            Toast.makeText(IdentityActivity.this, "Lỗi: " + code + " " + bodyStr, Toast.LENGTH_LONG).show();
                        }
                    });
                }
            } catch (Exception e) {
                Log.e(TAG, "POST registerUrl failed", e);
                runOnUiThread(() -> {
                    applyState(STATE_ERROR, "Gửi IP thất bại");
                    Toast.makeText(IdentityActivity.this, "Lỗi: " + e.getMessage(), Toast.LENGTH_LONG).show();
                });
            }
        }).start();
    }

    /** Returns this device's WiFi IPv4 address, or null if not available. */
    private String getWifiIpAddress() {
        try {
            Enumeration<NetworkInterface> interfaces = NetworkInterface.getNetworkInterfaces();
            while (interfaces != null && interfaces.hasMoreElements()) {
                NetworkInterface ni = interfaces.nextElement();
                if (ni.isLoopback() || !ni.isUp()) continue;
                Enumeration<InetAddress> addrs = ni.getInetAddresses();
                while (addrs.hasMoreElements()) {
                    InetAddress addr = addrs.nextElement();
                    if (addr instanceof Inet4Address && !addr.isLoopbackAddress()) {
                        String host = addr.getHostAddress();
                        if (host != null && !host.isEmpty()) return host;
                    }
                }
            }
        } catch (Exception e) {
            Log.w(TAG, "getWifiIpAddress failed", e);
        }
        return null;
    }

    // ──────────────────────────────────────────────────────────────────────
    // QR scan
    // ──────────────────────────────────────────────────────────────────────

    private void checkCameraAndScan() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M
                && ContextCompat.checkSelfPermission(this,
                        Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this,
                    new String[] { Manifest.permission.CAMERA }, CAMERA_PERMISSION_CODE);
        } else {
            startQrScan();
        }
    }

    private void startQrScan() {
        ScanOptions options = new ScanOptions();
        options.setCaptureActivity(QrCaptureActivity.class);
        options.setDesiredBarcodeFormats(ScanOptions.QR_CODE);
        options.setOrientationLocked(false);
        options.setBeepEnabled(true);
        options.setPrompt("");
        barcodeLauncher.launch(options);
    }

    @Override
    public void onRequestPermissionsResult(int requestCode,
            @NonNull String[] permissions, @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == CAMERA_PERMISSION_CODE
                && grantResults.length > 0
                && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            startQrScan();
        }
    }

    // ──────────────────────────────────────────────────────────────────────
    // Helpers
    // ──────────────────────────────────────────────────────────────────────

    private void ensureVisibility() {
        Window window = getWindow();
        window.addFlags(WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
        window.addFlags(WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD);
        window.addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED);
        unlock();
        WindowManager.LayoutParams params = window.getAttributes();
        params.screenBrightness = 1.0f;
        window.setAttributes(params);
    }

    @SuppressWarnings("deprecation")
    private void unlock() {
        KeyguardManager km = (KeyguardManager) getSystemService(KEYGUARD_SERVICE);
        km.newKeyguardLock("InputService/Unlock").disableKeyguard();
    }

    private String getProperty(String name, String defaultValue) {
        try {
            Class<?> sp = Class.forName("android.os.SystemProperties");
            Method get = sp.getMethod("get", String.class, String.class);
            return (String) get.invoke(sp, name, defaultValue);
        } catch (ClassNotFoundException | NoSuchMethodException
                | InvocationTargetException | IllegalAccessException e) {
            return defaultValue;
        }
    }

    /** e.g. ws://172.16.0.86:8081/device-agent?key=... → "172.16.0.86:8081" */
    private static String formatHostPort(String wsUrl) {
        if (wsUrl == null || wsUrl.isEmpty()) return null;
        try {
            java.net.URI u = java.net.URI.create(wsUrl);
            String host = u.getHost();
            int port = u.getPort();
            if (host != null) return port > 0 ? host + ":" + port : host;
        } catch (Exception ignored) { }
        return null;
    }

    /** When ro.serialno is "unknown", use ANDROID_ID so UI matches serial sent in WebSocket hello. */
    @SuppressLint("HardwareIds")
    private String getDisplaySerial() {
        String s = getProperty("ro.serialno", "unknown");
        if (s != null && !s.isEmpty() && !"unknown".equalsIgnoreCase(s))
            return s;
        String aid = Settings.Secure.getString(getContentResolver(), Settings.Secure.ANDROID_ID);
        if (aid != null && !aid.isEmpty())
            return aid;
        return "android-" + Build.MODEL.replaceAll("\\s", "_");
    }

    private String emptyOrUnknown(String v) {
        return (v == null || v.isEmpty()) ? "—" : v;
    }

    private interface SecuredGetter<T> {
        T get();
    }

    private String getSecuredId(SecuredGetter<String> s) {
        try {
            return s.get();
        } catch (SecurityException e) {
            return "secured";
        }
    }

    // ──────────────────────────────────────────────────────────────────────
    // Intent builder
    // ──────────────────────────────────────────────────────────────────────

    public static class IntentBuilder {
        @Nullable
        private String serial;

        public IntentBuilder serial(@NonNull String serial) {
            this.serial = serial;
            return this;
        }

        public Intent build(android.content.Context context) {
            Intent intent = new Intent(context.getApplicationContext(), IdentityActivity.class);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            if (serial != null)
                intent.putExtra(EXTRA_SERIAL, serial);
            return intent;
        }
    }
}
