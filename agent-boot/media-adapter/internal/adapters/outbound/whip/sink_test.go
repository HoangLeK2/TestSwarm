package whip

import (
	"bytes"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/bluenviron/gortsplib/v5/pkg/format/rtph264"
	"github.com/pion/rtcp"
	"github.com/pion/rtp"
	"github.com/pion/webrtc/v4"
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
		w.Header().Set("Location", "/session/abc")
		w.WriteHeader(http.StatusCreated)
		_, _ = w.Write([]byte("v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\n"))
	}))
	defer server.Close()

	sink := NewSink(Config{}, "SERIAL-1", server.URL, nil, nil, nil)
	answer, sessionURL, err := sink.exchange("v=0\r\noffer\r\n")
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
	if want := server.URL + "/session/abc"; sessionURL != want {
		t.Fatalf("session URL=%q, want %q", sessionURL, want)
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
	if _, _, err := NewSink(Config{}, "S", rejecting.URL, nil, nil, nil).exchange("v=0"); err == nil {
		t.Fatal("expected an error for a rejected WHIP offer")
	} else if !strings.Contains(err.Error(), "stream not found") {
		t.Fatalf("error=%v, want the server's explanation", err)
	}

	empty := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusCreated)
	}))
	defer empty.Close()
	if _, _, err := NewSink(Config{}, "S", empty.URL, nil, nil, nil).exchange("v=0"); err == nil {
		t.Fatal("expected an error for an empty WHIP answer")
	}
}

func TestCloseDeletesTheWHIPSessionResource(t *testing.T) {
	var deletes atomic.Int64
	var deleteAuthenticated atomic.Bool
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.Method {
		case http.MethodDelete:
			deletes.Add(1)
			user, password, ok := r.BasicAuth()
			deleteAuthenticated.Store(ok && user == "farm" && password == "secret")
			w.WriteHeader(http.StatusOK)
		case http.MethodPost:
			w.Header().Set("Location", "http://"+r.Host+"/session/abc")
			w.WriteHeader(http.StatusCreated)
			_, _ = w.Write([]byte("v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\n"))
		default:
			w.WriteHeader(http.StatusMethodNotAllowed)
		}
	}))
	defer server.Close()

	endpoint := strings.Replace(server.URL, "http://", "http://farm:secret@", 1)
	sink := NewSink(Config{Timeout: time.Second}, "SERIAL-1", endpoint, nil, nil, nil)
	_, sessionURL, err := sink.exchange("v=0\r\n")
	if err != nil {
		t.Fatalf("exchange: %v", err)
	}
	sink.sessionURL = sessionURL
	sink.Close()

	if got := deletes.Load(); got != 1 {
		t.Fatalf("DELETE requests=%d, want 1", got)
	}
	if !deleteAuthenticated.Load() {
		t.Fatal("WHIP session DELETE did not preserve endpoint authentication")
	}
}

