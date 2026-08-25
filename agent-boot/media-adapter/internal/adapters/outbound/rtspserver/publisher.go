package rtspserver

import (
	"context"
	"fmt"
	"log/slog"
	"net/url"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"devicefarm/media-adapter/internal/domain/stream"
	"github.com/bluenviron/gortsplib/v5"
	"github.com/bluenviron/gortsplib/v5/pkg/base"
	"github.com/bluenviron/gortsplib/v5/pkg/description"
	"github.com/bluenviron/gortsplib/v5/pkg/format"
	"github.com/bluenviron/gortsplib/v5/pkg/format/rtph264"
	h264codec "github.com/bluenviron/mediacommon/v2/pkg/codecs/h264"
	"github.com/pion/rtp"
)

type Config struct {
	RTSPAddress     string
	PublishTemplate string
	QueueMax        int
	StalePacketAge  time.Duration
	InputFPS        int
	WriteQueueSize  int
	RemoteQueueSize int
	RemoteTimeout   time.Duration
}

type Publisher struct {
	cfg    Config
	logger *slog.Logger
	server *gortsplib.Server
	rtsp   *rtspHandler
	mu     sync.RWMutex
	lanes  map[string]*serialLane
	idr    func(serial string) bool
	stats  publisherCounters
	err    error
}

type PublisherStats struct {
	OfferedPackets    uint64 `json:"offered_packets"`
	EnqueuedPackets   uint64 `json:"enqueued_packets"`
	QueueDrops        uint64 `json:"queue_drops"`
	QueueEvictions    uint64 `json:"queue_evictions"`
	StaleDrops        uint64 `json:"stale_drops"`
	WriteErrors       uint64 `json:"write_errors"`
	RTPPacketsWritten uint64 `json:"rtp_packets_written"`
	StreamsReady      uint64 `json:"streams_ready"`
	ActiveLanes       int    `json:"active_lanes"`
}

type publisherCounters struct {
	offeredPackets    atomic.Uint64
	enqueuedPackets   atomic.Uint64
	queueDrops        atomic.Uint64
	queueEvictions    atomic.Uint64
	staleDrops        atomic.Uint64
	writeErrors       atomic.Uint64
	rtpPacketsWritten atomic.Uint64
	streamsReady      atomic.Uint64
}

func New(cfg Config, logger *slog.Logger) *Publisher {
	if cfg.RTSPAddress == "" {
		cfg.RTSPAddress = ":8556"
	}
	if cfg.QueueMax <= 0 {
		cfg.QueueMax = 8
	} else if cfg.QueueMax < 2 {
		cfg.QueueMax = 2
	}
	if cfg.StalePacketAge <= 0 {
		cfg.StalePacketAge = 160 * time.Millisecond
	}
	if cfg.InputFPS <= 0 {
		cfg.InputFPS = 15
	}
	if cfg.WriteQueueSize <= 0 {
		cfg.WriteQueueSize = 128
	}
	if cfg.RemoteQueueSize <= 0 {
		cfg.RemoteQueueSize = 256
	}
	if cfg.RemoteTimeout <= 0 {
		cfg.RemoteTimeout = 1500 * time.Millisecond
	}
	handler := &rtspHandler{
		streams: make(map[string]*gortsplib.ServerStream),
		states:  make(map[string]*streamState),
	}
	p := &Publisher{
		cfg:    cfg,
		logger: logger,
		rtsp:   handler,
		lanes:  make(map[string]*serialLane),
	}
	handler.requestKeyframe = p.requestKeyframe
	p.server = &gortsplib.Server{
		Handler:        handler,
		RTSPAddress:    cfg.RTSPAddress,
		WriteQueueSize: cfg.WriteQueueSize,
	}
	handler.server = p.server
	if err := p.server.Start(); err != nil {
		p.err = err
		logger.Error("media adapter RTSP server failed to start", "addr", cfg.RTSPAddress, "error", err)
	} else {
		logger.Info("media adapter RTSP serving", "addr", cfg.RTSPAddress)
	}
	return p
}

