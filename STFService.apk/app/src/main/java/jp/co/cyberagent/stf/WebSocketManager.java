package jp.co.cyberagent.stf;

import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.WebSocket;
import okhttp3.WebSocketListener;
import okio.ByteString;

import java.util.concurrent.TimeUnit;

public class WebSocketManager {

    public interface Callback {
        void onConnected(String url);

        void onMessage(String text);

        void onDisconnected(String reason);

        void onError(String error);
    }

    private final OkHttpClient client;
    private volatile WebSocket webSocket;
    private volatile Callback callback;
    private volatile boolean destroyed = false;

    public WebSocketManager() {
        client = new OkHttpClient.Builder()
                .connectTimeout(10, TimeUnit.SECONDS)
                .readTimeout(0, TimeUnit.MILLISECONDS)
                // Disable OkHttp client-side ping — server sends heartbeat pings instead.
                // Client pings every 20s caused "no pong within 20000ms" disconnects when
                // the server event loop was briefly busy processing video frames.
                .pingInterval(0, TimeUnit.MILLISECONDS)
                .build();
    }

    public void setCallback(Callback callback) {
        this.callback = callback;
    }

    public void connect(String url) {
        if (destroyed)
            return;
        disconnect();
        Request request;
        try {
            request = new Request.Builder().url(url).build();
        } catch (IllegalArgumentException e) {
            if (callback != null)
                callback.onError("Invalid URL: " + e.getMessage());
            return;
        }
        webSocket = client.newWebSocket(request, new WebSocketListener() {
            @Override
            public void onOpen(WebSocket ws, Response response) {
                if (destroyed || callback == null)
                    return;
                try { callback.onConnected(url); } catch (Exception ignored) {}
            }

            @Override
            public void onMessage(WebSocket ws, String text) {
                if (destroyed || callback == null)
                    return;
                try { callback.onMessage(text); } catch (Exception ignored) {}
            }

            @Override
            public void onFailure(WebSocket ws, Throwable t, Response response) {
                webSocket = null;
                if (response != null) {
                    try { response.close(); } catch (Exception ignored) {}
                }
                if (destroyed || callback == null)
                    return;
                String msg = t.getMessage() != null ? t.getMessage() : "Connection failed";
                try { callback.onError(msg); } catch (Exception ignored) {}
            }

            @Override
            public void onClosed(WebSocket ws, int code, String reason) {
                webSocket = null;
                if (destroyed || callback == null)
                    return;
                try { callback.onDisconnected(reason); } catch (Exception ignored) {}
            }
        });
    }

    public void disconnect() {
        if (webSocket != null) {
            webSocket.close(1000, "User disconnected");
            webSocket = null;
        }
    }

    public boolean isConnected() {
        return webSocket != null;
    }

    public boolean send(String message) {
        return webSocket != null && webSocket.send(message);
    }

    public boolean sendBytes(byte[] bytes) {
        return webSocket != null && bytes != null && webSocket.send(ByteString.of(bytes));
    }

    public void shutdown() {
        destroyed = true;
        callback = null;
        disconnect();
        client.dispatcher().executorService().shutdown();
    }
}
