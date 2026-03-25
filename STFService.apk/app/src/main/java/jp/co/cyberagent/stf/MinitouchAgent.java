/*
 *  Copyright (C) 2019 Orange
 *
 *  Licensed under the Apache License, Version 2.0 (the "License");
 *  you may not use this file except in compliance with the License.
 *  You may obtain a copy of the License at
 *
 *         http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing, software
 *  distributed under the License is distributed on an "AS IS" BASIS,
 *  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *  See the License for the specific language governing permissions and
 *  limitations under the License.
 *
 */
package jp.co.cyberagent.stf;

import android.graphics.Point;
import android.net.LocalServerSocket;
import android.net.LocalSocket;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;
import android.view.Display;
import android.view.InputDevice;
import android.view.InputEvent;
import android.view.MotionEvent;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.lang.reflect.InvocationTargetException;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.NoSuchElementException;
import java.util.Scanner;

import jp.co.cyberagent.stf.compat.InputManagerWrapper;
import jp.co.cyberagent.stf.compat.WindowManagerWrapper;
import jp.co.cyberagent.stf.util.InternalApi;

public class MinitouchAgent extends Thread {
    private static final String TAG = MinitouchAgent.class.getSimpleName();
    private static final String SOCKET = "minitouchagent";
    private static final int DEFAULT_MAX_CONTACTS = 10;
    private static final int DEFAULT_MAX_PRESSURE = 0;
    private final int width;
    private final int height;
    private LocalServerSocket serverSocket;

    private MotionEvent.PointerProperties[] pointerProperties = new MotionEvent.PointerProperties[2];
    private MotionEvent.PointerCoords[] pointerCoords = new MotionEvent.PointerCoords[2];
    private PointerEvent[] events = new PointerEvent[2];

    private final InputManagerWrapper inputManager;
    private final WindowManagerWrapper windowManager;
    private final Handler handler;
    /** On Android 14+ (API 34), InputManager.injectInputEvent is restricted; use a11y for gesture. */
    private final boolean useA11yForTouch = Build.VERSION.SDK_INT >= 34;
    private boolean a11yInGesture;
    private boolean a11yPendingUp;
    private float a11yStartScreenX, a11yStartScreenY, a11yEndScreenX, a11yEndScreenY;
    private boolean a11yHasMove;
    private long a11yStartTime;
    private int a11yDurationMs;

    private class PointerEvent {
        long lastMouseDown;
        int lastX;
        int lastY;
        int action;
    }

    /**
     * Get the width and height of the display by getting the DisplayInfo through reflection
     * Using the android.hardware.display.DisplayManagerGlobal but there might be other ways.
     *
     * @return a Point whose x is the width and y the height of the screen
     */
    static Point getScreenSize() {
        Object displayManager = InternalApi.getSingleton("android.hardware.display.DisplayManagerGlobal");
        try {
            Object displayInfo = displayManager.getClass().getMethod("getDisplayInfo", int.class)
                .invoke(displayManager, Display.DEFAULT_DISPLAY);
            if (displayInfo != null) {
                Class<?> cls = displayInfo.getClass();
                int width = cls.getDeclaredField("logicalWidth").getInt(displayInfo);
                int height = cls.getDeclaredField("logicalHeight").getInt(displayInfo);
                return new Point(width, height);
            }
        } catch (IllegalAccessException e) {
            e.printStackTrace();
        } catch (InvocationTargetException e) {
            e.printStackTrace();
        } catch (NoSuchMethodException e) {
            e.printStackTrace();
        } catch (NoSuchFieldException e) {
            e.printStackTrace();
        }
        return null;
    }


    /**
     * Keep a way to start only the MinitouchAgent for debugging purpose
     */
    public static void main(String[] args) {
        //To create a Handler our main thread has to prepare the Looper
        Looper.prepare();
        Handler handler = new Handler();
        Point size = getScreenSize();
        if(size != null) {
            MinitouchAgent m = new MinitouchAgent(size.x, size.y, handler);
            m.start();
            Looper.loop();
        } else {
            System.err.println("Couldn't get screen resolution");
            System.exit(1);
        }
    }

    private void injectEvent(InputEvent event) {
        handler.post(() -> inputManager.injectInputEvent(event));
    }

    /** Run one tap or swipe via TouchAccessibilityService (Android 14+ when InputManager inject is restricted). */
    // private void flushA11yGesture() {
    //     if (!TouchAccessibilityService.isAvailable()) {
    //         Log.w(TAG, "minitouch: a11y not available — enable Settings → Accessibility → STFService for touch on Android 14+");
    //         return;
    //     }
    //     final int x1 = (int) a11yStartScreenX;
    //     final int y1 = (int) a11yStartScreenY;
    //     final int x2 = (int) a11yEndScreenX;
    //     final int y2 = (int) a11yEndScreenY;
    //     final int durationMs = a11yDurationMs > 0 ? a11yDurationMs : 300;
    //     handler.post(() -> {
    //         if (a11yHasMove) {
    //             TouchAccessibilityService.instance.doSwipe(x1, y1, x2, y2, durationMs);
    //         } else {
    //             TouchAccessibilityService.instance.doTap(x1, y1, Math.max(50, durationMs));
    //         }
    //     });
    // }

