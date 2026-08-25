package scrcpy

import (
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"strings"
	"sync"
	"time"

	"devicefarm/media-adapter/internal/domain/stream"
)

const (
	sessionPacketFlag = uint32(0x80000000)
	ptsConfigMask     = uint64(0x4000000000000000)
	ptsKeyframeMask   = uint64(0x2000000000000000)
	ptsFlagMask       = uint64(0xE000000000000000)
	resetVideoMsg     = byte(17)
	maxFrameBytes     = 8 * 1024 * 1024
)

type Publisher interface {
	Publish(ctx context.Context, packet stream.EncodedPacket) error
}

type StartRequest struct {
	Serial     string
	Host       string
	Port       int
	Control    bool
	OwnsScrcpy bool
	MaxFPS     int
	MaxWidth   int
	Bitrate    int
	VideoCodec string
	// Optional MediaCodec encoder name passed to scrcpy-server as
	// video_encoder=<name>. Empty lets scrcpy choose the device default.
	VideoEncoder string
	// Skip scrcpy 4.x's own size/fps clamping against the encoder's declared
	// MediaCodecInfo.VideoCapabilities. See ignoreEncoderConstraints.
	IgnoreEncoderConstraints bool
	// Omit max_size entirely so the device encodes at its native resolution.
	// Distinct from MaxWidth == 0, which normalize() fills with a default.
	// See safeProfileMaxSize.
	SkipMaxSize bool
	// Omit max_fps too. scrcpy turns it into the vendor MediaFormat key
	// max-fps-to-encoder, which aborts the same encoders that max_size does.
	SkipMaxFPS bool
	LowLatency  bool
	// Rung of the codec-option fallback ladder to launch with. Callers leave
	// this at 0; the session raises it when a device keeps refusing to start,
	// and the manager remembers what finally worked. See codecOptionsForLevel.
	CodecLevel int
}

type Status struct {
	Serial        string `json:"serial"`
	Host          string `json:"host"`
	Port          int    `json:"port"`
	Control       bool   `json:"control"`
	Running       bool   `json:"running"`
	Connected     bool   `json:"connected"`
	Width         uint16 `json:"width"`
	Height        uint16 `json:"height"`
	Frames        uint64 `json:"frames"`
	Bytes         uint64 `json:"bytes"`
	Keyframes     uint64 `json:"keyframes"`
	Configs       uint64 `json:"configs"`
	PublishErrs   uint64 `json:"publish_errors"`
	Reconnects    uint64 `json:"reconnects"`
	IDRRequests   uint64 `json:"idr_requests"`
	LastFrameUnix int64  `json:"last_frame_unix_ms"`
	OwnsScrcpy    bool   `json:"owns_scrcpy"`
	LastError     string `json:"last_error,omitempty"`
}

type Manager struct {
	publisher Publisher
	launcher  Launcher
	logger    *slog.Logger
	mu        sync.Mutex
	sessions  map[string]*Session
	// Cold scrcpy starts are ADB-heavy: push/check jar, kill old app_process,
	// create adb forward, then wait for the localabstract socket. A broken
	// device can retry this loop forever, so gate only the launch+handshake
	// phase and let established streams run outside the limiter.
	launchLimiter chan struct{}
	// Codec-option rung that last produced a stream, per serial. Climbing the
	// ladder costs one scrcpy cold start per rung (~4s each), so a device that
	// needs level 2 would pay that on every session without this.
	codecLevels map[string]int
}

func NewManager(publisher Publisher, logger *slog.Logger) *Manager {
	return NewManagerWithLauncher(publisher, NewADBLauncher(ConfigFromEnv()), logger)
}

func NewManagerWithLauncher(publisher Publisher, launcher Launcher, logger *slog.Logger) *Manager {
	if adbLauncher, ok := launcher.(*ADBLauncher); ok {
		adbLauncher.logger = logger
	}
	return &Manager{
		publisher:     publisher,
		launcher:      launcher,
		logger:        logger,
		sessions:      make(map[string]*Session),
		launchLimiter: newLaunchLimiterFromEnv(),
		codecLevels:   make(map[string]int),
	}
}

