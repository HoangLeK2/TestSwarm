package rtspserver

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"os"
	"strings"
	"testing"
	"time"

	"sync"
	"sync/atomic"

	"devicefarm/media-adapter/internal/domain/stream"
	"github.com/bluenviron/gortsplib/v5"
	"github.com/bluenviron/gortsplib/v5/pkg/base"
	"github.com/bluenviron/gortsplib/v5/pkg/description"
	"github.com/bluenviron/gortsplib/v5/pkg/format"
	"github.com/pion/rtp"
)

func TestNormalizePathMatchesGortsplibLeadingSlash(t *testing.T) {
	if got := normalizePath("/device-SERIAL-1"); got != "device-SERIAL-1" {
		t.Fatalf("path=%q", got)
	}
	if got := normalizePath("device-SERIAL-1"); got != "device-SERIAL-1" {
		t.Fatalf("path=%q", got)
	}
}

func TestOnPlayRequestsKeyframeForStreamSerial(t *testing.T) {
	var requested string
	handler := &rtspHandler{
		states: map[string]*streamState{
			"device-SERIAL-1": {serial: "SERIAL-1"},
		},
		requestKeyframe: func(serial string) bool {
			requested = serial
			return true
		},
	}

	response, err := handler.OnPlay(&gortsplib.ServerHandlerOnPlayCtx{
		Path: "/device-SERIAL-1",
	})
	if err != nil {
		t.Fatal(err)
	}
	if response.StatusCode != base.StatusOK {
		t.Fatalf("status=%d", response.StatusCode)
	}
	if requested != "SERIAL-1" {
		t.Fatalf("requested serial=%q", requested)
	}
}

func TestPublisherConfigKeepsSmallRealtimeQueue(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(os.Stdout, nil))
	publisher := New(Config{
		RTSPAddress:    "127.0.0.1:0",
		QueueMax:       4,
		StalePacketAge: 120 * time.Millisecond,
		InputFPS:       15,
		WriteQueueSize: 64,
	}, logger)
	t.Cleanup(func() {
		_ = publisher.Close(context.Background())
	})

	if publisher.cfg.QueueMax != 4 {
		t.Fatalf("queue max=%d, want 4", publisher.cfg.QueueMax)
	}
}

func TestPublisherDefaultsRemoteRTSPTimeoutToFiveSeconds(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(os.Stdout, nil))
	publisher := New(Config{RTSPAddress: "127.0.0.1:0"}, logger)
	t.Cleanup(func() {
		_ = publisher.Close(context.Background())
	})

	if publisher.cfg.RemoteTimeout != 5*time.Second {
		t.Fatalf("remote timeout=%s, want 5s", publisher.cfg.RemoteTimeout)
	}
}

func TestPublisherStatsCountQueueDrops(t *testing.T) {
	publisher := &Publisher{
		cfg: Config{QueueMax: 2, StalePacketAge: time.Second, InputFPS: 15},
	}
	lane := &serialLane{
		publisher: publisher,
		queue:     make(chan queuedPacket, 2),
	}

	for i := 0; i < 3; i++ {
		lane.offer(stream.EncodedPacket{Serial: "SERIAL-1", Payload: []byte{0, 0, 0, 1, 0x41}})
	}

	stats := publisher.Stats()
	if stats.EnqueuedPackets != 2 {
		t.Fatalf("enqueued=%d, want 2", stats.EnqueuedPackets)
	}
	if stats.QueueDrops != 1 {
		t.Fatalf("queue drops=%d, want 1", stats.QueueDrops)
	}
}

