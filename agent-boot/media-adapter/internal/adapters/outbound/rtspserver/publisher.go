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
	// Minimum spacing between keyframe requests for one device. See
	// Publisher.requestIDR — the request is a full encoder reset on the phone, not
	// a cheap hint, so it has to be bounded.
	IDRMinInterval time.Duration
	// How long a lane may go without receiving a packet before it closes itself
	// and releases its goroutine. See serialLane.run.
	LaneIdle time.Duration
	// NewRemoteSink builds the downstream publisher for a device. Nil selects
	// RTSP ANNOUNCE/RECORD, which is what every deployment used before WHIP
	// existed and remains the fallback: it needs one outbound TCP connection and
	// so survives NATs and firewalls that drop the UDP WebRTC needs.
	NewRemoteSink NewRemoteSinkFunc
}

type Publisher struct {
	cfg    Config
	logger *slog.Logger
	server *gortsplib.Server
	rtsp   *rtspHandler
	mu     sync.RWMutex
	lanes  map[string]*serialLane
	idr    func(serial string) bool
	// Last keyframe request per serial, the rate-limit gate shared by every
	// source that can ask for one. See requestIDR.
	lastIDR map[string]time.Time
	stats   publisherCounters
	err     error
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
	// Per device, because the fleet-wide totals above cannot answer the only
	// question worth asking during an incident: which phone is dropping.
	PerSerial map[string]SerialStats `json:"per_serial,omitempty"`
}

