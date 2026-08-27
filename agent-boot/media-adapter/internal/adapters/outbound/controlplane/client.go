package controlplane

import (
	"context"
	"crypto/tls"
	"fmt"
	"log/slog"
	"net"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"devicefarm/media-adapter/internal/adapters/adbserver"
	"devicefarm/media-adapter/internal/adapters/outbound/go2rtc"
	"devicefarm/media-adapter/internal/adapters/scrcpy"
	"devicefarm/media-adapter/internal/domain/stream"
	"devicefarm/media-adapter/internal/grpcapi/relaypb"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"
	_ "google.golang.org/grpc/encoding/gzip"
	"google.golang.org/grpc/keepalive"
	"google.golang.org/grpc/metadata"
)

type Config struct {
	Enabled         bool
	Server          string
	TLS             bool
	RootCertFile    string
	APIKey          string
	EnrollmentToken string
	AdapterID       string
	RelayID         string
	HeartbeatEvery  time.Duration
}

type Client struct {
	cfg     Config
	manager *scrcpy.Manager
	webrtc  *go2rtc.Client
	logger  *slog.Logger

	mu         sync.Mutex
	sessions   map[string]mediaSession
	streamRefs map[string]int
	stopTimers map[string]*time.Timer
	stopGrace  time.Duration
}

type mediaSession struct {
	ID       string
	Serial   string
	ViewerID string
	Expires  time.Time
}

const webRTCFirstFrameWait = 4 * time.Second

var viewerAttachKeyframeDelays = []time.Duration{
	300 * time.Millisecond,
	800 * time.Millisecond,
	1600 * time.Millisecond,
	3000 * time.Millisecond,
}

func ConfigFromEnv() Config {
	server := envDefault("MEDIA_ADAPTER_CONTROL_GRPC_SERVER", envDefault("RELAY_SERVER", "host.docker.internal:50051"))
	return Config{
		Enabled:         envBool("MEDIA_ADAPTER_CONTROL_GRPC_ENABLED", false),
		Server:          normalizeServer(server),
		TLS:             envBool("MEDIA_ADAPTER_CONTROL_GRPC_TLS", envBool("RELAY_GRPC_TLS", false)),
		RootCertFile:    envDefault("MEDIA_ADAPTER_CONTROL_GRPC_ROOT_CERT_FILE", envDefault("RELAY_GRPC_ROOT_CERT_FILE", "")),
		APIKey:          envDefault("MEDIA_ADAPTER_CONTROL_GRPC_API_KEY", envDefault("RELAY_API_KEY", "")),
		EnrollmentToken: envDefault("MEDIA_ADAPTER_CONTROL_GRPC_ENROLLMENT_TOKEN", envDefault("RELAY_ENROLLMENT_TOKEN", "")),
		AdapterID:       envDefault("MEDIA_ADAPTER_ID", envDefault("RELAY_ID", "")),
		RelayID:         envDefault("RELAY_ID", ""),
		HeartbeatEvery:  time.Duration(envInt("MEDIA_ADAPTER_CONTROL_HEARTBEAT_SECONDS", 5)) * time.Second,
	}
}

func New(cfg Config, manager *scrcpy.Manager, webrtc *go2rtc.Client, logger *slog.Logger) *Client {
	if cfg.AdapterID == "" {
		host, _ := os.Hostname()
		cfg.AdapterID = "media-" + host
	}
	if cfg.HeartbeatEvery <= 0 {
		cfg.HeartbeatEvery = 5 * time.Second
	}
	return &Client{
		cfg:        cfg,
		manager:    manager,
		webrtc:     webrtc,
		logger:     logger,
		sessions:   make(map[string]mediaSession),
		streamRefs: make(map[string]int),
		stopTimers: make(map[string]*time.Timer),
		stopGrace:  time.Duration(envInt("MEDIA_ADAPTER_WEBRTC_STOP_GRACE_MS", 5000)) * time.Millisecond,
	}
}

func (c *Client) Run(ctx context.Context) {
	if !c.cfg.Enabled {
		c.logger.Info("media adapter gRPC control disabled")
		return
	}
	delay := 300 * time.Millisecond
	for ctx.Err() == nil {
		err := c.connectOnce(ctx)
		if err != nil && ctx.Err() == nil {
			c.logger.Warn("media adapter gRPC control failed", "server", c.cfg.Server, "error", err, "retry", delay.String())
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(delay):
		}
		delay *= 2
		if delay > 5*time.Second {
			delay = 5 * time.Second
		}
	}
}

