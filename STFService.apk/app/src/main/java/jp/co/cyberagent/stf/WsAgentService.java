package jp.co.cyberagent.stf;

import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.ActivityNotFoundException;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;
import androidx.localbroadcastmanager.content.LocalBroadcastManager;
import android.content.pm.ServiceInfo;
import android.graphics.Point;
import android.graphics.Color;
import android.graphics.Bitmap;
import android.graphics.PixelFormat;
import android.hardware.display.DisplayManager;
import android.hardware.display.VirtualDisplay;
import android.media.Image;
import android.media.ImageReader;
import android.media.projection.MediaProjection;
import android.media.projection.MediaProjectionManager;
import android.os.HandlerThread;
import android.os.Build;
import android.os.IBinder;
import android.os.SystemClock;
import android.provider.Settings;
import android.util.Base64;
import android.util.DisplayMetrics;
import android.util.Log;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.WindowManager;

import androidx.annotation.Nullable;
import androidx.core.app.NotificationCompat;

import android.net.Uri;
import android.net.LocalSocket;
import android.net.LocalSocketAddress;
import android.net.wifi.WifiManager;
import android.os.PowerManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.Socket;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import android.content.ComponentName;
import android.content.pm.ActivityInfo;
import android.content.pm.ResolveInfo;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

import android.view.accessibility.AccessibilityNodeInfo;
import jp.co.cyberagent.stf.compat.InputManagerWrapper;

/**
 * WsAgentService — Foreground service.
 *
 * Set {@link #USE_MEDIA_PROJECTION} = false để tắt MJPEG trong app và dùng stream
 * ngoài (vd. scrcpy qua ADB). Khi bật lại: manifest FGS type + permission
 * FOREGROUND_SERVICE_MEDIA_PROJECTION và flow IdentityActivity như cũ.
 */
public class WsAgentService extends android.app.Service {

    /** false = không xin MediaProjection, không gửi MJPEG qua WS (dùng scrcpy / nguồn khác). */
    public static final boolean USE_MEDIA_PROJECTION = false;

    public static final String ACTION_START = "jp.co.cyberagent.stf.ws.START";
    public static final String ACTION_STOP = "jp.co.cyberagent.stf.ws.STOP";
    /**
     * Broadcast sent to IdentityActivity when we need a fresh MediaProjection
     * token.
     */
    public static final String ACTION_NEED_REAUTH = "jp.co.cyberagent.stf.ws.NEED_REAUTH";
    public static final String ACTION_SERVER_ERROR = "jp.co.cyberagent.stf.ws.SERVER_ERROR";
    public static final String ACTION_CONNECTION_FAILED = "jp.co.cyberagent.stf.ws.CONNECTION_FAILED";
    public static final String ACTION_CONNECTED = "jp.co.cyberagent.stf.ws.CONNECTED";

    public static final String EXTRA_WS_URL = "ws_url";
    public static final String EXTRA_PROJECTION_DATA = "projection_data";
    public static final String EXTRA_PROJECTION_CODE = "projection_code";
    public static final String EXTRA_ALLOW_BATTERY_DIALOG = "allow_battery_dialog";

    private static final String TAG = "WsAgentService";
    private static final String CHANNEL_ID = "ws_agent";
    private static final int NOTIF_ID = 0x2;
    private static final String PREFS_NAME = "stf_prefs";
    private static final String PREF_WS_URL = "ws_url";
    private static final int CAPTURE_WIDTH       = 1080; // max width; scales down if screen smaller
    private static final int TARGET_FPS          = 10;   // MJPEG target frame rate (low for perf)
    private static final int JPEG_QUALITY        = 75;   // JPEG compression (0-100)
    private static final long A11Y_AUTO_ENABLE_MIN_INTERVAL_MS = 10000L;

    /**
     * Shared MediaProjection token — static so it survives service restarts within the same
     * process. IdentityActivity checks this before requesting the system dialog again.
     * Cleared when the OS revokes the projection (MediaProjection.Callback.onStop) or when
     * the service is fully destroyed (stopAll).
     */
    static volatile MediaProjection sSharedProjection;

    /**
     * VirtualDisplay (and its supporting objects) kept as static fields so they survive
     * service destroy/restart within the same process. createVirtualDisplay() is called
     * at most once per process lifetime, avoiding repeated "You're sharing your screen"
     * system overlay banners on Android 12+.
     */
    private static volatile VirtualDisplay  sSharedVirtualDisplay;
    private static volatile ImageReader     sSharedImageReader;
    private static volatile HandlerThread   sSharedImageHandlerThread;
    private static volatile Handler         sSharedImageHandler;

    private WebSocketManager wsManager;
    private MediaProjection  mediaProjection;
    private final Map<String, ServiceTunnel> serviceTunnels = new ConcurrentHashMap<>();
    private volatile JSONObject tunnelPortsCache;  // saved from hello_ack for start_services retry
    private static volatile MinitouchAgent minitouchAgent;
    private static final Object minitouchAgentLock = new Object();
    private String           diagProjection = "not-set"; // filled in onStartCommand
    private String           wsUrl;                      // stored for auto-reconnect
    private volatile boolean destroyed = false;
    private final Handler    mainHandler = new Handler(Looper.getMainLooper());
    // Instance refs — point to the same objects as the static fields above.
    private VirtualDisplay   virtualDisplay;
    private ImageReader      imageReader;
    private HandlerThread    imageHandlerThread;
    private Handler          imageHandler;
    private volatile long    lastFrameTime   = 0;
    private volatile long    lastA11yAutoEnableMs = 0;
    private volatile byte[]  latestJpeg      = null;          // latest JPEG frame (for screenshot API)

    // Precomputed for binary JPEG frame protocol:
    //   [0x01][serial_len:1B][serial:NB][w:2B BE][h:2B BE][jpeg_bytes]
    private byte[] serialBytes;
    private int    serialByteLen;
    private int    headerWidth;
    private int    headerHeight;

    // Dynamic stream throttling (server sends set_stream_options).
    private volatile int  targetFps = TARGET_FPS;
    private volatile long minFrameIntervalMs = 1000L / TARGET_FPS;

    // Optional output downscale width from server (0 = use CAPTURE_WIDTH / heuristic).
    private volatile int streamMaxWidth = 0;

    private InputManagerWrapper inputManager;
    private ExecutorService  executor;
    private final AtomicBoolean capturing = new AtomicBoolean(false);

    // Wake locks — keep CPU + WiFi radio awake during Doze / screen-off so WS
    // read loop can service pings. Without these, vivo/oppo/xiaomi drop socket
    // after ~30min screen-off.
    private PowerManager.WakeLock cpuWakeLock;
    private WifiManager.WifiLock  wifiLock;

    // Exponential backoff for reconnect (1s → 2 → 4 → 8 → 16 → cap 30s).
    private volatile int reconnectAttempt = 0;
    private static final long RECONNECT_BASE_MS = 1000L;
    private static final long RECONNECT_MAX_MS  = 30000L;
    private final AtomicInteger connectionGeneration = new AtomicInteger(0);
    private final Runnable reconnectRunnable = new Runnable() {
        @Override
        public void run() {
            if (!destroyed && wsUrl != null && !wsUrl.isEmpty()) {
                connectWebSocket(wsUrl);
            }
        }
    };

    // Device info
    private String serial;
    private String brand;
    private String model;
    private String androidVersion;
    private String sdkVersion;
    private int screenWidth;
    private int screenHeight;

    // ──────────────────────────────────────────────────────────────────────
    // Lifecycle
    // ──────────────────────────────────────────────────────────────────────

    @Override
    public void onCreate() {
        super.onCreate();
        executor = Executors.newCachedThreadPool();

        try {
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            if (pm != null) {
                cpuWakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,
                        "DeviceFarm:WsAgentCpu");
                cpuWakeLock.setReferenceCounted(false);
                cpuWakeLock.acquire();
            }
            WifiManager wm = (WifiManager) getApplicationContext()
                    .getSystemService(WIFI_SERVICE);
            if (wm != null) {
                wifiLock = wm.createWifiLock(
                        WifiManager.WIFI_MODE_FULL_HIGH_PERF,
                        "DeviceFarm:WsAgentWifi");
                wifiLock.setReferenceCounted(false);
                wifiLock.acquire();
            }
            Log.i(TAG, "WakeLocks acquired cpu=" + (cpuWakeLock != null)
                    + " wifi=" + (wifiLock != null));
        } catch (Exception e) {
            Log.w(TAG, "WakeLock acquire failed: " + e.getMessage());
        }

        // Input injection (used by minitouch / InputManager gestures).
        try {
            inputManager = new InputManagerWrapper();
        } catch (Exception e) {
            Log.w(TAG, "InputManagerWrapper unavailable: " + e.getMessage());
        }

