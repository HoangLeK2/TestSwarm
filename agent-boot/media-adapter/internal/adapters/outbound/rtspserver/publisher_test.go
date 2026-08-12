package rtspserver

import (
	"context"
	"log/slog"
	"os"
	"testing"
	"time"

	"devicefarm/media-adapter/internal/domain/stream"
	"github.com/bluenviron/gortsplib/v5"
	"github.com/bluenviron/gortsplib/v5/pkg/base"
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
