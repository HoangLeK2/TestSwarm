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

    /** Double-tap at (x, y): two 50ms taps with 100ms gap. Requires API 24+. */
    public void doDoubleTap(int x, int y) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) return;
        Path path = new Path();
        path.moveTo(x, y);
        Path path2 = new Path();
        path2.moveTo(x, y);
        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(new GestureDescription.StrokeDescription(path, 0L, 50L))
                .addStroke(new GestureDescription.StrokeDescription(path2, 100L, 50L))
                .build();
        dispatchGesture(gesture, null, null);
    }

    /**
     * Pinch/zoom at (cx, cy). scale &gt; 1 = spread (zoom in), scale &lt; 1 = pinch (zoom out).
     * Two fingers move horizontally from/to center. Requires API 24+.
     */
    public void doPinch(int cx, int cy, float scale, int durationMs) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) return;
        int startDist = 150;
        int endDist = Math.max(10, (int)(startDist * scale));
        Path p1 = new Path();
        p1.moveTo(cx - startDist, cy);
        p1.lineTo(cx - endDist, cy);
        Path p2 = new Path();
        p2.moveTo(cx + startDist, cy);
        p2.lineTo(cx + endDist, cy);
        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(new GestureDescription.StrokeDescription(p1, 0L, Math.max(durationMs, 100)))
                .addStroke(new GestureDescription.StrokeDescription(p2, 0L, Math.max(durationMs, 100)))
                .build();
        dispatchGesture(gesture, null, null);
    }

    /**
     * Drag-and-drop from (x1,y1) to (x2,y2). Long press + slide.
     * A stroke &ge;500ms is treated by Android as drag rather than swipe. Requires API 24+.
     */
    public void doDrag(int x1, int y1, int x2, int y2, int durationMs) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) return;
        Path path = new Path();
        path.moveTo(x1, y1);
        path.lineTo(x2, y2);
        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(new GestureDescription.StrokeDescription(
                        path, 0L, Math.max(durationMs, 800)))
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
     * Dump the UI hierarchy as XML (same format as uiautomator2).
     *
     * Optimizations vs. full dump:
     *  - Skips TYPE_INPUT_METHOD (keyboard) and TYPE_SYSTEM windows — keyboard
     *    alone can add 60-80 nodes and is rarely needed for automation.
     *  - Skips nodes where isVisibleToUser() == false (still recurses into children).
     *  - Skips nodes with empty/zero bounds.
     *  - Only writes boolean attributes when true and string attributes when non-empty,
     *    cutting ~50% of attribute bytes per node.
     *
     * Result: typically 70-80% smaller than the unfiltered dump, which prevents
     * large JSON WebSocket messages from stalling the u2 tunnel.
     *
     * Requires flagRetrieveInteractiveWindows in accessibility_service_config.xml.
     * @return XML string, or null if no windows available.
     */
    public String dumpHierarchy() {
        try {
            StringBuilder sb = new StringBuilder(8192);
            sb.append("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n");
            sb.append("<hierarchy rotation=\"0\">\n");

            List<AccessibilityWindowInfo> windows = getWindows();
            if (windows != null && !windows.isEmpty()) {
                for (AccessibilityWindowInfo window : windows) {
                    int wType = window.getType();
                    // A1: Skip keyboard (IME) and system overlay windows.
                    // They are never needed for app automation and can add hundreds of nodes.
                    if (wType == AccessibilityWindowInfo.TYPE_INPUT_METHOD) continue;
                    if (wType == AccessibilityWindowInfo.TYPE_SYSTEM) continue;

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

        // A2: Skip invisible nodes but still recurse so we don't miss visible children.
        if (!node.isVisibleToUser()) {
            int cc = node.getChildCount();
            for (int i = 0; i < cc; i++) {
                AccessibilityNodeInfo child = node.getChild(i);
                if (child != null) { dumpNode(sb, child, i); child.recycle(); }
            }
            return;
        }

        Rect bounds = new Rect();
        node.getBoundsInScreen(bounds);

        // A4: Skip zero-size nodes — they are not visible on screen.
        if (bounds.isEmpty()) {
            int cc = node.getChildCount();
            for (int i = 0; i < cc; i++) {
                AccessibilityNodeInfo child = node.getChild(i);
                if (child != null) { dumpNode(sb, child, i); child.recycle(); }
            }
            return;
        }

        String className   = node.getClassName()          != null ? node.getClassName().toString()          : "";
        String text        = node.getText()               != null ? node.getText().toString()               : "";
        String resourceId  = node.getViewIdResourceName() != null ? node.getViewIdResourceName()            : "";
        String contentDesc = node.getContentDescription() != null ? node.getContentDescription().toString() : "";
        String pkg         = node.getPackageName()        != null ? node.getPackageName().toString()        : "";

        sb.append("<node");
        sb.append(" index=\"").append(index).append('"');

        // A3: Only write string attributes when non-empty.
        if (!className.isEmpty())   sb.append(" class=\"").append(escapeXml(className)).append('"');
        if (!text.isEmpty())        sb.append(" text=\"").append(escapeXml(text)).append('"');
        if (!resourceId.isEmpty())  sb.append(" resource-id=\"").append(escapeXml(resourceId)).append('"');
        if (!contentDesc.isEmpty()) sb.append(" content-desc=\"").append(escapeXml(contentDesc)).append('"');
        if (!pkg.isEmpty())         sb.append(" package=\"").append(escapeXml(pkg)).append('"');

        // A3: Only write boolean attributes when true (default is false — saves ~40% bytes).
        if (node.isClickable())     sb.append(" clickable=\"true\"");
        if (node.isEnabled())       sb.append(" enabled=\"true\"");
        if (node.isScrollable())    sb.append(" scrollable=\"true\"");
        if (node.isCheckable())     sb.append(" checkable=\"true\"");
        if (node.isChecked())       sb.append(" checked=\"true\"");
        if (node.isLongClickable()) sb.append(" long-clickable=\"true\"");
        if (node.isFocusable())     sb.append(" focusable=\"true\"");
        if (node.isFocused())       sb.append(" focused=\"true\"");
        if (node.isPassword())      sb.append(" password=\"true\"");
        if (node.isSelected())      sb.append(" selected=\"true\"");

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
