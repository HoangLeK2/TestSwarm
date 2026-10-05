// Package whip publishes a device's H264 stream to go2rtc over WebRTC-HTTP
// Ingestion (WHIP) instead of RTSP ANNOUNCE/RECORD.
//
// Why this exists: RTSP gives a publisher no feedback channel. Over WebRTC,
// go2rtc negotiates nack (pkg/webrtc/api.go lists goog-remb, ccm fir, nack and
// nack pli) and its default interceptors send a NACK for every missing sequence
// number, which is a real per-loss signal.
//
// What a NACK cannot do here is trigger a useful retransmission. go2rtc has no
// jitter buffer: pkg/webrtc/conn.go hands each packet to the H264 depacketizer
// in arrival order, and pkg/h264/rtp.go RTPDepay never checks sequence numbers.
// A retransmission always lands after the frame's marker packet, so it is glued
// onto the NEXT frame and corrupts that one too. This sink therefore does not
// retransmit; it turns a new NACK into one gated IDR request, the only thing
// that repairs a broken H264 reference chain.
//
// What this deliberately does NOT rely on is go2rtc's PLI. go2rtc fires one every
// two seconds on an unconditional ticker (pkg/webrtc/conn.go), not on real loss,
// so it carries no information. Honouring each one would reset MediaCodec on
// every phone every two seconds, and MediaCodec.configure() is exactly where
// Exynos encoders abort. Periodic PLI is ignored.
//
// Cost of this path: RTSP publishing needs one outbound TCP connection and so
// survives any NAT. WHIP needs UDP to go2rtc's media port plus STUN, so a
// customer network that blocks UDP loses the stream entirely. RTSP remains the
// default and the fallback.
package whip

import (
	"bytes"
	"fmt"
	"hash/fnv"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/pion/interceptor"
	"github.com/pion/rtcp"
	"github.com/pion/rtp"
	"github.com/pion/webrtc/v4"
)

type Config struct {
	// ICEServers is the STUN list. Publishing happens from behind the customer's
	// NAT, so without a reflexive candidate the offer carries private addresses
	// only and ICE never completes.
	ICEServers []string
	// Timeout bounds ICE gathering and the signalling POST together.
	Timeout time.Duration
	// RedialBackoff is the wait after a failed connect before trying again.
	RedialBackoff time.Duration
	// RedialMax caps exponential reconnect delay during a shared outage.
	RedialMax time.Duration
}

// Two simultaneous ICE/signalling handshakes are enough to recover quickly
// without letting a shared outage turn every device into a concurrent dialer.
// A sink that cannot acquire a slot drops the current packet and tries again on
// a later packet; media lanes therefore never queue behind a fleet-wide dial.
var dialSlots = make(chan struct{}, 2)

func ConfigFromEnv() Config {
	servers := strings.Split(envDefault("MEDIA_ADAPTER_WHIP_ICE_SERVERS", "stun:stun.l.google.com:19302"), ",")
	cleaned := make([]string, 0, len(servers))
	for _, server := range servers {
		if trimmed := strings.TrimSpace(server); trimmed != "" {
			cleaned = append(cleaned, trimmed)
		}
	}
	return Config{
		ICEServers:    cleaned,
		Timeout:       time.Duration(envInt("MEDIA_ADAPTER_WHIP_TIMEOUT_MS", 5000)) * time.Millisecond,
		RedialBackoff: time.Duration(envInt("MEDIA_ADAPTER_WHIP_REDIAL_MS", 2000)) * time.Millisecond,
		RedialMax:     time.Duration(envInt("MEDIA_ADAPTER_WHIP_REDIAL_MAX_MS", 30000)) * time.Millisecond,
	}
}

// Handles reports whether a publish template names a WHIP endpoint rather than
// an RTSP one. Selection is by scheme so an operator switches transports by
// changing one URL, with no second flag to keep consistent with it.
func Handles(template string) bool {
	value := strings.ToLower(strings.TrimSpace(template))
	return strings.HasPrefix(value, "http://") || strings.HasPrefix(value, "https://")
}