func (m *Manager) knownCodecLevel(serial string) int {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.codecLevels[serial]
}

func (m *Manager) recordCodecLevel(serial string, level int) {
	m.mu.Lock()
	if m.codecLevels == nil {
		m.codecLevels = make(map[string]int)
	}
	previous, seen := m.codecLevels[serial]
	m.codecLevels[serial] = level
	m.mu.Unlock()
	if m.logger != nil && (!seen || previous != level) && level > 0 {
		m.logger.Info("scrcpy codec level remembered for device",
			"serial", serial, "codec_level", level)
	}
}

func (m *Manager) Start(req StartRequest) (Status, error) {
	if req.Serial == "" {
		return Status{}, errors.New("serial is required")
	}
	if req.Host == "" && !req.OwnsScrcpy {
		req.Host = "127.0.0.1"
	}
	if req.Port <= 0 && !req.OwnsScrcpy {
		return Status{}, errors.New("port is required")
	}
	req.normalize()
	m.mu.Lock()
	defer m.mu.Unlock()
	current := m.sessions[req.Serial]
	if current != nil && current.matches(req) {
		return current.Status(), nil
	}
	// A live stream outranks a parameter change.
	//
	// Two callers ask for the same device with different numbers: the relay
	// picks fps/size/bitrate from the device's idle/visible/focused state, and
	// each WebRTC viewer asks for its own profile. Treating any difference as
	// "restart" meant every disagreement tore down a working stream and paid a
	// scrcpy cold start — longer than the 4s a viewer waits for its first
	// frame, so the viewer got 425, retried, and flipped the parameters back.
	// Measured on a live farm: 339 session requests in three minutes produced
	// 10 answers and zero attached viewers, while the streams themselves were
	// publishing fine the whole time.
	//
	// So only cosmetic differences are absorbed. Anything that changes what the
	// session *is* — a different endpoint, control socket, or codec — still
	// rebuilds it, because those cannot be papered over.
	if current != nil && current.isHealthy() && onlyEncodingProfileDiffers(current.request(), req) {
		if m.logger != nil {
			m.logger.Debug("scrcpy keeping live stream despite profile change",
				"serial", req.Serial)
		}
		return current.Status(), nil
	}
	if current != nil {
		current.Stop()
	}
	// Start straight at the rung this device is known to accept. Read the map
	// inline rather than via knownCodecLevel: m.mu is already held here and it
	// is not reentrant.
	req.CodecLevel = m.codecLevels[req.Serial]
	session := NewSession(req, m.publisher, m.launcher, m.logger)
	session.onCodecLevel = m.recordCodecLevel
	session.launchLimiter = m.launchLimiter
	m.sessions[req.Serial] = session
	session.Start()
	return session.Status(), nil
}

func (m *Manager) Stop(serial string) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	session := m.sessions[serial]
	if session == nil {
		return false
	}
	session.Stop()
	delete(m.sessions, serial)
	return true
}

func (m *Manager) Status(serial string) (Status, bool) {
	m.mu.Lock()
	session := m.sessions[serial]
	m.mu.Unlock()
	if session == nil {
		return Status{}, false
	}
	return session.Status(), true
}

// WaitForFirstFrame waits until the stream has delivered at least one packet
// through the publisher. Connected alone only proves the local scrcpy socket
// handshook; WebRTC viewers need actual H264/config data to exist downstream.
func (m *Manager) WaitForFirstFrame(ctx context.Context, serial string, timeout time.Duration) (Status, bool) {
	if timeout <= 0 {
		status, ok := m.Status(serial)
		return status, ok && streamHasPublishedFrame(status)
	}
	deadline := time.NewTimer(timeout)
	defer deadline.Stop()
	ticker := time.NewTicker(50 * time.Millisecond)
	defer ticker.Stop()
	var status Status
	for {
		current, ok := m.Status(serial)
		if ok {
			status = current
			if streamHasPublishedFrame(current) {
				return current, true
			}
		}
		select {
		case <-ctx.Done():
			return status, false
		case <-deadline.C:
			return status, false
		case <-ticker.C:
		}
	}
}