func TestPublisherStatsCountKeyframeEvictions(t *testing.T) {
	publisher := &Publisher{
		cfg: Config{QueueMax: 2, StalePacketAge: time.Second, InputFPS: 15},
	}
	lane := &serialLane{
		publisher: publisher,
		queue:     make(chan queuedPacket, 2),
	}

	lane.offer(stream.EncodedPacket{Serial: "SERIAL-1", Payload: []byte{0, 0, 0, 1, 0x41}})
	lane.offer(stream.EncodedPacket{Serial: "SERIAL-1", Payload: []byte{0, 0, 0, 1, 0x41}})
	lane.offer(stream.EncodedPacket{Serial: "SERIAL-1", Payload: []byte{0, 0, 0, 1, 0x65}, IsKey: true})

	stats := publisher.Stats()
	if stats.QueueEvictions != 2 {
		t.Fatalf("queue evictions=%d, want 2", stats.QueueEvictions)
	}
	if stats.EnqueuedPackets != 3 {
		t.Fatalf("enqueued=%d, want 3", stats.EnqueuedPackets)
	}
}

func TestPublisherStatsCountsActiveRTSPStatesNotRetainedLanes(t *testing.T) {
	publisher := &Publisher{
		lanes: map[string]*serialLane{
			"SERIAL-1": {},
		},
		rtsp: &rtspHandler{
			states: map[string]*streamState{},
		},
	}

	if stats := publisher.Stats(); stats.ActiveLanes != 0 {
		t.Fatalf("active lanes=%d, want 0", stats.ActiveLanes)
	}

	publisher.rtsp.states["device-SERIAL-1"] = &streamState{serial: "SERIAL-1"}

	if stats := publisher.Stats(); stats.ActiveLanes != 1 {
		t.Fatalf("active lanes=%d, want 1", stats.ActiveLanes)
	}
}

// Superseded by TestRemoteOverflowDrainsQueueAndRequestsKeyframe, which asserts
// the same "never block the lane" invariant plus the two things that actually
// matter now: the backlog goes whole rather than one packet at a time, and the
// device is asked for a keyframe.

// recordingServer accepts an ANNOUNCE/RECORD session so writeRemote can be
// driven against a real peer. A fake client cannot catch the bug this guards:
// the panic came from gortsplib's own bookkeeping of setupped medias.
type recordingServer struct {
	stream *gortsplib.ServerStream
	server *gortsplib.Server
	got    chan struct{}
	once   sync.Once
}

func (s *recordingServer) OnConnOpen(*gortsplib.ServerHandlerOnConnOpenCtx)         {}
func (s *recordingServer) OnConnClose(*gortsplib.ServerHandlerOnConnCloseCtx)       {}
func (s *recordingServer) OnSessionOpen(*gortsplib.ServerHandlerOnSessionOpenCtx)   {}
func (s *recordingServer) OnSessionClose(*gortsplib.ServerHandlerOnSessionCloseCtx) {}

func (s *recordingServer) OnAnnounce(ctx *gortsplib.ServerHandlerOnAnnounceCtx) (*base.Response, error) {
	s.stream = &gortsplib.ServerStream{Server: s.server, Desc: ctx.Description}
	return &base.Response{StatusCode: base.StatusOK}, nil
}

func (s *recordingServer) OnSetup(*gortsplib.ServerHandlerOnSetupCtx) (*base.Response, *gortsplib.ServerStream, error) {
	return &base.Response{StatusCode: base.StatusOK}, nil, nil
}

func (s *recordingServer) OnRecord(*gortsplib.ServerHandlerOnRecordCtx) (*base.Response, error) {
	return &base.Response{StatusCode: base.StatusOK}, nil
}

func (s *recordingServer) OnPacketsLost(*gortsplib.ServerHandlerOnPacketsLostCtx) {}