func (p *Publisher) StartError() error {
	return p.err
}

func (p *Publisher) SetKeyframeRequester(request func(serial string) bool) {
	p.mu.Lock()
	p.idr = request
	p.mu.Unlock()
}

func (p *Publisher) requestKeyframe(serial string) bool {
	p.mu.RLock()
	request := p.idr
	p.mu.RUnlock()
	return request != nil && request(serial)
}

func (p *Publisher) Stats() PublisherStats {
	p.mu.RLock()
	activeLanes := len(p.lanes)
	p.mu.RUnlock()
	return PublisherStats{
		OfferedPackets:    p.stats.offeredPackets.Load(),
		EnqueuedPackets:   p.stats.enqueuedPackets.Load(),
		QueueDrops:        p.stats.queueDrops.Load(),
		QueueEvictions:    p.stats.queueEvictions.Load(),
		StaleDrops:        p.stats.staleDrops.Load(),
		WriteErrors:       p.stats.writeErrors.Load(),
		RTPPacketsWritten: p.stats.rtpPacketsWritten.Load(),
		StreamsReady:      p.stats.streamsReady.Load(),
		ActiveLanes:       activeLanes,
	}
}

func (p *Publisher) Publish(ctx context.Context, packet stream.EncodedPacket) error {
	if p.server == nil {
		return nil
	}
	p.stats.offeredPackets.Add(1)
	p.mu.RLock()
	lane := p.lanes[packet.Serial]
	p.mu.RUnlock()
	if lane != nil {
		lane.offer(packet)
		return nil
	}
	p.mu.Lock()
	lane = p.lanes[packet.Serial]
	if lane == nil {
		lane = newSerialLane(packet.Serial, p, p.logger)
		p.lanes[packet.Serial] = lane
	}
	p.mu.Unlock()
	lane.offer(packet)
	return nil
}

func (p *Publisher) Close(ctx context.Context) error {
	p.mu.Lock()
	lanes := make([]*serialLane, 0, len(p.lanes))
	for serial, lane := range p.lanes {
		lanes = append(lanes, lane)
		delete(p.lanes, serial)
	}
	p.mu.Unlock()
	for _, lane := range lanes {
		lane.close()
	}
	if p.server != nil {
		p.server.Close()
	}
	return nil
}

func (p *Publisher) ensureRTSPStream(serial string, sps []byte, pps []byte) (*streamState, error) {
	name := stream.StreamName(serial)
	p.rtsp.mu.Lock()
	defer p.rtsp.mu.Unlock()
	if state := p.rtsp.states[name]; state != nil {
		state.format.SPS = append([]byte(nil), sps...)
		state.format.PPS = append([]byte(nil), pps...)
		state.stream.ReloadDesc()
		return state, nil
	}
	forma := &format.H264{
		PayloadTyp:        96,
		SPS:               append([]byte(nil), sps...),
		PPS:               append([]byte(nil), pps...),
		PacketizationMode: 1,
	}
	desc := &description.Session{
		Medias: []*description.Media{{
			Type:    description.MediaTypeVideo,
			Formats: []format.Format{forma},
		}},
	}
	rtspStream := &gortsplib.ServerStream{
		Server: p.server,
		Desc:   desc,
	}
	if err := rtspStream.Initialize(); err != nil {
		return nil, err
	}
	state := &streamState{
		serial:        serial,
		media:         desc.Medias[0],
		format:        forma,
		stream:        rtspStream,
		remoteURL:     p.remoteURL(serial),
		remoteQueue:   make(chan *rtp.Packet, p.cfg.RemoteQueueSize),
		remoteDone:    make(chan struct{}),
		remoteTimeout: p.cfg.RemoteTimeout,
		stats:         &p.stats,
	}
	state.startRemote(p.logger)
	p.rtsp.streams[name] = rtspStream
	p.rtsp.states[name] = state
	p.stats.streamsReady.Add(1)
	p.logger.Info("media adapter RTSP stream ready", "serial", serial, "stream", name)
	return state, nil
}