func streamHasPublishedFrame(status Status) bool {
	return status.Connected && status.Frames > 0
}

func (m *Manager) Statuses() []Status {
	m.mu.Lock()
	sessions := make([]*Session, 0, len(m.sessions))
	for _, session := range m.sessions {
		sessions = append(sessions, session)
	}
	m.mu.Unlock()
	out := make([]Status, 0, len(sessions))
	for _, session := range sessions {
		out = append(out, session.Status())
	}
	return out
}

func (m *Manager) RequestKeyframe(serial string) bool {
	m.mu.Lock()
	session := m.sessions[serial]
	m.mu.Unlock()
	if session == nil {
		return false
	}
	return session.RequestKeyframe()
}

func (m *Manager) Close() {
	m.mu.Lock()
	sessions := make([]*Session, 0, len(m.sessions))
	for serial, session := range m.sessions {
		sessions = append(sessions, session)
		delete(m.sessions, serial)
	}
	m.mu.Unlock()
	for _, session := range sessions {
		session.Stop()
	}
}

type Session struct {
	req       StartRequest
	publisher Publisher
	launcher  Launcher
	logger    *slog.Logger
	ctx       context.Context
	cancel    context.CancelFunc
	done      chan struct{}
	once      sync.Once
	mu        sync.Mutex
	status    Status
	ctrlConn  net.Conn
	launched  *LaunchedServer
	// Log tail of the last launch, kept so a failure can still report why.
	lastOutput []string

	// Fallback-ladder state. Without this, run() retried the identical launch
	// forever: a device whose encoder rejects a codec option never started and
	// never stopped trying, burning ADB and CPU indefinitely.
	codecLevel    int
	levelFailures int
	onCodecLevel  func(serial string, level int)
	launchLimiter chan struct{}
}

// codecFailuresPerLevel is how many consecutive failures at one rung before
// dropping to the next. Two rather than one so a transient hiccup — device
// busy, ADB blip — does not immediately give up encoder settings that the
// device actually supports.
const codecFailuresPerLevel = 2

const (
	normalReconnectBackoffMax       = 2 * time.Second
	safeProfileHandshakeBackoffMin  = 10 * time.Second
	safeProfileHandshakeBackoffMax  = 30 * time.Second
	scrcpyHandshakeNotReadyFragment = "scrcpy handshake not ready"
	defaultScrcpyLaunchConcurrency  = 2
)

func (r *StartRequest) normalize() {
	if r.VideoCodec == "" {
		r.VideoCodec = "h264"
	}
	if r.MaxFPS <= 0 {
		r.MaxFPS = 15
	}
	if r.MaxWidth <= 0 {
		r.MaxWidth = 320
	}
	if r.Bitrate <= 0 {
		r.Bitrate = 150000
	}
}

func NewSession(req StartRequest, publisher Publisher, launcher Launcher, logger *slog.Logger) *Session {
	ctx, cancel := context.WithCancel(context.Background())
	req.normalize()
	return &Session{
		req:        req,
		publisher:  publisher,
		launcher:   launcher,
		logger:     logger,
		ctx:        ctx,
		cancel:     cancel,
		codecLevel: req.CodecLevel,
		done:       make(chan struct{}),
		status: Status{
			Serial:     req.Serial,
			Host:       req.Host,
			Port:       req.Port,
			Control:    req.Control,
			Running:    true,
			OwnsScrcpy: req.OwnsScrcpy,
		},
	}
}

func (s *Session) Start() {
	go s.run()
}

func (s *Session) Stop() {
	s.once.Do(func() {
		s.cancel()
		s.closeControl()
		<-s.done
	})
}

// isHealthy reports whether the session is connected and has actually
// delivered a frame — the same bar WaitForFirstFrame holds a viewer to.
func (s *Session) isHealthy() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return streamHasPublishedFrame(s.status)
}