func TestRTSPSinkUsesTheAnnouncedMediaNotTheLocalOne(t *testing.T) {
	// Regression: the sink announces a freshly built description.Media, but the
	// write path used to hand gortsplib the local server's media instead.
	// The client has no entry for that pointer, so WritePacketRTPWithNTP
	// dereferenced nil and panicked — killing the whole adapter process on the
	// first published packet. Publishing had never actually run before, so no
	// existing test covered it.
	// Grab a free port rather than pinning one: a pinned port leaves the test
	// unrunnable until whatever still holds it exits.
	probe, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("reserve port: %v", err)
	}
	addr := probe.Addr().String()
	probe.Close()

	handler := &recordingServer{got: make(chan struct{})}
	server := &gortsplib.Server{
		Handler:     handler,
		RTSPAddress: addr,
	}
	handler.server = server
	if err := server.Start(); err != nil {
		t.Fatalf("start rtsp server: %v", err)
	}
	defer server.Close()

	forma := &format.H264{
		PayloadTyp:        96,
		SPS:               []byte{0x67, 0x42, 0x00, 0x0a, 0xf8, 0x41, 0xa2},
		PPS:               []byte{0x68, 0xce, 0x38, 0x80},
		PacketizationMode: 1,
	}
	// Deliberately a different pointer than the one the sink announces: this is
	// exactly the mismatch that used to panic.
	localMedia := &description.Media{Type: description.MediaTypeVideo, Formats: []format.Format{forma}}
	sink := newRTSPSink(
		"rtsp://"+addr+"/device-SERIAL-1",
		2*time.Second,
		forma,
		slog.New(slog.NewTextHandler(os.Stderr, nil)),
	)
	sink.retryAttempt = 4
	state := &streamState{
		serial:    "SERIAL-1",
		media:     localMedia,
		format:    forma,
		remoteURL: sink.url,
		remote:    sink,
	}

	packet := &rtp.Packet{
		Header:  rtp.Header{Version: 2, PayloadType: 96, SequenceNumber: 1, Marker: true},
		Payload: []byte{0x65, 0x88, 0x84, 0x00},
	}
	if err := state.writeRemote(packet); err != nil {
		t.Fatalf("writeRemote returned error: %v", err)
	}
	if sink.media == nil {
		t.Fatal("announced media not retained; writes cannot reference it")
	}
	if sink.media == state.media {
		t.Fatal("sink must write to the announced media, not the local server's")
	}
	if sink.retryAttempt != 0 {
		t.Fatalf("successful publish kept retry attempt=%d, want reset to 0", sink.retryAttempt)
	}

	sink.writePacket = func(*gortsplib.Client, *description.Media, *rtp.Packet) error {
		return errors.New("forced write failure")
	}
	started := time.Now()
	if err := sink.WriteRTP(packet); err == nil {
		t.Fatal("forced packet write unexpectedly succeeded")
	}
	if sink.retryAttempt != 1 {
		t.Fatalf("write failure retry attempt=%d, want 1", sink.retryAttempt)
	}
	retryIn := sink.nextDial.Sub(started)
	if retryIn < 800*time.Millisecond || retryIn > 1200*time.Millisecond {
		t.Fatalf("write failure retry=%s, want 800ms..1.2s", retryIn)
	}
	sink.Close()
}

func TestRemoteRetryDelayGrowsWithJitterAndCaps(t *testing.T) {
	tests := []struct {
		attempt int
		min     time.Duration
		max     time.Duration
	}{
		{attempt: 0, min: 800 * time.Millisecond, max: 1200 * time.Millisecond},
		{attempt: 1, min: 1600 * time.Millisecond, max: 2400 * time.Millisecond},
		{attempt: 2, min: 3200 * time.Millisecond, max: 4800 * time.Millisecond},
		{attempt: 3, min: 6400 * time.Millisecond, max: 9600 * time.Millisecond},
		{attempt: 4, min: 10 * time.Second, max: remoteRetryMax},
		{attempt: 20, min: 10 * time.Second, max: remoteRetryMax},
	}

	for _, tt := range tests {
		got := remoteRetryDelay(tt.attempt, 0x12345678)
		if got < tt.min || got > tt.max {
			t.Fatalf("attempt %d delay=%s, want %s..%s", tt.attempt, got, tt.min, tt.max)
		}
	}

	first := remoteRetryDelay(0, remoteRetrySeed("rtsp://farm:secret@host:8554/device-A"))
	second := remoteRetryDelay(0, remoteRetrySeed("rtsp://farm:secret@host:8554/device-B"))
	if first == second {
		t.Fatalf("different streams received identical initial jitter: %s", first)
	}

	for _, attempt := range []int{4, 20} {
		counts := make(map[time.Duration]int)
		for i := 0; i < 100; i++ {
			rawURL := fmt.Sprintf("rtsp://farm:secret@host:8554/device-%03d", i)
			counts[remoteRetryDelay(attempt, remoteRetrySeed(rawURL))]++
		}
		if len(counts) < 20 {
			t.Fatalf("attempt %d produced only %d distinct fleet delays", attempt, len(counts))
		}
		if counts[remoteRetryMax] > 10 {
			t.Fatalf("attempt %d collapsed %d streams onto the 15s cap", attempt, counts[remoteRetryMax])
		}
	}
}