// SerialStats is what one device's lane has seen. Note that a healthy stream is
// not "zero drops" but "zero drops that outlived an IDR request": IDRRequests
// rising alongside drops is the recovery working, not a second fault.
type SerialStats struct {
	QueueDrops     uint64 `json:"queue_drops"`
	StaleDrops     uint64 `json:"stale_drops"`
	RemoteResyncs  uint64 `json:"remote_resyncs"`
	IDRRequests    uint64 `json:"idr_requests"`
	RTPWritten     uint64 `json:"rtp_written"`
	LastPacketUnix int64  `json:"last_packet_unix_ms"`
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

// minRemoteQueueSize is the floor for Config.RemoteQueueSize, counted in RTP
// packets. One access unit has to fit, or enqueueRemote's overflow drain
// destroys the keyframe it was meant to protect.
//
// A keyframe at 1260x2800 packetises to roughly 85 RTP packets, and every
// deployment shipped RemoteQueueSize=32. Measured on one device over 242s:
// 39 keyframes, 35 remote resyncs, 1120 evicted packets — exactly 35x the
// 32-slot queue. Each overflow then asked the device for a fresh IDR, which
// arrived as another oversized keyframe and overflowed in turn, so the drop
// loop sustained itself with the uplink perfectly healthy (write_errors=0).
// Below one access unit this is not a shallow queue, it is a keyframe shredder.
//
// The old "shallow on purpose" reasoning feared a deep queue sitting full and
// adding permanent latency. Draining the whole backlog on overflow is what
// makes that impossible: the queue resynchronises to now rather than staying
// behind, so depth costs burst memory, not steady-state lag.
//
// ponytail: flat packet count, not derived from frame geometry — the publisher
// has no resolution at config time. ~3x the measured keyframe; raise it if a
// larger panel still reports remote_resyncs.
const minRemoteQueueSize = 256

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
		cfg.StalePacketAge = time.Second
	}
	if cfg.InputFPS <= 0 {
		cfg.InputFPS = 15
	}
	if cfg.WriteQueueSize <= 0 {
		cfg.WriteQueueSize = 128
	}
	if cfg.RemoteQueueSize < minRemoteQueueSize {
		cfg.RemoteQueueSize = minRemoteQueueSize
	}
	if cfg.RemoteTimeout <= 0 {
		cfg.RemoteTimeout = 1500 * time.Millisecond
	}
	if cfg.IDRMinInterval <= 0 {
		cfg.IDRMinInterval = 3 * time.Second
	}
	if cfg.LaneIdle <= 0 {
		cfg.LaneIdle = 120 * time.Second
	}
	handler := &rtspHandler{
		streams: make(map[string]*gortsplib.ServerStream),
		states:  make(map[string]*streamState),
	}
	p := &Publisher{
		cfg:     cfg,
		logger:  logger,
		rtsp:    handler,
		lanes:   make(map[string]*serialLane),
		lastIDR: make(map[string]time.Time),
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

// dropReason names a lossy event. Every one of them corrupts the same thing —
// the H264 reference chain — so they share one recovery path and differ only in
// which counter they raise.
type dropReason string

const (
	dropQueue          dropReason = "queue"
	dropStale          dropReason = "stale"
	dropRemoteOverflow dropReason = "remote_overflow"
	// dropRemoteFeedback is an RTCP PLI/FIR from the peer we publish to: the
	// receiver telling us it has already lost the picture.
	dropRemoteFeedback dropReason = "remote_feedback"
)

// requestIDR asks a device for a fresh IDR, at most once per IDRMinInterval.
//
// This is the only thing that turns a dropped packet back into a picture. H264
// P-frames are reference frames, so losing one breaks every frame after it until
// the next IDR — and that IDR is often never coming on its own. scrcpy only
// receives i-frame-interval at codec level <= 2 (scrcpy/launcher.go
// codecOptionsForLevel); the device safe profile and every device the fallback
// ladder walked down run at level 4 with no codec options at all. Before this,
// the only thing asking for a keyframe was the viewer-attach burst in
// controlplane/client.go, which fires once and never again, so a single dropped
// P-frame froze the stream until the viewer reconnected.
//
// Rate-limited, and that is not a tuning detail. scrcpy's RESET_VIDEO is
// Controller.resetVideo -> CaptureControl.reset(): a full capture teardown that
// reconfigures MediaCodec. MediaCodec.configure() is the exact call that aborts
// Samsung Exynos encoders (see scrcpy/launcher.go safeProfileMaxSize), so an
// unbounded request rate would kill the very devices the safe profile exists to
// rescue. The comment on requestKeyframeBurst in controlplane/client.go set this
// constraint first — "without becoming a steady-state IDR loop"; this is the
// single gate that holds it for every source, including RTCP feedback.
//
// The request runs on its own goroutine because it ends in a blocking write to
// the device's control socket, which has no deadline. Doing it inline would let
// a wedged phone stall the lane that serves it. The gate bounds this to one
// goroutine per device per IDRMinInterval.
func (p *Publisher) requestIDR(lane *serialLane) {
	if lane == nil || lane.serial == "" {
		return
	}
	serial := lane.serial
	now := time.Now()
	p.mu.Lock()
	if p.lastIDR == nil {
		p.lastIDR = make(map[string]time.Time)
	}
	last, seen := p.lastIDR[serial]
	allow := !seen || now.Sub(last) >= p.cfg.IDRMinInterval
	if allow {
		p.lastIDR[serial] = now
	}
	p.mu.Unlock()
	if !allow {
		return
	}
	go func() {
		if p.requestKeyframe(serial) {
			lane.counters.idrRequests.Add(1)
		}
	}()
}

// laneDrop routes a drop reported from outside the lane — the remote publish
// loop runs on its own goroutine — back through the lane that owns the device.
func (p *Publisher) laneDrop(serial string, reason dropReason) {
	p.mu.RLock()
	lane := p.lanes[serial]
	p.mu.RUnlock()
	if lane != nil {
		lane.drop(reason)
	}
}

// closeLane retires an idle lane. Guarded by pointer identity so a lane that was
// replaced while the idle check was running does not take its successor with it.
func (p *Publisher) closeLane(serial string, lane *serialLane) {
	p.mu.Lock()
	if p.lanes[serial] == lane {
		delete(p.lanes, serial)
	}
	delete(p.lastIDR, serial)
	p.mu.Unlock()
	lane.close()
}

func (p *Publisher) Stats() PublisherStats {
	activeLanes := 0
	if p.rtsp != nil {
		p.rtsp.mu.RLock()
		activeLanes = len(p.rtsp.states)
		p.rtsp.mu.RUnlock()
	}
	p.mu.RLock()
	var perSerial map[string]SerialStats
	if len(p.lanes) > 0 {
		perSerial = make(map[string]SerialStats, len(p.lanes))
		for serial, lane := range p.lanes {
			perSerial[serial] = lane.counters.snapshot()
		}
	}
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
		PerSerial:         perSerial,
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
	remoteURL := p.remoteURL(serial)
	state := &streamState{
		serial:      serial,
		media:       desc.Medias[0],
		format:      forma,
		stream:      rtspStream,
		remoteURL:   remoteURL,
		remoteQueue: make(chan *rtp.Packet, p.cfg.RemoteQueueSize),
		remoteDone:  make(chan struct{}),
		stats:       &p.stats,
		onOverflow:  func() { p.laneDrop(serial, dropRemoteOverflow) },
	}
	if remoteURL != "" {
		if p.cfg.NewRemoteSink != nil {
			state.remote = p.cfg.NewRemoteSink(serial, remoteURL, func() {
				p.laneDrop(serial, dropRemoteFeedback)
			})
		} else {
			state.remote = newRTSPSink(remoteURL, p.cfg.RemoteTimeout, forma,
				p.logger.With("serial", serial))
		}
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
	serial        string
	media         *description.Media
	format        *format.H264
	stream        *gortsplib.ServerStream
	remoteURL     string
	remote        RemoteSink
	remoteMu      sync.Mutex
	remoteQueue   chan *rtp.Packet
	remoteDone    chan struct{}
	remoteOnce    sync.Once
	remoteNextLog time.Time
	stats         *publisherCounters
	// onOverflow reports a resync to the publisher so it can ask the device for
	// a keyframe. Optional so tests can build a state without a publisher.
	onOverflow func()
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
			if err := s.writeRemote(packet); err != nil {
				if s.stats != nil {
					s.stats.writeErrors.Add(1)
				}
				s.logRemoteWriteError(logger, err)
			}
		}
	}
}

