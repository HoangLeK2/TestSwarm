package scrcpy

import (
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
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
	LowLatency bool
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
}

func NewManager(publisher Publisher, logger *slog.Logger) *Manager {
	return NewManagerWithLauncher(publisher, NewADBLauncher(ConfigFromEnv()), logger)
}

func NewManagerWithLauncher(publisher Publisher, launcher Launcher, logger *slog.Logger) *Manager {
	if adbLauncher, ok := launcher.(*ADBLauncher); ok {
		adbLauncher.logger = logger
	}
	return &Manager{
		publisher: publisher,
		launcher:  launcher,
		logger:    logger,
		sessions:  make(map[string]*Session),
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
	if current != nil {
		current.Stop()
	}
	session := NewSession(req, m.publisher, m.launcher, m.logger)
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
}

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
		req:       req,
		publisher: publisher,
		launcher:  launcher,
		logger:    logger,
		ctx:       ctx,
		cancel:    cancel,
		done:      make(chan struct{}),
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
		if err := s.connectAndRead(); err != nil && s.ctx.Err() == nil {
			s.setError(err)
			if s.logger != nil {
				s.logger.Warn("scrcpy direct session failed", "serial", s.req.Serial, "error", err)
			}
		}
		s.markDisconnected()
		if s.ctx.Err() != nil {
			break
		}
		time.Sleep(backoff)
		backoff *= 2
		if backoff > 2*time.Second {
			backoff = 2 * time.Second
		}
		s.bumpReconnect()
	}
	s.setRunning(false)
}

func (s *Session) connectAndRead() error {
	host := s.req.Host
	port := s.req.Port
	if s.req.OwnsScrcpy {
		if s.launcher == nil {
			return errors.New("scrcpy launcher is unavailable")
		}
		launched, err := s.launcher.Start(s.ctx, s.req)
		if err != nil {
			return err
		}
		s.setLaunched(launched)
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
	s.mu.Lock()
	if s.launched == launched {
		s.launched = nil
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