// request returns a copy of the request this session was built from.
func (s *Session) request() StartRequest {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.req
}

// onlyEncodingProfileDiffers reports whether two requests differ solely in
// picture quality knobs — the ones scrcpy fixes at launch and that cost a cold
// start to change. Identity of the session (endpoint, sockets, codec, encoder)
// must be identical; those genuinely need a rebuild.
func onlyEncodingProfileDiffers(before StartRequest, after StartRequest) bool {
	before.MaxFPS, after.MaxFPS = 0, 0
	before.MaxWidth, after.MaxWidth = 0, 0
	before.Bitrate, after.Bitrate = 0, 0
	before.CodecLevel, after.CodecLevel = 0, 0
	return before == after
}

func (s *Session) matches(req StartRequest) bool {
	return s.req.Serial == req.Serial &&
		s.req.Host == req.Host &&
		s.req.Port == req.Port &&
		s.req.Control == req.Control &&
		s.req.OwnsScrcpy == req.OwnsScrcpy &&
		s.req.MaxFPS == req.MaxFPS &&
		s.req.MaxWidth == req.MaxWidth &&
		s.req.Bitrate == req.Bitrate &&
		s.req.VideoCodec == req.VideoCodec &&
		s.req.VideoEncoder == req.VideoEncoder &&
		s.req.IgnoreEncoderConstraints == req.IgnoreEncoderConstraints &&
		s.req.LowLatency == req.LowLatency
}

func (s *Session) Status() Status {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.status
}

func (s *Session) run() {
	defer close(s.done)
	backoff := 150 * time.Millisecond
	for s.ctx.Err() == nil {
		err := s.connectAndRead()
		if err != nil && s.ctx.Err() == nil {
			s.setError(err)
			output := s.recentLaunchOutput()
			if s.logger != nil {
				// The device's own explanation lives in the scrcpy-server log,
				// which is otherwise Debug-only and therefore invisible at the
				// default level. Surface it here, where it is actually needed.
				s.logger.Warn("scrcpy direct session failed",
					"serial", s.req.Serial,
					"codec_level", s.codecLevel,
					"error", err,
					"scrcpy_output", strings.Join(output, " | "))
			}
			s.invalidateServerCache()
			if encoderAbortedNatively(output) {
				s.skipToLastCodecLevel()
			} else {
				s.degradeCodecLevel()
			}
		} else if err == nil {
			s.rememberCodecLevel()
		}
		s.markDisconnected()
		if s.ctx.Err() != nil {
			break
		}
		sleepCtx(s.ctx, s.reconnectSleep(backoff, err))
		backoff *= 2
		if cap := s.reconnectBackoffCap(err); backoff > cap {
			backoff = cap
		}
		s.bumpReconnect()
	}
	s.setRunning(false)
}

// serverInvalidator is implemented by launchers that cache "this device already
// has the scrcpy jar". Optional so test doubles need not care.
type serverInvalidator interface {
	InvalidateServer(serial string)
}

// invalidateServerCache makes the next attempt re-check the jar on the device.
// A missing jar fails exactly like an unsupported codec option — silently — so
// the retry has to rule it out rather than assume the cache is still true.
func (s *Session) invalidateServerCache() {
	if inv, ok := s.launcher.(serverInvalidator); ok && inv != nil {
		inv.InvalidateServer(s.req.Serial)
	}
}

func (s *Session) currentCodecLevel() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.codecLevel
}

// recentLaunchOutput returns what scrcpy-server last printed on the device,
// falling back to the tail kept by clearLaunched once the launch is gone.
func (s *Session) recentLaunchOutput() []string {
	s.mu.Lock()
	launched := s.launched
	last := s.lastOutput
	s.mu.Unlock()
	if live := launched.RecentOutput(); len(live) > 0 {
		return live
	}
	return last
}