    private float[] calculateCoordsForScreen(PointerEvent p){
        float[] result = new float[2];
        int x_translate=0, y_translate=0;
        int rotation = windowManager.getRotation();
        if (rotation == 1){
            y_translate = width;
        } else if (rotation == 3){
            x_translate = height;
        }
        double rad = Math.toRadians(rotation*-90);
        result[0] = (float)(p.lastX * Math.cos(rad) - p.lastY * Math.sin(rad))+x_translate;
        result[1] = (float)(p.lastX * Math.sin(rad) + p.lastY * Math.cos(rad))+y_translate;
        return result;
    }

    private MotionEvent getMotionEvent(PointerEvent p) {
        return getMotionEvent(p,0);
    }

    private MotionEvent getMotionEvent(PointerEvent p, int idx) {
        long now = SystemClock.uptimeMillis();
        if (p.action == MotionEvent.ACTION_DOWN) {
            p.lastMouseDown = now;
        }
        MotionEvent.PointerCoords coords = pointerCoords[idx];

        float[] screenCoords = calculateCoordsForScreen(p);
        coords.x = screenCoords[0];
        coords.y = screenCoords[1];
        return MotionEvent.obtain(p.lastMouseDown, now, p.action, idx+1, pointerProperties,
            pointerCoords, 0, 0, 1f, 1f, 0, 0,
            InputDevice.SOURCE_TOUCHSCREEN, 0);
    }

    private List<MotionEvent> getMotionEvent(PointerEvent p1, PointerEvent p2) {
        List<MotionEvent> combinedEvents = new ArrayList<>(2);
        long now = SystemClock.uptimeMillis();
        if (p1.action != MotionEvent.ACTION_MOVE) {
            combinedEvents.add(getMotionEvent(p1));
            combinedEvents.add(getMotionEvent(p2,1));
        } else {
            MotionEvent.PointerCoords coords1 = pointerCoords[0];
            MotionEvent.PointerCoords coords2 = pointerCoords[1];

            float[] screenCoords1 = calculateCoordsForScreen(p1);
            float[] screenCoords2 = calculateCoordsForScreen(p2);

            coords1.x = screenCoords1[0];
            coords1.y = screenCoords1[1];;

            coords2.x = screenCoords2[0];
            coords2.y = screenCoords2[1];

            MotionEvent event = MotionEvent.obtain(p1.lastMouseDown, now, p1.action, 2, pointerProperties,
                pointerCoords, 0, 0, 1f, 1f, 0, 0,
                InputDevice.SOURCE_TOUCHSCREEN, 0);
            combinedEvents.add(event);
        }
        return combinedEvents;
    }

    /** Send minitouch protocol banner (no ADB — client is ServiceTunnel over WebSocket). */
    private void sendBanner(LocalSocket clientSocket) {
        try {
            OutputStreamWriter out = new OutputStreamWriter(clientSocket.getOutputStream());
            out.write("v 1\n");
            String resolution = String.format(Locale.US, "^ %d %d %d %d%n",
                DEFAULT_MAX_CONTACTS, width, height, DEFAULT_MAX_PRESSURE);
            out.write(resolution);
            out.write("$ 0\n");
            out.flush();
            Log.i(TAG, "minitouch banner sent (in-app, no ADB) -> WebSocket tunnel");
        } catch (IOException e) {
            Log.e(TAG, "sendBanner failed", e);
            e.printStackTrace();
        }
    }

    /**
     * Manages the client connection. The client is supposed to be minitouch.
     */
    private void manageClientConnection() {
        while (true) {
            Log.i(TAG, String.format("Listening on %s", SOCKET));
            LocalSocket clientSocket;
            try {
                clientSocket = serverSocket.accept();
                Log.d(TAG, "client connected");
                sendBanner(clientSocket);
                processCommandLoop(clientSocket);
            } catch (IOException e) {
                e.printStackTrace();
            }
        }
    }