func (c *Client) connectOnce(ctx context.Context) error {
	connCtx, cancelConn := context.WithCancel(ctx)
	defer cancelConn()
	conn, err := grpc.NewClient(
		c.cfg.Server,
		grpc.WithTransportCredentials(c.transportCredentials()),
		grpc.WithKeepaliveParams(keepalive.ClientParameters{
			Time:                10 * time.Second,
			Timeout:             5 * time.Second,
			PermitWithoutStream: true,
		}),
	)
	if err != nil {
		return err
	}
	defer conn.Close()

	md := metadata.Pairs(
		"x-relay-api-key", c.cfg.APIKey,
		"x-relay-enrollment-token", c.cfg.EnrollmentToken,
		"x-media-adapter-id", c.cfg.AdapterID,
	)
	streamCtx := metadata.NewOutgoingContext(connCtx, md)
	streamClient, err := relaypb.NewMediaAdapterControlServiceClient(conn).ControlStream(streamCtx)
	if err != nil {
		return err
	}
	sendQ := make(chan *relaypb.MediaAdapterMsg, 256)
	sendErr := make(chan error, 1)
	go func() {
		for msg := range sendQ {
			if err := streamClient.Send(msg); err != nil {
				sendErr <- err
				return
			}
		}
		sendErr <- nil
	}()
	sendQ <- c.registerMsg(connCtx)
	ticker := time.NewTicker(c.cfg.HeartbeatEvery)
	var heartbeatWG sync.WaitGroup
	heartbeatWG.Add(1)
	go func() {
		defer heartbeatWG.Done()
		for {
			select {
			case <-connCtx.Done():
				return
			case <-ticker.C:
				select {
				case sendQ <- c.heartbeatMsg(connCtx):
				default:
					c.logger.Warn("media adapter heartbeat dropped: send queue full")
				}
			}
		}
	}()
	closeSend := func() error {
		cancelConn()
		ticker.Stop()
		heartbeatWG.Wait()
		close(sendQ)
		err := <-sendErr
		return err
	}
	for {
		select {
		case err := <-sendErr:
			cancelConn()
			ticker.Stop()
			heartbeatWG.Wait()
			return err
		default:
		}
		cmd, err := streamClient.Recv()
		if err != nil {
			if sendErr := closeSend(); sendErr != nil && !strings.Contains(sendErr.Error(), "context canceled") {
				c.logger.Debug("media adapter sender stopped after recv error", "error", sendErr)
			}
			return err
		}
		if result := c.handleCommand(connCtx, cmd); result != nil {
			select {
			case sendQ <- result:
			case <-connCtx.Done():
				return connCtx.Err()
			}
		}
	}
}

func (c *Client) transportCredentials() credentials.TransportCredentials {
	if !c.cfg.TLS {
		return insecure.NewCredentials()
	}
	if c.cfg.RootCertFile != "" {
		if creds, err := credentials.NewClientTLSFromFile(c.cfg.RootCertFile, ""); err == nil {
			return creds
		}
		c.logger.Warn("media adapter root cert failed, using system roots", "file", c.cfg.RootCertFile)
	}
	return credentials.NewTLS(&tls.Config{MinVersion: tls.VersionTLS12})
}

func (c *Client) registerMsg(ctx context.Context) *relaypb.MediaAdapterMsg {
	host, _ := os.Hostname()
	return &relaypb.MediaAdapterMsg{Payload: &relaypb.MediaAdapterMsg_Register{
		Register: &relaypb.MediaAdapterRegister{
			AdapterId:            c.cfg.AdapterID,
			RelayId:              c.cfg.RelayID,
			Serials:              listDeviceSerials(ctx),
			Hostname:             host,
			Ip:                   outboundIP(),
			AdapterVersion:       "0.1.4",
			Go2RtcBaseUrl:        envDefault("MEDIA_ADAPTER_GO2RTC_URL", envDefault("GO2RTC_URL", "")),
			StreamSourceTemplate: envDefault("MEDIA_ADAPTER_GO2RTC_RTSP_PUBLISH_TEMPLATE", envDefault("MEDIA_ADAPTER_GO2RTC_RTSP_SOURCE_TEMPLATE", "")),
		},
	}}
}