// encoderAbortedNatively reports whether scrcpy-server died inside the vendor
// encoder rather than returning an error.
//
// libc's stack protector prints this and aborts the process, so there is no
// Java exception, nothing in logcat, and no chance the next rung down helps:
// the crash happens for every codec option combination. Walking the ladder one
// step at a time costs two failed launches per rung — around 80 seconds of a
// device visibly not working — to reach a conclusion this line already gives.
func encoderAbortedNatively(output []string) bool {
	for _, line := range output {
		if strings.Contains(line, "stack corruption detected") {
			return true
		}
	}
	return false
}

// skipToLastCodecLevel jumps straight to the final rung, which is also the one
// that stops asking the device to scale. See nativeResolutionLevel.
func (s *Session) skipToLastCodecLevel() {
	s.mu.Lock()
	if s.codecLevel >= MaxCodecLevel {
		s.mu.Unlock()
		return
	}
	s.codecLevel = MaxCodecLevel
	s.levelFailures = 0
	serial := s.req.Serial
	s.mu.Unlock()
	if s.logger != nil {
		s.logger.Warn("scrcpy encoder aborted natively, skipping to native resolution",
			"serial", serial, "codec_level", MaxCodecLevel)
	}
}

// degradeCodecLevel drops to the next rung once a level has failed enough times
// in a row, so a device that rejects an encoder option eventually starts with
// fewer options instead of retrying the same doomed launch forever.
func (s *Session) degradeCodecLevel() {
	s.mu.Lock()
	s.levelFailures++
	if s.levelFailures < codecFailuresPerLevel || s.codecLevel >= MaxCodecLevel {
		s.mu.Unlock()
		return
	}
	s.codecLevel++
	s.levelFailures = 0
	level := s.codecLevel
	serial := s.req.Serial
	s.mu.Unlock()
	if s.logger != nil {
		s.logger.Warn("scrcpy dropping codec options after repeated failures",
			"serial", serial, "codec_level", level)
	}
}

// rememberCodecLevel records a level that actually produced a stream, so the
// next session for this device skips straight to it instead of re-climbing the
// ladder — each rung costs a full scrcpy cold start.
func (s *Session) rememberCodecLevel() {
	s.mu.Lock()
	s.levelFailures = 0
	level := s.codecLevel
	serial := s.req.Serial
	notify := s.onCodecLevel
	s.mu.Unlock()
	if notify != nil {
		notify(serial, level)
	}
}

func (s *Session) reconnectSleep(backoff time.Duration, err error) time.Duration {
	if s.shouldCoolDownAfterFailure(err) && backoff < safeProfileHandshakeBackoffMin {
		return safeProfileHandshakeBackoffMin
	}
	return backoff
}

func (s *Session) reconnectBackoffCap(err error) time.Duration {
	if s.shouldCoolDownAfterFailure(err) {
		return safeProfileHandshakeBackoffMax
	}
	return normalReconnectBackoffMax
}

func (s *Session) shouldCoolDownAfterFailure(err error) bool {
	if err == nil || s.currentCodecLevel() < MaxCodecLevel {
		return false
	}
	return strings.Contains(err.Error(), scrcpyHandshakeNotReadyFragment)
}

func (s *Session) adoptLaunchProfile(launched *LaunchedServer) {
	if launched == nil || !launched.SafeProfile {
		return
	}
	s.mu.Lock()
	if launched.CodecLevel > s.codecLevel {
		s.codecLevel = launched.CodecLevel
		s.levelFailures = 0
	}
	s.mu.Unlock()
}