        // Device info
        brand = Build.BRAND;
        model = Build.MODEL;
        androidVersion = Build.VERSION.RELEASE;
        sdkVersion = String.valueOf(Build.VERSION.SDK_INT);

        // Serial: Build.getSerial() requires READ_PHONE_STATE; fallback to ANDROID_ID
        try {
            serial = Build.getSerial();
            if (serial == null || serial.isEmpty() || "unknown".equalsIgnoreCase(serial)) {
                throw new Exception("empty serial");
            }
        } catch (Exception e) {
            serial = Settings.Secure.getString(getContentResolver(), Settings.Secure.ANDROID_ID);
            if (serial == null)
                serial = "android-" + Build.MODEL.replaceAll("\\s", "_");
        }

        DisplayMetrics dm = new DisplayMetrics();
        ((WindowManager) getSystemService(WINDOW_SERVICE))
                .getDefaultDisplay().getRealMetrics(dm);
        screenWidth = dm.widthPixels;
        screenHeight = dm.heightPixels;

        headerWidth  = Math.max(0, Math.min(screenWidth,  0xFFFF));
        headerHeight = Math.max(0, Math.min(screenHeight, 0xFFFF));

        serialBytes = serial.getBytes(StandardCharsets.UTF_8);
        serialByteLen = Math.min(255, serialBytes.length);
        if (serialByteLen != serialBytes.length) {
            serialBytes = Arrays.copyOf(serialBytes, serialByteLen);
        }

        Log.i(TAG, "Device: " + brand + " " + model + " Android " + androidVersion
                + " serial=" + serial + " screen=" + screenWidth + "x" + screenHeight);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent != null ? intent.getAction() : ACTION_START;

        if (ACTION_STOP.equals(action)) {
            stopSelf();
            return START_NOT_STICKY;
        }

        if (ACTION_START.equals(action)) {
            String wsUrl = intent != null ? intent.getStringExtra(EXTRA_WS_URL) : null;
            if (wsUrl == null || wsUrl.isEmpty()) {
                SharedPreferences prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
                wsUrl = prefs.getString(PREF_WS_URL, null);
                Log.i(TAG, "onStartCommand: wsUrl from SharedPreferences=" + wsUrl);
            }
            Intent projData = null;
            int projCode = -1;
            if (intent != null) {
                projData = Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                        ? intent.getParcelableExtra(EXTRA_PROJECTION_DATA, Intent.class)
                        : intent.getParcelableExtra(EXTRA_PROJECTION_DATA);
                projCode = intent.getIntExtra(EXTRA_PROJECTION_CODE, -1);
            }

            Log.i(TAG, "onStartCommand: wsUrl=" + wsUrl
                    + " projCode=" + projCode
                    + " projData=" + (projData != null ? "OK" : "NULL"));

            startForeground();
            maybeRequestBatteryOptimizationExemption(
                    intent != null && intent.getBooleanExtra(EXTRA_ALLOW_BATTERY_DIALOG, false));

            if (USE_MEDIA_PROJECTION) {
                // Get MediaProjection token — reuse static if already valid (avoids dialog).
                if (sSharedProjection != null) {
                    mediaProjection = sSharedProjection;
                    diagProjection = "reused-sSharedProjection";
                    Log.i(TAG, diagProjection);
                } else {
                    MediaProjectionManager mpm = (MediaProjectionManager) getSystemService(MEDIA_PROJECTION_SERVICE);
                    if (projData == null || projCode != Activity.RESULT_OK) {
                        diagProjection = "SKIP: projData=" + (projData != null ? "OK" : "NULL")
                                + " projCode=" + projCode + " (RESULT_OK=" + Activity.RESULT_OK + ")";
                        Log.w(TAG, diagProjection);
                    } else if (mpm == null) {
                        diagProjection = "SKIP: MediaProjectionManager is null";
                        Log.w(TAG, diagProjection);
                    } else {
                        try {
                            mediaProjection = mpm.getMediaProjection(projCode, projData);
                            if (mediaProjection != null) {
                                sSharedProjection = mediaProjection;
                                mediaProjection.registerCallback(new MediaProjection.Callback() {
                                    @Override
                                    public void onStop() {
                                        Log.w(TAG, "MediaProjection.onStop() — token revoked by OS");
                                        sSharedProjection = null;
                                        mediaProjection   = null;
                                        LocalBroadcastManager.getInstance(WsAgentService.this)
                                                .sendBroadcast(new Intent(ACTION_NEED_REAUTH));
                                    }
                                }, mainHandler);
                            }
                            diagProjection = "getMediaProjection=" + (mediaProjection != null ? "OK" : "returned-null");
                            Log.i(TAG, diagProjection);
                        } catch (Exception e) {
                            diagProjection = "getMediaProjection EXCEPTION: " + e.getMessage();
                            Log.e(TAG, diagProjection, e);
                        }
                    }
                }
            } else {
                diagProjection = "OFF: USE_MEDIA_PROJECTION=false (external video e.g. scrcpy)";
                Log.i(TAG, diagProjection);
            }

            if (wsUrl != null && !wsUrl.isEmpty()) {
                this.wsUrl = wsUrl;
                getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
                        .putString(PREF_WS_URL, wsUrl)
                        .apply();
                connectWebSocket(wsUrl);
            }
        }