func (c *Client) heartbeatMsg(ctx context.Context) *relaypb.MediaAdapterMsg {
	serialSet := map[string]struct{}{}
	for _, serial := range listDeviceSerials(ctx) {
		serialSet[serial] = struct{}{}
	}
	statuses := c.manager.Statuses()
	streams := make([]*relaypb.MediaStreamStatus, 0, len(statuses))
	for _, status := range statuses {
		serialSet[status.Serial] = struct{}{}
		streams = append(streams, c.statusProto(status))
	}
	serials := make([]string, 0, len(serialSet))
	for serial := range serialSet {
		serials = append(serials, serial)
	}
	return &relaypb.MediaAdapterMsg{Payload: &relaypb.MediaAdapterMsg_Heartbeat{
		Heartbeat: &relaypb.MediaAdapterHeartbeat{
			AdapterId: c.cfg.AdapterID,
			Serials:   serials,
			Streams:   streams,
		},
	}}
}

func (c *Client) handleCommand(ctx context.Context, cmd *relaypb.MediaAdapterCommand) *relaypb.MediaAdapterMsg {
	switch payload := cmd.GetPayload().(type) {
	case *relaypb.MediaAdapterCommand_StartSession:
		return c.startSession(ctx, payload.StartSession)
	case *relaypb.MediaAdapterCommand_AnswerSession:
		return c.answerSession(ctx, payload.AnswerSession)
	case *relaypb.MediaAdapterCommand_HeartbeatSession:
		return c.heartbeatSession(payload.HeartbeatSession)
	case *relaypb.MediaAdapterCommand_CloseSession:
		return c.closeSession(payload.CloseSession)
	default:
		return nil
	}
}

func (c *Client) startSession(ctx context.Context, cmd *relaypb.MediaAdapterStartSessionCmd) *relaypb.MediaAdapterMsg {
	ttl := int(cmd.GetTtlSeconds())
	if ttl <= 0 {
		ttl = 300
	}
	status, err := c.manager.Start(scrcpy.StartRequest{
		Serial: cmd.GetSerial(),
		// Keep scrcpy control socket open even for observe-only WebRTC viewers.
		// It is required for fast IDR/keyframe requests; viewer input is a
		// separate permission concern handled above this adapter.
		Control:    true,
		OwnsScrcpy: true,
		MaxFPS:     int(cmd.GetMaxFps()),
		MaxWidth:   int(cmd.GetMaxWidth()),
		Bitrate:    int(cmd.GetBitrate()),
		VideoCodec: "h264",
		LowLatency: scrcpy.LowLatencyEnabled(),
	})
	if err != nil {
		return c.result(cmd.GetRequestId(), false, err.Error(), 250, mediaSession{}, "", "")
	}
	status, ready := c.manager.WaitForFirstFrame(ctx, cmd.GetSerial(), webRTCFirstFrameWait)
	if !ready {
		if c.logger != nil {
			c.logger.Warn("media adapter stream has no first frame",
				"serial", cmd.GetSerial(),
				"connected", status.Connected,
				"frames", status.Frames,
				"publish_errors", status.PublishErrs,
				"error", status.LastError)
		}
		// Keep the scrcpy session alive. Returning 425 tells the backend/browser
		// to retry, while the manager continues its encoder fallback loop. If we
		// stop here, every retry restarts the fragile device from zero and the
		// fallback ladder never has time to produce a first frame.
		return c.result(cmd.GetRequestId(), false, "media adapter stream has no frames", 1000, mediaSession{Serial: cmd.GetSerial(), ViewerID: cmd.GetViewerId()}, "", "")
	}
	// A viewer is opening this device, so force fresh IDRs around attachment.
	//
	// scrcpy only encodes when the screen changes, so an idle phone simply
	// stops producing frames — a 2.83s stretch with no frames at all was
	// measured on a live stream. When Manager.Start reuses an already-running
	// session (the common case: the device was already publishing at the 1fps
	// visible profile) nothing else emits a keyframe, and the viewer stares at
	// an empty player until something happens to move on the phone.
	//
	// Nothing else covers this. The OnPlay hook that used to request keyframes
	// only fires when a client PLAYs from the adapter's own RTSP server, and in
	// the push topology go2rtc is pushed to rather than played from. The
	// backend does not reach the device either: with
	// MEDIA_WEBRTC_SIGNALING_PLANE=backend it talks straight to go2rtc, so the
	// adapter's answerSession never runs and this start command is the only
	// point where a viewer's arrival is visible on this side of the NAT. A
	// single request here is still too early: the browser only attaches after
	// this command returns and the backend finishes the go2rtc answer. Keep the
	// burst short and session-scoped so it fixes first paint without becoming a
	// steady-state IDR loop.

	if err := c.webrtc.RegisterStream(ctx, cmd.GetSerial()); err != nil {
		c.logger.Warn("go2rtc stream register failed", "serial", cmd.GetSerial(), "error", err)
	}
	session := mediaSession{
		ID:       newID(),
		Serial:   cmd.GetSerial(),
		ViewerID: cmd.GetViewerId(),
		Expires:  time.Now().Add(time.Duration(ttl) * time.Second),
	}
	c.mu.Lock()
	c.cancelPendingStopLocked(session.Serial)
	c.sessions[session.ID] = session
	c.streamRefs[session.Serial]++
	c.mu.Unlock()
	c.requestKeyframe(session.Serial)
	c.requestKeyframeBurst(session)
	return c.result(cmd.GetRequestId(), true, "", 0, session, "", "")
}