func (p *Publisher) remoteURL(serial string) string {
	tpl := strings.TrimSpace(p.cfg.PublishTemplate)
	if tpl == "" {
		return ""
	}
	name := stream.StreamName(serial)
	return strings.NewReplacer(
		"{serial}", url.PathEscape(serial),
		"{stream}", url.PathEscape(name),
		"{stream_raw}", name,
	).Replace(tpl)
}

type rtspHandler struct {
	server          *gortsplib.Server
	mu              sync.RWMutex
	streams         map[string]*gortsplib.ServerStream
	states          map[string]*streamState
	requestKeyframe func(serial string) bool
}

func (h *rtspHandler) OnDescribe(ctx *gortsplib.ServerHandlerOnDescribeCtx) (*base.Response, *gortsplib.ServerStream, error) {
	h.mu.RLock()
	rtspStream := h.streams[normalizePath(ctx.Path)]
	h.mu.RUnlock()
	if rtspStream == nil {
		return &base.Response{StatusCode: base.StatusNotFound}, nil, nil
	}
	return &base.Response{StatusCode: base.StatusOK}, rtspStream, nil
}

func (h *rtspHandler) OnSetup(ctx *gortsplib.ServerHandlerOnSetupCtx) (*base.Response, *gortsplib.ServerStream, error) {
	h.mu.RLock()
	rtspStream := h.streams[normalizePath(ctx.Path)]
	h.mu.RUnlock()
	if rtspStream == nil {
		return &base.Response{StatusCode: base.StatusNotFound}, nil, nil
	}
	return &base.Response{StatusCode: base.StatusOK}, rtspStream, nil
}

func (h *rtspHandler) OnPlay(ctx *gortsplib.ServerHandlerOnPlayCtx) (*base.Response, error) {
	h.mu.RLock()
	state := h.states[normalizePath(ctx.Path)]
	requestKeyframe := h.requestKeyframe
	h.mu.RUnlock()
	if state != nil && requestKeyframe != nil {
		requestKeyframe(state.serial)
	}
	return &base.Response{StatusCode: base.StatusOK}, nil
}

func normalizePath(path string) string {
	return strings.TrimPrefix(path, "/")
}

type streamState struct {
	serial         string
	media          *description.Media
	format         *format.H264
	stream         *gortsplib.ServerStream
	remoteURL      string
	remoteClient   *gortsplib.Client
	// Media announced to the remote server. A gortsplib client only accepts
	// writes for a media pointer it was given in StartRecording; passing the
	// local server's `media` instead makes it look up a nil entry and panic
	// inside WritePacketRTPWithNTP, taking the whole adapter down.
	remoteMedia    *description.Media
	remoteMu       sync.Mutex
	remoteQueue    chan *rtp.Packet
	remoteDone     chan struct{}
	remoteOnce     sync.Once
	remoteTimeout  time.Duration
	remoteNextDial time.Time
	remoteNextLog  time.Time
	stats          *publisherCounters
}

func (s *streamState) startRemote(logger *slog.Logger) {
	if s.remoteURL == "" {
		return
	}
	go s.remoteLoop(logger)
}

func (s *streamState) remoteLoop(logger *slog.Logger) {
	for {
		select {
		case <-s.remoteDone:
			return
		case packet := <-s.remoteQueue:
			if packet == nil {
				continue
			}
			if err := s.writeRemote(logger, packet); err != nil {
				if s.stats != nil {
					s.stats.writeErrors.Add(1)
				}
				s.logRemoteWriteError(logger, err)
			}
		}
	}
}