func TestRTSPSinkFailedConnectEscalatesRetryBackoff(t *testing.T) {
	probe, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("reserve port: %v", err)
	}
	addr := probe.Addr().String()
	probe.Close()

	forma := &format.H264{PayloadTyp: 96, PacketizationMode: 1}
	sink := newRTSPSink("rtsp://"+addr+"/device-SERIAL-1", 20*time.Millisecond, forma, nil)

	started := time.Now()
	if sink.ensure() {
		t.Fatal("closed RTSP endpoint unexpectedly connected")
	}
	first := sink.nextDial.Sub(started)
	if first < 800*time.Millisecond || first > 1200*time.Millisecond {
		t.Fatalf("first retry=%s, want 800ms..1.2s", first)
	}
	if sink.retryAttempt != 1 {
		t.Fatalf("retry attempt=%d, want 1", sink.retryAttempt)
	}

	sink.nextDial = time.Time{}
	started = time.Now()
	if sink.ensure() {
		t.Fatal("closed RTSP endpoint unexpectedly connected on retry")
	}
	second := sink.nextDial.Sub(started)
	if second < 1600*time.Millisecond || second > 2400*time.Millisecond {
		t.Fatalf("second retry=%s, want 1.6s..2.4s", second)
	}
	if sink.retryAttempt != 2 {
		t.Fatalf("retry attempt=%d, want 2", sink.retryAttempt)
	}
}

func TestRemoteURLForLogRedactsCredentials(t *testing.T) {
	got := remoteURLForLog("rtsp://farm:super-secret@host.example:8554/device-SERIAL-1")
	want := "rtsp://host.example:8554/device-SERIAL-1"
	if got != want {
		t.Fatalf("log URL=%q, want %q", got, want)
	}
	if got := remoteURLForLog("not a URL"); got != "[invalid remote URL]" {
		t.Fatalf("invalid log URL=%q", got)
	}
}

func TestRemoteWriteErrorLogRedactsCredentials(t *testing.T) {
	var output bytes.Buffer
	logger := slog.New(slog.NewTextHandler(&output, nil))
	state := &streamState{
		serial:    "SERIAL-1",
		remoteURL: "rtsp://farm:super-secret@host.example:8554/device-SERIAL-1",
	}

	state.logRemoteWriteError(logger, errors.New("forced write failure"))
	got := output.String()
	if strings.Contains(got, "super-secret") || strings.Contains(got, "farm@") {
		t.Fatalf("remote write log leaked credentials: %s", got)
	}
	if !strings.Contains(got, "rtsp://host.example:8554/device-SERIAL-1") {
		t.Fatalf("remote write log lost safe target context: %s", got)
	}
}