type Sink struct {
	cfg              Config
	serial           string
	url              string
	logger           *slog.Logger
	onKeyframeNeeded func()
	onConnected      func()
	client           *http.Client

	mu           sync.Mutex
	pc           *webrtc.PeerConnection
	track        *webrtc.TrackLocalStaticRTP
	sessionURL   string
	connecting   bool
	nextDial     time.Time
	retryAttempt int
	retrySeed    uint32
	closed       bool

	// The sink numbers packets itself rather than passing the lane encoder's
	// sequence through. Packets held back while waiting for a keyframe must not
	// leave a gap — go2rtc would NACK it and the hold would re-arm forever — and
	// one counter across reconnects keeps "newer than" comparisons meaningful.
	seq uint16
	// waitKey holds P-frames back until the next keyframe. go2rtc forwards
	// whatever it gets, so a P-frame after a loss or before the first IDR is
	// painted by the browser as green smear; a held picture is the honest one.
	waitKey   bool
	waitSince time.Time
	// repaired is the newest sequence number whose loss is already handled,
	// either by a requested IDR or by a keyframe sent after it. go2rtc re-sends
	// the same NACK every ~100ms until the packet ages out of its log, so only
	// a NACK past this point is a new loss.
	repaired     uint16
	haveRepaired bool
}

// keyframeWaitMax bounds how long P-frames are held after a loss. The IDR it
// waits for is rate-gated by the publisher (IDRMinInterval, 3s by default) but
// guaranteed; if it still never comes — a wedged control socket — a smeared
// moving picture beats a frozen one.
//
// ponytail: fixed, not derived from IDRMinInterval; raise it together with
// that interval.
const keyframeWaitMax = 5 * time.Second

type peerConnection struct {
	pc         *webrtc.PeerConnection
	track      *webrtc.TrackLocalStaticRTP
	sessionURL string
	states     <-chan webrtc.PeerConnectionState
}

func NewSink(
	cfg Config,
	serial string,
	url string,
	onKeyframeNeeded func(),
	onConnected func(),
	logger *slog.Logger,
) *Sink {
	if cfg.Timeout <= 0 {
		cfg.Timeout = 5 * time.Second
	}
	if cfg.RedialBackoff <= 0 {
		cfg.RedialBackoff = 2 * time.Second
	}
	if cfg.RedialMax <= 0 {
		cfg.RedialMax = 30 * time.Second
	}
	if cfg.RedialMax < cfg.RedialBackoff {
		cfg.RedialMax = cfg.RedialBackoff
	}
	return &Sink{
		cfg:              cfg,
		serial:           serial,
		url:              url,
		logger:           logger,
		onKeyframeNeeded: onKeyframeNeeded,
		onConnected:      onConnected,
		client:           &http.Client{Timeout: cfg.Timeout},
		retrySeed:        whipRetrySeed(serial, url),
	}
}

func whipRetrySeed(serial string, rawURL string) uint32 {
	h := fnv.New32a()
	_, _ = h.Write([]byte(serial))
	_, _ = h.Write([]byte{0})
	_, _ = h.Write([]byte(whipURLForLog(rawURL)))
	return h.Sum32()
}

func whipRetryDelay(base time.Duration, maximum time.Duration, attempt int, seed uint32) time.Duration {
	if attempt < 0 {
		attempt = 0
	}
	if maximum < base {
		maximum = base
	}
	exponent := attempt
	if exponent > 6 {
		exponent = 6
	}
	delay := base << exponent
	maxBase := maximum * 100 / 120
	if delay > maxBase {
		delay = maxBase
	}
	mixed := seed + uint32(attempt)*0x9e3779b9
	mixed ^= mixed << 13
	mixed ^= mixed >> 17
	mixed ^= mixed << 5
	delay = delay * time.Duration(80+mixed%41) / 100
	if delay > maximum {
		return maximum
	}
	return delay
}