func (s *streamState) enqueueRemote(logger *slog.Logger, packet *rtp.Packet) {
	if s.remoteURL == "" || s.remoteQueue == nil {
		return
	}
	clone := packet.Clone()
	select {
	case s.remoteQueue <- clone:
		return
	default:
	}
	select {
	case <-s.remoteQueue:
		if s.stats != nil {
			s.stats.queueEvictions.Add(1)
		}
	default:
	}
	select {
	case s.remoteQueue <- clone:
	default:
		if s.stats != nil {
			s.stats.queueDrops.Add(1)
		}
		s.logRemoteWriteError(logger, fmt.Errorf("remote RTSP queue full"))
	}
}

func (s *streamState) ensureRemote(logger *slog.Logger) bool {
	if s.remoteURL == "" {
		return false
	}
	s.remoteMu.Lock()
	defer s.remoteMu.Unlock()
	if s.remoteClient != nil {
		return true
	}
	now := time.Now()
	if now.Before(s.remoteNextDial) {
		return false
	}
	remoteMedia := &description.Media{
		Type:    description.MediaTypeVideo,
		Formats: []format.Format{s.format},
	}
	desc := &description.Session{Medias: []*description.Media{remoteMedia}}
	client := &gortsplib.Client{
		ReadTimeout:  s.remoteTimeout,
		WriteTimeout: s.remoteTimeout,
	}
	if err := client.StartRecording(s.remoteURL, desc); err != nil {
		client.Close()
		s.remoteNextDial = now.Add(1 * time.Second)
		s.logRemoteConnectErrorLocked(logger, err, now)
		return false
	}
	s.remoteClient = client
	// Keep the announced media: writes must reference this pointer, not the
	// local server's, or gortsplib dereferences nil and panics.
	s.remoteMedia = remoteMedia
	logger.Info("media adapter remote RTSP publishing", "serial", s.serial, "url", s.remoteURL)
	return true
}

func (s *streamState) writeRemote(logger *slog.Logger, packet *rtp.Packet) error {
	if s.remoteURL == "" {
		return nil
	}
	if !s.ensureRemote(logger) {
		return nil
	}
	s.remoteMu.Lock()
	client := s.remoteClient
	media := s.remoteMedia
	s.remoteMu.Unlock()
	if client == nil || media == nil {
		return nil
	}
	if err := client.WritePacketRTP(media, packet); err != nil {
		s.remoteMu.Lock()
		if s.remoteClient != nil {
			s.remoteClient.Close()
			s.remoteClient = nil
		}
		s.remoteMedia = nil
		s.remoteMu.Unlock()
		return err
	}
	return nil
}

func (s *streamState) logRemoteConnectErrorLocked(logger *slog.Logger, err error, now time.Time) {
	if logger == nil || now.Before(s.remoteNextLog) {
		return
	}
	s.remoteNextLog = now.Add(5 * time.Second)
	logger.Warn("media adapter remote RTSP publish not ready", "serial", s.serial, "url", s.remoteURL, "error", err)
}

func (s *streamState) logRemoteWriteError(logger *slog.Logger, err error) {
	if logger == nil {
		return
	}
	now := time.Now()
	s.remoteMu.Lock()
	defer s.remoteMu.Unlock()
	if now.Before(s.remoteNextLog) {
		return
	}
	s.remoteNextLog = now.Add(5 * time.Second)
	logger.Warn("media adapter remote RTSP packet dropped", "serial", s.serial, "url", s.remoteURL, "error", err)
}

func (s *streamState) closeRemote() {
	s.remoteOnce.Do(func() {
		if s.remoteDone != nil {
			close(s.remoteDone)
		}
		s.remoteMu.Lock()
		defer s.remoteMu.Unlock()
		if s.remoteClient != nil {
			s.remoteClient.Close()
			s.remoteClient = nil
		}
		s.remoteMedia = nil
	})
}

type serialLane struct {
	serial     string
	publisher  *Publisher
	logger     *slog.Logger
	queue      chan queuedPacket
	done       chan struct{}
	closeOnce  sync.Once
	mu         sync.Mutex
	state      *streamState
	encoder    h264Encoder
	sps        []byte
	pps        []byte
	rtpTime    uint32
	tick       uint32
	lastPTSUs  uint64
	haveLastTS bool
}