// enqueueRemote hands one RTP packet to the remote publish loop, dropping the
// whole backlog rather than one packet when the loop cannot keep up.
//
// This used to evict a single packet — the OLDEST one — to make room. That is
// the head of an access unit still being written, so it did not risk cutting a
// frame in half, it guaranteed it. Worse, the packet most likely to be evicted
// is the one from the largest frame, and the largest frame is the keyframe: the
// eviction preferentially destroyed the picture that recovery depends on.
//
// gortsplib's own ring buffer refuses the NEW packet instead (ringbuffer.Push
// returns false when full) and MediaMTX queues whole units, so neither can ever
// emit a partial frame. Refusing is wrong here though: this is a live view, and
// a queue that only ever refuses new packets serves an ever-staler picture.
// Draining resynchronises to now, and the IDR request makes the gap decodable.
//
// Overflow is not hypothetical. writeRemote calls WritePacketRTP synchronously
// with a 1500ms WriteTimeout, and deployments run RemoteQueueSize=32 — about a
// second of packets at 15fps — so any hiccup on the uplink fills it.
//
// ponytail: drains the whole queue, which discards good packets from the tail
// too. Cutting at the RTP marker bit would drop only up to the access-unit
// boundary; worth doing if the resync gap ever shows up in practice.
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
	drained := uint64(0)
	for {
		select {
		case <-s.remoteQueue:
			drained++
			continue
		default:
		}
		break
	}
	select {
	case s.remoteQueue <- clone:
	default:
		drained++
	}
	if s.stats != nil {
		s.stats.queueEvictions.Add(drained)
	}
	if s.onOverflow != nil {
		s.onOverflow()
	}
	s.logRemoteWriteError(logger, fmt.Errorf("remote RTSP queue full, resynced after %d packets", drained))
}

