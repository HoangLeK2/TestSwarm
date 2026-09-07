// Package whip publishes a device's H264 stream to go2rtc over WebRTC-HTTP
// Ingestion (WHIP) instead of RTSP ANNOUNCE/RECORD.
//
// Why this exists: RTSP gives a publisher no feedback channel. Once a packet is
// lost between the customer's machine and the server there is no way for the
// receiver to say so and no way to repair it, so the picture stays broken until
// the next IDR — which on scrcpy codec level >= 4 may never come. Over WebRTC,
// go2rtc negotiates nack (go2rtc pkg/webrtc/api.go RegisterDefaultCodecs lists
// goog-remb, ccm fir, nack and nack pli) and registers the default interceptors,
// so pion's NACK responder on this side simply retransmits the lost packets. The
// loss is repaired without touching the encoder at all.
//
// What this deliberately does NOT rely on is go2rtc's PLI. go2rtc fires one every
// two seconds on an unconditional ticker (pkg/webrtc/conn.go), not on real loss,
// so it carries no information. Honouring each one would reset MediaCodec on
// every phone every two seconds, and MediaCodec.configure() is exactly where
// Exynos encoders abort. PLI is therefore reported through the publisher's
// shared rate-limit gate, same as a local drop, and nothing else.
//
// Cost of this path: RTSP publishing needs one outbound TCP connection and so
// survives any NAT. WHIP needs UDP to go2rtc's media port plus STUN, so a
// customer network that blocks UDP loses the stream entirely. RTSP remains the
// default and the fallback.
package whip

import (
	"bytes"
	"fmt"
	"io"
	"log/slog"
	"net/http"
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
}

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
	client           *http.Client

	mu       sync.Mutex
	pc       *webrtc.PeerConnection
	track    *webrtc.TrackLocalStaticRTP
	nextDial time.Time
	closed   bool
}

func NewSink(cfg Config, serial string, url string, onKeyframeNeeded func(), logger *slog.Logger) *Sink {
	if cfg.Timeout <= 0 {
		cfg.Timeout = 5 * time.Second
	}
	if cfg.RedialBackoff <= 0 {
		cfg.RedialBackoff = 2 * time.Second
	}
	return &Sink{
		cfg:              cfg,
		serial:           serial,
		url:              url,
		logger:           logger,
		onKeyframeNeeded: onKeyframeNeeded,
		client:           &http.Client{Timeout: cfg.Timeout},
	}
}

// WriteRTP sends one packet, connecting on demand.
//
// A packet offered before the peer connection is up returns nil rather than an
// error: a cold start is not a write failure, and counting it as one would make
// every stream begin its life reporting errors.
func (s *Sink) WriteRTP(packet *rtp.Packet) error {
	track := s.ensure()
	if track == nil {
		return nil
	}
	if err := track.WriteRTP(packet); err != nil {
		s.reset(err)
		return err
	}
	return nil
}

