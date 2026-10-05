package rtspserver

import (
	"errors"
	"hash/fnv"
	"log/slog"
	"net/url"
	"sync"
	"time"

	"github.com/bluenviron/gortsplib/v5"
	"github.com/bluenviron/gortsplib/v5/pkg/description"
	"github.com/bluenviron/gortsplib/v5/pkg/format"
	"github.com/bluenviron/gortsplib/v5/pkg/liberrors"
	"github.com/pion/rtp"
)

// RemoteSink publishes one device's RTP packets to whatever sits downstream of
// the adapter: the cloud RTSP server by default, a WHIP endpoint when the
// publish template names one.
//
// Only the transport differs. Everything upstream — the per-device lane, the
// H264 packetiser, the RTP timestamps, the drop accounting and the keyframe
// gate — is shared, so a sink cannot change what is sent, only where.
type RemoteSink interface {
	// WriteRTP sends one packet, connecting on demand. It returns nil while the
	// connection is still coming up so a cold start is not counted as a write
	// error; only a failure on an established connection is an error.
	WriteRTP(packet *rtp.Packet) error
	Close()
}

// NewRemoteSinkFunc builds the sink for one device.
//
// onKeyframeNeeded reports loss on the WHIP link (a new NACK, or an explicit
// FIR). It routes into the rate-limited but never-swallowed gate
// (Publisher.requestIDRAfterRemoteConnect). Periodic go2rtc PLI is filtered by
// the WHIP sink because go2rtc emits it on an unconditional two-second ticker
// rather than in response to actual loss.
//
// onConnected is separate because the first usable IDR after a WHIP handshake
// must not be swallowed by that gate. The startup IDR is commonly sent while
// ICE is still connecting, and therefore never reaches the remote peer.
type NewRemoteSinkFunc func(
	serial string,
	url string,
	onKeyframeNeeded func(),
	onConnected func(),
) RemoteSink

// rtspSink publishes over RTSP ANNOUNCE/RECORD, the default transport.
//
// It never sees keyframe feedback: RTSP has no channel for a receiver to tell a
// publisher it lost the picture, so onKeyframeNeeded is unused here. That gap is
// the whole reason the WHIP sink exists.
type rtspSink struct {
	url         string
	timeout     time.Duration
	format      *format.H264
	logger      *slog.Logger
	writePacket func(*gortsplib.Client, *description.Media, *rtp.Packet) error

	mu     sync.Mutex
	client *gortsplib.Client
	// Media announced to the remote server. A gortsplib client only accepts
	// writes for a media pointer it was given in StartRecording; passing the
	// local server's media instead makes it look up a nil entry and panic
	// inside WritePacketRTPWithNTP, taking the whole adapter down.
	media    *description.Media
	nextDial time.Time
	nextLog  time.Time
	// retryAttempt is reset only after a complete ANNOUNCE/SETUP/RECORD
	// handshake. Keeping it per stream prevents one broken phone from delaying
	// another; deterministic jitter from retrySeed keeps a whole fleet from
	// reconnecting in lockstep after the same network outage.
	retryAttempt int
	retrySeed    uint32
	// onReconnected asks for an IDR after every connect but the first. The
	// packets sent while the session was down are gone, so without it the remote
	// picture stays broken until the device happens to send a keyframe — at
	// codec level >= 4, never. The first connect needs none: it happens inside
	// the write of the lane's opening SPS/PPS, before anything was lost.
	onReconnected func()
	connected     bool
}

func newRTSPSink(url string, timeout time.Duration, forma *format.H264, logger *slog.Logger) *rtspSink {
	return &rtspSink{
		url:       url,
		timeout:   timeout,
		format:    forma,
		logger:    logger,
		retrySeed: remoteRetrySeed(url),
		writePacket: func(client *gortsplib.Client, media *description.Media, packet *rtp.Packet) error {
			return client.WritePacketRTP(media, packet)
		},
	}
}

const (
	remoteRetryBase = time.Second
	remoteRetryMax  = 15 * time.Second
)

func remoteRetrySeed(rawURL string) uint32 {
	h := fnv.New32a()
	_, _ = h.Write([]byte(remoteURLForLog(rawURL)))
	return h.Sum32()
}

