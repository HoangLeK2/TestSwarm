package httpapi

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"devicefarm/media-adapter/internal/adapters/outbound/go2rtc"
	"devicefarm/media-adapter/internal/adapters/scrcpy"
	"devicefarm/media-adapter/internal/domain/stream"
)

type fakePublisher struct{}

func (fakePublisher) Publish(context.Context, stream.EncodedPacket) error {
	return nil
}

func TestHandleStreamDecodesSerialPath(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	manager := scrcpy.NewManager(fakePublisher{}, logger)
	server := NewServer("127.0.0.1:0", manager, logger)

	req := httptest.NewRequest(
		http.MethodPost,
		"/v1/scrcpy/streams/10.0.0.1%3A5555/start",
		strings.NewReader(`{"host":"127.0.0.1","port":27183,"control":true}`),
	)
	res := httptest.NewRecorder()

	server.routes().ServeHTTP(res, req)

	if res.Code != http.StatusAccepted {
		t.Fatalf("status=%d body=%s", res.Code, res.Body.String())
	}
	if _, ok := manager.Status("10.0.0.1:5555"); !ok {
		t.Fatal("expected decoded serial to be stored in manager")
	}
	manager.Close()
}

func TestWebRTCSessionStartsOwnedScrcpyAndProxiesGo2RTC(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	manager := scrcpy.NewManagerWithLauncher(fakePublisher{}, fakeLauncher{}, logger)
	var go2rtcCalls []string
	go2rtcServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		go2rtcCalls = append(go2rtcCalls, r.Method+" "+r.URL.String())
		switch r.URL.Path {
		case "/api/streams":
			if r.Method != http.MethodPut {
				t.Fatalf("method=%s, want PUT", r.Method)
			}
			if r.URL.Query().Get("name") != "device-SERIAL-1" {
				t.Fatalf("unexpected stream name %q", r.URL.Query().Get("name"))
			}
			if r.URL.Query().Get("src") != "rtsp://adapter.local:8556/device-SERIAL-1" {
				t.Fatalf("unexpected source %q", r.URL.Query().Get("src"))
			}
			w.WriteHeader(http.StatusOK)
		case "/api/webrtc":
			if r.Method != http.MethodPost {
				t.Fatalf("method=%s, want POST", r.Method)
			}
			if r.URL.Query().Get("src") != "device-SERIAL-1" {
				t.Fatalf("unexpected webrtc src %q", r.URL.Query().Get("src"))
			}
			writeJSON(w, http.StatusOK, map[string]string{"type": "answer", "sdp": "v=0 answer"})
		default:
			http.NotFound(w, r)
		}
	}))
	defer go2rtcServer.Close()
	server := NewServerWithWebRTC(
		"127.0.0.1:0",
		manager,
		go2rtc.New(go2rtc.Config{
			BaseURL:      go2rtcServer.URL,
			RTSPTemplate: "rtsp://adapter.local:8556/{stream_raw}",
		}),
		logger,
	)
	server.stopGrace = 0

	create := httptest.NewRequest(
		http.MethodPost,
		"/v1/webrtc/sessions",
		strings.NewReader(`{"serial":"SERIAL-1","viewer_id":"viewer-1","ttl_seconds":120,"profile":"degraded","max_fps":1,"max_width":320,"bitrate":150000}`),
	)
	createRes := httptest.NewRecorder()
	server.routes().ServeHTTP(createRes, create)

	if createRes.Code != http.StatusAccepted {
		t.Fatalf("create status=%d body=%s", createRes.Code, createRes.Body.String())
	}
	var created struct {
		ID         string        `json:"id"`
		StreamName string        `json:"stream_name"`
		Scrcpy     scrcpy.Status `json:"scrcpy"`
	}
	if err := json.Unmarshal(createRes.Body.Bytes(), &created); err != nil {
		t.Fatal(err)
	}
	if created.StreamName != "device-SERIAL-1" {
		t.Fatalf("stream=%q", created.StreamName)
	}
	if !created.Scrcpy.OwnsScrcpy {
		t.Fatalf("unexpected scrcpy status: %+v", created.Scrcpy)
	}

	heartbeat := httptest.NewRequest(
		http.MethodPost,
		"/v1/webrtc/sessions/"+created.ID+"/heartbeat",
		strings.NewReader(`{"ttl_seconds":120}`),
	)
	heartbeatRes := httptest.NewRecorder()
	server.routes().ServeHTTP(heartbeatRes, heartbeat)
	if heartbeatRes.Code != http.StatusOK {
		t.Fatalf("heartbeat status=%d body=%s", heartbeatRes.Code, heartbeatRes.Body.String())
	}
	if !strings.Contains(heartbeatRes.Body.String(), `"ok":true`) {
		t.Fatalf("heartbeat body=%s", heartbeatRes.Body.String())
	}

	answer := httptest.NewRequest(
		http.MethodPost,
		"/v1/webrtc/sessions/"+created.ID+"/answer",
		strings.NewReader(`{"type":"offer","sdp":"v=0 offer"}`),
	)
	answerRes := httptest.NewRecorder()
	server.routes().ServeHTTP(answerRes, answer)

	if answerRes.Code != http.StatusOK {
		t.Fatalf("answer status=%d body=%s", answerRes.Code, answerRes.Body.String())
	}
	if !strings.Contains(answerRes.Body.String(), "v=0 answer") {
		t.Fatalf("answer body=%s", answerRes.Body.String())
	}
	if len(go2rtcCalls) != 2 {
		t.Fatalf("go2rtc calls=%v", go2rtcCalls)
	}

	closeReq := httptest.NewRequest(http.MethodDelete, "/v1/webrtc/sessions/"+created.ID, nil)
	closeRes := httptest.NewRecorder()
	server.routes().ServeHTTP(closeRes, closeReq)
	if closeRes.Code != http.StatusOK {
		t.Fatalf("close status=%d", closeRes.Code)
	}
	if _, ok := manager.Status("SERIAL-1"); ok {
		t.Fatal("expected stream to stop after last WebRTC session closes")
	}
}