type h264Encoder interface {
	Encode(au [][]byte) ([]*rtp.Packet, error)
}

type queuedPacket struct {
	payload  []byte
	isConfig bool
	isKey    bool
	ptsUs    uint64
	received time.Time
}

func newSerialLane(serial string, publisher *Publisher, logger *slog.Logger) *serialLane {
	lane := &serialLane{
		serial:    serial,
		publisher: publisher,
		logger:    logger,
		queue:     make(chan queuedPacket, publisher.cfg.QueueMax),
		done:      make(chan struct{}),
		tick:      uint32(90000 / publisher.cfg.InputFPS),
	}
	go lane.run()
	return lane
}

func (l *serialLane) offer(packet stream.EncodedPacket) {
	item := queuedPacket{
		payload:  packet.ClonePayload(),
		isConfig: packet.IsConfig,
		isKey:    packet.IsKey,
		ptsUs:    packet.PTSUs,
		received: packet.Received,
	}
	if item.received.IsZero() {
		item.received = time.Now()
	}
	select {
	case l.queue <- item:
		l.publisher.stats.enqueuedPackets.Add(1)
		return
	default:
	}
	if !item.isConfig && !item.isKey {
		l.publisher.stats.queueDrops.Add(1)
		return
	}
	for {
		select {
		case <-l.queue:
			l.publisher.stats.queueEvictions.Add(1)
			continue
		default:
		}
		break
	}
	select {
	case l.queue <- item:
		l.publisher.stats.enqueuedPackets.Add(1)
	default:
		l.publisher.stats.queueDrops.Add(1)
	}
}

func (l *serialLane) run() {
	for {
		select {
		case <-l.done:
			return
		case item := <-l.queue:
			if l.isStale(item) {
				l.publisher.stats.staleDrops.Add(1)
				continue
			}
			if err := l.write(item); err != nil {
				l.publisher.stats.writeErrors.Add(1)
				l.logger.Warn("media adapter RTSP packet dropped", "serial", l.serial, "error", err)
			}
		}
	}
}

func (l *serialLane) write(item queuedPacket) error {
	var au h264codec.AnnexB
	if err := au.Unmarshal(item.payload); err != nil {
		return err
	}
	sps, pps := findParams(au)
	if len(sps) > 0 && len(pps) > 0 {
		if err := l.setParams(sps, pps); err != nil {
			return err
		}
		if item.isConfig {
			return nil
		}
	}
	l.mu.Lock()
	state := l.state
	encoder := l.encoder
	spsCopy := append([]byte(nil), l.sps...)
	ppsCopy := append([]byte(nil), l.pps...)
	l.mu.Unlock()
	if state == nil || encoder == nil {
		return nil
	}
	if item.isKey {
		au = prependParams(spsCopy, ppsCopy, au)
	}
	packets, err := encoder.Encode(au)
	if err != nil {
		return err
	}
	timestamp := l.nextTimestamp(item.ptsUs)
	for _, packet := range packets {
		packet.Timestamp = timestamp
		if err := state.stream.WritePacketRTP(state.media, packet); err != nil {
			return err
		}
		state.enqueueRemote(l.logger, packet)
		l.publisher.stats.rtpPacketsWritten.Add(1)
	}
	return nil
}

func (l *serialLane) setParams(sps []byte, pps []byte) error {
	l.mu.Lock()
	if string(l.sps) == string(sps) && string(l.pps) == string(pps) && l.state != nil && l.encoder != nil {
		l.mu.Unlock()
		return nil
	}
	l.sps = append([]byte(nil), sps...)
	l.pps = append([]byte(nil), pps...)
	l.mu.Unlock()

	state, err := l.publisher.ensureRTSPStream(l.serial, sps, pps)
	if err != nil {
		return err
	}
	encoder, err := state.format.CreateEncoder()
	if err != nil {
		return err
	}
	l.mu.Lock()
	l.state = state
	l.encoder = encoder
	l.mu.Unlock()
	return nil
}