func (s *Session) connectAndRead() error {
	host := s.req.Host
	port := s.req.Port
	var releaseLaunch func()
	if s.req.OwnsScrcpy {
		if s.launcher == nil {
			return errors.New("scrcpy launcher is unavailable")
		}
		release, err := s.acquireLaunchSlot()
		if err != nil {
			return err
		}
		releaseLaunch = release
		req := s.req
		req.CodecLevel = s.currentCodecLevel()
		launched, err := s.launcher.Start(s.ctx, req)
		if err != nil {
			releaseLaunch()
			return err
		}
		s.setLaunched(launched)
		s.adoptLaunchProfile(launched)
		defer func() {
			launched.Stop(context.Background())
			s.clearLaunched(launched)
		}()
		host = launched.Host
		port = launched.Port
		s.updateEndpoint(host, port)
	}
	addr := net.JoinHostPort(host, fmt.Sprintf("%d", port))
	videoConn, ctrlConn, width, height, err := s.openReadySockets(addr, 10*time.Second)
	if releaseLaunch != nil {
		releaseLaunch()
		releaseLaunch = nil
	}
	if err != nil {
		return err
	}
	defer videoConn.Close()
	if ctrlConn != nil {
		s.setControl(ctrlConn)
		defer s.closeControl()
		go drainControl(s.ctx, ctrlConn)
	}

	s.markConnected(width, height)
	s.requestIDR()

	for s.ctx.Err() == nil {
		_ = videoConn.SetReadDeadline(time.Now().Add(5 * time.Second))
		var header [12]byte
		if _, err := io.ReadFull(videoConn, header[:]); err != nil {
			if ne, ok := err.(net.Error); ok && ne.Timeout() {
				s.requestIDR()
				continue
			}
			return err
		}
		if header[0]&0x80 != 0 {
			flags := binary.BigEndian.Uint32(header[0:4])
			if flags&sessionPacketFlag == 0 {
				return fmt.Errorf("invalid scrcpy session packet flags=0x%08x", flags)
			}
			width = uint16(binary.BigEndian.Uint32(header[4:8]))
			height = uint16(binary.BigEndian.Uint32(header[8:12]))
			s.updateDimensions(width, height)
			continue
		}
		ptsRaw := binary.BigEndian.Uint64(header[0:8])
		size := binary.BigEndian.Uint32(header[8:12])
		if size == 0 || size > maxFrameBytes {
			return fmt.Errorf("invalid scrcpy frame size=%d", size)
		}
		payload := make([]byte, size)
		if _, err := io.ReadFull(videoConn, payload); err != nil {
			return err
		}
		isConfig := ptsRaw&ptsConfigMask != 0
		isKey := ptsRaw&ptsKeyframeMask != 0 || annexBContainsIDR(payload)
		packet := stream.EncodedPacket{
			Serial:   s.req.Serial,
			Payload:  payload,
			Owned:    true,
			IsConfig: isConfig,
			IsKey:    isKey,
			PTSUs:    ptsRaw &^ ptsFlagMask,
			Received: time.Now(),
		}
		if isConfig {
			packet.Width = width
			packet.Height = height
		}
		if err := s.publisher.Publish(s.ctx, packet); err != nil {
			s.recordPublishError()
			continue
		}
		s.recordFrame(len(payload), isConfig, isKey)
	}
	return nil
}

func (s *Session) acquireLaunchSlot() (func(), error) {
	if s.launchLimiter == nil {
		return func() {}, nil
	}
	select {
	case s.launchLimiter <- struct{}{}:
		var once sync.Once
		return func() {
			once.Do(func() {
				<-s.launchLimiter
			})
		}, nil
	case <-s.ctx.Done():
		return nil, s.ctx.Err()
	}
}

func newLaunchLimiterFromEnv() chan struct{} {
	concurrency := envInt("MEDIA_ADAPTER_SCRCPY_LAUNCH_CONCURRENCY", defaultScrcpyLaunchConcurrency)
	return make(chan struct{}, concurrency)
}

func (s *Session) openReadySockets(addr string, timeout time.Duration) (net.Conn, net.Conn, uint16, uint16, error) {
	deadline := time.Now().Add(timeout)
	var lastErr error = context.DeadlineExceeded
	attempts := 0
	for time.Now().Before(deadline) {
		if s.ctx.Err() != nil {
			return nil, nil, 0, 0, s.ctx.Err()
		}
		remaining := time.Until(deadline)
		videoConn, ctrlConn, width, height, err := s.tryOpenReadySockets(addr, remaining)
		if err == nil {
			return videoConn, ctrlConn, width, height, nil
		}
		lastErr = err
		attempts++
		if attempts == 1 || attempts%10 == 0 {
			if s.logger != nil {
				s.logger.Debug("scrcpy handshake retry", "serial", s.req.Serial, "addr", addr, "attempts", attempts, "error", err)
			}
		}
		sleepCtx(s.ctx, 120*time.Millisecond)
	}
	return nil, nil, 0, 0, fmt.Errorf("scrcpy handshake not ready at %s after %s: %w", addr, timeout, lastErr)
}