// requestKeyframe asks the device for an immediate IDR so a newly attached
// viewer has something to decode without waiting for the screen to change.
//
// Best effort: it fails when scrcpy has not finished connecting, which is fine
// — the first frames of a fresh session are a keyframe anyway. The value is on
// re-attach to a device that has been sitting idle.
func (c *Client) requestKeyframe(serial string) {
	if c.manager == nil || serial == "" {
		return
	}
	if !c.manager.RequestKeyframe(serial) && c.logger != nil {
		c.logger.Debug("keyframe request skipped", "serial", serial)
	}
}

func (c *Client) requestKeyframeBurst(session mediaSession) {
	if session.ID == "" || session.Serial == "" {
		return
	}
	for _, delay := range viewerAttachKeyframeDelays {
		delay := delay
		time.AfterFunc(delay, func() {
			if c.sessionActive(session.ID, session.Serial) {
				c.requestKeyframe(session.Serial)
			}
		})
	}
}

func (c *Client) sessionActive(sessionID string, serial string) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	session, ok := c.sessions[sessionID]
	return ok && session.Serial == serial
}

func (c *Client) answerSession(ctx context.Context, cmd *relaypb.MediaAdapterAnswerSessionCmd) *relaypb.MediaAdapterMsg {
	c.mu.Lock()
	session, ok := c.sessions[cmd.GetSessionId()]
	c.mu.Unlock()
	if !ok {
		return c.result(cmd.GetRequestId(), false, "WebRTC session not found", 250, mediaSession{}, "", "")
	}
	// A viewer is attaching right now, so force a fresh IDR.
	//
	// scrcpy only encodes when the screen changes. On an idle device the stream
	// simply stops — gaps of several seconds are normal — so a new viewer sees
	// nothing until something moves on the phone, however healthy the pipeline
	// is. Measured on a live stream: a 2.83s stretch with no frames at all.
	//
	// The RTSP-push topology removes the usual trigger: go2rtc is pushed to, it
	// never PLAYs from the adapter, so the OnPlay hook that used to request a
	// keyframe never fires for real viewers. This is now the only thing asking.
	c.requestKeyframe(session.Serial)

	answer, err := c.webrtc.Answer(ctx, session.Serial, go2rtc.SessionDescription{
		Type: cmd.GetSdpType(),
		SDP:  cmd.GetSdp(),
	})
	if err != nil {
		return c.result(cmd.GetRequestId(), false, err.Error(), 250, session, "", "")
	}
	return c.result(cmd.GetRequestId(), true, "", 0, session, answer.Type, answer.SDP)
}

func (c *Client) heartbeatSession(cmd *relaypb.MediaAdapterHeartbeatSessionCmd) *relaypb.MediaAdapterMsg {
	ttl := int(cmd.GetTtlSeconds())
	if ttl <= 0 {
		ttl = 300
	}
	c.mu.Lock()
	session, ok := c.sessions[cmd.GetSessionId()]
	if ok {
		session.Expires = time.Now().Add(time.Duration(ttl) * time.Second)
		c.sessions[session.ID] = session
	}
	c.mu.Unlock()
	if !ok {
		return c.result(cmd.GetRequestId(), false, "WebRTC session not found", 250, mediaSession{}, "", "")
	}
	return c.result(cmd.GetRequestId(), true, "", 0, session, "", "")
}