func TestNextTimestampUsesMicrosecondsOn90kHzClock(t *testing.T) {
	// scrcpy PTS is in microseconds. Ticks are us*90/1000; the code once used
	// us*90, stamping frames 1000x further apart than reality (100 seconds
	// between frames at 10 fps, measured on a real device). Receivers pace
	// playback from these values, so the stream could never be smooth.
	lane := &serialLane{tick: 90000 / 15}

	const frameUs = 66_667 // 15 fps
	base := lane.nextTimestamp(1_000_000)
	second := lane.nextTimestamp(1_000_000 + frameUs)
	third := lane.nextTimestamp(1_000_000 + 2*frameUs)

	if got := second - base; got != 6000 {
		t.Fatalf("one frame at 15fps = %d ticks, want 6000 (%.3fs vs 0.067s)",
			got, float64(got)/90000)
	}
	if got := third - base; got != 12000 {
		t.Fatalf("two frames = %d ticks, want 12000", got)
	}

	// A second of wall clock must advance the clock by one second, with no
	// drift from per-frame rounding.
	lane2 := &serialLane{tick: 90000 / 15}
	start := lane2.nextTimestamp(500_000)
	var pts uint64 = 500_000
	for i := 0; i < 15; i++ {
		pts += frameUs
		lane2.nextTimestamp(pts)
	}
	elapsed := lane2.nextTimestamp(pts) - start
	if elapsed < 89_900 || elapsed > 90_100 {
		t.Fatalf("15 frames advanced %d ticks, want ~90000 (one second)", elapsed)
	}
}

func TestNextTimestampRebasesWhenDeviceClockRestarts(t *testing.T) {
	// A restarted scrcpy session reuses the lane and its PTS starts over. The
	// clock must keep moving forward instead of jumping backwards.
	lane := &serialLane{tick: 90000 / 15}
	lane.nextTimestamp(10_000_000)
	before := lane.nextTimestamp(10_066_667)
	after := lane.nextTimestamp(1_000) // device restarted
	if after <= before {
		t.Fatalf("timestamp went backwards after restart: %d -> %d", before, after)
	}
}

// idrRecorder records keyframe requests. requestIDR issues them on their own
// goroutine — a device control socket write has no deadline and must not stall
// the lane — so tests wait on the count rather than reading it inline.
type idrRecorder struct {
	mu      sync.Mutex
	serials []string
}

func (r *idrRecorder) request(serial string) bool {
	r.mu.Lock()
	r.serials = append(r.serials, serial)
	r.mu.Unlock()
	return true
}

func (r *idrRecorder) count() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return len(r.serials)
}

func (r *idrRecorder) waitFor(t *testing.T, want int) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if r.count() >= want {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatalf("keyframe requests=%d, want %d", r.count(), want)
}

func newTestPublisher(cfg Config) (*Publisher, *idrRecorder) {
	recorder := &idrRecorder{}
	return &Publisher{
		cfg:     cfg,
		lanes:   make(map[string]*serialLane),
		lastIDR: make(map[string]time.Time),
		idr:     recorder.request,
		rtsp: &rtspHandler{
			streams: make(map[string]*gortsplib.ServerStream),
			states:  make(map[string]*streamState),
		},
	}, recorder
}

func addTestLane(publisher *Publisher, serial string) *serialLane {
	lane := &serialLane{
		serial:    serial,
		publisher: publisher,
		queue:     make(chan queuedPacket, publisher.cfg.QueueMax),
		done:      make(chan struct{}),
	}
	publisher.mu.Lock()
	publisher.lanes[serial] = lane
	publisher.mu.Unlock()
	return lane
}

func pFrame() stream.EncodedPacket {
	return stream.EncodedPacket{Serial: "SERIAL-1", Payload: []byte{0, 0, 0, 1, 0x41}}
}

// A dropped P-frame breaks the reference chain for every frame after it, and on
// codec level >= 4 scrcpy schedules no IDR of its own. Without this request the
// viewer stays on a frozen picture until it reconnects.
func TestQueueDropRequestsKeyframe(t *testing.T) {
	publisher, recorder := newTestPublisher(Config{
		QueueMax: 2, StalePacketAge: time.Second, InputFPS: 15, IDRMinInterval: time.Hour,
	})
	lane := addTestLane(publisher, "SERIAL-1")

	for i := 0; i < 3; i++ {
		lane.offer(pFrame())
	}

	recorder.waitFor(t, 1)
	if got := recorder.serials[0]; got != "SERIAL-1" {
		t.Fatalf("requested serial=%q, want SERIAL-1", got)
	}
	if drops := publisher.Stats().PerSerial["SERIAL-1"].QueueDrops; drops != 1 {
		t.Fatalf("per-serial queue drops=%d, want 1", drops)
	}
}