func remoteRetryDelay(attempt int, seed uint32) time.Duration {
	if attempt < 0 {
		attempt = 0
	}
	exponent := attempt
	if exponent > 4 {
		exponent = 4
	}
	delay := remoteRetryBase << exponent
	// Keep the unjittered ceiling low enough that the +20% edge remains inside
	// remoteRetryMax. Capping after jitter would collapse most streams onto the
	// exact same 15-second retry and recreate the herd this backoff prevents.
	maxBase := remoteRetryMax * 100 / 120
	if delay > maxBase {
		delay = maxBase
	}

	// A small deterministic xorshift gives each stream and attempt a stable
	// value in [80, 120]. Stable jitter keeps tests deterministic while still
	// spreading reconnects across the fleet.
	mixed := seed + uint32(attempt)*0x9e3779b9
	mixed ^= mixed << 13
	mixed ^= mixed >> 17
	mixed ^= mixed << 5
	delay = delay * time.Duration(80+mixed%41) / 100
	if delay > remoteRetryMax {
		return remoteRetryMax
	}
	return delay
}

func remoteURLForLog(rawURL string) string {
	parsed, err := url.Parse(rawURL)
	if err != nil || parsed.Scheme == "" || parsed.Host == "" {
		return "[invalid remote URL]"
	}
	parsed.User = nil
	return parsed.String()
}

func (s *rtspSink) scheduleRetryLocked(now time.Time) {
	s.nextDial = now.Add(remoteRetryDelay(s.retryAttempt, s.retrySeed))
	if s.retryAttempt < 30 {
		s.retryAttempt++
	}
}

func (s *rtspSink) ensure() bool {
	if s.url == "" {
		return false
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.client != nil {
		return true
	}
	now := time.Now()
	if now.Before(s.nextDial) {
		return false
	}
	media := &description.Media{
		Type:    description.MediaTypeVideo,
		Formats: []format.Format{s.format},
	}
	desc := &description.Session{Medias: []*description.Media{media}}
	client := &gortsplib.Client{
		ReadTimeout:  s.timeout,
		WriteTimeout: s.timeout,
	}
	if err := client.StartRecording(s.url, desc); err != nil {
		client.Close()
		s.scheduleRetryLocked(time.Now())
		s.logConnectErrorLocked(err, now)
		return false
	}
	s.client = client
	s.retryAttempt = 0
	s.nextDial = time.Time{}
	// Keep the announced media: writes must reference this pointer, not the
	// local server's, or gortsplib dereferences nil and panics.
	s.media = media
	if s.logger != nil {
		s.logger.Info("media adapter remote RTSP publishing", "url", remoteURLForLog(s.url))
	}
	if s.connected && s.onReconnected != nil {
		s.onReconnected()
	}
	s.connected = true
	return true
}

func (s *rtspSink) WriteRTP(packet *rtp.Packet) error {
	if s.url == "" || !s.ensure() {
		return nil
	}
	s.mu.Lock()
	client := s.client
	media := s.media
	s.mu.Unlock()
	if client == nil || media == nil {
		return nil
	}
	if err := s.writePacket(client, media, packet); err != nil {
		// gortsplib's write queue filling up means the uplink fell behind for a
		// moment; the session itself is fine. Tearing it down used to turn a
		// sub-second burst into a full outage: close, back off, re-dial,
		// ANNOUNCE/SETUP/RECORD, and go2rtc dropping its viewers in between.
		// Drop the packet only; the caller asks the device for an IDR.
		if errors.As(err, &liberrors.ErrClientWriteQueueFull{}) {
			return err
		}
		s.mu.Lock()
		if s.client != nil {
			s.client.Close()
			s.client = nil
		}
		s.media = nil
		s.scheduleRetryLocked(time.Now())
		s.mu.Unlock()
		return err
	}
	return nil
}

func (s *rtspSink) Close() {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.client != nil {
		s.client.Close()
		s.client = nil
	}
	s.media = nil
}

func (s *rtspSink) logConnectErrorLocked(err error, now time.Time) {
	if s.logger == nil || now.Before(s.nextLog) {
		return
	}
	s.nextLog = now.Add(5 * time.Second)
	s.logger.Warn("media adapter remote RTSP publish not ready", "url", remoteURLForLog(s.url), "error", err)
}
