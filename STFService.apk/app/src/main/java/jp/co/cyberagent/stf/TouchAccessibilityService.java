package jp.co.cyberagent.stf;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.graphics.Path;
import android.os.Build;
import android.os.Bundle;
import android.util.Log;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

/**
 * TouchAccessibilityService — enables tap/swipe injection without INJECT_EVENTS permission.
 *
 * Android 14+ (SDK 34) restricts injectInputEvent() to system apps only.
 * AccessibilityService.dispatchGesture() works without any system privilege.
 *
 * USER MUST ENABLE in: Settings → Accessibility → STFService → Enable
 */
public class TouchAccessibilityService extends AccessibilityService {

    private static final String TAG = "TouchA11yService";

    /** Singleton reference, set when service connects. Thread-safe (volatile). */
    public static volatile TouchAccessibilityService instance;

    @Override
    public void onServiceConnected() {
        super.onServiceConnected();
        instance = this;
        Log.i(TAG, "TouchAccessibilityService connected — gesture injection ready");
    }

    @Override
    public void onDestroy() {
        instance = null;
        super.onDestroy();
        Log.i(TAG, "TouchAccessibilityService destroyed");
    }

    @Override public void onAccessibilityEvent(AccessibilityEvent event) {}
    @Override public void onInterrupt() {}

    // ──────────────────────────────────────────────────────────────────────
    // Public gesture API (called from WsAgentService)
    // ──────────────────────────────────────────────────────────────────────

    /** Dispatch a tap at (x, y). Requires API 24+. */
    public void doTap(int x, int y) {
        doTap(x, y, 50);
    }

    /** Tap with custom duration (ms); use >50 for long-press. */
    public void doTap(int x, int y, int durationMs) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) return;
        Path path = new Path();
        path.moveTo(x, y);
        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(new GestureDescription.StrokeDescription(path, 0L, Math.max(durationMs, 1)))
                .build();
        dispatchGesture(gesture, null, null);
    }

    /** Dispatch a swipe from (x1,y1) to (x2,y2) over durationMs. Requires API 24+. */
    public void doSwipe(int x1, int y1, int x2, int y2, int durationMs) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) return;
        Path path = new Path();
        path.moveTo(x1, y1);
        path.lineTo(x2, y2);
        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(new GestureDescription.StrokeDescription(
                        path, 0L, Math.max(durationMs, 1L)))
                .build();
        dispatchGesture(gesture, null, null);
    }

    /**
     * Type text into the currently focused editable field.
     * Uses ACTION_SET_TEXT on the focused node (API 21+), which works for EditText.
     */
    public void doType(String text) {
        AccessibilityNodeInfo focused = findFocusedNode(getRootInActiveWindow());
        if (focused != null) {
            Bundle args = new Bundle();
            args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text);
            focused.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args);
            focused.recycle();
        } else {
            Log.w(TAG, "doType: no focused editable node found");
        }
    }

    private AccessibilityNodeInfo findFocusedNode(AccessibilityNodeInfo root) {
        if (root == null) return null;
        AccessibilityNodeInfo focused = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
        if (focused != null && focused.isEditable()) return focused;
        if (focused != null) focused.recycle();
        return null;
    }

    /** Returns true if the service is currently enabled and connected. */
    public static boolean isAvailable() {
        return instance != null;
    }

    /**
     * Perform a global action (home, back, recents). Works without INJECT_EVENTS.
     * Use this for home/back so they work on Android 10+ where InputManager inject is blocked.
     * @return true if the action was performed
     */
    public boolean doGlobalAction(int action) {
        return performGlobalAction(action);
    }
}