// RESET_VIDEO is a full MediaCodec reconfigure on the phone, and
// MediaCodec.configure() is where Exynos encoders abort. An unbounded request
// rate would kill the devices the safe profile exists to rescue.
func TestKeyframeRequestRateLimited(t *testing.T) {
	publisher, recorder := newTestPublisher(Config{
		QueueMax: 2, StalePacketAge: time.Second, InputFPS: 15, IDRMinInterval: time.Hour,
	})
	lane := addTestLane(publisher, "SERIAL-1")

	for i := 0; i < 100; i++ {
		lane.offer(pFrame())
	}

	recorder.waitFor(t, 1)
	time.Sleep(50 * time.Millisecond)
	if got := recorder.count(); got != 1 {
		t.Fatalf("keyframe requests=%d, want exactly 1 — the rate-limit gate is open", got)
	}
	if drops := publisher.Stats().PerSerial["SERIAL-1"].QueueDrops; drops != 98 {
		t.Fatalf("per-serial queue drops=%d, want 98", drops)
	}
}

// The browser can drive RequestKeyframeGated on every stall it sees, so it must
// share the same gate as every internal caller. Ungated, a viewer stuck in a
// stall loop would reconfigure MediaCodec continuously — the exact thing
// TestKeyframeRequestRateLimited exists to prevent, reachable from the internet.
func TestGatedKeyframeSharesTheRateLimit(t *testing.T) {
	publisher, recorder := newTestPublisher(Config{
		QueueMax: 2, StalePacketAge: time.Second, InputFPS: 15, IDRMinInterval: time.Hour,
	})
	addTestLane(publisher, "SERIAL-1")

	if !publisher.RequestKeyframeGated("SERIAL-1") {
		t.Fatal("first gated request was not sent")
	}
	for i := 0; i < 10; i++ {
		if publisher.RequestKeyframeGated("SERIAL-1") {
			t.Fatalf("request %d passed the gate", i+2)
		}
	}
	if got := recorder.count(); got != 1 {
		t.Fatalf("keyframe requests=%d, want exactly 1 — the gate is open to viewers", got)
	}
	if got := publisher.Stats().PerSerial["SERIAL-1"].IDRRequests; got != 1 {
		t.Fatalf("per-serial idr requests=%d, want 1", got)
	}
	// A different device has its own budget: one phone's stall must not silence
	// another phone's repair.
	addTestLane(publisher, "SERIAL-2")
	if !publisher.RequestKeyframeGated("SERIAL-2") {
		t.Fatal("a second device was blocked by the first device's gate")
	}
	if publisher.RequestKeyframeGated("") {
		t.Fatal("an empty serial passed the gate")
	}
}

func TestStaleDropRequestsKeyframe(t *testing.T) {
	publisher, recorder := newTestPublisher(Config{
		QueueMax: 4, StalePacketAge: 10 * time.Millisecond, InputFPS: 15,
		IDRMinInterval: time.Hour, LaneIdle: time.Hour,
	})
	lane := addTestLane(publisher, "SERIAL-1")
	go lane.run()
	t.Cleanup(func() { close(lane.done) })

	lane.queue <- queuedPacket{
		payload:  []byte{0, 0, 0, 1, 0x41},
		received: time.Now().Add(-time.Second),
	}

	recorder.waitFor(t, 1)
	if drops := publisher.Stats().PerSerial["SERIAL-1"].StaleDrops; drops != 1 {
		t.Fatalf("per-serial stale drops=%d, want 1", drops)
	}
}