func TestWebRTCObserveOnlySessionKeepsScrcpyControlSocketForKeyframes(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	manager := scrcpy.NewManagerWithLauncher(fakePublisher{}, fakeLauncher{}, logger)
	server := NewServerWithWebRTC(
		"127.0.0.1:0",
		manager,
		go2rtc.New(go2rtc.Config{}),
		logger,
	)
	defer manager.Close()

	create := httptest.NewRequest(
		http.MethodPost,
		"/v1/webrtc/sessions",
		strings.NewReader(`{"serial":"SERIAL-1","viewer_id":"viewer-1","control":false}`),
	)
	createRes := httptest.NewRecorder()
	server.routes().ServeHTTP(createRes, create)

	if createRes.Code != http.StatusAccepted {
		t.Fatalf("create status=%d body=%s", createRes.Code, createRes.Body.String())
	}
	status, ok := manager.Status("SERIAL-1")
	if !ok {
		t.Fatal("expected stream status")
	}
	if !status.Control {
		t.Fatal("expected internal scrcpy control socket for keyframe requests")
	}
}

func TestWebRTCSessionCloseKeepsScrcpyWarmDuringTransientSwitch(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	manager := scrcpy.NewManagerWithLauncher(fakePublisher{}, fakeLauncher{}, logger)
	server := NewServerWithWebRTC(
		"127.0.0.1:0",
		manager,
		go2rtc.New(go2rtc.Config{}),
		logger,
	)
	server.stopGrace = 30 * time.Millisecond
	defer manager.Close()

	firstID := createWebRTCSessionForTest(t, server, "SERIAL-1", "viewer-1")
	closeReq := httptest.NewRequest(http.MethodDelete, "/v1/webrtc/sessions/"+firstID, nil)
	closeRes := httptest.NewRecorder()
	server.routes().ServeHTTP(closeRes, closeReq)
	if closeRes.Code != http.StatusOK {
		t.Fatalf("close status=%d", closeRes.Code)
	}
	if _, ok := manager.Status("SERIAL-1"); !ok {
		t.Fatal("expected stream to remain warm during stop grace")
	}

	_ = createWebRTCSessionForTest(t, server, "SERIAL-1", "viewer-2")
	time.Sleep(60 * time.Millisecond)
	if _, ok := manager.Status("SERIAL-1"); !ok {
		t.Fatal("expected new session to cancel pending stop")
	}
}

func createWebRTCSessionForTest(t *testing.T, server *Server, serial string, viewerID string) string {
	t.Helper()
	create := httptest.NewRequest(
		http.MethodPost,
		"/v1/webrtc/sessions",
		strings.NewReader(`{"serial":"`+serial+`","viewer_id":"`+viewerID+`","ttl_seconds":120,"profile":"degraded","max_fps":1,"max_width":320,"bitrate":150000}`),
	)
	createRes := httptest.NewRecorder()
	server.routes().ServeHTTP(createRes, create)
	if createRes.Code != http.StatusAccepted {
		t.Fatalf("create status=%d body=%s", createRes.Code, createRes.Body.String())
	}
	var created struct {
		ID string `json:"id"`
	}
	if err := json.Unmarshal(createRes.Body.Bytes(), &created); err != nil {
		t.Fatal(err)
	}
	if created.ID == "" {
		t.Fatal("expected session id")
	}
	return created.ID
}

type fakeLauncher struct{}

func (fakeLauncher) Start(context.Context, scrcpy.StartRequest) (*scrcpy.LaunchedServer, error) {
	return &scrcpy.LaunchedServer{Serial: "SERIAL-1", Host: "127.0.0.1", Port: 27183}, nil
}
