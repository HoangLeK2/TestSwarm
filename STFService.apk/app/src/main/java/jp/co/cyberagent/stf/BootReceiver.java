package jp.co.cyberagent.stf;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.util.Log;

/**
 * BootReceiver — auto-starts WsAgentService after device boot.
 *
 * If a WebSocket URL was saved from a previous session, the service is restarted
 * automatically. MediaProjection cannot be re-acquired silently after boot, so the
 * service starts in "no-projection" mode and requests re-auth via IdentityActivity
 * when the screen is next unlocked.
 */
public class BootReceiver extends BroadcastReceiver {

    private static final String TAG       = "BootReceiver";
    private static final String PREFS_NAME = "stf_prefs";
    private static final String PREF_WS_URL = "ws_url";

    @Override
    public void onReceive(Context context, Intent intent) {
        String action = intent.getAction();
        if (!Intent.ACTION_BOOT_COMPLETED.equals(action)
                && !"android.intent.action.LOCKED_BOOT_COMPLETED".equals(action)) {
            return;
        }

        SharedPreferences prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        String savedUrl = prefs.getString(PREF_WS_URL, null);

        if (savedUrl == null || savedUrl.isEmpty()) {
            Log.i(TAG, "Boot complete — no saved WS URL, skipping auto-start");
            return;
        }

        Log.i(TAG, "Boot complete — launching IdentityActivity for re-auth (savedUrl present)");

        // Launch IdentityActivity so it can re-request MediaProjection permission
        // and restart the service. We cannot obtain MediaProjection silently on boot.
        Intent ui = new IdentityActivity.IntentBuilder().build(context);
        ui.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        context.startActivity(ui);
    }
}