        return START_STICKY;  // Ensure OS restarts service if killed
    }

    @Override
    public void onDestroy() {
        super.onDestroy();
        destroyed = true;
        connectionGeneration.incrementAndGet();
        mainHandler.removeCallbacksAndMessages(null);
        stopAll();  // release MediaProjection token on full shutdown
        for (ServiceTunnel t : serviceTunnels.values()) t.close();
        serviceTunnels.clear();
        if (wsManager != null)
            wsManager.shutdown();
        if (executor != null)
            executor.shutdownNow();
        try {
            if (cpuWakeLock != null && cpuWakeLock.isHeld()) cpuWakeLock.release();
        } catch (Exception ignored) {}
        try {
            if (wifiLock != null && wifiLock.isHeld()) wifiLock.release();
        } catch (Exception ignored) {}
        cpuWakeLock = null;
        wifiLock = null;
        Log.i(TAG, "WsAgentService destroyed");
    }

    @Nullable
    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    // ──────────────────────────────────────────────────────────────────────
    // Notification (required for foreground service)
    // ──────────────────────────────────────────────────────────────────────

    private void startForeground() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel ch = new NotificationChannel(
                    CHANNEL_ID, "Device Farm Agent",
                    NotificationManager.IMPORTANCE_LOW);
            ch.setLightColor(Color.BLUE);
            ((NotificationManager) getSystemService(NOTIFICATION_SERVICE))
                    .createNotificationChannel(ch);
        }
        Notification notif = new NotificationCompat.Builder(this, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_menu_share)
                .setContentTitle("Device Farm Agent")
                .setContentText(USE_MEDIA_PROJECTION
                        ? "Streaming screen to server…"
                        : "Connected to server (screen: external / scrcpy)…")
                .setOngoing(true)
                .build();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            // connectedDevice: no 6h/day cap (dataSync has one on Android 14+),
            // matches actual use-case (LAN device bridge).
            int fgsType = USE_MEDIA_PROJECTION
                    ? ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION
                    : ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE;
            startForeground(NOTIF_ID, notif, fgsType);
        } else {
            startForeground(NOTIF_ID, notif);
        }
    }

    /**
     * Request battery optimization exemption so Doze mode doesn't kill our WS connection.
     * Shows system dialog on first call; no-op if already exempted.
     */
    private void maybeRequestBatteryOptimizationExemption(boolean allowDialog) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            android.os.PowerManager pm = (android.os.PowerManager) getSystemService(POWER_SERVICE);
            if (pm != null && !pm.isIgnoringBatteryOptimizations(getPackageName())) {
                if (!allowDialog) {
                    Log.w(TAG, "Battery optimization is active; open STFService UI once to request exemption");
                    return;
                }
                try {
                    android.content.Intent intent = new android.content.Intent(
                            android.provider.Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS);
                    intent.setData(android.net.Uri.parse("package:" + getPackageName()));
                    intent.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK);
                    startActivity(intent);
                    Log.i(TAG, "Requested battery optimization exemption");
                } catch (Exception e) {
                    Log.w(TAG, "Could not request battery optimization exemption: " + e.getMessage());
                }
            } else {
                Log.i(TAG, "Already exempt from battery optimizations");
            }
        }
    }

    // ──────────────────────────────────────────────────────────────────────
    // WebSocket
    // ──────────────────────────────────────────────────────────────────────

    /**
     * Send a log line over WebSocket so the PC server can see Android-side events.
     */
    private void sendLog(String msg) {
        Log.i(TAG, msg);
        if (wsManager == null || !wsManager.isConnected())
            return;
        try {
            JSONObject m = new JSONObject();
            m.put("type", "log");
            m.put("line", "[android] " + msg);
            wsManager.send(m.toString());
        } catch (Exception ignored) {
        }
    }

    /** Notify server of open_url success/failure so scenario step is marked correctly. */
    private void sendOpenUrlResult(boolean success, String error) {
        if (wsManager == null || !wsManager.isConnected())
            return;
        try {
            JSONObject m = new JSONObject();
            m.put("type", "open_url_result");
            m.put("success", success);
            if (error != null && !error.isEmpty())
                m.put("error", error);
            wsManager.send(m.toString());
        } catch (Exception ignored) {
        }
    }

    private void connectWebSocket(String wsUrl) {
        mainHandler.removeCallbacks(reconnectRunnable);
        WebSocketManager oldManager = wsManager;
        if (oldManager != null) {
            oldManager.shutdown();
        }

        final int generation = connectionGeneration.incrementAndGet();
        WebSocketManager manager = new WebSocketManager();
        wsManager = manager;
        manager.setCallback(new WebSocketManager.Callback() {
            @Override
            public void onConnected(String url) {
                if (generation != connectionGeneration.get()) return;
                Log.i(TAG, "WebSocket connected: " + url);
                reconnectAttempt = 0;
                Intent connected = new Intent(ACTION_CONNECTED);
                connected.putExtra("url", url);
                LocalBroadcastManager.getInstance(WsAgentService.this).sendBroadcast(connected);
                sendHello();
                sendStatus();
                sendLog("SDK=" + Build.VERSION.SDK_INT
                        + " mediaProjection=" + (USE_MEDIA_PROJECTION
                                ? (mediaProjection != null ? "OK" : "NULL") : "disabled")
                        + " diag=" + diagProjection
                        + " capturing=" + capturing.get()
                        + " touch=" + (TouchAccessibilityService.isAvailable() ? "a11y"
                                : inputManager != null ? "inputMgr" : "NONE"));
                if (USE_MEDIA_PROJECTION) {
                    if (mediaProjection != null && !capturing.get()) {
                        sendLog("startCapture() called");
                        startCapture();
                    } else if (mediaProjection == null) {
                        sendLog("ERROR: mediaProjection is null — requesting re-auth from IdentityActivity");
                        LocalBroadcastManager.getInstance(WsAgentService.this)
                                .sendBroadcast(new Intent(ACTION_NEED_REAUTH));
                    }
                } else {
                    sendLog("MJPEG capture skipped — use scrcpy (or similar) for display");
                }
                if (!TouchAccessibilityService.isAvailable()) {
                    requestAutoEnableAccessibility("connect");
                }
            }

            @Override
            public void onMessage(String text) {
                if (generation != connectionGeneration.get()) return;
                handleCommand(text);
            }

            @Override
            public void onDisconnected(String reason) {
                if (generation != connectionGeneration.get()) return;
                Log.i(TAG, "WebSocket disconnected: " + reason);
                stopCapture();  // stop loop + VirtualDisplay, keep mediaProjection for reconnect
                scheduleReconnect();
            }

            @Override
            public void onError(String error) {
                if (generation != connectionGeneration.get()) return;
                Log.w(TAG, "WebSocket error: " + error);
                Intent err = new Intent(ACTION_CONNECTION_FAILED);
                err.putExtra("message", error != null ? error : "Connection failed");
                LocalBroadcastManager.getInstance(WsAgentService.this).sendBroadcast(err);
                stopCapture();  // same — keep mediaProjection
                scheduleReconnect();
            }
        });
        manager.connect(wsUrl);
        Log.i(TAG, "Connecting to " + wsUrl);
    }

    private void scheduleReconnect() {
        if (destroyed || wsUrl == null) return;
        long delay = Math.min(RECONNECT_MAX_MS,
                RECONNECT_BASE_MS * (1L << Math.min(reconnectAttempt, 5)));
        reconnectAttempt++;
        Log.i(TAG, "Reconnecting in " + delay + "ms (attempt " + reconnectAttempt + ")");
        mainHandler.removeCallbacks(reconnectRunnable);
        mainHandler.postDelayed(reconnectRunnable, delay);
    }

   
    private void sendHello() {
        try {
            JSONObject m = new JSONObject();
            m.put("type", "hello");
            m.put("serial", serial);
            String adbSerial = getAdbSerialHint();
            if (adbSerial != null && !adbSerial.isEmpty()) {
                m.put("adb_serial", adbSerial);
            }
            // STFService: u2, stfservice, optional mjpeg, minitouch
            JSONArray caps = new JSONArray();
            caps.put("u2");
            caps.put("stfservice");
            if (USE_MEDIA_PROJECTION) {
                caps.put("mjpeg");
            }
            caps.put("minitouch");
            m.put("capabilities", caps);
            // Server needs touch_mode in hello so it can create MinitouchWsClient before tunnels_ready
            String touchMode = TouchAccessibilityService.isAvailable() ? "a11y"
                    : (inputManager != null ? "inputMgr" : "NONE");
            m.put("touch_mode", touchMode);
            wsManager.send(m.toString());
            Log.i(TAG, "hello sent (serial=" + serial + " touch_mode=" + touchMode + ")");
        } catch (Exception e) {
            Log.w(TAG, "sendHello: " + e);
        }
    }

    private String getAdbSerialHint() {
        try {
            Process p = Runtime.getRuntime().exec(new String[]{"sh", "-c", "getprop ro.serialno"});
            byte[] out = p.getInputStream().readAllBytes();
            p.waitFor();
            String v = new String(out).trim();
            if (!v.isEmpty() && !"unknown".equalsIgnoreCase(v)) {
                return v;
            }
        } catch (Exception ignored) {}
        return "";
    }

    private void sendStatus() {
        try {
            JSONObject m = new JSONObject();
            m.put("type", "status");
            m.put("serial", serial);
            m.put("brand", brand);
            m.put("model", model);
            m.put("android", androidVersion);
            m.put("sdk", sdkVersion);
            m.put("screen_width", screenWidth);
            m.put("screen_height", screenHeight);
            m.put("state", "READY");
            m.put("battery", getBatteryLevel());
            wsManager.send(m.toString());
        } catch (Exception e) {
            Log.w(TAG, "sendStatus: " + e);
        }
    }

    // ──────────────────────────────────────────────────────────────────────
    // Screen capture — ScreenStream-style: MediaProjection → ImageReader → JPEG → WebSocket
    //
    // Replaces MediaCodec/H264 with ImageReader for:
    //   • Compatibility with all Android API levels (21+)
    //   • No codec initialization complexity or crashes
    //   • Simple JPEG frames decoded natively by browser <img> or canvas
    // ──────────────────────────────────────────────────────────────────────

    private void startCapture() {
        if (!USE_MEDIA_PROJECTION) {
            Log.d(TAG, "startCapture: skipped (USE_MEDIA_PROJECTION=false)");
            return;
        }
        if (mediaProjection == null) {
            Log.w(TAG, "startCapture: no MediaProjection token");
            return;
        }

        // Decide capture resolution (downscale) based on stream options.
        // Server may send `set_stream_options.max_width` to reduce browser decode cost.
        int maxW = streamMaxWidth > 0 ? streamMaxWidth : CAPTURE_WIDTH;
        // Even dimensions required by ImageReader.
        int capW = (Math.min(screenWidth, maxW)) & ~1;
        int capH = ((int) (screenHeight * ((float) capW / screenWidth))) & ~1;
        headerWidth  = Math.max(0, Math.min(capW, 0xFFFF));
        headerHeight = Math.max(0, Math.min(capH, 0xFFFF));

        // Reuse VirtualDisplay from a previous service instance (static field).
        // createVirtualDisplay() is the ONLY call that triggers the "You're sharing
        // your screen" system overlay on Android 12+, so we keep the VD alive for
        // the lifetime of the process — across WS reconnects AND service restarts.
        if (sSharedVirtualDisplay != null && sSharedImageReader != null) {
            // If resolution matches, reuse. Otherwise recreate once for the new width.
            if (sSharedImageReader.getWidth() == capW && sSharedImageReader.getHeight() == capH) {
            virtualDisplay     = sSharedVirtualDisplay;
            imageReader        = sSharedImageReader;
            imageHandlerThread = sSharedImageHandlerThread;
            imageHandler       = sSharedImageHandler;
            capturing.set(true);
            sendLog("MJPEG capture resumed (VirtualDisplay reused across restart)");
            return;
            }

            // Resolution changed: force-recreate ImageReader/VirtualDisplay with new size.
            try { sSharedVirtualDisplay.release(); } catch (Exception ignored) {}
            try { sSharedImageReader.close(); } catch (Exception ignored) {}
            HandlerThread ht = sSharedImageHandlerThread;
            if (ht != null) ht.quitSafely();
            sSharedVirtualDisplay     = null;
            sSharedImageReader        = null;
            sSharedImageHandlerThread = null;
            sSharedImageHandler       = null;
        }

        DisplayMetrics dm = new DisplayMetrics();
        ((WindowManager) getSystemService(WINDOW_SERVICE))
                .getDefaultDisplay().getRealMetrics(dm);
        int density = dm.densityDpi;

        // Dedicated handler thread for image processing (keeps UI thread free)
        imageHandlerThread = new HandlerThread("ScreenCapture");
        imageHandlerThread.start();
        imageHandler = new Handler(imageHandlerThread.getLooper());

        // ImageReader: RGBA_8888 is the universal format supported by all GPUs
        imageReader = ImageReader.newInstance(capW, capH, PixelFormat.RGBA_8888, 2);
        imageReader.setOnImageAvailableListener(reader -> {
            Image image = null;
            try {
                image = reader.acquireLatestImage();
                // Always close the image; skip encoding when not actively streaming.
                if (image == null || !capturing.get()
                        || wsManager == null || !wsManager.isConnected()) return;

                // FPS throttle — drop frames exceeding TARGET_FPS
                long now = SystemClock.uptimeMillis();
                if (now - lastFrameTime < minFrameIntervalMs) {
                    return;
                }
                lastFrameTime = now;

                byte[] jpeg = imageToJpeg(image);
                if (jpeg == null) return;

                latestJpeg = jpeg;

                // Send binary JPEG frame to server:
                //   [0x01][serial_len:1B][serial:NB][w:2B BE][h:2B BE][jpeg_bytes]
                int slen = serialByteLen;
                int w = headerWidth;
                int h = headerHeight;
                int totalLen = 1 + 1 + slen + 2 + 2 + jpeg.length;
                byte[] frame = new byte[totalLen];
                int off = 0;
                frame[off++] = 0x01;
                frame[off++] = (byte) (slen & 0xFF);
                System.arraycopy(serialBytes, 0, frame, off, slen);
                off += slen;
                frame[off++] = (byte) ((w >> 8) & 0xFF);
                frame[off++] = (byte) (w & 0xFF);
                frame[off++] = (byte) ((h >> 8) & 0xFF);
                frame[off++] = (byte) (h & 0xFF);
                System.arraycopy(jpeg, 0, frame, off, jpeg.length);
                wsManager.sendBytes(frame);
            } catch (Exception e) {
                Log.w(TAG, "frame send: " + e.getMessage());
            } finally {
                if (image != null) image.close();
            }
        }, imageHandler);

        // First time only: createVirtualDisplay triggers the system "sharing" banner once.
        virtualDisplay = mediaProjection.createVirtualDisplay(
                "DeviceFarm",
                capW, capH, density,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                imageReader.getSurface(), null, null);

        // Save to statics so next service instance can reuse without a new banner.
        sSharedVirtualDisplay     = virtualDisplay;
        sSharedImageReader        = imageReader;
        sSharedImageHandlerThread = imageHandlerThread;
        sSharedImageHandler       = imageHandler;

        capturing.set(true);
        sendLog("MJPEG capture started: " + capW + "x" + capH
                + " @" + targetFps + "fps quality=" + JPEG_QUALITY);
    }

    /**
     * Convert an ImageReader RGBA_8888 Image to a JPEG byte array.
     * Handles row padding that some GPUs add (ScreenStream pattern).
     */
    private byte[] imageToJpeg(Image image) {
        try {
            Image.Plane plane      = image.getPlanes()[0];
            ByteBuffer  buffer     = plane.getBuffer();
            int         pixStride  = plane.getPixelStride();
            int         rowStride  = plane.getRowStride();
            int         w          = image.getWidth();
            int         h          = image.getHeight();
            int         rowPadding = rowStride - pixStride * w;

            // createBitmap with padded width, then crop if needed
            Bitmap bmp = Bitmap.createBitmap(w + rowPadding / pixStride, h, Bitmap.Config.ARGB_8888);
            bmp.copyPixelsFromBuffer(buffer);
            if (rowPadding > 0) {
                Bitmap cropped = Bitmap.createBitmap(bmp, 0, 0, w, h);
                bmp.recycle();
                bmp = cropped;
            }

            ByteArrayOutputStream baos = new ByteArrayOutputStream(w * h / 4);
            bmp.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, baos);
            bmp.recycle();
            return baos.toByteArray();
        } catch (Exception e) {
            Log.w(TAG, "imageToJpeg: " + e.getMessage());
            return null;
        }
    }

    /**
     * Stop capture: pause frame streaming only.
     * VirtualDisplay, ImageReader, and HandlerThread are kept alive to avoid
     * re-triggering the Android 12+ "You're sharing your screen" system overlay
     * on every WebSocket reconnection.
     */
    private void stopCapture() {
        capturing.set(false);
        // Intentionally keep virtualDisplay, imageReader, imageHandlerThread alive
        // so startCapture() can resume without calling createVirtualDisplay() again.
        // mediaProjection is also kept — not stopped here.
    }

    /** Full teardown: release VirtualDisplay, ImageReader, MediaProjection. */
    private void stopAll() {
        capturing.set(false);
        // Release VirtualDisplay (static + instance)
        VirtualDisplay vd = sSharedVirtualDisplay;
        if (vd != null) { vd.release(); }
        sSharedVirtualDisplay = null;
        virtualDisplay = null;
        // Close ImageReader (static + instance)
        ImageReader ir = sSharedImageReader;
        if (ir != null) { try { ir.close(); } catch (Exception ignored) {} }
        sSharedImageReader = null;
        imageReader = null;
        // Stop HandlerThread (static + instance)
        HandlerThread ht = sSharedImageHandlerThread;
        if (ht != null) { ht.quitSafely(); }
        sSharedImageHandlerThread = null;
        sSharedImageHandler = null;
        imageHandlerThread = null;
        imageHandler = null;
        if (USE_MEDIA_PROJECTION) {
            if (mediaProjection != null) {
                mediaProjection.stop();
                mediaProjection = null;
            }
            sSharedProjection = null;
        }
    }

    // ──────────────────────────────────────────────────────────────────────
    // Command handling — tap / swipe / key (via InputManagerWrapper = minitouch
    // equiv.)
    // ──────────────────────────────────────────────────────────────────────

    private void handleCommand(String text) {
        try {
            JSONObject msg = new JSONObject(text);
            String type = msg.optString("type", "");
            switch (type) {
                case "error": {
                    String serverMessage = msg.optString("message", "Connection rejected");
                    Log.w(TAG, "Server error: " + serverMessage);
                    Intent err = new Intent(ACTION_SERVER_ERROR);
                    err.putExtra("message", serverMessage);
                    LocalBroadcastManager.getInstance(this).sendBroadcast(err);
                    wsUrl = null;
                    stopSelf();
                    return;
                }
                case "hello_ack":
                    // Server gửi tunnel ports — start services và tạo WS bridges
                    JSONObject tunnels = msg.optJSONObject("tunnels");
                    if (tunnels != null) {
                        final JSONObject ports = tunnels;
                        executor.submit(() -> setupServiceTunnels(ports));
                    }
                    break;
                case "ping":
                    // Server keepalive ping — reply with pong so server detects dead connections
                    try {
                        JSONObject pong = new JSONObject();
                        pong.put("type", "pong");
                        wsManager.send(pong.toString());
                    } catch (Exception ignored) {}
                    break;
                case "tunnel_data":
                    // Server → Agent: forward data đến device service
                    String ch = msg.optString("channel");
                    String d  = msg.optString("data");
                    ServiceTunnel tunnel = serviceTunnels.get(ch);
                    if (tunnel != null && !d.isEmpty()) {
                        tunnel.write(Base64.decode(d, Base64.NO_WRAP));
                    }
                    break;
                case "tap": {
                    final int tx = msg.optInt("x", 0);
                    final int ty = msg.optInt("y", 0);
                    final int tdur = msg.optInt("ms", 50);
                    if (TouchAccessibilityService.isAvailable()) {
                        mainHandler.post(() -> {
                            TouchAccessibilityService svc = TouchAccessibilityService.instance;
                            if (svc != null) svc.doTap(tx, ty, Math.max(tdur, 50));
                        });
                    } else if (Build.VERSION.SDK_INT < 34 && inputManager != null) {
                        executor.submit(() -> injectTouchEvent(tx, ty));
                    }
                    break;
                }
                case "swipe": {
                    final int x1 = msg.optInt("x1", 0), y1 = msg.optInt("y1", 0);
                    final int x2 = msg.optInt("x2", 0), y2 = msg.optInt("y2", 0);
                    final int dur = Math.max(msg.optInt("ms", 300), 50);
                    if (TouchAccessibilityService.isAvailable()) {
                        mainHandler.post(() -> {
                            TouchAccessibilityService svc = TouchAccessibilityService.instance;
                            if (svc != null) svc.doSwipe(x1, y1, x2, y2, dur);
                        });
                    } else if (Build.VERSION.SDK_INT < 34 && inputManager != null) {
                        executor.submit(() -> injectSwipeEvent(x1, y1, x2, y2, dur));
                    }
                    break;
                }
                case "long_tap": {
                    final int ltx = msg.optInt("x", 0);
                    final int lty = msg.optInt("y", 0);
                    final int ltdur = Math.max(msg.optInt("ms", 800), 300);
                    if (TouchAccessibilityService.isAvailable()) {
                        mainHandler.post(() -> {
                            TouchAccessibilityService svc = TouchAccessibilityService.instance;
                            if (svc != null) svc.doTap(ltx, lty, ltdur);
                        });
                    }
                    break;
                }
                case "double_tap": {
                    final int dtx = msg.optInt("x", 0);
                    final int dty = msg.optInt("y", 0);
                    if (TouchAccessibilityService.isAvailable()) {
                        mainHandler.post(() -> {
                            TouchAccessibilityService svc = TouchAccessibilityService.instance;
                            if (svc != null) svc.doDoubleTap(dtx, dty);
                        });
                    } else if (Build.VERSION.SDK_INT < 34 && inputManager != null) {
                        // Fallback: two injected taps 100ms apart
                        executor.submit(() -> {
                            injectTouchEvent(dtx, dty);
                            try { Thread.sleep(100); } catch (InterruptedException ignored) {}
                            injectTouchEvent(dtx, dty);
                        });
                    }
                    break;
                }
                case "pinch": {
                    final int pcx = msg.optInt("cx", 0);
                    final int pcy = msg.optInt("cy", 0);
                    final float pscale = (float) msg.optDouble("scale", 0.5);
                    final int pdur = Math.max(msg.optInt("ms", 400), 100);
                    if (TouchAccessibilityService.isAvailable()) {
                        mainHandler.post(() -> {
                            TouchAccessibilityService svc = TouchAccessibilityService.instance;
                            if (svc != null) svc.doPinch(pcx, pcy, pscale, pdur);
                        });
                    }
                    break;
                }
                case "drag": {
                    final int drx1 = msg.optInt("x1", 0), dry1 = msg.optInt("y1", 0);
                    final int drx2 = msg.optInt("x2", 0), dry2 = msg.optInt("y2", 0);
                    final int drdur = Math.max(msg.optInt("ms", 1000), 500);
                    if (TouchAccessibilityService.isAvailable()) {
                        mainHandler.post(() -> {
                            TouchAccessibilityService svc = TouchAccessibilityService.instance;
                            if (svc != null) svc.doDrag(drx1, dry1, drx2, dry2, drdur);
                        });
                    } else if (Build.VERSION.SDK_INT < 34 && inputManager != null) {
                        executor.submit(() -> injectSwipeEvent(drx1, dry1, drx2, dry2, drdur));
                    }
                    break;
                }
                case "key":
                    executor.submit(() -> injectKey(msg.optString("key", "home")));
                    break;
                case "enable_accessibility":
                    // Disabled: do not auto-enable accessibility; we rely on minitouch.
                    // mainHandler.post(() -> autoEnableAccessibility());
                    break;
                case "open_accessibility_settings":
                    // Disabled: do not auto-open accessibility settings.
                    // mainHandler.post(() -> openAccessibilitySettings());
                    break;
                case "type":
                    executor.submit(() -> injectText(msg.optString("text", "")));
                    break;
                case "paste": {
                    final String pasteText = msg.optString("text", "");
                    executor.submit(() -> {
                        boolean done = false;
                        // Step 1: ACTION_SET_TEXT via accessibility — most reliable, no clipboard needed
                        if (TouchAccessibilityService.isAvailable()) {
                            try {
                                android.view.accessibility.AccessibilityNodeInfo node =
                                    TouchAccessibilityService.instance.getRootInActiveWindow()
                                        .findFocus(android.view.accessibility.AccessibilityNodeInfo.FOCUS_INPUT);
                                if (node != null && node.isEditable()) {
                                    android.os.Bundle args = new android.os.Bundle();
                                    args.putCharSequence(
                                        android.view.accessibility.AccessibilityNodeInfo
                                            .ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, pasteText);
                                    done = node.performAction(
                                        android.view.accessibility.AccessibilityNodeInfo.ACTION_SET_TEXT, args);
                                    sendLog("paste: ACTION_SET_TEXT: " + done);
                                } else {
                                    sendLog("paste: a11y no focused editable node");
                                }
                            } catch (Exception e) {
                                sendLog("paste: ACTION_SET_TEXT error: " + e.getMessage());
                            }
                        } else {
                            sendLog("paste: a11y not available");
                        }
                        if (done) return;
                        // Step 2: set clipboard then ACTION_PASTE via a11y
                        try {
                            android.content.ClipboardManager cm =
                                (android.content.ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
                            cm.setPrimaryClip(android.content.ClipData.newPlainText("", pasteText));
                            sendLog("paste: clipboard set (" + pasteText.length() + " chars)");
                        } catch (Exception e) {
                            sendLog("paste: clipboard error: " + e.getMessage());
                        }
                        try { Thread.sleep(150); } catch (InterruptedException ignored) {}
                        if (TouchAccessibilityService.isAvailable()) {
                            try {
                                android.view.accessibility.AccessibilityNodeInfo node =
                                    TouchAccessibilityService.instance.getRootInActiveWindow()
                                        .findFocus(android.view.accessibility.AccessibilityNodeInfo.FOCUS_INPUT);
                                if (node != null) {
                                    done = node.performAction(
                                        android.view.accessibility.AccessibilityNodeInfo.ACTION_PASTE);
                                    sendLog("paste: ACTION_PASTE: " + done);
                                }
                            } catch (Exception e) {
                                sendLog("paste: ACTION_PASTE error: " + e.getMessage());
                            }
                        }
                        // Step 3: fallback — shell input text (often blocked in app UID on Android 14+)
                        if (!done) {
                            String safeText = toShellInputText(pasteText);
                            if (!safeText.isEmpty()) {
                                boolean ok = runShell("input text \"" + safeText + "\"");
                                if (ok) {
                                    sendLog("paste: input text fallback ok");
                                } else {
                                    sendLog("paste: input text fallback blocked (likely INJECT_EVENTS)");
                                }
                            } else {
                                sendLog("paste: fallback skipped (empty text)");
                            }
                        }
                    });
                    break;
                }
                case "shell":
                    executor.submit(() -> runShell(msg.optString("cmd", "")));
                    break;
                case "launch_app": {
                    final String pkg = msg.optString("package", "");
                    final String component = msg.optString("component", "").trim();
                    mainHandler.post(() -> {
                        if ((pkg == null || pkg.isEmpty()) && component.isEmpty()) {
                            sendLog("launch_app: empty package");
                            return;
                        }
                        try {
                            Intent i = null;
                            if (!component.isEmpty() && component.contains("/")) {
                                String[] parts = component.split("/", 2);
                                String cpkg = parts[0].trim();
                                String cls = parts[1].trim();
                                if (!cpkg.isEmpty() && !cls.isEmpty()) {
                                    if (cls.startsWith(".")) cls = cpkg + cls;
                                    i = new Intent(Intent.ACTION_MAIN);
                                    i.addCategory(Intent.CATEGORY_LAUNCHER);
                                    i.setComponent(new ComponentName(cpkg, cls));
                                    sendLog("launch_app: explicit component " + cpkg + "/" + cls);
                                }
                            }
                            if (i == null) {
                                i = getPackageManager().getLaunchIntentForPackage(pkg);
                            }
                            if (i == null) {
                                // Fallback: query all LAUNCHER activities for the package.
                                // Some apps (e.g. Facebook) do not expose a standard launch
                                // intent via getLaunchIntentForPackage on certain OEMs.
                                Intent query = new Intent(Intent.ACTION_MAIN);
                                query.addCategory(Intent.CATEGORY_LAUNCHER);
                                query.setPackage(pkg);
                                List<ResolveInfo> resolved = getPackageManager()
                                        .queryIntentActivities(query, 0);
                                if (!resolved.isEmpty()) {
                                    ActivityInfo ai = resolved.get(0).activityInfo;
                                    i = new Intent(Intent.ACTION_MAIN);
                                    i.addCategory(Intent.CATEGORY_LAUNCHER);
                                    i.setComponent(new ComponentName(ai.packageName, ai.name));
                                    sendLog("launch_app: resolved via queryIntentActivities → " + ai.name);
                                }
                            }
                            if (i == null) {
                                sendLog("launch_app: no launch intent for " + pkg);
                                return;
                            }
                            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                                    | Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED
                                    | Intent.FLAG_ACTIVITY_CLEAR_TASK);
                            startActivity(i);
                            sendLog("launch_app: started " + (!component.isEmpty() ? component : pkg));
                        } catch (Exception e) {
                            sendLog("launch_app error: " + e.getMessage());
                        }
                    });
                    break;
                }
                case "open_url": {
                    final String url = msg.optString("url", "").trim();
                    final String pkg = msg.optString("package", "").trim().isEmpty()
                            ? "com.android.chrome"
                            : msg.optString("package", "").trim();
                    mainHandler.post(() -> {
                        if (url.isEmpty()) {
                            sendLog("open_url: empty url");
                            sendOpenUrlResult(false, "empty url");
                            return;
                        }
                        try {
                            Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                            i.addCategory(Intent.CATEGORY_BROWSABLE);
                            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP
                                    | Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED);
                            if (!pkg.isEmpty()) {
                                i.setPackage(pkg);
                                try {
                                    startActivity(i);
                                    sendLog("open_url: opened " + url + " (package=" + pkg + ")");
                                    sendOpenUrlResult(true, null);
                                    return;
                                } catch (ActivityNotFoundException e) {
                                    if ("com.android.chrome".equals(pkg)) {
                                        i.setPackage("com.android.browser");
                                        try {
                                            startActivity(i);
                                            sendLog("open_url: opened " + url + " (package=com.android.browser)");
                                            sendOpenUrlResult(true, null);
                                            return;
                                        } catch (ActivityNotFoundException e2) {
                                            i.setPackage(null);
                                        }
                                    } else {
                                        i.setPackage(null);
                                    }
                                }
                            }
                            startActivity(i);
                            sendLog("open_url: opened " + url);
                            sendOpenUrlResult(true, null);
                        } catch (Exception e) {
                            sendLog("open_url error: " + e.getMessage());
                            sendOpenUrlResult(false, e.getMessage());
                        }
                    });
                    break;
                }
                case "start_services":
                    // u2 cannot be started from within the app (am instrument needs shell UID).
                    // If u2 is now running (started externally via ADB), connect the tunnel.
                    sendLog("start_services received — checking u2 availability…");
                    executor.submit(() -> {
                        if (!serviceTunnels.containsKey("u2") && tunnelPortsCache != null && tunnelPortsCache.has("u2")) {
                            ensureU2Running();  // just checks + logs
                            ServiceTunnel t = new ServiceTunnel("u2");
                            if (t.connectTcp("127.0.0.1", 9008)) {
                                serviceTunnels.put("u2", t);
                                sendLog("✓ u2 tunnel connected (:9008)");
                                try {
                                    JSONObject ready = new JSONObject();
                                    ready.put("type", "tunnels_ready");
                                    ready.put("connected", serviceTunnels.keySet().toString());
                                    if (wsManager != null) wsManager.send(ready.toString());
                                } catch (Exception e) { sendLog("tunnels_ready update error: " + e.getMessage()); }
                            } else {
                                t.close();
                            }
                        }
                    });
                    break;
                case "set_stream_options":
                    // Server hint: reduce both FPS and capture resolution.
                    int maxFps = msg.optInt("max_fps", -1);
                    if (maxFps >= 1 && maxFps <= 120) {
                        targetFps = maxFps;
                        minFrameIntervalMs = 1000L / Math.max(1, targetFps);
                        sendLog("set_stream_options max_fps=" + targetFps);
                    }

                    int maxWidth = msg.optInt("max_width", -1);
                    boolean widthChanged = false;
                    if (maxWidth >= 1 && maxWidth <= 4096) {
                        widthChanged = (streamMaxWidth != maxWidth);
                        streamMaxWidth = maxWidth;
                    } else if (maxWidth == 0) {
                        widthChanged = (streamMaxWidth != 0);
                        streamMaxWidth = 0; // native / heuristic
                    }

                    if (widthChanged && wsManager != null && wsManager.isConnected()) {
                        // Force recreate VirtualDisplay/ImageReader with the new size.
                        capturing.set(false);
                        executor.submit(this::startCapture);
                    }
                    break;

                case "dump_hierarchy":
                    // Fast UI hierarchy dump via AccessibilityService (~100-500ms)
                    executor.submit(() -> {
                        try {
                            String xml = TouchAccessibilityService.dumpHierarchyIfAvailable();
                            JSONObject resp = new JSONObject();
                            resp.put("type", "hierarchy");
                            if (xml != null) {
                                resp.put("xml", xml);
                            } else {
                                resp.put("error", "accessibility_not_available");
                                requestAutoEnableAccessibility("dump_hierarchy");
                            }
                            if (wsManager != null) wsManager.send(resp.toString());
                        } catch (Exception e) {
                            Log.w(TAG, "dump_hierarchy error: " + e);
                        }
                    });
                    break;
            }
        } catch (Exception e) {
            Log.w(TAG, "handleCommand: " + e);
        }
    }

    // Touch (tap/swipe) is via minitouch tunnel only — no injectTap/injectSwipe a11y in this service.

    // ──────────────────────────────────────────────────────────────────────
    // Service Tunnels — bridge device services to WS channels (no ADB needed)
    // ──────────────────────────────────────────────────────────────────────

    /**
     * Bidirectional bridge: device service socket ↔ WebSocket channel.
     * Any data read from the socket is sent to the server as tunnel_data.
     * Data received from server (tunnel_data) is written to the socket.
     */
    private class ServiceTunnel {
        private final String   channel;
        private volatile OutputStream out;
        private Thread         readThread;
        private volatile boolean closed = false;

        // Stored for u2 auto-reconnect (uiautomator2 closes idle HTTP keep-alive connections)
        private String tcpHost;
        private int    tcpPort;

        ServiceTunnel(String channel) { this.channel = channel; }

        /** Connect to a TCP socket (e.g. u2 HTTP server on 127.0.0.1:9008). */
        boolean connectTcp(String host, int port) {
            tcpHost = host;
            tcpPort = port;
            return openTcpAndStart(host, port);
        }

        private boolean openTcpAndStart(String host, int port) {
            try {
                Socket s = new Socket(host, port);
                s.setTcpNoDelay(true);
                s.setSoTimeout("u2".equals(channel) ? 60000 : 0); // 60s for u2 (hierarchy dump can be slow)
                out = s.getOutputStream();
                startReadThread(s.getInputStream());
                return true;
            } catch (Exception e) {
                sendLog("tunnel " + channel + " tcp connect failed: " + e.getMessage());
                return false;
            }
        }

        /** Connect to an Android abstract socket (e.g. "stfservice", "minitouchagent"). */
        boolean connectAbstract(String name) {
            try {
                LocalSocket ls = new LocalSocket();
                ls.connect(new LocalSocketAddress(name, LocalSocketAddress.Namespace.ABSTRACT));
                out = ls.getOutputStream();
                startReadThread(ls.getInputStream());
                return true;
            } catch (Exception e) {
                sendLog("tunnel " + channel + " abstract:" + name + " failed: " + e.getMessage());
                return false;
            }
        }

        void write(byte[] data) {
            if (closed) return;
            OutputStream o = out;
            // u2: if reconnect is in progress (out == null), wait up to 1.5s for it to finish.
            // Without this, HTTP request bytes are dropped and the server-side keepalive sees
            // a timeout → marks u2 as dead → cascading disconnects.
            if (o == null && "u2".equals(channel)) {
                for (int i = 0; i < 15 && !closed && out == null; i++) {
                    try { Thread.sleep(100); } catch (InterruptedException e) { break; }
                }
                o = out;
            }
            if (o == null || closed) return;
            try {
                o.write(data);
            } catch (Exception e) {
                Log.d(TAG, "tunnel " + channel + " write error: " + e.getMessage());
                if ("u2".equals(channel)) out = null;
            }
        }

        void close() {
            closed = true;
            OutputStream o = out;
            out = null;
            if (o != null) try { o.close(); } catch (Exception ignored) {}
        }

        private void startReadThread(InputStream in) {
            readThread = new Thread(() -> {
                byte[] buf = new byte[8192];
                try {
                    // Give the other end (e.g. MinitouchAgent) time to send banner before we read
                    if ("minitouch".equals(channel)) {
                        try { Thread.sleep(500); } catch (InterruptedException ignored) {}
                    }
                    int n;
                    while (!closed && (n = in.read(buf)) >= 0) {
                        String b64 = Base64.encodeToString(Arrays.copyOf(buf, n), Base64.NO_WRAP);
                        JSONObject msg = new JSONObject();
                        msg.put("type",    "tunnel_data");
                        msg.put("channel", channel);
                        msg.put("data",    b64);
                        if (wsManager != null) wsManager.send(msg.toString());
                    }
                } catch (Exception ignored) {
                } finally {
                    // u2: uiautomator2 closes idle HTTP keep-alive connections (~5s timeout).
                    // Reconnect automatically so Python requests never time out waiting for a
                    // response that the dead read thread can no longer deliver.
                    if ("u2".equals(channel) && !closed && tcpHost != null) {
                        sendLog("tunnel u2 disconnected — reconnecting to port " + tcpPort + "…");
                        try { Thread.sleep(50); } catch (InterruptedException ignored2) {}
                        if (!closed) openTcpAndStart(tcpHost, tcpPort);
                    } else {
                        sendLog("tunnel " + channel + " disconnected");
                    }
                }
            }, "tunnel-read-" + channel);
            readThread.setDaemon(true);
            readThread.start();
        }
    }

    /** Start all device services and create WS tunnels. Called after hello_ack. */
    private void setupServiceTunnels(JSONObject tunnelPorts) {
        tunnelPortsCache = tunnelPorts;
        sendLog("Setting up service tunnels (no ADB)…");
        // Close existing tunnels first
        for (ServiceTunnel t : serviceTunnels.values()) t.close();
        serviceTunnels.clear();

        if (tunnelPorts.has("u2")) {
            ensureU2Running();
            ServiceTunnel t = new ServiceTunnel("u2");
            if (t.connectTcp("127.0.0.1", 9008)) {
                serviceTunnels.put("u2", t);
                sendLog("✓ u2 tunnel ready (127.0.0.1:9008 ↔ WS)");
            } else {
                t.close();
                sendLog("u2 tunnel: uiautomator2 not available. Cài APK: cd agent-boot && uv run main.py --serial <device>");
            }
        }

        // ── Minitouch: in-app only, no ADB. MinitouchAgent listens on abstract "minitouchagent",
        //    we connect via LocalSocket and bridge to WebSocket; server MinitouchSender uses tunnel.
        if (tunnelPorts.has("minitouch")) {
            ensureMinitouchAgentStarted();
            ServiceTunnel t = new ServiceTunnel("minitouch");
            boolean minitouchOk = false;
            for (int attempt = 0; attempt < 4 && !minitouchOk; attempt++) {
                if (attempt > 0) {
                    try { Thread.sleep(400); } catch (InterruptedException ignored) {}
                }
                minitouchOk = t.connectAbstract("minitouchagent");
            }
            if (minitouchOk) {
                serviceTunnels.put("minitouch", t);
                sendLog("✓ minitouch tunnel ready (abstract:minitouchagent ↔ WS)");
            } else {
                t.close();
                sendLog("minitouch tunnel (minitouchagent) connect failed after retries");
            }
        }

        // ── STFService abstract socket ─────────────────────────────────────
        if (tunnelPorts.has("stfservice")) {
            // Start the STFService component so it binds its abstract socket
            try {
                Intent stfIntent = new Intent(this, Service.class);
                stfIntent.setAction("jp.co.cyberagent.stf.ACTION_START");
                startService(stfIntent);
                sendLog("STFService component start requested — waiting 2s…");
                Thread.sleep(2000);
            } catch (Exception e) {
                sendLog("Could not start STFService component: " + e.getMessage());
            }
            ServiceTunnel t = new ServiceTunnel("stfservice");
            if (t.connectAbstract("stfservice")) {
                serviceTunnels.put("stfservice", t);
                sendLog("✓ stfservice tunnel ready (abstract:stfservice ↔ WS)");
            }
        }

        // ── Notify server ─────────────────────────────────────────────────
        try {
            JSONObject ready = new JSONObject();
            ready.put("type", "tunnels_ready");
            ready.put("connected", serviceTunnels.keySet().toString());
            if (wsManager != null) wsManager.send(ready.toString());
            sendLog("tunnels_ready sent (" + serviceTunnels.size() + " tunnels)");
        } catch (Exception e) {
            sendLog("tunnels_ready error: " + e.getMessage());
        }
    }

    /**
     * Check if uiautomator2 server is already running on port 9008.
     *
     * NOTE: am instrument requires shell UID — this app cannot start it.
     * u2 must be started via agent-boot (ADB) before opening this app:
     *   adb shell am instrument -w com.github.uiautomator.test/androidx.test.runner.AndroidJUnitRunner
     * After that, u2 keeps running until the device reboots.
     */
    private void ensureU2Running() {
        try (java.net.Socket s = new java.net.Socket()) {
            s.connect(new java.net.InetSocketAddress("127.0.0.1", 9008), 400);
            sendLog("✓ uiautomator2 running on :9008");
            return;
        } catch (Exception ignored) {}

        // u2 not running — try to start it via am instrument (needs shell context,
        // may fail from app context but worth trying)
        sendLog("uiautomator2 NOT running — attempting restart...");
        try {
            ProcessBuilder pb = new ProcessBuilder("sh", "-c",
                "am instrument -w -e debug false " +
                "com.github.uiautomator.test/androidx.test.runner.AndroidJUnitRunner " +
                ">/dev/null 2>&1 &");
            pb.redirectErrorStream(true);
            pb.start();
            // Wait briefly for it to start
            Thread.sleep(3000);
            // Re-check
            try (java.net.Socket s2 = new java.net.Socket()) {
                s2.connect(new java.net.InetSocketAddress("127.0.0.1", 9008), 400);
                sendLog("✓ uiautomator2 restarted successfully on :9008");
                return;
            } catch (Exception e2) {
                sendLog("uiautomator2 restart failed — still not on :9008");
            }
        } catch (Exception e) {
            sendLog("uiautomator2 restart error: " + e.getMessage());
        }

        sendLog("uiautomator2 NOT running on :9008. Run agent-boot first:\n"
              + "  cd agent-boot && uv run main.py --serial <device>");
    }

    /**
     * Start in-app MinitouchAgent once (listens on abstract socket "minitouchagent").
     * Provides minitouch protocol over WS tunnel — no ADB, no binary.
     */
    private void ensureMinitouchAgentStarted() {
        if (minitouchAgent != null && minitouchAgent.isAlive()) return;
        synchronized (minitouchAgentLock) {
            if (minitouchAgent != null && minitouchAgent.isAlive()) return;
            Point size = MinitouchAgent.getScreenSize();
            if (size == null) {
                DisplayMetrics dm = getResources().getDisplayMetrics();
                size = new Point(dm.widthPixels, dm.heightPixels);
            }
            minitouchAgent = new MinitouchAgent(size.x, size.y, mainHandler);
            minitouchAgent.setDaemon(true);
            minitouchAgent.start();
            sendLog("MinitouchAgent started (abstract:minitouchagent)");
        }
    }

    // activeU2Port() / startU2Server() removed for ADB-first builds.

    private void requestAutoEnableAccessibility(String reason) {
        long now = SystemClock.elapsedRealtime();
        long last = lastA11yAutoEnableMs;
        if (now - last < A11Y_AUTO_ENABLE_MIN_INTERVAL_MS) {
            return;
        }
        lastA11yAutoEnableMs = now;
        sendLog("a11y not available — attempting auto-enable (" + reason + ")");
        mainHandler.post(() -> autoEnableAccessibility());
    }

    /**
     * Try to enable TouchAccessibilityService programmatically via WRITE_SECURE_SETTINGS.
     * Falls back to opening the Accessibility Settings screen if permission is not granted.
     * Must be called on the main thread.
     */
    private void autoEnableAccessibility() {
        String service = getPackageName() + "/jp.co.cyberagent.stf.TouchAccessibilityService";
        try {
            android.content.ContentResolver cr = getContentResolver();
            String current = Settings.Secure.getString(cr, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
            if (current != null && current.contains(service)) {
                if (TouchAccessibilityService.isAvailable()) {
                    sendLog("✓ a11y service already bound and available");
                    return;
                }
                // Listed but not bound — force rebind by toggling off/on
                sendLog("a11y listed but not bound — force rebind...");
                try {
                    String without = current.replace(service, "").replace("::", ":").replaceAll("^:|:$", "");
                    Settings.Secure.putString(cr, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES, without);
                    Thread.sleep(500);
                    Settings.Secure.putString(cr, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES, current);
                    sendLog("a11y force-rebind toggled");
                } catch (Exception rebindErr) {
                    sendLog("a11y rebind toggle failed: " + rebindErr.getMessage());
                }
                return;
            }
            String newList = (current == null || current.isEmpty()) ? service : current + ":" + service;
            Settings.Secure.putString(cr, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES, newList);
            Settings.Secure.putInt(cr, Settings.Secure.ACCESSIBILITY_ENABLED, 1);
            sendLog("Accessibility auto-enabled via WRITE_SECURE_SETTINGS ✓");
        } catch (SecurityException e) {
            sendLog("WRITE_SECURE_SETTINGS not granted — opening settings screen. "
                    + "Grant once with: adb shell pm grant " + getPackageName()
                    + " android.permission.WRITE_SECURE_SETTINGS");
            openAccessibilitySettings();
        } catch (Exception e) {
            sendLog("autoEnableAccessibility error: " + e.getMessage());
            openAccessibilitySettings();
        }
    }

    /** Type text into the currently focused field. */
    private void injectText(String text) {
        if (text.isEmpty()) return;
        if (TouchAccessibilityService.isAvailable()) {
            TouchAccessibilityService.instance.doType(text);
            sendLog("type via a11y: " + text.length() + " chars");
            return;
        }
        // Fallback: shell input text (avoid KEYCODE_PASTE which needs INJECT_EVENTS on some devices)
        String safeText = toShellInputText(text);
        if (safeText.isEmpty()) return;
        boolean ok = runShell("input text \"" + safeText + "\"");
        if (ok) {
            sendLog("type via shell input text: " + text.length() + " chars");
        } else {
            sendLog("type via shell blocked (likely INJECT_EVENTS) — need a11y or adb relay typing");
        }
    }

    /** Escape text for `input text "..."` shell command. */
    private String toShellInputText(String text) {
        if (text == null || text.isEmpty()) return "";
        return text
                .replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace(" ", "%s");
    }

    /** Run a shell command (am, pm, input, etc.). */
    private boolean runShell(String cmd) {
        if (cmd.isEmpty()) return false;
        try {
            Process p = Runtime.getRuntime().exec(new String[]{"sh", "-c", cmd});
            byte[] out = p.getInputStream().readAllBytes();
            byte[] err = p.getErrorStream().readAllBytes();
            int code = p.waitFor();
            String stdout = new String(out).trim();
            String stderr = new String(err).trim();
            String result = "shell[" + code + "] $ " + cmd;
            if (!stdout.isEmpty()) result += "\n" + stdout;
            if (!stderr.isEmpty()) result += "\nSTDERR: " + stderr;
            sendLog(result);
            return code == 0;
        } catch (Exception e) {
            sendLog("shell error: " + e.getMessage());
            return false;
        }
    }

    /** Open the system Accessibility Settings screen so user can enable manually. */
    private void openAccessibilitySettings() {
        try {
            Intent intent = new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
            startActivity(intent);
            sendLog("Opened Accessibility Settings — enable 'Device Farm Agent' then return");
        } catch (Exception e) {
            sendLog("Could not open Accessibility Settings: " + e.getMessage());
        }
    }

    private void injectTouchEvent(int x, int y) {
        if (inputManager == null) return;
        long now = SystemClock.uptimeMillis();
        MotionEvent down = motionEvent(now, now, MotionEvent.ACTION_DOWN, x, y);
        MotionEvent up   = motionEvent(now, now + 50, MotionEvent.ACTION_UP, x, y);
        inputManager.injectInputEvent(down);
        inputManager.injectInputEvent(up);
        down.recycle(); up.recycle();
    }

    private void injectSwipeEvent(int x1, int y1, int x2, int y2, int durationMs) {
        if (inputManager == null) return;
        int steps = Math.max(5, durationMs / 20);
        long now = SystemClock.uptimeMillis();
        MotionEvent down = motionEvent(now, now, MotionEvent.ACTION_DOWN, x1, y1);
        inputManager.injectInputEvent(down);
        down.recycle();
        long stepMs = durationMs / steps;
        for (int i = 1; i <= steps; i++) {
            float ix = x1 + (x2 - x1) * i / (float) steps;
            float iy = y1 + (y2 - y1) * i / (float) steps;
            try { Thread.sleep(stepMs); } catch (InterruptedException ignored) {}
            MotionEvent move = motionEvent(now, SystemClock.uptimeMillis(), MotionEvent.ACTION_MOVE, ix, iy);
            inputManager.injectInputEvent(move);
            move.recycle();
        }
        MotionEvent up = motionEvent(now, SystemClock.uptimeMillis(), MotionEvent.ACTION_UP, x2, y2);
        inputManager.injectInputEvent(up);
        up.recycle();
    }

    private void injectKey(String key) {
        String k = (key != null) ? key.trim().toLowerCase() : "";
        // home / back / recent: use AccessibilityService so they work on Android 10+ (InputManager inject is blocked)
        if (TouchAccessibilityService.isAvailable()) {
            Integer globalAction = keyToGlobalAction(k);
            if (globalAction != null) {
                TouchAccessibilityService.instance.doGlobalAction(globalAction);
                return;
            }
        }
        // enter: trigger IME action (Search/Go/Done/Next) on focused editable node (API 30+).
        // This is more reliable than KEYCODE_ENTER injection — handles imeOptions correctly.
        if ("enter".equals(k) && TouchAccessibilityService.isAvailable()
                && Build.VERSION.SDK_INT >= 30) {
            AccessibilityNodeInfo focused = TouchAccessibilityService.instance
                    .findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
            if (focused != null) {
                focused.performAction(
                        AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.getId());
                focused.recycle();
                return;
            }
        }

        // other keys (enter fallback, menu, power, volume...) or a11y not available: inject via InputManager
        if (inputManager == null)
            return;
        int keycode = resolveKeycode(key);
        long now = SystemClock.uptimeMillis();
        KeyEvent down = new KeyEvent(now, now, KeyEvent.ACTION_DOWN, keycode, 0,
                0, -1, 0, KeyEvent.FLAG_FROM_SYSTEM, InputDevice.SOURCE_KEYBOARD);
        KeyEvent up = new KeyEvent(now, now + 10, KeyEvent.ACTION_UP, keycode, 0,
                0, -1, 0, KeyEvent.FLAG_FROM_SYSTEM, InputDevice.SOURCE_KEYBOARD);
        inputManager.injectKeyEvent(down);
        inputManager.injectKeyEvent(up);
    }

    /** Map home/back/recent to AccessibilityService global action; other keys return null. */
    private static Integer keyToGlobalAction(String key) {
        if (key == null) return null;
        switch (key) {
            case "home":
                return android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_HOME;
            case "back":
                return android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_BACK;
            case "recent":
                return android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_RECENTS;
            default:
                return null;
        }
    }

    private MotionEvent motionEvent(long downTime, long eventTime, int action, float x, float y) {
        MotionEvent ev = MotionEvent.obtain(downTime, eventTime, action, x, y, 0);
        ev.setSource(InputDevice.SOURCE_TOUCHSCREEN);
        return ev;
    }

    private int resolveKeycode(String key) {
        switch (key.toLowerCase()) {
            case "home":
                return KeyEvent.KEYCODE_HOME;
            case "back":
                return KeyEvent.KEYCODE_BACK;
            case "menu":
                return KeyEvent.KEYCODE_MENU;
            case "power":
                return KeyEvent.KEYCODE_POWER;
            case "enter":
                return KeyEvent.KEYCODE_ENTER;
            case "del":
                return KeyEvent.KEYCODE_DEL;
            case "recent":
                return KeyEvent.KEYCODE_APP_SWITCH;
            case "volumeup":
                return KeyEvent.KEYCODE_VOLUME_UP;
            case "volumedown":
                return KeyEvent.KEYCODE_VOLUME_DOWN;
            default:
                try {
                    return Integer.parseInt(key);
                } catch (NumberFormatException ignored) {
                }
                try {
                    String name = key.startsWith("KEYCODE_") ? key : "KEYCODE_" + key.toUpperCase();
                    return (int) KeyEvent.class.getField(name).get(null);
                } catch (Exception ignored) {
                }
                return KeyEvent.KEYCODE_UNKNOWN;
        }
    }

    // ──────────────────────────────────────────────────────────────────────
    // Helpers
    // ──────────────────────────────────────────────────────────────────────

    private int getBatteryLevel() {
        try {
            Intent bi = registerReceiver(null,
                    new android.content.IntentFilter(Intent.ACTION_BATTERY_CHANGED));
            if (bi != null)
                return bi.getIntExtra(android.os.BatteryManager.EXTRA_LEVEL, -1);
        } catch (Exception ignored) {
        }
        return -1;
    }

    // ──────────────────────────────────────────────────────────────────────
    // Static helpers (called from IdentityActivity)
    // ──────────────────────────────────────────────────────────────────────

    // ── Getters for U2CompatServer ─────────────────────────────────────────────

    String getSerial()      { return serial; }
    String getModel()       { return model; }
    int    getScreenWidth() { return screenWidth; }
    int    getScreenHeight(){ return screenHeight; }

    /** Returns the most recent JPEG frame captured, or null if none yet. */
    byte[] getLatestJpeg()  { return latestJpeg; }

    public static void start(Context ctx, String wsUrl, int resultCode, Intent projData) {
        Intent i = new Intent(ctx, WsAgentService.class);
        i.setAction(ACTION_START);
        i.putExtra(EXTRA_WS_URL, wsUrl);
        i.putExtra(EXTRA_PROJECTION_CODE, resultCode);
        i.putExtra(EXTRA_PROJECTION_DATA, projData);
        i.putExtra(EXTRA_ALLOW_BATTERY_DIALOG, ctx instanceof Activity);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            ctx.startForegroundService(i);
        } else {
            ctx.startService(i);
        }
    }

    public static void stop(Context ctx) {
        Intent i = new Intent(ctx, WsAgentService.class);
        i.setAction(ACTION_STOP);
        ctx.startService(i);
    }
}
