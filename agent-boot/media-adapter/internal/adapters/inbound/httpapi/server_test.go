package httpapi

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"

	"devicefarm/media-adapter/internal/adapters/outbound/go2rtc"
	"devicefarm/media-adapter/internal/adapters/outbound/rtspserver"
	"devicefarm/media-adapter/internal/adapters/scrcpy"
	"devicefarm/media-adapter/internal/domain/stream"
)

type fakePublisher struct{}

func (fakePublisher) Publish(context.Context, stream.EncodedPacket) error {
	return nil
}

type fakePublisherStats struct {
	stats rtspserver.PublisherStats
}

func (f fakePublisherStats) Stats() rtspserver.PublisherStats {
	return f.stats
}

func TestHandlePublisherStats(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	manager := scrcpy.NewManager(fakePublisher{}, logger)
	server := NewServer("127.0.0.1:0", manager, logger)
	server.SetPublisherStatsProvider(fakePublisherStats{
		stats: rtspserver.PublisherStats{
			OfferedPackets:    10,
			EnqueuedPackets:   9,
			QueueDrops:        1,
			RTPPacketsWritten: 8,
			ActiveLanes:       2,
		},
	})
	defer manager.Close()

	req := httptest.NewRequest(http.MethodGet, "/v1/rtsp/publisher/status", nil)
	res := httptest.NewRecorder()

	server.routes().ServeHTTP(res, req)

	if res.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", res.Code, res.Body.String())
	}
	var body rtspserver.PublisherStats
	if err := json.Unmarshal(res.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if body.OfferedPackets != 10 || body.QueueDrops != 1 || body.ActiveLanes != 2 {
		t.Fatalf("unexpected publisher stats: %+v", body)
	}
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

func TestHandleStartPassesVideoEncoder(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	launcher := recordingLauncher{started: make(chan scrcpy.StartRequest, 1)}
	manager := scrcpy.NewManagerWithLauncher(fakePublisher{}, launcher, logger)
	server := NewServer("127.0.0.1:0", manager, logger)
	defer manager.Close()

	req := httptest.NewRequest(
		http.MethodPost,
		"/v1/scrcpy/streams/SERIAL-1/start",
		strings.NewReader(`{"host":"127.0.0.1","port":27183,"control":true,"owns_scrcpy":true,"video_codec":"h264","video_encoder":"c2.android.avc.encoder"}`),
	)
	res := httptest.NewRecorder()

	server.routes().ServeHTTP(res, req)

	if res.Code != http.StatusAccepted {
		t.Fatalf("status=%d body=%s", res.Code, res.Body.String())
	}
	select {
	case got := <-launcher.started:
		if got.VideoEncoder != "c2.android.avc.encoder" {
			t.Fatalf("video encoder=%q", got.VideoEncoder)
		}
	case <-time.After(time.Second):
		t.Fatal("timed out waiting for launcher start")
	}
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

func (fakeLauncher) Start(ctx context.Context, req scrcpy.StartRequest) (*scrcpy.LaunchedServer, error) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return nil, err
	}
	go func() {
		<-ctx.Done()
		_ = ln.Close()
	}()
	go serveFakeScrcpy(ctx, ln, req.Control)
	_, portText, err := net.SplitHostPort(ln.Addr().String())
	if err != nil {
		_ = ln.Close()
		return nil, err
	}
	port, err := strconv.Atoi(portText)
	if err != nil {
		_ = ln.Close()
		return nil, err
	}
	return &scrcpy.LaunchedServer{Serial: req.Serial, Host: "127.0.0.1", Port: port}, nil
}

type recordingLauncher struct {
	started chan scrcpy.StartRequest
}

func (l recordingLauncher) Start(ctx context.Context, req scrcpy.StartRequest) (*scrcpy.LaunchedServer, error) {
	l.started <- req
	return fakeLauncher{}.Start(ctx, req)
}

func serveFakeScrcpy(ctx context.Context, ln net.Listener, control bool) {
	connCount := 1
	if control {
		connCount = 2
	}
	for i := 0; i < connCount; i++ {
		conn, err := ln.Accept()
		if err != nil {
			return
		}
		if i == 0 {
			go serveFakeScrcpyVideo(conn)
			continue
		}
		go func() {
			defer conn.Close()
			_, _ = io.Copy(io.Discard, conn)
		}()
	}
	<-ctx.Done()
	_ = ln.Close()
}

func serveFakeScrcpyVideo(conn net.Conn) {
	defer conn.Close()
	handshake := make([]byte, 1+64+4+12)
	copy(handshake[1+64:], []byte("h264"))
	binary.BigEndian.PutUint32(handshake[1+64+4:1+64+8], 0x80000000)
	binary.BigEndian.PutUint32(handshake[1+64+8:1+64+12], 320)
	binary.BigEndian.PutUint32(handshake[1+64+12:1+64+16], 640)
	if _, err := conn.Write(handshake); err != nil {
		return
	}
	payload := []byte{0x00, 0x00, 0x00, 0x01, 0x65}
	header := make([]byte, 12)
	binary.BigEndian.PutUint64(header[0:8], 0x2000000000000000)
	binary.BigEndian.PutUint32(header[8:12], uint32(len(payload)))
	_, _ = conn.Write(append(header, payload...))
	time.Sleep(25 * time.Millisecond)
}
