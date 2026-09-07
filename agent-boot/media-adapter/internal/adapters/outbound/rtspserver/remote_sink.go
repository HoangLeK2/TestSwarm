package rtspserver

import (
	"log/slog"
	"sync"
	"time"

	"github.com/bluenviron/gortsplib/v5"
	"github.com/bluenviron/gortsplib/v5/pkg/description"
	"github.com/bluenviron/gortsplib/v5/pkg/format"
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
// onKeyframeNeeded is how a sink reports that the receiver has lost the picture
// — an RTCP PLI or FIR on the WHIP path. It routes into the same rate-limited
// gate as a local drop (Publisher.requestIDR), which is not optional: go2rtc
// sends PLI on an unconditional two-second ticker rather than on actual loss
// (pkg/webrtc/conn.go), and honouring each one would reconfigure MediaCodec
// every two seconds on every phone.
type NewRemoteSinkFunc func(serial string, url string, onKeyframeNeeded func()) RemoteSink

// rtspSink publishes over RTSP ANNOUNCE/RECORD, the default transport.
//
// It never sees keyframe feedback: RTSP has no channel for a receiver to tell a
// publisher it lost the picture, so onKeyframeNeeded is unused here. That gap is
// the whole reason the WHIP sink exists.
type rtspSink struct {
	url     string
	timeout time.Duration
	format  *format.H264
	logger  *slog.Logger

	mu     sync.Mutex
	client *gortsplib.Client
	// Media announced to the remote server. A gortsplib client only accepts
	// writes for a media pointer it was given in StartRecording; passing the
	// local server's media instead makes it look up a nil entry and panic
	// inside WritePacketRTPWithNTP, taking the whole adapter down.
	media    *description.Media
	nextDial time.Time
	nextLog  time.Time
}

func newRTSPSink(url string, timeout time.Duration, forma *format.H264, logger *slog.Logger) *rtspSink {
	return &rtspSink{url: url, timeout: timeout, format: forma, logger: logger}
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
		s.nextDial = now.Add(1 * time.Second)
		s.logConnectErrorLocked(err, now)
		return false
	}
	s.client = client
	// Keep the announced media: writes must reference this pointer, not the
	// local server's, or gortsplib dereferences nil and panics.
	s.media = media
	if s.logger != nil {
		s.logger.Info("media adapter remote RTSP publishing", "url", s.url)
	}
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
	if err := client.WritePacketRTP(media, packet); err != nil {
		s.mu.Lock()
		if s.client != nil {
			s.client.Close()
			s.client = nil
		}
		s.media = nil
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
	s.logger.Warn("media adapter remote RTSP publish not ready", "url", s.url, "error", err)
}