func (s *streamState) writeRemote(packet *rtp.Packet) error {
	if s.remoteURL == "" || s.remote == nil {
		return nil
	}
	return s.remote.WriteRTP(packet)
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
		if s.remote != nil {
			s.remote.Close()
		}
	})
}

// laneCounters is one device's tally. Separate from publisherCounters rather
// than derived from it: the fleet-wide totals cannot say which phone is broken.
type laneCounters struct {
	queueDrops     atomic.Uint64
	staleDrops     atomic.Uint64
	remoteResyncs  atomic.Uint64
	idrRequests    atomic.Uint64
	rtpWritten     atomic.Uint64
	lastPacketUnix atomic.Int64
}

func (c *laneCounters) snapshot() SerialStats {
	return SerialStats{
		QueueDrops:     c.queueDrops.Load(),
		StaleDrops:     c.staleDrops.Load(),
		RemoteResyncs:  c.remoteResyncs.Load(),
		IDRRequests:    c.idrRequests.Load(),
		RTPWritten:     c.rtpWritten.Load(),
		LastPacketUnix: c.lastPacketUnix.Load(),
	}
}

type serialLane struct {
	serial     string
	publisher  *Publisher
	logger     *slog.Logger
	queue      chan queuedPacket
	done       chan struct{}
	closeOnce  sync.Once
	counters   laneCounters
	mu         sync.Mutex
	state      *streamState
	encoder    h264Encoder
	sps        []byte
	pps        []byte
	rtpTime    uint32
	tick       uint32
	basePTSUs  uint64
	baseRTP    uint32
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
		l.accepted()
		return
	default:
	}
	if !item.isConfig && !item.isKey {
		// A P-frame goes over the side. Everything after it is undecodable
		// until an IDR arrives, so ask for one rather than leaving the viewer
		// on a frozen picture.
		l.drop(dropQueue)
		return
	}
	// Evicting P-frames to make room for a keyframe is the right trade: the
	// keyframe is what makes them decodable again. Only the eviction is
	// deliberate here, so it does not go through drop().
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
		l.accepted()
	default:
		l.drop(dropQueue)
	}
}

func (l *serialLane) accepted() {
	l.counters.lastPacketUnix.Store(time.Now().UnixMilli())
	if l.publisher != nil {
		l.publisher.stats.enqueuedPackets.Add(1)
	}
}

// drop records a lossy event on this device and asks it for a fresh IDR. Every
// drop site goes through here so the counter and the recovery can never drift
// apart, and so one rate-limit gate covers all of them.
func (l *serialLane) drop(reason dropReason) {
	l.countDrop(reason)
	if l.publisher != nil {
		l.publisher.requestIDR(l)
	}
}

func (l *serialLane) countDrop(reason dropReason) {
	switch reason {
	case dropQueue:
		l.counters.queueDrops.Add(1)
		if l.publisher != nil {
			l.publisher.stats.queueDrops.Add(1)
		}
	case dropStale:
		l.counters.staleDrops.Add(1)
		if l.publisher != nil {
			l.publisher.stats.staleDrops.Add(1)
		}
	case dropRemoteOverflow:
		l.counters.remoteResyncs.Add(1)
	case dropRemoteFeedback:
		// Nothing was dropped on this side — the peer is reporting its own
		// loss. It shows up as the IDR request it causes and nowhere else.
	}
}