func (c *Client) closeSession(cmd *relaypb.MediaAdapterCloseSessionCmd) *relaypb.MediaAdapterMsg {
	c.mu.Lock()
	session, ok := c.sessions[cmd.GetSessionId()]
	if ok {
		delete(c.sessions, cmd.GetSessionId())
		refs := c.streamRefs[session.Serial] - 1
		if refs <= 0 {
			delete(c.streamRefs, session.Serial)
			c.scheduleStopLocked(session.Serial)
		} else {
			c.streamRefs[session.Serial] = refs
		}
	}
	c.mu.Unlock()
	if !ok {
		return c.result(cmd.GetRequestId(), true, "", 0, mediaSession{ID: cmd.GetSessionId()}, "", "")
	}
	return c.result(cmd.GetRequestId(), true, "", 0, session, "", "")
}

func (c *Client) result(requestID string, ok bool, errText string, retryAfterMS int32, session mediaSession, sdpType string, sdp string) *relaypb.MediaAdapterMsg {
	return &relaypb.MediaAdapterMsg{Payload: &relaypb.MediaAdapterMsg_SessionResult{
		SessionResult: &relaypb.MediaAdapterSessionResult{
			RequestId:       requestID,
			Ok:              ok,
			Error:           errText,
			RetryAfterMs:    retryAfterMS,
			SessionId:       session.ID,
			Serial:          session.Serial,
			ViewerId:        session.ViewerID,
			StreamName:      stream.StreamName(session.Serial),
			StreamSource:    c.webrtc.StreamSource(session.Serial),
			ExpiresAtUnixMs: session.Expires.UnixMilli(),
			SdpType:         sdpType,
			Sdp:             sdp,
		},
	}}
}

func (c *Client) statusProto(status scrcpy.Status) *relaypb.MediaStreamStatus {
	return &relaypb.MediaStreamStatus{
		Serial:          status.Serial,
		StreamName:      c.webrtc.StreamName(status.Serial),
		StreamSource:    c.webrtc.StreamSource(status.Serial),
		Active:          status.Running,
		Connected:       status.Connected,
		Width:           uint32(status.Width),
		Height:          uint32(status.Height),
		Frames:          status.Frames,
		Bytes:           status.Bytes,
		Keyframes:       status.Keyframes,
		PublishErrors:   status.PublishErrs,
		LastFrameUnixMs: status.LastFrameUnix,
		Error:           status.LastError,
	}
}

func (c *Client) cancelPendingStopLocked(serial string) {
	if timer := c.stopTimers[serial]; timer != nil {
		timer.Stop()
		delete(c.stopTimers, serial)
	}
}

func (c *Client) scheduleStopLocked(serial string) {
	c.cancelPendingStopLocked(serial)
	c.stopTimers[serial] = time.AfterFunc(c.stopGrace, func() {
		c.manager.Stop(serial)
		c.mu.Lock()
		delete(c.stopTimers, serial)
		c.mu.Unlock()
	})
}

func listDeviceSerials(ctx context.Context) []string {
	adb := envDefault("MEDIA_ADAPTER_ADB_PATH", "adb")
	return adbserver.DeviceSerials(ctx, adb)
}

func outboundIP() string {
	conn, err := net.DialTimeout("udp", "8.8.8.8:80", 100*time.Millisecond)
	if err != nil {
		return ""
	}
	defer conn.Close()
	if addr, ok := conn.LocalAddr().(*net.UDPAddr); ok {
		return addr.IP.String()
	}
	return ""
}

func normalizeServer(value string) string {
	value = strings.TrimSpace(value)
	for _, prefix := range []string{"grpcs://", "grpc://", "https://", "http://", "wss://", "ws://"} {
		value = strings.TrimPrefix(value, prefix)
	}
	if !strings.Contains(value, ":") {
		return value + ":50051"
	}
	return value
}

func newID() string {
	return strconv.FormatInt(time.Now().UnixNano(), 36)
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

func envBool(name string, fallback bool) bool {
	value := strings.TrimSpace(os.Getenv(name))
	if value == "" {
		return fallback
	}
	switch strings.ToLower(value) {
	case "1", "true", "yes", "on":
		return true
	case "0", "false", "no", "off":
		return false
	default:
		return fallback
	}
}
