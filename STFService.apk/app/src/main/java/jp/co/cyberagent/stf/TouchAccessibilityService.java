package jp.co.cyberagent.stf;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.graphics.Path;
import android.graphics.Rect;
import android.os.Build;
import android.os.Bundle;
import android.util.Log;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;
import java.util.List;

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

    // ──────────────────────────────────────────────────────────────────────
    // UI Hierarchy Dump via AccessibilityNodeInfo (~100-500ms, much faster
    // than uiautomator2 dumpWindowHierarchy which takes 1-4s)
    // ──────────────────────────────────────────────────────────────────────

    /**
     * Dump the full UI hierarchy as XML (same format as uiautomator2).
     * Uses getWindows() to capture ALL visible windows: app, status bar,
     * navigation bar, dialogs, keyboard, PiP, split-screen, overlays.
     * Requires flagRetrieveInteractiveWindows in accessibility_service_config.xml.
     * @return XML string, or null if no windows available.
     */
    public String dumpHierarchy() {
        try {
            StringBuilder sb = new StringBuilder(16384);
            sb.append("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n");
            sb.append("<hierarchy rotation=\"0\">\n");

            // getWindows() returns ALL visible windows (API 21+)
            // flagRetrieveInteractiveWindows ensures we see non-interactive windows too
            List<AccessibilityWindowInfo> windows = getWindows();
            if (windows != null && !windows.isEmpty()) {
                for (AccessibilityWindowInfo window : windows) {
                    AccessibilityNodeInfo root = window.getRoot();
                    if (root != null) {
                        dumpNode(sb, root, 0);
                        root.recycle();
                    }
                }
            } else {
                // Fallback: single active window (pre-API 21 or no windows returned)
                AccessibilityNodeInfo root = getRootInActiveWindow();
                if (root != null) {
                    dumpNode(sb, root, 0);
                    root.recycle();
                } else {
                    return null;
                }
            }

            sb.append("</hierarchy>\n");
            return sb.toString();
        } catch (Exception e) {
            Log.e(TAG, "dumpHierarchy error", e);
            return null;
        }
    }

    private void dumpNode(StringBuilder sb, AccessibilityNodeInfo node, int index) {
        if (node == null) return;
        Rect bounds = new Rect();
        node.getBoundsInScreen(bounds);

        String className = node.getClassName() != null ? node.getClassName().toString() : "";
        String text = node.getText() != null ? node.getText().toString() : "";
        String resourceId = node.getViewIdResourceName() != null ? node.getViewIdResourceName() : "";
        String contentDesc = node.getContentDescription() != null ? node.getContentDescription().toString() : "";
        String pkg = node.getPackageName() != null ? node.getPackageName().toString() : "";

        sb.append("<node");
        sb.append(" index=\"").append(index).append('"');
        sb.append(" text=\"").append(escapeXml(text)).append('"');
        sb.append(" resource-id=\"").append(escapeXml(resourceId)).append('"');
        sb.append(" class=\"").append(escapeXml(className)).append('"');
        sb.append(" package=\"").append(escapeXml(pkg)).append('"');
        sb.append(" content-desc=\"").append(escapeXml(contentDesc)).append('"');
        sb.append(" checkable=\"").append(node.isCheckable()).append('"');
        sb.append(" checked=\"").append(node.isChecked()).append('"');
        sb.append(" clickable=\"").append(node.isClickable()).append('"');
        sb.append(" enabled=\"").append(node.isEnabled()).append('"');
        sb.append(" focusable=\"").append(node.isFocusable()).append('"');
        sb.append(" focused=\"").append(node.isFocused()).append('"');
        sb.append(" scrollable=\"").append(node.isScrollable()).append('"');
        sb.append(" long-clickable=\"").append(node.isLongClickable()).append('"');
        sb.append(" password=\"").append(node.isPassword()).append('"');
        sb.append(" selected=\"").append(node.isSelected()).append('"');
        sb.append(" bounds=\"[").append(bounds.left).append(',').append(bounds.top)
                .append("][").append(bounds.right).append(',').append(bounds.bottom).append("]\"");

        int childCount = node.getChildCount();
        if (childCount == 0) {
            sb.append(" />\n");
        } else {
            sb.append(">\n");
            for (int i = 0; i < childCount; i++) {
                AccessibilityNodeInfo child = node.getChild(i);
                if (child != null) {
                    dumpNode(sb, child, i);
                    child.recycle();
                }
            }
            sb.append("</node>\n");
        }
    }

    private static String escapeXml(String s) {
        if (s == null || s.isEmpty()) return "";
        return s.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\"", "&quot;")
                .replace("'", "&apos;");
    }

    /**
     * Static convenience: dump hierarchy if service is available, null otherwise.
     */
    public static String dumpHierarchyIfAvailable() {
        TouchAccessibilityService svc = instance;
        return svc != null ? svc.dumpHierarchy() : null;
    }
}