    /**
     * processCommandLoop parses touch related commands sent by stf
     * and inject them in Android InputManager.
     * Commmands can be of type down, up, move, commit
     * Note that it currently doesn't support multitouch
     *
     * @param clientSocket the socket to read on
     */
    private void processCommandLoop(LocalSocket clientSocket) throws IOException{
        try (BufferedReader in = new BufferedReader(new InputStreamReader(clientSocket.getInputStream()))) {
            String cmd;
            int count = 0;
            while ((cmd = in.readLine()) != null) {
                try (Scanner scanner = new Scanner(cmd)) {
                    scanner.useDelimiter(" ");
                    String type = scanner.next();
                    int contact;
                    switch (type) {
                        case "c":
                            // if (useA11yForTouch && a11yInGesture) {
                            //     if (a11yPendingUp) {
                            //         flushA11yGesture();
                            //         a11yInGesture = false;
                            //         a11yPendingUp = false;
                            //     }
                            // } else
                            if (count == 1) {
                                injectEvent(getMotionEvent(events[0]));
                            } else if (count == 2) {
                                for (MotionEvent event : getMotionEvent(events[0], events[1])) {
                                    injectEvent(event);
                                }
                            } else {
                                System.out.println("count not manage events #" + count);
                            }
                            count = 0;
                            break;
                        case "u":
                            count++;
                            contact = scanner.nextInt();
                            events[contact].action = (contact == 0) ? MotionEvent.ACTION_UP : MotionEvent.ACTION_POINTER_2_UP;
                            // if (useA11yForTouch && a11yInGesture && contact == 0) {
                            //     a11yPendingUp = true;
                            //     float[] s = calculateCoordsForScreen(events[0]);
                            //     a11yEndScreenX = s[0];
                            //     a11yEndScreenY = s[1];
                            // }
                            break;
                        case "d":
                            count++;
                            contact = scanner.nextInt();
                            events[contact].lastX = scanner.nextInt();
                            events[contact].lastY = scanner.nextInt();
                            //scanner.nextInt(); //pressure is currently not supported
                            events[contact].action = (contact == 0) ? MotionEvent.ACTION_DOWN : MotionEvent.ACTION_POINTER_2_DOWN;
                            // if (useA11yForTouch && contact == 0) {
                            //     a11yInGesture = true;
                            //     a11yPendingUp = false;
                            //     a11yDurationMs = 50;
                            //     float[] s = calculateCoordsForScreen(events[0]);
                            //     a11yStartScreenX = a11yEndScreenX = s[0];
                            //     a11yStartScreenY = a11yEndScreenY = s[1];
                            //     a11yHasMove = false;
                            //     a11yStartTime = SystemClock.uptimeMillis();
                            // }
                            break;
                        case "m":
                            count++;
                            contact = scanner.nextInt();
                            events[contact].lastX = scanner.nextInt();
                            events[contact].lastY = scanner.nextInt();
                            //scanner.nextInt(); //pressure is currently not supported
                            events[contact].action = MotionEvent.ACTION_MOVE;
                            // if (useA11yForTouch && a11yInGesture && contact == 0) {
                            //     float[] s = calculateCoordsForScreen(events[0]);
                            //     a11yEndScreenX = s[0];
                            //     a11yEndScreenY = s[1];
                            //     a11yHasMove = true;
                            // }
                            break;
                        case "w":
                            int delayMs = scanner.nextInt();
                            // if (useA11yForTouch && a11yInGesture) {
                            //     a11yDurationMs += delayMs;
                            // }
                            Thread.sleep(delayMs);
                            break;
                        // case "r":
                        //     // reset all contacts (no-op for state; client clears before new gesture)
                        //     break;
                        default:
                            System.out.println("could not parse: " + cmd);
                    }
                } catch (NoSuchElementException e) {
                    System.out.println("could not parse: " + cmd);
                } catch (InterruptedException e) {
                    e.printStackTrace();
                }
            }
        }
    }

    public MinitouchAgent(int width, int height, Handler handler) {
        this.width = width;
        this.height = height;
        this.handler = handler;
        inputManager = new InputManagerWrapper();
        windowManager = new WindowManagerWrapper();
        MotionEvent.PointerProperties pointerProps0 = new MotionEvent.PointerProperties();
        pointerProps0.id = 0;
        pointerProps0.toolType = MotionEvent.TOOL_TYPE_FINGER;
        MotionEvent.PointerProperties pointerProps1 = new MotionEvent.PointerProperties();
        pointerProps1.id = 1;
        pointerProps1.toolType = MotionEvent.TOOL_TYPE_FINGER;
        pointerProperties[0] = pointerProps0;
        pointerProperties[1] = pointerProps1;

        MotionEvent.PointerCoords pointerCoords0 = new MotionEvent.PointerCoords();
        MotionEvent.PointerCoords pointerCoords1 = new MotionEvent.PointerCoords();
        pointerCoords0.orientation = 0;
        pointerCoords0.pressure = 1; // pressure and size have to be set
        pointerCoords0.size = 1;
        pointerCoords1.orientation = 0;
        pointerCoords1.pressure = 1;
        pointerCoords1.size = 1;
        pointerCoords[0] = pointerCoords0;
        pointerCoords[1] = pointerCoords1;

        events[0] = new PointerEvent();
        events[1] = new PointerEvent();
    }

    @Override
    public void run() {
        try {
            Log.i(TAG, String.format("creating socket %s", SOCKET));
            serverSocket = new LocalServerSocket(SOCKET);
        } catch (IOException e) {
            e.printStackTrace();
            return;
        }
        manageClientConnection();
        try {
            serverSocket.close();
        } catch (IOException e) {
            e.printStackTrace();
        }
    }
}
