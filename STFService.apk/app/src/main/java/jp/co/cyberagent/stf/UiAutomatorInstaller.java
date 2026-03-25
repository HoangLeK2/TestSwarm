package jp.co.cyberagent.stf;

import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.util.Log;

import androidx.core.content.FileProvider;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;

/**
 * UiAutomatorInstaller — checks and installs uiautomator2 APKs from assets.
 *
 * APKs bundled in assets/:
 *   app-uiautomator.apk       — main uiautomator2 app
 *   app-uiautomator-test.apk  — test runner (required for am instrument)
 *
 * Usage:
 *   UiAutomatorInstaller.ensureInstalled(context);
 */
public class UiAutomatorInstaller {

    private static final String TAG          = "U2Installer";
    static final String         U2_PACKAGE   = "com.github.uiautomator";
    static final String         U2T_PACKAGE  = "com.github.uiautomator.test";

    private static final String[] ASSETS = {
        "app-uiautomator.apk",
        "app-uiautomator-test.apk",
    };

    /**
     * Check if u2 APKs are installed. If not, extract from assets to cache
     * and launch the system install dialog for each missing APK.
     * Returns true if already fully installed (no dialog needed).
     */
    public static boolean ensureInstalled(Context ctx) {
        boolean mainOk = isInstalled(ctx, U2_PACKAGE);
        boolean testOk = isInstalled(ctx, U2T_PACKAGE);

        if (mainOk && testOk) {
            Log.i(TAG, "uiautomator2 already installed ✓");
            return true;
        }

        Log.i(TAG, "uiautomator2 not fully installed (main=" + mainOk + " test=" + testOk + ") — installing from assets");

        for (String asset : ASSETS) {
            if (asset.contains("test") && !testOk) {
                extractAndInstall(ctx, asset);
            } else if (!asset.contains("test") && !mainOk) {
                extractAndInstall(ctx, asset);
            }
        }
        return false;
    }

    /** Try silent install via pm shell command (works on debuggable builds / shell user). */
    public static boolean silentInstall(Context ctx, String assetName) {
        File apk = extractAsset(ctx, assetName);
        if (apk == null) return false;
        try {
            Process p = Runtime.getRuntime().exec(
                new String[]{"pm", "install", "-r", "-t", apk.getAbsolutePath()});
            byte[] out = p.getInputStream().readAllBytes();
            int code = p.waitFor();
            String result = new String(out).trim();
            Log.i(TAG, "pm install " + assetName + " → code=" + code + " " + result);
            return code == 0 && result.contains("Success");
        } catch (Exception e) {
            Log.w(TAG, "pm install failed: " + e.getMessage());
            return false;
        }
    }

    /** Extract APK from assets and open system install dialog. */
    public static void extractAndInstall(Context ctx, String assetName) {
        // First try silent install (works when running with shell-level privileges)
        if (silentInstall(ctx, assetName)) return;

        // Fallback: show system install dialog
        File apk = extractAsset(ctx, assetName);
        if (apk == null) return;
        try {
            Intent intent = new Intent(Intent.ACTION_VIEW);
            Uri uri;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                uri = FileProvider.getUriForFile(
                    ctx,
                    ctx.getPackageName() + ".fileprovider",
                    apk);
                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            } else {
                uri = Uri.fromFile(apk);
            }
            intent.setDataAndType(uri, "application/vnd.android.package-archive");
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            ctx.startActivity(intent);
            Log.i(TAG, "Install dialog launched for: " + assetName);
        } catch (Exception e) {
            Log.e(TAG, "Could not launch install dialog: " + e.getMessage());
        }
    }

    /** Extract an APK asset to the app's cache directory. Returns the File, or null on error. */
    public static File extractAsset(Context ctx, String assetName) {
        File dest = new File(ctx.getCacheDir(), assetName);
        if (dest.exists()) return dest; // already extracted
        try {
            InputStream  in  = ctx.getAssets().open(assetName);
            OutputStream out = new FileOutputStream(dest);
            byte[] buf = new byte[65536];
            int n;
            while ((n = in.read(buf)) >= 0) out.write(buf, 0, n);
            in.close();
            out.close();
            Log.i(TAG, "Extracted asset: " + assetName + " → " + dest);
            return dest;
        } catch (Exception e) {
            Log.e(TAG, "extractAsset " + assetName + ": " + e.getMessage());
            return null;
        }
    }

    public static boolean isInstalled(Context ctx, String pkg) {
        try {
            ctx.getPackageManager().getPackageInfo(pkg, 0);
            return true;
        } catch (PackageManager.NameNotFoundException e) {
            return false;
        }
    }
}