// Overflow discards the whole backlog rather than the oldest packet. Evicting
// one packet cuts the access unit being written in half, which is strictly
// worse than a gap: the decoder rejects the frame either way, and a truncated
// keyframe also destroys the recovery.
func TestRemoteOverflowDrainsQueueAndRequestsKeyframe(t *testing.T) {
	publisher, recorder := newTestPublisher(Config{
		QueueMax: 2, StalePacketAge: time.Second, InputFPS: 15,
		RemoteQueueSize: 4, IDRMinInterval: time.Hour,
	})
	addTestLane(publisher, "SERIAL-1")
	state := &streamState{
		serial:      "SERIAL-1",
		remoteURL:   "rtsp://127.0.0.1:1/device-SERIAL-1",
		remoteQueue: make(chan *rtp.Packet, 4),
		remoteDone:  make(chan struct{}),
		stats:       &publisher.stats,
		onOverflow:  func() { publisher.laneDrop("SERIAL-1", dropRemoteOverflow) },
	}

	for i := 0; i < 5; i++ {
		state.enqueueRemote(nil, &rtp.Packet{
			Header:  rtp.Header{SequenceNumber: uint16(i)},
			Payload: []byte{byte(i)},
		})
	}

	if got := len(state.remoteQueue); got != 1 {
		t.Fatalf("remote queue len=%d, want 1 — the backlog should be gone, not trimmed", got)
	}
	if surviving := <-state.remoteQueue; surviving.SequenceNumber != 4 {
		t.Fatalf("surviving packet seq=%d, want 4 (the newest)", surviving.SequenceNumber)
	}
	recorder.waitFor(t, 1)
	if resyncs := publisher.Stats().PerSerial["SERIAL-1"].RemoteResyncs; resyncs != 1 {
		t.Fatalf("per-serial remote resyncs=%d, want 1", resyncs)
	}
}

// The drain above only protects a keyframe if the queue can hold one. Every
// deployment shipped RemoteQueueSize=32 against a ~85-packet keyframe, so the
// drain discarded the frame it existed to save and the IDR it asked for came
// back oversized — a drop loop that ran with a perfectly healthy uplink.
// Customer .env files still carry 32, so the floor has to live here.
func TestNewFloorsRemoteQueueToHoldOneAccessUnit(t *testing.T) {
	publisher := New(Config{
		RTSPAddress:     "127.0.0.1:0",
		RemoteQueueSize: 32,
	}, slog.New(slog.NewTextHandler(os.Stderr, nil)))
	t.Cleanup(func() { _ = publisher.Close(context.Background()) })

	if got := publisher.cfg.RemoteQueueSize; got != minRemoteQueueSize {
		t.Fatalf("RemoteQueueSize=%d, want %d — 32 cannot hold one keyframe", got, minRemoteQueueSize)
	}
}