func (s *Sink) scheduleRetryLocked(now time.Time) {
	s.nextDial = now.Add(whipRetryDelay(s.cfg.RedialBackoff, s.cfg.RedialMax, s.retryAttempt, s.retrySeed))
	if s.retryAttempt < 30 {
		s.retryAttempt++
	}
}

// WriteRTP sends one packet, connecting on demand.
//
// A packet offered before the peer connection is up returns nil rather than an
// error: a cold start is not a write failure, and counting it as one would make
// every stream begin its life reporting errors.
func (s *Sink) WriteRTP(packet *rtp.Packet) error {
	track := s.ensure()
	if track == nil || !s.admit(packet, time.Now()) {
		return nil
	}
	if err := track.WriteRTP(packet); err != nil {
		s.reset(track, err)
		return err
	}
	return nil
}

func (s *Sink) Close() {
	s.mu.Lock()
	s.closed = true
	pc := s.pc
	sessionURL := s.sessionURL
	s.pc = nil
	s.track = nil
	s.sessionURL = ""
	s.mu.Unlock()
	if pc != nil {
		_ = pc.Close()
	}
	s.deleteSession(sessionURL)
}

func (s *Sink) deleteSession(sessionURL string) {
	if sessionURL == "" {
		return
	}
	request, err := http.NewRequest(http.MethodDelete, sessionURL, nil)
	if err != nil {
		return
	}
	response, err := s.client.Do(request)
	if err != nil {
		if s.logger != nil {
			s.logger.Warn("media adapter WHIP session cleanup failed",
				"serial", s.serial, "url", whipURLForLog(sessionURL), "error", err)
		}
		return
	}
	_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, 1<<20))
	_ = response.Body.Close()
	if response.StatusCode >= 400 && s.logger != nil {
		s.logger.Warn("media adapter WHIP session cleanup rejected",
			"serial", s.serial, "url", whipURLForLog(sessionURL), "status", response.StatusCode)
	}
}

func (s *Sink) ensure() *webrtc.TrackLocalStaticRTP {
	s.mu.Lock()
	if s.closed {
		s.mu.Unlock()
		return nil
	}
	if s.track != nil {
		track := s.track
		s.mu.Unlock()
		return track
	}
	if s.connecting {
		s.mu.Unlock()
		return nil
	}
	if now := time.Now(); now.Before(s.nextDial) {
		s.mu.Unlock()
		return nil
	}
	select {
	case dialSlots <- struct{}{}:
	default:
		s.mu.Unlock()
		return nil
	}
	s.connecting = true
	s.mu.Unlock()

	connection, err := s.connect()
	<-dialSlots
	if err != nil {
		s.mu.Lock()
		s.connecting = false
		s.scheduleRetryLocked(time.Now())
		s.mu.Unlock()
		if s.logger != nil {
			s.logger.Warn("media adapter WHIP publish not ready",
				"serial", s.serial, "url", whipURLForLog(s.url), "error", err)
		}
		return nil
	}

	s.mu.Lock()
	s.connecting = false
	if s.closed {
		s.mu.Unlock()
		_ = connection.pc.Close()
		s.deleteSession(connection.sessionURL)
		return nil
	}
	s.pc = connection.pc
	s.track = connection.track
	s.sessionURL = connection.sessionURL
	s.retryAttempt = 0
	s.nextDial = time.Time{}
	// A fresh receiver has no reference frame; hold P-frames until the IDR
	// requested by onConnected below arrives.
	s.waitKey, s.waitSince = true, time.Now()
	s.mu.Unlock()
	go s.watchConnection(connection.pc, connection.states)
	// The handshake can finish long after the lane's startup SPS/PPS and IDR
	// were offered, especially when a fleet shares the global dial slots. Those
	// packets are intentionally not queued while ICE is connecting, so request
	// one fresh keyframe after every successful connection. The publisher routes
	// this distinct connect callback past a rate gate that startup may already
	// have spent. Periodic go2rtc PLI remains ignored below; this is one encoder
	// refresh per connect, not one every two seconds.
	if s.onConnected != nil {
		s.onConnected()
	}
	if s.logger != nil {
		s.logger.Info("media adapter WHIP publishing", "serial", s.serial, "url", whipURLForLog(s.url))
	}
	return connection.track
}