func (s *Sink) Close() {
	s.mu.Lock()
	s.closed = true
	pc := s.pc
	s.pc = nil
	s.track = nil
	s.mu.Unlock()
	if pc != nil {
		_ = pc.Close()
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
	if now := time.Now(); now.Before(s.nextDial) {
		s.mu.Unlock()
		return nil
	}
	s.mu.Unlock()

	pc, track, err := s.connect()
	if err != nil {
		s.mu.Lock()
		s.nextDial = time.Now().Add(s.cfg.RedialBackoff)
		s.mu.Unlock()
		if s.logger != nil {
			s.logger.Warn("media adapter WHIP publish not ready",
				"serial", s.serial, "url", s.url, "error", err)
		}
		return nil
	}

	s.mu.Lock()
	if s.closed {
		s.mu.Unlock()
		_ = pc.Close()
		return nil
	}
	s.pc = pc
	s.track = track
	s.mu.Unlock()
	if s.logger != nil {
		s.logger.Info("media adapter WHIP publishing", "serial", s.serial, "url", s.url)
	}
	return track
}

func (s *Sink) reset(cause error) {
	s.mu.Lock()
	pc := s.pc
	s.pc = nil
	s.track = nil
	s.nextDial = time.Now().Add(s.cfg.RedialBackoff)
	s.mu.Unlock()
	if pc != nil {
		_ = pc.Close()
	}
	if s.logger != nil && cause != nil {
		s.logger.Warn("media adapter WHIP write failed, will redial",
			"serial", s.serial, "url", s.url, "error", cause)
	}
}

func (s *Sink) connect() (*webrtc.PeerConnection, *webrtc.TrackLocalStaticRTP, error) {
	api, err := newAPI()
	if err != nil {
		return nil, nil, err
	}
	pc, err := api.NewPeerConnection(webrtc.Configuration{
		ICEServers: []webrtc.ICEServer{{URLs: s.cfg.ICEServers}},
	})
	if err != nil {
		return nil, nil, err
	}
	track, err := webrtc.NewTrackLocalStaticRTP(
		webrtc.RTPCodecCapability{MimeType: webrtc.MimeTypeH264, ClockRate: 90000},
		"video", "device-"+s.serial,
	)
	if err != nil {
		_ = pc.Close()
		return nil, nil, err
	}
	sender, err := pc.AddTrack(track)
	if err != nil {
		_ = pc.Close()
		return nil, nil, err
	}
	go s.readRTCP(sender)

	offer, err := pc.CreateOffer(nil)
	if err != nil {
		_ = pc.Close()
		return nil, nil, err
	}
	// WHIP has no trickle: the single POST must carry every candidate, so wait
	// for gathering to finish before reading the local description back.
	gathered := webrtc.GatheringCompletePromise(pc)
	if err := pc.SetLocalDescription(offer); err != nil {
		_ = pc.Close()
		return nil, nil, err
	}
	select {
	case <-gathered:
	case <-time.After(s.cfg.Timeout):
		_ = pc.Close()
		return nil, nil, fmt.Errorf("ICE gathering timed out after %s", s.cfg.Timeout)
	}

	answer, err := s.exchange(pc.LocalDescription().SDP)
	if err != nil {
		_ = pc.Close()
		return nil, nil, err
	}
	if err := pc.SetRemoteDescription(webrtc.SessionDescription{
		Type: webrtc.SDPTypeAnswer,
		SDP:  answer,
	}); err != nil {
		_ = pc.Close()
		return nil, nil, err
	}
	return pc, track, nil
}

// readRTCP turns receiver feedback into keyframe requests.
//
// Reading is mandatory even when nothing acts on the result: the interceptor
// chain only processes NACKs — the retransmissions that make this transport
// worth using — for a sender someone is draining.
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

// handleRTCP reports receiver-side picture loss. NACKs are absent here by
// design: the interceptor chain answers those with a retransmission before they
// reach this point, which is the repair that costs the device nothing.
func (s *Sink) handleRTCP(raw []byte) {
	packets, err := rtcp.Unmarshal(raw)
	if err != nil {
		return
	}
	for _, packet := range packets {
		switch packet.(type) {
		case *rtcp.PictureLossIndication, *rtcp.FullIntraRequest:
			if s.onKeyframeNeeded != nil {
				s.onKeyframeNeeded()
			}
		}
	}
}

func (s *Sink) exchange(offer string) (string, error) {
	request, err := http.NewRequest(http.MethodPost, s.url, bytes.NewReader([]byte(offer)))
	if err != nil {
		return "", err
	}
	request.Header.Set("Content-Type", "application/sdp")
	response, err := s.client.Do(request)
	if err != nil {
		return "", err
	}
	defer response.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(response.Body, 1<<20))
	if response.StatusCode >= 400 {
		return "", fmt.Errorf("WHIP endpoint returned %d: %s",
			response.StatusCode, strings.TrimSpace(string(body)))
	}
	answer := strings.TrimSpace(string(body))
	if answer == "" {
		return "", fmt.Errorf("WHIP endpoint returned an empty answer")
	}
	return answer, nil
}

// newAPI builds the media engine.
//
// The feedback list mirrors go2rtc's own (pkg/webrtc/api.go): without nack in
// the offer the receiver has no way to ask for a retransmission, and this
// transport would then be a more fragile RTSP with extra steps.
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
	// Brings the NACK responder, which is the entire point of this transport:
	// it keeps recently sent packets and retransmits the ones the receiver
	// reports missing, repairing loss without an encoder reset.
	if err := webrtc.RegisterDefaultInterceptors(engine, registry); err != nil {
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