func (s *Session) tryOpenReadySockets(addr string, remaining time.Duration) (net.Conn, net.Conn, uint16, uint16, error) {
	dialTimeout := remaining
	if dialTimeout > 700*time.Millisecond {
		dialTimeout = 700 * time.Millisecond
	}
	videoConn, err := dialScrcpy(s.ctx, addr, dialTimeout)
	if err != nil {
		return nil, nil, 0, 0, err
	}
	tuneTCP(videoConn)
	var ctrlConn net.Conn
	defer func() {
		if err != nil {
			_ = videoConn.Close()
			if ctrlConn != nil {
				_ = ctrlConn.Close()
			}
		}
	}()
	if s.req.Control {
		ctrlConn, err = dialScrcpy(s.ctx, addr, dialTimeout)
		if err != nil {
			return nil, nil, 0, 0, err
		}
		tuneTCP(ctrlConn)
	}
	handshakeTimeout := remaining
	if handshakeTimeout > 1500*time.Millisecond {
		handshakeTimeout = 1500 * time.Millisecond
	}
	width, height, err := readHandshake(videoConn, handshakeTimeout)
	if err != nil {
		return nil, nil, 0, 0, err
	}
	return videoConn, ctrlConn, width, height, nil
}

func dialScrcpy(ctx context.Context, addr string, timeout time.Duration) (net.Conn, error) {
	deadline := time.Now().Add(timeout)
	var lastErr error = context.DeadlineExceeded
	dialer := net.Dialer{Timeout: 500 * time.Millisecond}
	for time.Now().Before(deadline) {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		conn, err := dialer.DialContext(ctx, "tcp", addr)
		if err == nil {
			return conn, nil
		}
		lastErr = err
		time.Sleep(150 * time.Millisecond)
	}
	return nil, fmt.Errorf("scrcpy socket not ready at %s: %w", addr, lastErr)
}

func readHandshake(conn net.Conn, timeout time.Duration) (uint16, uint16, error) {
	if timeout <= 0 {
		timeout = 1500 * time.Millisecond
	}
	_ = conn.SetReadDeadline(time.Now().Add(timeout))
	var dummy [1]byte
	if _, err := io.ReadFull(conn, dummy[:]); err != nil {
		return 0, 0, err
	}
	deviceName := make([]byte, 64)
	if _, err := io.ReadFull(conn, deviceName); err != nil {
		return 0, 0, err
	}
	var codec [4]byte
	if _, err := io.ReadFull(conn, codec[:]); err != nil {
		return 0, 0, err
	}
	if string(codec[:]) != "h264" {
		return 0, 0, fmt.Errorf("unsupported scrcpy codec %q", string(codec[:]))
	}
	var meta [12]byte
	if _, err := io.ReadFull(conn, meta[:]); err != nil {
		return 0, 0, err
	}
	flags := binary.BigEndian.Uint32(meta[0:4])
	if flags&sessionPacketFlag == 0 {
		return 0, 0, fmt.Errorf("expected scrcpy session packet, got flags=0x%08x", flags)
	}
	return uint16(binary.BigEndian.Uint32(meta[4:8])),
		uint16(binary.BigEndian.Uint32(meta[8:12])),
		nil
}

func tuneTCP(conn net.Conn) {
	if tcpConn, ok := conn.(*net.TCPConn); ok {
		_ = tcpConn.SetNoDelay(true)
		_ = tcpConn.SetKeepAlive(true)
		_ = tcpConn.SetKeepAlivePeriod(30 * time.Second)
	}
}