func (s *Sink) reset(expected *webrtc.TrackLocalStaticRTP, cause error) {
	s.mu.Lock()
	// A delayed failure from an old track must not tear down a replacement
	// connection that another packet has already established.
	if s.track != expected {
		s.mu.Unlock()
		return
	}
	pc := s.pc
	sessionURL := s.sessionURL
	s.pc = nil
	s.track = nil
	s.sessionURL = ""
	s.scheduleRetryLocked(time.Now())
	s.mu.Unlock()
	if pc != nil {
		_ = pc.Close()
	}
	s.deleteSession(sessionURL)
	if s.logger != nil && cause != nil {
		s.logger.Warn("media adapter WHIP write failed, will redial",
			"serial", s.serial, "url", whipURLForLog(s.url), "error", cause)
	}
}

func (s *Sink) watchConnection(pc *webrtc.PeerConnection, states <-chan webrtc.PeerConnectionState) {
	for state := range states {
		switch state {
		case webrtc.PeerConnectionStateDisconnected, webrtc.PeerConnectionStateFailed:
			s.resetConnection(pc, fmt.Errorf("peer connection became %s", state.String()))
			return
		case webrtc.PeerConnectionStateClosed:
			return
		}
	}
}

func (s *Sink) resetConnection(expected *webrtc.PeerConnection, cause error) {
	s.mu.Lock()
	if s.pc != expected {
		s.mu.Unlock()
		return
	}
	pc := s.pc
	sessionURL := s.sessionURL
	s.pc = nil
	s.track = nil
	s.sessionURL = ""
	s.scheduleRetryLocked(time.Now())
	s.mu.Unlock()
	if pc != nil {
		_ = pc.Close()
	}
	s.deleteSession(sessionURL)
	if s.logger != nil {
		s.logger.Warn("media adapter WHIP connection lost, will redial",
			"serial", s.serial, "url", whipURLForLog(s.url), "error", cause)
	}
}

func whipURLForLog(rawURL string) string {
	parsed, err := url.Parse(rawURL)
	if err != nil || parsed.Scheme == "" || parsed.Host == "" {
		return "[invalid WHIP URL]"
	}
	parsed.User = nil
	return parsed.String()
}

func (s *Sink) connect() (*peerConnection, error) {
	api, err := newAPI()
	if err != nil {
		return nil, err
	}
	pc, err := api.NewPeerConnection(webrtc.Configuration{
		ICEServers: []webrtc.ICEServer{{URLs: s.cfg.ICEServers}},
	})
	if err != nil {
		return nil, err
	}
	states := make(chan webrtc.PeerConnectionState, 8)
	pc.OnConnectionStateChange(func(state webrtc.PeerConnectionState) {
		select {
		case states <- state:
		default:
		}
	})
	track, err := webrtc.NewTrackLocalStaticRTP(
		webrtc.RTPCodecCapability{MimeType: webrtc.MimeTypeH264, ClockRate: 90000},
		"video", "device-"+s.serial,
	)
	if err != nil {
		_ = pc.Close()
		return nil, err
	}
	sender, err := pc.AddTrack(track)
	if err != nil {
		_ = pc.Close()
		return nil, err
	}
	go s.readRTCP(sender)

	offer, err := pc.CreateOffer(nil)
	if err != nil {
		_ = pc.Close()
		return nil, err
	}
	// WHIP has no trickle: the single POST must carry every candidate, so wait
	// for gathering to finish before reading the local description back.
	gathered := webrtc.GatheringCompletePromise(pc)
	if err := pc.SetLocalDescription(offer); err != nil {
		_ = pc.Close()
		return nil, err
	}
	select {
	case <-gathered:
	case <-time.After(s.cfg.Timeout):
		_ = pc.Close()
		return nil, fmt.Errorf("ICE gathering timed out after %s", s.cfg.Timeout)
	}

	answer, sessionURL, err := s.exchange(pc.LocalDescription().SDP)
	if err != nil {
		_ = pc.Close()
		return nil, err
	}
	if err := pc.SetRemoteDescription(webrtc.SessionDescription{
		Type: webrtc.SDPTypeAnswer,
		SDP:  answer,
	}); err != nil {
		_ = pc.Close()
		s.deleteSession(sessionURL)
		return nil, err
	}

	timer := time.NewTimer(s.cfg.Timeout)
	defer timer.Stop()
	for {
		select {
		case state := <-states:
			switch state {
			case webrtc.PeerConnectionStateConnected:
				return &peerConnection{
					pc:         pc,
					track:      track,
					sessionURL: sessionURL,
					states:     states,
				}, nil
			case webrtc.PeerConnectionStateFailed, webrtc.PeerConnectionStateClosed:
				_ = pc.Close()
				s.deleteSession(sessionURL)
				return nil, fmt.Errorf("peer connection became %s before publishing", state.String())
			}
		case <-timer.C:
			_ = pc.Close()
			s.deleteSession(sessionURL)
			return nil, fmt.Errorf("peer connection timed out after %s", s.cfg.Timeout)
		}
	}
}

