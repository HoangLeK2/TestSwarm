package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"devicefarm/media-adapter/internal/adapters/outbound/go2rtc"
	"devicefarm/media-adapter/internal/adapters/outbound/rtspserver"
	"devicefarm/media-adapter/internal/adapters/scrcpy"
	"github.com/go-chi/chi/v5"
)

type Server struct {
	addr       string
	manager    *scrcpy.Manager
	webrtc     *go2rtc.Client
	logger     *slog.Logger
	server     *http.Server
	mu         sync.Mutex
	sessions   map[string]webrtcSession
	streamRefs map[string]int
	stopTimers map[string]*time.Timer
	stopGrace  time.Duration
	stats      publisherStatsProvider
}

const webRTCFirstFrameWait = 4 * time.Second

type publisherStatsProvider interface {
	Stats() rtspserver.PublisherStats
}

type webrtcSession struct {
	ID       string
	Serial   string
	ViewerID string
	Expires  time.Time
}

func NewServer(addr string, manager *scrcpy.Manager, logger *slog.Logger) *Server {
	return NewServerWithWebRTC(addr, manager, go2rtc.New(go2rtc.ConfigFromEnv()), logger)
}

func NewServerWithWebRTC(addr string, manager *scrcpy.Manager, webrtc *go2rtc.Client, logger *slog.Logger) *Server {
	return &Server{
		addr:       addr,
		manager:    manager,
		webrtc:     webrtc,
		logger:     logger,
		sessions:   make(map[string]webrtcSession),
		streamRefs: make(map[string]int),
		stopTimers: make(map[string]*time.Timer),
		stopGrace:  time.Duration(envInt("MEDIA_ADAPTER_WEBRTC_STOP_GRACE_MS", 5000)) * time.Millisecond,
	}
}

func (s *Server) SetPublisherStatsProvider(provider publisherStatsProvider) {
	s.stats = provider
}

func (s *Server) Run(ctx context.Context) error {
	router := s.routes()
	server := &http.Server{
		Addr:              s.addr,
		Handler:           router,
		ReadHeaderTimeout: 2 * time.Second,
	}
	s.server = server
	ln, err := net.Listen("tcp", s.addr)
	if err != nil {
		return err
	}
	s.logger.Info("media adapter HTTP listening", "addr", ln.Addr().String())
	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdownCtx)
	}()
	err = server.Serve(ln)
	if errors.Is(err, http.ErrServerClosed) {
		return nil
	}
	return err
}

func (s *Server) routes() http.Handler {
	router := chi.NewRouter()
	router.Get("/healthz", s.handleHealth)
	router.Get("/v1/scrcpy/streams", s.handleStreams)
	router.Get("/v1/rtsp/publisher/status", s.handlePublisherStats)
	router.Route("/v1/scrcpy/streams/{serial}", func(r chi.Router) {
		r.Post("/start", func(w http.ResponseWriter, r *http.Request) {
			serial, ok := routeParam(w, r, "serial")
			if ok {
				s.handleStart(w, r, serial)
			}
		})
		r.Post("/stop", func(w http.ResponseWriter, r *http.Request) {
			serial, ok := routeParam(w, r, "serial")
			if !ok {
				return
			}
			s.manager.Stop(serial)
			writeJSON(w, http.StatusOK, map[string]any{"stopped": true})
		})
		r.Post("/keyframe", func(w http.ResponseWriter, r *http.Request) {
			serial, ok := routeParam(w, r, "serial")
			if !ok {
				return
			}
			if !s.manager.RequestKeyframe(serial) {
				writeError(w, http.StatusNotFound, "stream not found or control unavailable")
				return
			}
			writeJSON(w, http.StatusAccepted, map[string]any{"requested": true})
		})
		r.Get("/status", func(w http.ResponseWriter, r *http.Request) {
			serial, ok := routeParam(w, r, "serial")
			if !ok {
				return
			}
			status, ok := s.manager.Status(serial)
			if !ok {
				writeError(w, http.StatusNotFound, "stream not found")
				return
			}
			writeJSON(w, http.StatusOK, status)
		})
	})
	router.Post("/v1/webrtc/sessions", s.handleWebRTCSessions)
	router.Route("/v1/webrtc/sessions/{sessionID}", func(r chi.Router) {
		r.Post("/answer", func(w http.ResponseWriter, r *http.Request) {
			s.handleWebRTCAnswer(w, r, chi.URLParam(r, "sessionID"))
		})
		r.Post("/heartbeat", func(w http.ResponseWriter, r *http.Request) {
			s.handleWebRTCHeartbeat(w, r, chi.URLParam(r, "sessionID"))
		})
		r.Delete("/", func(w http.ResponseWriter, r *http.Request) {
			s.closeWebRTCSession(chi.URLParam(r, "sessionID"))
			writeJSON(w, http.StatusOK, map[string]any{"ok": true})
		})
	})
	return router
}