func TestSinkPublishesOnlyAfterPeerConnectionIsConnected(t *testing.T) {
	received := make(chan *rtp.Packet, 1)
	var deletes atomic.Int64
	var keyframeRequests atomic.Int64
	var serverState atomic.Value
	var answerSize atomic.Int64
	var serverPC *webrtc.PeerConnection
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodDelete {
			deletes.Add(1)
			w.WriteHeader(http.StatusOK)
			return
		}
		if r.Method != http.MethodPost {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}

		offer, err := io.ReadAll(r.Body)
		if err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		api, err := newAPI()
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		pc, err := api.NewPeerConnection(webrtc.Configuration{})
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		serverPC = pc
		pc.OnConnectionStateChange(func(state webrtc.PeerConnectionState) {
			serverState.Store(state.String())
		})
		pc.OnTrack(func(track *webrtc.TrackRemote, _ *webrtc.RTPReceiver) {
			packet, _, readErr := track.ReadRTP()
			if readErr == nil {
				received <- packet
			}
		})
		if err := pc.SetRemoteDescription(webrtc.SessionDescription{
			Type: webrtc.SDPTypeOffer,
			SDP:  string(offer),
		}); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		answer, err := pc.CreateAnswer(nil)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		gathered := webrtc.GatheringCompletePromise(pc)
		if err := pc.SetLocalDescription(answer); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		<-gathered
		answerSDP := pc.LocalDescription().SDP
		answerSize.Store(int64(len(answerSDP)))
		w.Header().Set("Content-Type", "application/sdp")
		w.Header().Set("Location", "/session/local-canary")
		w.WriteHeader(http.StatusCreated)
		_, _ = w.Write([]byte(answerSDP))
	}))
	defer server.Close()
	defer func() {
		if serverPC != nil {
			_ = serverPC.Close()
		}
	}()

	var logs bytes.Buffer
	logger := slog.New(slog.NewTextHandler(&logs, nil))
	sink := NewSink(Config{Timeout: 3 * time.Second, RedialBackoff: time.Hour},
		"SERIAL-LOCAL", server.URL, nil, func() { keyframeRequests.Add(1) }, logger)
	packet := &rtp.Packet{
		Header:  rtp.Header{Version: 2, PayloadType: 96, SequenceNumber: 7, Timestamp: 9000, Marker: true},
		Payload: []byte{0x41, 0x01},
	}
	if err := sink.WriteRTP(packet); err != nil {
		t.Fatalf("publish packet: %v", err)
	}
	// A real source keeps producing after ICE reaches Connected: P-frames
	// first, then the keyframe the connect callback asked for. Only the
	// keyframe may reach the receiver first — anything before it has no
	// reference and paints green. Several keyframe packets so the test does
	// not depend on the first SRTP packet racing the receiver track callback.
	for i := 1; i <= 3; i++ {
		if err := sink.WriteRTP(packet); err != nil {
			t.Fatalf("publish P-frame %d: %v", i, err)
		}
		time.Sleep(20 * time.Millisecond)
	}
	for i := 1; i <= 5; i++ {
		keyframe := &rtp.Packet{
			Header:  rtp.Header{Version: 2, PayloadType: 96, Timestamp: 18000, Marker: true},
			Payload: []byte{0x67, 0x42, 0x00, 0x0a},
		}
		if err := sink.WriteRTP(keyframe); err != nil {
			t.Fatalf("publish keyframe %d: %v", i, err)
		}
		time.Sleep(20 * time.Millisecond)
	}
	select {
	case got := <-received:
		if got.PayloadType != packet.PayloadType {
			t.Fatalf("payload type=%d, want %d", got.PayloadType, packet.PayloadType)
		}
		if !startsKeyframe(got.Payload) {
			t.Fatalf("receiver's first packet %x is not the keyframe; P-frames leaked before it", got.Payload)
		}
	case <-time.After(3 * time.Second):
		t.Fatalf("connected WHIP peer did not receive RTP; server_state=%v answer_size=%d logs=%s",
			serverState.Load(), answerSize.Load(), logs.String())
	}
	if got := keyframeRequests.Load(); got != 1 {
		t.Fatalf("keyframe requests after WHIP connect=%d, want exactly 1", got)
	}

	sink.Close()
	if got := deletes.Load(); got != 1 {
		t.Fatalf("session DELETE requests=%d, want 1", got)
	}
}