func sleepCtx(ctx context.Context, duration time.Duration) {
	timer := time.NewTimer(duration)
	defer timer.Stop()
	select {
	case <-ctx.Done():
	case <-timer.C:
	}
}

func drainControl(ctx context.Context, conn net.Conn) {
	buf := make([]byte, 4096)
	for ctx.Err() == nil {
		_ = conn.SetReadDeadline(time.Now().Add(30 * time.Second))
		if _, err := conn.Read(buf); err != nil {
			return
		}
	}
}

func (s *Session) setControl(conn net.Conn) {
	s.mu.Lock()
	old := s.ctrlConn
	s.ctrlConn = conn
	s.mu.Unlock()
	if old != nil {
		_ = old.Close()
	}
}

func (s *Session) setLaunched(launched *LaunchedServer) {
	s.mu.Lock()
	s.launched = launched
	s.mu.Unlock()
}

func (s *Session) clearLaunched(launched *LaunchedServer) {
	// Snapshot the server's log tail before dropping the pointer.
	//
	// connectAndRead clears the launch in a defer, so it runs before run() logs
	// the failure. Reading the tail from the cleared pointer made scrcpy_output
	// empty on every single failure — the one field meant to carry the device's
	// own explanation never carried anything, and every diagnosis built on its
	// emptiness was built on nothing.
	tail := launched.RecentOutput()
	s.mu.Lock()
	if s.launched == launched {
		s.launched = nil
		if len(tail) > 0 {
			s.lastOutput = tail
		}
	}
	s.mu.Unlock()
}

func (s *Session) closeControl() {
	s.mu.Lock()
	conn := s.ctrlConn
	s.ctrlConn = nil
	s.mu.Unlock()
	if conn != nil {
		_ = conn.Close()
	}
}

func (s *Session) requestIDR() {
	s.mu.Lock()
	conn := s.ctrlConn
	if conn != nil {
		s.status.IDRRequests++
	}
	s.mu.Unlock()
	if conn != nil {
		_, _ = conn.Write([]byte{resetVideoMsg})
	}
}

func (s *Session) RequestKeyframe() bool {
	s.mu.Lock()
	conn := s.ctrlConn
	if conn != nil {
		s.status.IDRRequests++
	}
	s.mu.Unlock()
	if conn == nil {
		return false
	}
	_, err := conn.Write([]byte{resetVideoMsg})
	return err == nil
}

func (s *Session) markConnected(width uint16, height uint16) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.status.Connected = true
	s.status.Width = width
	s.status.Height = height
	s.status.LastError = ""
}

func (s *Session) updateEndpoint(host string, port int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.status.Host = host
	s.status.Port = port
}

func (s *Session) markDisconnected() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.status.Connected = false
}

func (s *Session) updateDimensions(width uint16, height uint16) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.status.Width = width
	s.status.Height = height
}

func (s *Session) recordFrame(size int, isConfig bool, isKey bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.status.Frames++
	s.status.Bytes += uint64(size)
	if isConfig {
		s.status.Configs++
	}
	if isKey {
		s.status.Keyframes++
	}
	s.status.LastFrameUnix = time.Now().UnixMilli()
}

func (s *Session) recordPublishError() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.status.PublishErrs++
}

func (s *Session) bumpReconnect() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.status.Reconnects++
}

func (s *Session) setError(err error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.status.LastError = err.Error()
}

func (s *Session) setRunning(running bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.status.Running = running
	s.status.Connected = false
}

func annexBContainsIDR(data []byte) bool {
	for i := 0; i+3 < len(data); i++ {
		if data[i] == 0 && data[i+1] == 0 && data[i+2] == 1 && data[i+3]&0x1F == 5 {
			return true
		}
		if i+4 < len(data) && data[i] == 0 && data[i+1] == 0 && data[i+2] == 0 && data[i+3] == 1 && data[i+4]&0x1F == 5 {
			return true
		}
	}
	return false
}