func routeParam(w http.ResponseWriter, r *http.Request, name string) (string, bool) {
	value, err := url.PathUnescape(chi.URLParam(r, name))
	if err != nil || strings.TrimSpace(value) == "" {
		writeError(w, http.StatusNotFound, "not found")
		return "", false
	}
	return value, true
}

func (s *Server) handleHealth(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"ok": true})
}

func (s *Server) handleStreams(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"streams": s.manager.Statuses()})
}

func (s *Server) handlePublisherStats(w http.ResponseWriter, r *http.Request) {
	if s.stats == nil {
		writeError(w, http.StatusServiceUnavailable, "publisher stats are not configured")
		return
	}
	writeJSON(w, http.StatusOK, s.stats.Stats())
}

func (s *Server) handleStart(w http.ResponseWriter, r *http.Request, serial string) {
	var body struct {
		Host         string `json:"host"`
		Port         int    `json:"port"`
		Control      *bool  `json:"control"`
		OwnsScrcpy   bool   `json:"owns_scrcpy"`
		MaxFPS       int    `json:"max_fps"`
		MaxWidth     int    `json:"max_width"`
		Bitrate      int    `json:"bitrate"`
		VideoCodec   string `json:"video_codec"`
		VideoEncoder string `json:"video_encoder"`
		LowLatency   bool   `json:"low_latency"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "invalid json body")
		return
	}
	control := true
	if body.Control != nil {
		control = *body.Control
	}
	status, err := s.manager.Start(scrcpy.StartRequest{
		Serial:       serial,
		Host:         body.Host,
		Port:         body.Port,
		Control:      control,
		OwnsScrcpy:   body.OwnsScrcpy,
		MaxFPS:       body.MaxFPS,
		MaxWidth:     body.MaxWidth,
		Bitrate:      body.Bitrate,
		VideoCodec:   body.VideoCodec,
		VideoEncoder: body.VideoEncoder,
		LowLatency:   body.LowLatency,
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	writeJSON(w, http.StatusAccepted, status)
}

func (s *Server) handleWebRTCSessions(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Serial     string `json:"serial"`
		ViewerID   string `json:"viewer_id"`
		TTLSeconds int    `json:"ttl_seconds"`
		Control    *bool  `json:"control"`
		MaxFPS     int    `json:"max_fps"`
		MaxWidth   int    `json:"max_width"`
		Bitrate    int    `json:"bitrate"`
		Profile    string `json:"profile"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "invalid json body")
		return
	}
	serial := strings.TrimSpace(body.Serial)
	if serial == "" {
		writeError(w, http.StatusBadRequest, "serial is required")
		return
	}
	if body.TTLSeconds <= 0 {
		body.TTLSeconds = 300
	}
	if body.TTLSeconds > 1800 {
		body.TTLSeconds = 1800
	}
	maxFPS, maxWidth, bitrate := normalizeWebRTCProfile(body.Profile, body.MaxFPS, body.MaxWidth, body.Bitrate)
	now := time.Now()
	s.mu.Lock()
	stopSerials := s.gcExpiredLocked(now)
	s.cancelPendingStreamStopLocked(serial)
	stopSerials = removeSerial(stopSerials, serial)
	s.mu.Unlock()
	s.stopStreams(stopSerials)

	status, err := s.manager.Start(scrcpy.StartRequest{
		Serial: serial,
		// Keep scrcpy control socket open even for observe-only WebRTC viewers.
		// The socket is required to request IDR/keyframes; viewer input remains
		// governed by the WebRTC/control API layer, not by this internal socket.
		Control:    true,
		OwnsScrcpy: true,
		MaxFPS:     maxFPS,
		MaxWidth:   maxWidth,
		Bitrate:    bitrate,
		VideoCodec: "h264",
		LowLatency: scrcpy.LowLatencyEnabled(),
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	status, ready := s.manager.WaitForFirstFrame(r.Context(), serial, webRTCFirstFrameWait)
	if !ready {
		if s.logger != nil {
			s.logger.Warn("media adapter stream has no first frame",
				"serial", serial,
				"connected", status.Connected,
				"frames", status.Frames,
				"publish_errors", status.PublishErrs,
				"error", status.LastError)
		}
		// Do not stop here. On slower or fragile encoders (notably Note 10+
		// Exynos), the internal session may still be climbing the codec/retry
		// ladder. Stopping on every viewer retry cold-starts scrcpy again and
		// keeps the device permanently at frames=0.
		w.Header().Set("Retry-After", "1.00")
		writeError(w, http.StatusTooEarly, "media adapter stream has no frames")
		return
	}
	expires := now.Add(time.Duration(body.TTLSeconds) * time.Second)
	session := webrtcSession{
		ID:       newSessionID(),
		Serial:   serial,
		ViewerID: strings.TrimSpace(body.ViewerID),
		Expires:  expires,
	}
	s.mu.Lock()
	stopSerials = s.gcExpiredLocked(time.Now())
	s.cancelPendingStreamStopLocked(serial)
	s.sessions[session.ID] = session
	s.streamRefs[serial]++
	s.mu.Unlock()
	s.stopStreams(removeSerial(stopSerials, serial))
	writeJSON(w, http.StatusAccepted, map[string]any{
		"id":            session.ID,
		"serial":        serial,
		"viewer_id":     session.ViewerID,
		"stream_name":   s.webrtc.StreamName(serial),
		"stream_source": s.webrtc.StreamSource(serial),
		"expires_at":    expires.UTC().Format(time.RFC3339Nano),
		"scrcpy":        status,
	})
}

func (s *Server) handleWebRTCAnswer(w http.ResponseWriter, r *http.Request, sessionID string) {
	var offer go2rtc.SessionDescription
	if err := json.NewDecoder(r.Body).Decode(&offer); err != nil {
		writeError(w, http.StatusBadRequest, "invalid json body")
		return
	}
	if offer.Type != "offer" || strings.TrimSpace(offer.SDP) == "" {
		writeError(w, http.StatusBadRequest, "WebRTC offer is required")
		return
	}
	now := time.Now()
	s.mu.Lock()
	stopSerials := s.gcExpiredLocked(now)
	session, ok := s.sessions[sessionID]
	s.mu.Unlock()
	s.stopStreams(stopSerials)
	if !ok {
		writeError(w, http.StatusNotFound, "WebRTC session not found")
		return
	}
	answer, err := s.webrtc.Answer(r.Context(), session.Serial, offer)
	if err != nil {
		var httpErr go2rtc.HTTPError
		if errors.As(err, &httpErr) {
			writeError(w, http.StatusBadGateway, httpErr.Error())
			return
		}
		writeError(w, http.StatusTooEarly, "go2rtc media source is not ready")
		return
	}
	writeJSON(w, http.StatusOK, answer)
}

func (s *Server) handleWebRTCHeartbeat(w http.ResponseWriter, r *http.Request, sessionID string) {
	var body struct {
		TTLSeconds int `json:"ttl_seconds"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "invalid json body")
		return
	}
	if body.TTLSeconds <= 0 {
		body.TTLSeconds = 300
	}
	if body.TTLSeconds > 1800 {
		body.TTLSeconds = 1800
	}
	now := time.Now()
	expires := now.Add(time.Duration(body.TTLSeconds) * time.Second)
	s.mu.Lock()
	stopSerials := s.gcExpiredLocked(now)
	session, ok := s.sessions[sessionID]
	if ok {
		session.Expires = expires
		s.sessions[sessionID] = session
	}
	s.mu.Unlock()
	s.stopStreams(stopSerials)
	if !ok {
		writeError(w, http.StatusNotFound, "WebRTC session not found")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"ok":         true,
		"id":         session.ID,
		"serial":     session.Serial,
		"viewer_id":  session.ViewerID,
		"expires_at": expires.UTC().Format(time.RFC3339Nano),
	})
}

func (s *Server) closeWebRTCSession(sessionID string) {
	var stopSerials []string
	s.mu.Lock()
	session, ok := s.sessions[sessionID]
	if ok {
		delete(s.sessions, sessionID)
	}
	if ok {
		refs := s.streamRefs[session.Serial] - 1
		if refs <= 0 {
			delete(s.streamRefs, session.Serial)
			if stopSerial := s.scheduleStreamStopLocked(session.Serial); stopSerial != "" {
				stopSerials = append(stopSerials, stopSerial)
			}
		} else {
			s.streamRefs[session.Serial] = refs
		}
	}
	s.mu.Unlock()
	s.stopStreams(stopSerials)
}

func (s *Server) gcExpiredLocked(now time.Time) []string {
	var stopSerials []string
	for id, session := range s.sessions {
		if session.Expires.After(now) {
			continue
		}
		delete(s.sessions, id)
		refs := s.streamRefs[session.Serial] - 1
		if refs <= 0 {
			delete(s.streamRefs, session.Serial)
			if stopSerial := s.scheduleStreamStopLocked(session.Serial); stopSerial != "" {
				stopSerials = append(stopSerials, stopSerial)
			}
			continue
		}
		s.streamRefs[session.Serial] = refs
	}
	return stopSerials
}

func (s *Server) cancelPendingStreamStopLocked(serial string) {
	timer := s.stopTimers[serial]
	if timer == nil {
		return
	}
	timer.Stop()
	delete(s.stopTimers, serial)
}

func (s *Server) scheduleStreamStopLocked(serial string) string {
	if s.streamRefs[serial] > 0 {
		return ""
	}
	s.cancelPendingStreamStopLocked(serial)
	if s.stopGrace <= 0 {
		return serial
	}
	s.stopTimers[serial] = time.AfterFunc(s.stopGrace, func() {
		s.stopStreamIfIdle(serial)
	})
	return ""
}

func (s *Server) stopStreamIfIdle(serial string) {
	s.mu.Lock()
	if s.streamRefs[serial] > 0 {
		delete(s.stopTimers, serial)
		s.mu.Unlock()
		return
	}
	delete(s.stopTimers, serial)
	s.mu.Unlock()
	s.manager.Stop(serial)
}

func (s *Server) stopStreams(serials []string) {
	for _, serial := range serials {
		s.manager.Stop(serial)
	}
}

func normalizeWebRTCProfile(profile string, fps int, width int, bitrate int) (int, int, int) {
	if fps > 0 && width > 0 && bitrate > 0 {
		return fps, width, bitrate
	}
	switch strings.ToLower(strings.TrimSpace(profile)) {
	case "degraded", "preview", "thumbnail", "thumb":
		if fps <= 0 {
			fps = 1
		}
		if width <= 0 {
			width = 320
		}
		if bitrate <= 0 {
			bitrate = 150000
		}
	case "focused", "control":
		if fps <= 0 {
			fps = 15
		}
		if width <= 0 {
			width = 540
		}
		if bitrate <= 0 {
			bitrate = 800000
		}
	default:
		if fps <= 0 {
			fps = 12
		}
		if width <= 0 {
			width = 360
		}
		if bitrate <= 0 {
			bitrate = 350000
		}
	}
	return fps, width, bitrate
}

func newSessionID() string {
	value := time.Now().UnixNano()
	value ^= value << 13
	value ^= value >> 7
	value ^= value << 17
	if value < 0 {
		value = -value
	}
	return strconv.FormatInt(time.Now().UnixNano(), 36) + "-" + strconv.FormatInt(value, 36)
}

func removeSerial(serials []string, serial string) []string {
	if len(serials) == 0 {
		return serials
	}
	next := serials[:0]
	for _, item := range serials {
		if item != serial {
			next = append(next, item)
		}
	}
	return next
}

func envInt(name string, fallback int) int {
	value := strings.TrimSpace(os.Getenv(name))
	if value == "" {
		return fallback
	}
	parsed, err := strconv.Atoi(value)
	if err != nil || parsed < 0 {
		return fallback
	}
	return parsed
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"error": message})
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	data, err := json.Marshal(value)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Length", strconv.Itoa(len(data)))
	w.WriteHeader(status)
	_, _ = w.Write(data)
}