// TestGo2RTCWHIPIntegration is an opt-in local canary against a real go2rtc.
// It stays skipped in the normal suite because it needs a separately started
// process. Example:
//
//	GO2RTC_WHIP_TEST_ENDPOINT='http://127.0.0.1:11984/api/webrtc?dst=local-canary' \
//	GO2RTC_STREAM_TEST_URL='http://127.0.0.1:11984/api/streams?src=local-canary' \
//	go test ./internal/adapters/outbound/whip -run TestGo2RTCWHIPIntegration
func TestGo2RTCWHIPIntegration(t *testing.T) {
	endpoint := strings.TrimSpace(os.Getenv("GO2RTC_WHIP_TEST_ENDPOINT"))
	streamURL := strings.TrimSpace(os.Getenv("GO2RTC_STREAM_TEST_URL"))
	if endpoint == "" || streamURL == "" {
		t.Skip("set GO2RTC_WHIP_TEST_ENDPOINT and GO2RTC_STREAM_TEST_URL for the local go2rtc canary")
	}

	var keyframeRequests atomic.Int64
	sink := NewSink(Config{
		Timeout:       5 * time.Second,
		RedialBackoff: time.Hour,
		RedialMax:     time.Hour,
	}, "SERIAL-GO2RTC-CANARY", endpoint, func() { keyframeRequests.Add(1) }, nil, nil)
	defer sink.Close()

	packet := &rtp.Packet{
		Header: rtp.Header{
			Version:        2,
			PayloadType:    96,
			SequenceNumber: 1,
			Timestamp:      3000,
			SSRC:           0x12345678,
			Marker:         true,
		},
		Payload: []byte{0x65, 0x88, 0x84},
	}
	// Keep the publisher alive past go2rtc's two-second PLI ticker. The source
	// must continue flowing while those synthetic PLIs remain local to the sink.
	for i := 0; i < 150; i++ {
		// An SPS-led keyframe every ten frames, P-frames between: the sink
		// holds everything until the first keyframe after connect.
		packet.Payload = []byte{0x41, 0x9a, 0x02}
		if i%10 == 0 {
			packet.Payload = []byte{0x67, 0x42, 0x00, 0x0a}
		}
		if err := sink.WriteRTP(packet); err != nil {
			t.Fatalf("publish packet %d: %v", i, err)
		}
		packet.SequenceNumber++
		packet.Timestamp += 3000
		time.Sleep(20 * time.Millisecond)
	}

	// The farm declares every stream with a placeholder source before the
	// adapter pushes, so the WHIP session is one producer among others.
	state := readGo2RTCStreamState(t, streamURL)
	producer, found := webrtcProducer(state)
	if !found || !strings.Contains(producer.Protocol, "udp") {
		t.Fatalf("go2rtc producers=%+v, want one WebRTC over UDP", state.Producers)
	}
	if producer.BytesRecv == 0 {
		t.Fatalf("go2rtc producer received no RTP: %+v", producer)
	}
	if got := keyframeRequests.Load(); got != 0 {
		t.Fatalf("go2rtc periodic PLI reached the encoder callback %d times", got)
	}

	sink.Close()
	deadline := time.Now().Add(2 * time.Second)
	for {
		if _, found := webrtcProducer(readGo2RTCStreamState(t, streamURL)); !found {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("WHIP session remained in go2rtc after Sink.Close")
		}
		time.Sleep(25 * time.Millisecond)
	}
}

type go2RTCProducer struct {
	FormatName string `json:"format_name"`
	Protocol   string `json:"protocol"`
	BytesRecv  int    `json:"bytes_recv"`
}

type go2RTCStreamState struct {
	Producers []go2RTCProducer `json:"producers"`
}

func webrtcProducer(state go2RTCStreamState) (go2RTCProducer, bool) {
	for _, producer := range state.Producers {
		if producer.FormatName == "webrtc" {
			return producer, true
		}
	}
	return go2RTCProducer{}, false
}

