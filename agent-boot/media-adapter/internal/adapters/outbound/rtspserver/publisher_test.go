package rtspserver

import (
	"context"
	"log/slog"
	"net"
	"os"
	"testing"
	"time"

	"sync"

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

func TestRemoteRTSPQueueDropsInsteadOfBlockingLane(t *testing.T) {
	publisher := &Publisher{
		cfg: Config{
			QueueMax:        2,
			StalePacketAge:  time.Second,
			InputFPS:        15,
			RemoteQueueSize: 1,
			RemoteTimeout:   time.Millisecond,
		},
	}
	state := &streamState{
		serial:      "SERIAL-1",
		remoteURL:   "rtsp://127.0.0.1:1/device-SERIAL-1",
		remoteQueue: make(chan *rtp.Packet, 1),
		remoteDone:  make(chan struct{}),
		stats:       &publisher.stats,
	}
	packet := &rtp.Packet{Payload: []byte{0x01}}

	state.enqueueRemote(nil, packet)
	state.enqueueRemote(nil, packet)
	state.enqueueRemote(nil, packet)

	if queued := len(state.remoteQueue); queued != 1 {
		t.Fatalf("remote queue len=%d, want 1", queued)
	}
	if publisher.Stats().QueueEvictions == 0 {
		t.Fatal("expected remote queue eviction instead of blocking")
	}
}

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

func TestWriteRemoteUsesTheAnnouncedMediaNotTheLocalOne(t *testing.T) {
	// Regression: ensureRemote announces a freshly built description.Media,
	// but writeRemote used to hand gortsplib the local server's media instead.
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
	state := &streamState{
		serial: "SERIAL-1",
		// Deliberately a different pointer than the one ensureRemote announces:
		// this is exactly the mismatch that used to panic.
		media:         &description.Media{Type: description.MediaTypeVideo, Formats: []format.Format{forma}},
		format:        forma,
		remoteURL:     "rtsp://" + addr + "/device-SERIAL-1",
		remoteTimeout: 2 * time.Second,
	}

	packet := &rtp.Packet{
		Header:  rtp.Header{Version: 2, PayloadType: 96, SequenceNumber: 1, Marker: true},
		Payload: []byte{0x65, 0x88, 0x84, 0x00},
	}
	if err := state.writeRemote(slog.New(slog.NewTextHandler(os.Stderr, nil)), packet); err != nil {
		t.Fatalf("writeRemote returned error: %v", err)
	}
	if state.remoteMedia == nil {
		t.Fatal("remoteMedia not retained; writes cannot reference the announced media")
	}
	if state.remoteMedia == state.media {
		t.Fatal("remoteMedia must be the announced media, not the local server's")
	}
	state.closeRemote()
}