// A lane used to live until Publisher.Close, so every device that ever streamed
// kept a goroutine and a queue for the life of the process.
func TestLaneClosesAfterIdle(t *testing.T) {
	publisher, _ := newTestPublisher(Config{
		QueueMax: 2, StalePacketAge: time.Second, InputFPS: 15,
		IDRMinInterval: time.Hour, LaneIdle: 40 * time.Millisecond,
	})
	lane := addTestLane(publisher, "SERIAL-1")
	lane.counters.lastPacketUnix.Store(time.Now().Add(-time.Second).UnixMilli())
	go lane.run()

	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		publisher.mu.RLock()
		_, still := publisher.lanes["SERIAL-1"]
		publisher.mu.RUnlock()
		if !still {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatal("idle lane was never retired; its goroutine and queue leak for the process lifetime")
}

// Fleet-wide totals cannot answer the only question worth asking during an
// incident: which phone is dropping.
func TestPerSerialStatsIsolateDevices(t *testing.T) {
	publisher, _ := newTestPublisher(Config{
		QueueMax: 2, StalePacketAge: time.Second, InputFPS: 15, IDRMinInterval: time.Hour,
	})
	broken := addTestLane(publisher, "SERIAL-BROKEN")
	healthy := addTestLane(publisher, "SERIAL-OK")

	for i := 0; i < 5; i++ {
		broken.offer(pFrame())
	}
	healthy.offer(pFrame())

	stats := publisher.Stats()
	if got := stats.PerSerial["SERIAL-BROKEN"].QueueDrops; got != 3 {
		t.Fatalf("broken device queue drops=%d, want 3", got)
	}
	if got := stats.PerSerial["SERIAL-OK"].QueueDrops; got != 0 {
		t.Fatalf("healthy device queue drops=%d, want 0", got)
	}
	if stats.PerSerial["SERIAL-OK"].LastPacketUnix == 0 {
		t.Fatal("healthy device has no last-packet timestamp")
	}
}

// An explicit FIR asks for a full MediaCodec refresh. Even explicit remote
// feedback must pass through the same gate as a local drop so a noisy receiver
// cannot reconfigure the phone encoder continuously.
func TestRemoteFeedbackGoesThroughTheKeyframeRateLimit(t *testing.T) {
	publisher, recorder := newTestPublisher(Config{
		QueueMax: 2, StalePacketAge: time.Second, InputFPS: 15, IDRMinInterval: time.Hour,
	})
	addTestLane(publisher, "SERIAL-1")

	for i := 0; i < 30; i++ {
		publisher.laneDrop("SERIAL-1", dropRemoteFeedback)
	}

	recorder.waitFor(t, 1)
	time.Sleep(50 * time.Millisecond)
	if got := recorder.count(); got != 1 {
		t.Fatalf("keyframe requests=%d, want exactly 1", got)
	}
	// Nothing was dropped on this side, so no drop counter should move: the
	// peer reported its own loss.
	stats := publisher.Stats().PerSerial["SERIAL-1"]
	if stats.QueueDrops != 0 || stats.StaleDrops != 0 || stats.RemoteResyncs != 0 {
		t.Fatalf("remote feedback raised a local drop counter: %+v", stats)
	}
}

func TestNewRemoteSinkOverrideReplacesTheRTSPTransport(t *testing.T) {
	var gotSerial, gotURL string
	sink := &fakeRemoteSink{}
	publisher := New(Config{
		RTSPAddress:     "127.0.0.1:0",
		PublishTemplate: "http://go2rtc:1984/api/webrtc?dst={stream_raw}",
		NewRemoteSink: func(serial string, url string, onKeyframeNeeded func()) RemoteSink {
			gotSerial, gotURL = serial, url
			return sink
		},
	}, slog.New(slog.NewTextHandler(os.Stderr, nil)))
	t.Cleanup(func() { _ = publisher.Close(context.Background()) })

	state, err := publisher.ensureRTSPStream("SERIAL-1",
		[]byte{0x67, 0x42, 0x00, 0x0a, 0xf8, 0x41, 0xa2}, []byte{0x68, 0xce, 0x38, 0x80})
	if err != nil {
		t.Fatalf("ensureRTSPStream: %v", err)
	}
	if gotSerial != "SERIAL-1" {
		t.Fatalf("sink built for serial=%q", gotSerial)
	}
	if gotURL != "http://go2rtc:1984/api/webrtc?dst=device-SERIAL-1" {
		t.Fatalf("sink built for url=%q", gotURL)
	}
	if err := state.writeRemote(&rtp.Packet{Payload: []byte{0x41}}); err != nil {
		t.Fatalf("writeRemote: %v", err)
	}
	if sink.writes.Load() != 1 {
		t.Fatalf("sink writes=%d, want 1 — packets are not reaching the override", sink.writes.Load())
	}
}

type fakeRemoteSink struct {
	writes atomic.Int64
	closed atomic.Bool
}

func (f *fakeRemoteSink) WriteRTP(*rtp.Packet) error {
	f.writes.Add(1)
	return nil
}

func (f *fakeRemoteSink) Close() { f.closed.Store(true) }
