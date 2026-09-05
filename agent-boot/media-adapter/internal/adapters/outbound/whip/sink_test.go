package whip

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/pion/rtcp"
	"github.com/pion/rtp"
)

func TestHandlesSelectsTransportByScheme(t *testing.T) {
	for _, tc := range []struct {
		template string
		want     bool
	}{
		{"http://go2rtc:1984/api/webrtc?dst={stream_raw}", true},
		{"https://go2rtc.example/api/webrtc?dst={stream_raw}", true},
		{"HTTP://go2rtc:1984/api/webrtc?dst=x", true},
		{"  http://go2rtc:1984/api/webrtc  ", true},
		{"rtsp://go2rtc:8554/{stream_raw}", false},
		{"", false},
	} {
		if got := Handles(tc.template); got != tc.want {
			t.Errorf("Handles(%q)=%v, want %v", tc.template, got, tc.want)
		}
	}
}

func TestExchangePostsSDPOfferAndReturnsAnswer(t *testing.T) {
	var gotBody, gotType string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		gotBody = string(body)
		gotType = r.Header.Get("Content-Type")
		w.WriteHeader(http.StatusCreated)
		_, _ = w.Write([]byte("v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\n"))
	}))
	defer server.Close()

	sink := NewSink(Config{}, "SERIAL-1", server.URL, nil, nil)
	answer, err := sink.exchange("v=0\r\noffer\r\n")
	if err != nil {
		t.Fatalf("exchange: %v", err)
	}
	if !strings.Contains(gotBody, "offer") {
		t.Fatalf("server received body %q, want the offer SDP", gotBody)
	}
	if gotType != "application/sdp" {
		t.Fatalf("content-type=%q, want application/sdp", gotType)
	}
	if !strings.HasPrefix(answer, "v=0") {
		t.Fatalf("answer=%q, want an SDP", answer)
	}
}

func TestExchangeReportsRejectionAndEmptyAnswer(t *testing.T) {
	rejecting := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
		_, _ = w.Write([]byte("stream not found"))
	}))
	defer rejecting.Close()
	// go2rtc refuses a dst it has not been told about, so this is the shape of a
	// misconfigured stream name rather than a transport fault.
	if _, err := NewSink(Config{}, "S", rejecting.URL, nil, nil).exchange("v=0"); err == nil {
		t.Fatal("expected an error for a rejected WHIP offer")
	} else if !strings.Contains(err.Error(), "stream not found") {
		t.Fatalf("error=%v, want the server's explanation", err)
	}

	empty := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusCreated)
	}))
	defer empty.Close()
	if _, err := NewSink(Config{}, "S", empty.URL, nil, nil).exchange("v=0"); err == nil {
		t.Fatal("expected an error for an empty WHIP answer")
	}
}

// PLI and FIR both mean the receiver has lost the picture. Everything else on
// the RTCP channel — receiver reports, and the NACKs the interceptor chain has
// already answered with a retransmission — must not reach the device.
func TestHandleRTCPOnlyReactsToPictureLoss(t *testing.T) {
	var calls atomic.Int64
	sink := NewSink(Config{}, "SERIAL-1", "http://example/whip", func() { calls.Add(1) }, nil)

	for _, tc := range []struct {
		name   string
		packet rtcp.Packet
		want   int64
	}{
		{"pli", &rtcp.PictureLossIndication{MediaSSRC: 1}, 1},
		{"fir", &rtcp.FullIntraRequest{MediaSSRC: 1, FIR: []rtcp.FIREntry{{SSRC: 1}}}, 1},
		{"receiver report", &rtcp.ReceiverReport{SSRC: 1}, 0},
		{"nack", &rtcp.TransportLayerNack{MediaSSRC: 1, Nacks: []rtcp.NackPair{{PacketID: 7}}}, 0},
	} {
		raw, err := rtcp.Marshal([]rtcp.Packet{tc.packet})
		if err != nil {
			t.Fatalf("%s: marshal: %v", tc.name, err)
		}
		calls.Store(0)
		sink.handleRTCP(raw)
		if got := calls.Load(); got != tc.want {
			t.Errorf("%s: keyframe requests=%d, want %d", tc.name, got, tc.want)
		}
	}
}

func TestHandleRTCPIgnoresGarbage(t *testing.T) {
	var calls atomic.Int64
	sink := NewSink(Config{}, "S", "http://example/whip", func() { calls.Add(1) }, nil)
	sink.handleRTCP([]byte{0xff, 0x00, 0x13})
	if calls.Load() != 0 {
		t.Fatal("malformed RTCP must not reach the device")
	}
}

// A packet offered before the peer connection is up is not a write failure.
// Counting it as one would make every stream start its life reporting errors,
// and the backoff must keep a dead endpoint from being dialled per packet.
func TestWriteRTPBeforeConnectIsNotAnErrorAndBacksOff(t *testing.T) {
	var attempts atomic.Int64
	refusing := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		attempts.Add(1)
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer refusing.Close()

	sink := NewSink(Config{Timeout: 2 * time.Second, RedialBackoff: time.Hour},
		"SERIAL-1", refusing.URL, nil, nil)
	defer sink.Close()

	packet := &rtp.Packet{Header: rtp.Header{Version: 2, PayloadType: 96}, Payload: []byte{0x41}}
	for i := 0; i < 5; i++ {
		if err := sink.WriteRTP(packet); err != nil {
			t.Fatalf("write %d returned an error during cold start: %v", i, err)
		}
	}
	if got := attempts.Load(); got != 1 {
		t.Fatalf("signalling attempts=%d, want 1 — the redial backoff is not holding", got)
	}
}