func (l *serialLane) nextTimestamp(ptsUs uint64) uint32 {
	l.mu.Lock()
	defer l.mu.Unlock()
	if ptsUs > 0 {
		if l.haveLastTS && ptsUs > l.lastPTSUs {
			l.rtpTime += uint32((ptsUs - l.lastPTSUs) * 90)
		} else if !l.haveLastTS {
			l.rtpTime += l.tick
		}
		l.lastPTSUs = ptsUs
		l.haveLastTS = true
		return l.rtpTime
	}
	l.rtpTime += l.tick
	return l.rtpTime
}

func (l *serialLane) isStale(item queuedPacket) bool {
	if item.isConfig || item.isKey || item.received.IsZero() {
		return false
	}
	return time.Since(item.received) > l.publisher.cfg.StalePacketAge
}

func (l *serialLane) close() {
	l.closeOnce.Do(func() {
		close(l.done)
		l.mu.Lock()
		state := l.state
		l.state = nil
		l.mu.Unlock()
		if state != nil {
			state.closeRemote()
		}
		if state != nil {
			state.stream.Close()
		}
		l.publisher.rtsp.mu.Lock()
		delete(l.publisher.rtsp.streams, stream.StreamName(l.serial))
		delete(l.publisher.rtsp.states, stream.StreamName(l.serial))
		l.publisher.rtsp.mu.Unlock()
	})
}

func findParams(au [][]byte) ([]byte, []byte) {
	var sps []byte
	var pps []byte
	for _, nalu := range au {
		if len(nalu) == 0 {
			continue
		}
		switch nalu[0] & 0x1F {
		case 7:
			sps = nalu
		case 8:
			pps = nalu
		}
	}
	return sps, pps
}

func prependParams(sps []byte, pps []byte, au [][]byte) [][]byte {
	out := make([][]byte, 0, len(au)+2)
	if len(sps) > 0 {
		out = append(out, sps)
	}
	if len(pps) > 0 {
		out = append(out, pps)
	}
	out = append(out, au...)
	return out
}

func ConfigFromEnv() Config {
	return Config{
		RTSPAddress:     envDefault("MEDIA_ADAPTER_RTSP_ADDRESS", ":8556"),
		PublishTemplate: envDefault("MEDIA_ADAPTER_GO2RTC_RTSP_PUBLISH_TEMPLATE", ""),
		QueueMax:        envInt("MEDIA_ADAPTER_QUEUE_MAX", 8),
		StalePacketAge:  time.Duration(envInt("MEDIA_ADAPTER_STALE_PACKET_MS", 160)) * time.Millisecond,
		InputFPS:        envInt("MEDIA_ADAPTER_INPUT_FPS", 15),
		WriteQueueSize:  envInt("MEDIA_ADAPTER_RTSP_WRITE_QUEUE", 128),
		RemoteQueueSize: envInt("MEDIA_ADAPTER_REMOTE_RTSP_QUEUE", 256),
		RemoteTimeout:   time.Duration(envInt("MEDIA_ADAPTER_REMOTE_RTSP_TIMEOUT_MS", 1500)) * time.Millisecond,
	}
}

func envDefault(name string, fallback string) string {
	value := strings.TrimSpace(os.Getenv(name))
	if value == "" {
		return fallback
	}
	return value
}

func envInt(name string, fallback int) int {
	value := strings.TrimSpace(os.Getenv(name))
	if value == "" {
		return fallback
	}
	var parsed int
	if _, err := fmt.Sscanf(value, "%d", &parsed); err != nil || parsed <= 0 {
		return fallback
	}
	return parsed
}

var _ h264Encoder = (*rtph264.Encoder)(nil)