func (l *serialLane) run() {
	// A lane used to live until Publisher.Close, so every device that ever
	// streamed kept this goroutine and its queue for the life of the process.
	// On a farm that cycles devices they only accumulate, and per-serial stats
	// would report every one of them as if it were still streaming.
	idle := l.publisher.cfg.LaneIdle
	if idle <= 0 {
		// New() fills this in, but a Publisher built directly — as tests do —
		// would otherwise reach time.NewTicker(0), which panics.
		idle = 120 * time.Second
	}
	ticker := time.NewTicker(idle / 2)
	defer ticker.Stop()
	for {
		select {
		case <-l.done:
			return
		case <-ticker.C:
			last := l.counters.lastPacketUnix.Load()
			if last == 0 || time.Since(time.UnixMilli(last)) < idle {
				continue
			}
			if l.logger != nil {
				l.logger.Debug("media adapter retiring idle lane", "serial", l.serial)
			}
			l.publisher.closeLane(l.serial, l)
			return
		case item := <-l.queue:
			if l.isStale(item) {
				// Same corruption as a queue drop, so the same recovery. The
				// stale window used to be 160ms — under three frames at 15fps —
				// which made a routine scheduler hiccup enough to break the
				// reference chain on a device with nothing else wrong.
				l.drop(dropStale)
				continue
			}
			if err := l.write(item); err != nil {
				l.publisher.stats.writeErrors.Add(1)
				if l.logger != nil {
					l.logger.Warn("media adapter RTSP packet dropped", "serial", l.serial, "error", err)
				}
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
	// Copy the parameter sets only when they are about to be used. They are
	// prepended to keyframes and nothing else, so on a 1s IDR cadence at 15fps
	// this used to allocate twice for fourteen frames out of every fifteen —
	// inside the critical section, for values immediately discarded.
	var spsCopy, ppsCopy []byte
	if item.isKey {
		spsCopy = append([]byte(nil), l.sps...)
		ppsCopy = append([]byte(nil), l.pps...)
	}
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
		l.counters.rtpWritten.Add(1)
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

// nextTimestamp maps a scrcpy presentation timestamp onto the RTP 90 kHz clock.
//
// scrcpy reports PTS in MICROseconds, so a tick is µs * 90 / 1000 — not µs * 90.
// The missing divisor stamped every frame 1000x further apart than it really
// was: at 10 fps, consecutive frames were 100 seconds apart on the wire instead
// of 0.1s. Receivers pace playback from these timestamps, so the stream could
// not be smooth no matter how clean the network was, and the 32-bit clock
// wrapped roughly every 48 seconds of real time.
//
// Derived from an absolute base rather than accumulated per frame: rounding
// each delta independently loses up to one tick every frame, which drifts.
func (l *serialLane) nextTimestamp(ptsUs uint64) uint32 {
	l.mu.Lock()
	defer l.mu.Unlock()
	if ptsUs > 0 {
		// Rebase on the first frame, and again if the device clock goes
		// backwards (a restarted scrcpy session reuses the lane).
		if !l.haveLastTS || ptsUs < l.basePTSUs {
			l.basePTSUs = ptsUs
			l.baseRTP = l.rtpTime + l.tick
			l.haveLastTS = true
		}
		l.rtpTime = l.baseRTP + uint32((ptsUs-l.basePTSUs)*90/1000)
		l.lastPTSUs = ptsUs
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
		// 1s, not the 160ms this used to be. At 15fps that window was under three
		// frames, so an ordinary scheduler or GC hiccup was enough to drop a
		// reference frame on a device with nothing wrong with it. The latency it
		// bought back was never observable — the browser's jitter buffer holds
		// more than that on its own.
		StalePacketAge:  time.Duration(envInt("MEDIA_ADAPTER_STALE_PACKET_MS", 1000)) * time.Millisecond,
		InputFPS:        envInt("MEDIA_ADAPTER_INPUT_FPS", 15),
		WriteQueueSize:  envInt("MEDIA_ADAPTER_RTSP_WRITE_QUEUE", 128),
		RemoteQueueSize: envInt("MEDIA_ADAPTER_REMOTE_RTSP_QUEUE", 256),
		RemoteTimeout:   time.Duration(envInt("MEDIA_ADAPTER_REMOTE_RTSP_TIMEOUT_MS", 1500)) * time.Millisecond,
		IDRMinInterval:  time.Duration(envInt("MEDIA_ADAPTER_IDR_MIN_INTERVAL_MS", 3000)) * time.Millisecond,
		LaneIdle:        time.Duration(envInt("MEDIA_ADAPTER_LANE_IDLE_S", 120)) * time.Second,
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
