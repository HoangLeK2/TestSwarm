// package jp.co.cyberagent.stf;

// import android.content.Context;
// import android.content.pm.PackageManager;
// import android.util.Log;

// import java.net.Socket;

// /**
//  * AtxAgentLauncher — Ensures the uiautomator2 HTTP server runs on port 9008.
//  *
//  * Priority chain (Shizuku removed — no external dependency needed):
//  *   1. Port 9008 already open (pre-started externally) → use immediately.
//  *   2. Return false → caller (WsAgentService) starts U2CompatServer as built-in fallback.
//  *
//  * U2CompatServer provides full uiautomator2-compatible HTTP on port 7912
//  * backed by AccessibilityService — no ADB, no root, no Shizuku required.
//  */
// public class AtxAgentLauncher {

//     private static final String TAG     = "AtxAgentLauncher";
//     /** android-uiautomator-server JSON-RPC port. */
//     public  static final int    U2_PORT = 9008;

//     private static final String PKG_SERVER = "com.github.uiautomator";
//     private static final String PKG_TEST   = "com.github.uiautomator.test";

//     private final Context context;

//     public AtxAgentLauncher(Context context) {
//         this.context = context.getApplicationContext();
//     }

//     /**
//      * Check if uiautomator2 is already running on port 9008.
//      * No blocking — returns immediately.
//      *
//      * @return true if port 9008 is already open, false otherwise.
//      *         Caller should start U2CompatServer as fallback when false.
//      */
//     public boolean start() {
//         // Already running (e.g. started externally via ADB in dev mode)?
//         if (isPortOpen(U2_PORT)) {
//             Log.i(TAG, "uiautomator2 already running on port " + U2_PORT);
//             return true;
//         }

//         boolean pkgsInstalled = isPackageInstalled(PKG_SERVER) && isPackageInstalled(PKG_TEST);
//         if (pkgsInstalled) {
//             Log.d(TAG, "com.github.uiautomator installed but not running. "
//                     + "Using U2CompatServer (AccessibilityService-backed, no ADB needed).");
//         } else {
//             Log.d(TAG, "com.github.uiautomator not installed. Using U2CompatServer.");
//         }
//         return false;
//     }

//     public void stop() { /* no-op: U2CompatServer lifecycle managed by WsAgentService */ }

//     public boolean isRunning() {
//         return isPortOpen(U2_PORT);
//     }

//     // ── Helpers ──────────────────────────────────────────────────────────────

//     private boolean isPackageInstalled(String pkg) {
//         try {
//             context.getPackageManager().getPackageInfo(pkg, 0);
//             return true;
//         } catch (PackageManager.NameNotFoundException e) {
//             return false;
//         }
//     }

//     private static boolean isPortOpen(int port) {
//         try (Socket s = new Socket("127.0.0.1", port)) {
//             return true;
//         } catch (Exception e) {
//             return false;
//         }
//     }
// }