// readRTCP turns receiver feedback into keyframe requests.
func (s *Sink) readRTCP(sender *webrtc.RTPSender) {
	buf := make([]byte, 1500)
	for {
		n, _, err := sender.Read(buf)
		if err != nil {
			return
		}
		s.handleRTCP(buf[:n])
	}
}

// handleRTCP reports loss the receiver could not recover from: a NACK naming a
// new loss (see the package doc for why go2rtc cannot use a retransmission) or
// an explicit FIR. PLI is ignored because go2rtc emits it on an unconditional
// two-second ticker. The callback is rate-gated by the publisher.
func (s *Sink) handleRTCP(raw []byte) {
	packets, err := rtcp.Unmarshal(raw)
	if err != nil {
		return
	}
	for _, packet := range packets {
		switch packet := packet.(type) {
		case *rtcp.FullIntraRequest:
			s.keyframeNeeded()
		case *rtcp.TransportLayerNack:
			if s.newLoss(packet) {
				s.keyframeNeeded()
			}
		}
	}
}

func (s *Sink) keyframeNeeded() {
	if s.onKeyframeNeeded != nil {
		s.onKeyframeNeeded()
	}
}

func (s *Sink) newLoss(nack *rtcp.TransportLayerNack) bool {
	var newest uint16
	found := false
	for _, pair := range nack.Nacks {
		for _, seq := range pair.PacketList() {
			if !found || int16(seq-newest) > 0 {
				newest, found = seq, true
			}
		}
	}
	if !found {
		return false
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.haveRepaired && int16(newest-s.repaired) <= 0 {
		return false
	}
	s.repaired, s.haveRepaired = newest, true
	if s.waitKey {
		// Already holding for a keyframe that is on its way; asking again
		// would only queue a second encoder reset behind it.
		return false
	}
	s.waitKey, s.waitSince = true, time.Now()
	return true
}

// admit decides whether a packet goes on the wire, and numbers it if so.
func (s *Sink) admit(packet *rtp.Packet, now time.Time) bool {
	key := startsKeyframe(packet.Payload)
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.waitKey {
		if !key && now.Sub(s.waitSince) < keyframeWaitMax {
			return false
		}
		s.waitKey = false
	}
	packet.SequenceNumber = s.seq
	if key {
		// Any loss before this keyframe is repaired by it.
		if before := s.seq - 1; !s.haveRepaired || int16(before-s.repaired) > 0 {
			s.repaired, s.haveRepaired = before, true
		}
	}
	s.seq++
	return true
}

// startsKeyframe reports whether an RTP payload is the first packet of a
// keyframe access unit. The lane prepends SPS and PPS to every keyframe
// (rtspserver prependParams), so that first packet is the SPS on its own or a
// STAP-A that opens with it. An IDR slice alone is not enough: a multi-slice
// IDR's second slice also starts an FU-A of type 5, mid access unit.
func startsKeyframe(payload []byte) bool {
	if len(payload) == 0 {
		return false
	}
	switch payload[0] & 0x1F {
	case 7: // SPS
		return true
	case 24: // STAP-A: 1-byte header, 2-byte size, then the first NAL
		return len(payload) > 3 && payload[3]&0x1F == 7
	}
	return false
}

func (s *Sink) exchange(offer string) (string, string, error) {
	request, err := http.NewRequest(http.MethodPost, s.url, bytes.NewReader([]byte(offer)))
	if err != nil {
		return "", "", err
	}
	request.Header.Set("Content-Type", "application/sdp")
	response, err := s.client.Do(request)
	if err != nil {
		return "", "", err
	}
	defer response.Body.Close()
	body, err := io.ReadAll(io.LimitReader(response.Body, 1<<20))
	if err != nil {
		return "", "", fmt.Errorf("read WHIP response: %w", err)
	}
	if response.StatusCode >= 400 {
		return "", "", fmt.Errorf("WHIP endpoint returned %d: %s",
			response.StatusCode, strings.TrimSpace(string(body)))
	}
	answer := string(body)
	if strings.TrimSpace(answer) == "" {
		return "", "", fmt.Errorf("WHIP endpoint returned an empty answer")
	}
	sessionURL := ""
	if location := strings.TrimSpace(response.Header.Get("Location")); location != "" {
		base, baseErr := url.Parse(s.url)
		reference, locationErr := url.Parse(location)
		if baseErr != nil || locationErr != nil {
			return "", "", fmt.Errorf("WHIP endpoint returned an invalid session location")
		}
		resolved := base.ResolveReference(reference)
		// WHIP authentication applies to both the endpoint and the session
		// resource. Preserve URL userinfo only for a same-origin Location; never
		// forward credentials to a different host returned by the server.
		if resolved.User == nil && base.User != nil &&
			resolved.Scheme == base.Scheme && resolved.Host == base.Host {
			resolved.User = base.User
		}
		sessionURL = resolved.String()
	}
	return answer, sessionURL, nil
}

// newAPI builds the media engine.
//
// The feedback list mirrors go2rtc's own (pkg/webrtc/api.go). nack stays in the
// offer even though nothing retransmits: it is what makes go2rtc report loss.
func newAPI() (*webrtc.API, error) {
	engine := &webrtc.MediaEngine{}
	if err := engine.RegisterCodec(webrtc.RTPCodecParameters{
		RTPCodecCapability: webrtc.RTPCodecCapability{
			MimeType:    webrtc.MimeTypeH264,
			ClockRate:   90000,
			SDPFmtpLine: "level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42001f",
			RTCPFeedback: []webrtc.RTCPFeedback{
				{Type: "goog-remb"},
				{Type: "ccm", Parameter: "fir"},
				{Type: "nack"},
				{Type: "nack", Parameter: "pli"},
			},
		},
		PayloadType: 96,
	}, webrtc.RTPCodecTypeVideo); err != nil {
		return nil, err
	}
	registry := &interceptor.Registry{}
	// Sender reports only. No NACK responder: go2rtc has no jitter buffer, so a
	// late retransmission corrupts the next frame instead of repairing this one.
	if err := webrtc.ConfigureRTCPReports(registry); err != nil {
		return nil, err
	}
	return webrtc.NewAPI(
		webrtc.WithMediaEngine(engine),
		webrtc.WithInterceptorRegistry(registry),
	), nil
}

func envDefault(name string, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(name)); value != "" {
		return value
	}
	return fallback
}

func envInt(name string, fallback int) int {
	value := strings.TrimSpace(os.Getenv(name))
	if value == "" {
		return fallback
	}
	parsed, err := strconv.Atoi(value)
	if err != nil || parsed <= 0 {
		return fallback
	}
	return parsed
}