func readGo2RTCStreamState(t *testing.T, streamURL string) go2RTCStreamState {
	t.Helper()
	client := &http.Client{Timeout: 2 * time.Second}
	response, err := client.Get(streamURL)
	if err != nil {
		t.Fatalf("read go2rtc stream state: %v", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("go2rtc stream API returned %s", response.Status)
	}
	var state go2RTCStreamState
	if err := json.NewDecoder(io.LimitReader(response.Body, 1<<20)).Decode(&state); err != nil {
		t.Fatalf("decode go2rtc stream state: %v", err)
	}
	return state
}

// go2rtc sends PLI every two seconds for every passive WebRTC producer whether
// or not a viewer lost the picture. Forwarding that ticker to the phone would
// continuously reset MediaCodec. FIR is an explicit full-refresh request.
func TestHandleRTCPForwardsFIRButNotPeriodicPLI(t *testing.T) {
	var calls atomic.Int64
	sink := NewSink(Config{}, "SERIAL-1", "http://example/whip", func() { calls.Add(1) }, nil, nil)

	for _, tc := range []struct {
		name   string
		packet rtcp.Packet
		want   int64
	}{
		{"pli", &rtcp.PictureLossIndication{MediaSSRC: 1}, 0},
		{"fir", &rtcp.FullIntraRequest{MediaSSRC: 1, FIR: []rtcp.FIREntry{{SSRC: 1}}}, 1},
		{"receiver report", &rtcp.ReceiverReport{SSRC: 1}, 0},
	} {
		calls.Store(0)
		sendRTCP(t, sink, tc.packet)
		if got := calls.Load(); got != tc.want {
			t.Errorf("%s: keyframe requests=%d, want %d", tc.name, got, tc.want)
		}
	}
}

// go2rtc has no jitter buffer, so a NACK is a picture it already painted
// wrong. The sink must ask for exactly one IDR per loss, hold P-frames until
// it arrives instead of feeding the smear, and ignore go2rtc's ~100ms repeats
// of the same NACK as well as NACKs the keyframe has already repaired.
func TestNACKHoldsPFramesUntilTheRepairKeyframe(t *testing.T) {
	var calls atomic.Int64
	sink := NewSink(Config{}, "SERIAL-1", "http://example/whip", func() { calls.Add(1) }, nil, nil)
	key, delta := encodedFrames(t)
	now := time.Now()
	send := func(packets []*rtp.Packet) (sent []uint16) {
		for _, packet := range packets {
			clone := packet.Clone()
			if sink.admit(clone, now) {
				sent = append(sent, clone.SequenceNumber)
			}
		}
		return sent
	}
	nack := func(seq uint16) int64 {
		calls.Store(0)
		sendRTCP(t, sink, &rtcp.TransportLayerNack{MediaSSRC: 1, Nacks: []rtcp.NackPair{{PacketID: seq}}})
		return calls.Load()
	}

	first := send(key)
	send(delta)
	if len(first) != len(key) || first[0] != 0 {
		t.Fatalf("keyframe sent as %v, want %d packets from seq 0", first, len(key))
	}
	lost := first[len(first)-1]
	if got := nack(lost); got != 1 {
		t.Fatalf("new loss: keyframe requests=%d, want 1", got)
	}
	if got := nack(lost); got != 0 {
		t.Fatalf("repeated NACK: keyframe requests=%d, want 0", got)
	}
	if sent := send(delta); len(sent) != 0 {
		t.Fatalf("P-frame after loss went out as %v; it paints over a broken reference", sent)
	}
	repair := send(key)
	if len(repair) != len(key) {
		t.Fatalf("repair keyframe held back: sent %v", repair)
	}
	// Held packets were never numbered, so go2rtc sees no gap to NACK.
	if want := first[len(first)-1] + uint16(len(delta)) + 1; repair[0] != want {
		t.Fatalf("repair keyframe starts at seq %d, want %d (no gap)", repair[0], want)
	}
	if sent := send(delta); len(sent) != len(delta) {
		t.Fatalf("P-frame after repair held back: sent %v", sent)
	}
	if got := nack(repair[0] - 1); got != 0 {
		t.Fatalf("NACK from before the repair keyframe: keyframe requests=%d, want 0", got)
	}
	if got := nack(repair[0]); got != 1 {
		t.Fatalf("loss inside the new keyframe: keyframe requests=%d, want 1", got)
	}
}

// If the IDR never arrives, a smeared moving picture beats a frozen one.
func TestKeyframeHoldGivesUp(t *testing.T) {
	sink := NewSink(Config{}, "SERIAL-1", "http://example/whip", nil, nil, nil)
	_, delta := encodedFrames(t)
	now := time.Now()
	sink.waitKey, sink.waitSince = true, now
	if sink.admit(delta[0].Clone(), now.Add(keyframeWaitMax/2)) {
		t.Fatal("P-frame admitted while the repair IDR is still due")
	}
	if !sink.admit(delta[0].Clone(), now.Add(keyframeWaitMax)) {
		t.Fatal("hold never released after keyframeWaitMax")
	}
}

func TestStartsKeyframeMatchesTheLanePacketizer(t *testing.T) {
	key, delta := encodedFrames(t)
	if !startsKeyframe(key[0].Payload) {
		t.Fatalf("first keyframe packet %x not recognised", key[0].Payload[:4])
	}
	for i, packet := range append(key[1:], delta...) {
		if startsKeyframe(packet.Payload) {
			t.Fatalf("packet %d (%x) mistaken for a keyframe start", i, packet.Payload[:2])
		}
	}
}

// encodedFrames packetises a keyframe the way the lane does (SPS and PPS
// prepended, rtph264 at the lane's 1200-byte payload limit) plus one P-frame.
func encodedFrames(t *testing.T) (key []*rtp.Packet, delta []*rtp.Packet) {
	t.Helper()
	encoder := &rtph264.Encoder{PayloadType: 96, PacketizationMode: 1, PayloadMaxSize: 1200}
	if err := encoder.Init(); err != nil {
		t.Fatalf("encoder: %v", err)
	}
	sps := []byte{0x67, 0x42, 0x00, 0x0a, 0xf8, 0x41, 0xa2}
	pps := []byte{0x68, 0xce, 0x38, 0x80}
	idr := append([]byte{0x65}, bytes.Repeat([]byte{0x88}, 4000)...)
	pFrame := append([]byte{0x41}, bytes.Repeat([]byte{0x9a}, 2500)...)
	key, err := encoder.Encode([][]byte{sps, pps, idr})
	if err != nil {
		t.Fatalf("encode keyframe: %v", err)
	}
	delta, err = encoder.Encode([][]byte{pFrame})
	if err != nil {
		t.Fatalf("encode P-frame: %v", err)
	}
	return key, delta
}

func sendRTCP(t *testing.T, sink *Sink, packet rtcp.Packet) {
	t.Helper()
	raw, err := rtcp.Marshal([]rtcp.Packet{packet})
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	sink.handleRTCP(raw)
}

func TestHandleRTCPIgnoresGarbage(t *testing.T) {
	var calls atomic.Int64
	sink := NewSink(Config{}, "S", "http://example/whip", func() { calls.Add(1) }, nil, nil)
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
		"SERIAL-1", refusing.URL, nil, nil, nil)
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

func TestWHIPRetryDelayBacksOffWithStableJitter(t *testing.T) {
	base := time.Second
	maximum := 30 * time.Second
	seed := uint32(12345)
	first := whipRetryDelay(base, maximum, 0, seed)
	second := whipRetryDelay(base, maximum, 1, seed)
	last := whipRetryDelay(base, maximum, 20, seed)

	if first < 800*time.Millisecond || first > 1200*time.Millisecond {
		t.Fatalf("first retry=%s, want 0.8s..1.2s", first)
	}
	if second < 1600*time.Millisecond || second > 2400*time.Millisecond {
		t.Fatalf("second retry=%s, want 1.6s..2.4s", second)
	}
	if last > maximum {
		t.Fatalf("capped retry=%s, maximum=%s", last, maximum)
	}
	if again := whipRetryDelay(base, maximum, 1, seed); again != second {
		t.Fatalf("retry jitter changed: first=%s second=%s", second, again)
	}
}

func TestStaleTrackFailureDoesNotResetReplacementConnection(t *testing.T) {
	oldTrack, err := webrtc.NewTrackLocalStaticRTP(
		webrtc.RTPCodecCapability{MimeType: webrtc.MimeTypeH264, ClockRate: 90000},
		"video", "old",
	)
	if err != nil {
		t.Fatalf("old track: %v", err)
	}
	newTrack, err := webrtc.NewTrackLocalStaticRTP(
		webrtc.RTPCodecCapability{MimeType: webrtc.MimeTypeH264, ClockRate: 90000},
		"video", "new",
	)
	if err != nil {
		t.Fatalf("new track: %v", err)
	}

	sink := NewSink(Config{}, "SERIAL-1", "http://example/whip", nil, nil, nil)
	sink.track = newTrack
	sink.reset(oldTrack, io.ErrClosedPipe)

	if sink.track != newTrack {
		t.Fatal("a delayed failure from the old track cleared the replacement track")
	}
	if !sink.nextDial.IsZero() || sink.retryAttempt != 0 {
		t.Fatalf("stale failure changed retry state: next=%s attempt=%d", sink.nextDial, sink.retryAttempt)
	}
}

func TestConcurrentPacketsStartOnlyOneWHIPHandshake(t *testing.T) {
	var attempts atomic.Int64
	started := make(chan struct{})
	release := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if attempts.Add(1) == 1 {
			close(started)
		}
		<-release
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer server.Close()

	sink := NewSink(Config{Timeout: 2 * time.Second, RedialBackoff: time.Hour},
		"SERIAL-1", server.URL, nil, nil, nil)
	defer sink.Close()
	packet := &rtp.Packet{Header: rtp.Header{Version: 2, PayloadType: 96}, Payload: []byte{0x41}}

	done := make(chan struct{}, 8)
	go func() {
		_ = sink.WriteRTP(packet)
		done <- struct{}{}
	}()
	<-started
	for i := 1; i < cap(done); i++ {
		go func() {
			_ = sink.WriteRTP(packet)
			done <- struct{}{}
		}()
	}
	time.Sleep(50 * time.Millisecond)
	close(release)
	for i := 0; i < cap(done); i++ {
		<-done
	}

	if got := attempts.Load(); got != 1 {
		t.Fatalf("concurrent signalling attempts=%d, want 1", got)
	}
}

func TestWHIPHandshakesAreLimitedAcrossDevices(t *testing.T) {
	var attempts atomic.Int64
	started := make(chan struct{}, 3)
	release := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		attempts.Add(1)
		started <- struct{}{}
		<-release
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer server.Close()

	packet := &rtp.Packet{Header: rtp.Header{Version: 2, PayloadType: 96}, Payload: []byte{0x41}}
	done := make(chan struct{}, 3)
	sinks := make([]*Sink, 0, 3)
	for i := 0; i < 3; i++ {
		sink := NewSink(Config{Timeout: 2 * time.Second, RedialBackoff: time.Hour},
			"SERIAL-"+strconv.Itoa(i), server.URL, nil, nil, nil)
		sinks = append(sinks, sink)
		go func() {
			_ = sink.WriteRTP(packet)
			done <- struct{}{}
		}()
	}
	defer func() {
		for _, sink := range sinks {
			sink.Close()
		}
	}()

	<-started
	<-started
	select {
	case <-started:
		close(release)
		t.Fatal("a third WHIP handshake started while both global slots were occupied")
	case <-time.After(100 * time.Millisecond):
	}
	close(release)
	for i := 0; i < 3; i++ {
		<-done
	}
	if got := attempts.Load(); got != 2 {
		t.Fatalf("signalling attempts=%d, want 2", got)
	}
}

func TestWriteRTPNeverLogsWHIPCredentials(t *testing.T) {
	refusing := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer refusing.Close()

	endpoint := strings.Replace(refusing.URL, "http://", "http://whip-user:whip-secret@", 1)
	var logs bytes.Buffer
	logger := slog.New(slog.NewTextHandler(&logs, nil))
	sink := NewSink(Config{Timeout: time.Second, RedialBackoff: time.Hour},
		"SERIAL-1", endpoint, nil, nil, logger)
	defer sink.Close()

	packet := &rtp.Packet{Header: rtp.Header{Version: 2, PayloadType: 96}, Payload: []byte{0x41}}
	if err := sink.WriteRTP(packet); err != nil {
		t.Fatalf("write during cold start: %v", err)
	}
	if got := logs.String(); strings.Contains(got, "whip-user") || strings.Contains(got, "whip-secret") {
		t.Fatalf("WHIP credentials leaked into logs: %s", got)
	}
}
