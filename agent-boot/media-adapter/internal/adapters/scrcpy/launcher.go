package scrcpy

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"devicefarm/media-adapter/internal/adapters/adbserver"
)

const (
	defaultScrcpyVersion    = "4.1"
	defaultDeviceDir        = "/data/local/tmp/device-farm"
	defaultLocalServerPath  = "/app/media-adapter/assets/scrcpy-server"
	defaultForwardHost      = "127.0.0.1"
	defaultLaunchVerifyTTLS = 300

	// Budget for the getprop probe in deviceSignature. Generous on purpose: a
	// timeout here silently costs the device its safe profile, and the result
	// is cached, so the cost of waiting is paid once rather than per launch.
	deviceSignatureProbeTimeout = 5 * time.Second
)

type Launcher interface {
	Start(ctx context.Context, req StartRequest) (*LaunchedServer, error)
}

type LauncherConfig struct {
	ADBPath       string
	ServerPath    string
	ServerVersion string
	DeviceDir     string
	ForwardHost   string
	VerifyTTL     time.Duration
	Cleanup       bool
}

type ADBLauncher struct {
	cfg     LauncherConfig
	logger  *slog.Logger
	mu      sync.Mutex
	ready   map[string]time.Time
	scripts map[string]time.Time
	// Last known `getprop` signature per serial. See deviceSignature.
	signatures map[string]deviceProbe
}

// deviceProbe is one cached getprop result. probedAt drives refresh; value is
// kept indefinitely as the fallback for a probe that fails.
type deviceProbe struct {
	value    string
	probedAt time.Time
}

type LaunchedServer struct {
	Serial string
	Host   string
	Port   int

	SafeProfile  bool
	CodecLevel   int
	VideoEncoder string

	cancel  context.CancelFunc
	cmd     *exec.Cmd
	logger  *slog.Logger
	cleanup func(context.Context)

	// Ring of the server's own log lines. When a device refuses to encode, the
	// reason is printed here and nowhere else — the adapter only sees a socket
	// that never opens. Keeping the tail lets the failure path report why.
	outMu   sync.Mutex
	outTail []string
}

// recentOutputCap bounds the retained scrcpy-server log tail. The interesting
// lines (chosen encoder, each codec option, the exception) are the last few
// before it dies, so a short ring is enough.
const recentOutputCap = 12

// RecentOutput returns the last lines scrcpy-server printed, oldest first.
func (s *LaunchedServer) RecentOutput() []string {
	if s == nil {
		return nil
	}
	s.outMu.Lock()
	defer s.outMu.Unlock()
	return append([]string(nil), s.outTail...)
}

func (s *LaunchedServer) recordOutput(line string) {
	s.outMu.Lock()
	defer s.outMu.Unlock()
	s.outTail = append(s.outTail, line)
	if len(s.outTail) > recentOutputCap {
		s.outTail = s.outTail[len(s.outTail)-recentOutputCap:]
	}
}

func NewADBLauncher(cfg LauncherConfig) *ADBLauncher {
	if cfg.ADBPath == "" {
		cfg.ADBPath = "adb"
	}
	if cfg.ServerPath == "" {
		cfg.ServerPath = defaultLocalServerPath
	}
	if cfg.ServerVersion == "" {
		cfg.ServerVersion = defaultScrcpyVersion
	}
	if cfg.DeviceDir == "" {
		cfg.DeviceDir = defaultDeviceDir
	}
	if cfg.ForwardHost == "" {
		cfg.ForwardHost = forwardHostFromEnv()
	}
	if cfg.VerifyTTL <= 0 {
		cfg.VerifyTTL = defaultLaunchVerifyTTLS * time.Second
	}
	return &ADBLauncher{
		cfg:        cfg,
		ready:      make(map[string]time.Time),
		scripts:    make(map[string]time.Time),
		signatures: make(map[string]deviceProbe),
	}
}

func ConfigFromEnv() LauncherConfig {
	return LauncherConfig{
		ADBPath:       envDefault("MEDIA_ADAPTER_ADB_PATH", "adb"),
		ServerPath:    envDefault("MEDIA_ADAPTER_SCRCPY_SERVER_PATH", defaultLocalServerPath),
		ServerVersion: envDefault("MEDIA_ADAPTER_SCRCPY_SERVER_VERSION", defaultScrcpyVersion),
		DeviceDir:     envDefault("MEDIA_ADAPTER_SCRCPY_DEVICE_DIR", defaultDeviceDir),
		ForwardHost:   envDefault("MEDIA_ADAPTER_ADB_FORWARD_HOST", forwardHostFromEnv()),
		VerifyTTL:     time.Duration(envInt("MEDIA_ADAPTER_SCRCPY_VERIFY_TTL_S", defaultLaunchVerifyTTLS)) * time.Second,
		Cleanup:       envBool("MEDIA_ADAPTER_SCRCPY_CLEANUP", false),
	}
}

func (l *ADBLauncher) Start(ctx context.Context, req StartRequest) (*LaunchedServer, error) {
	if req.Serial == "" {
		return nil, errors.New("serial is required")
	}
	req.normalize()
	deviceSignature := l.deviceSignature(ctx, req.Serial)
	original := req
	safeProfile := needsDeviceSafeProfile(deviceSignature)
	req = applyDeviceSafeProfile(req, deviceSignature)
	if launchProfileChanged(original, req) {
		l.logLine(slog.LevelInfo, "scrcpy device safe profile applied",
			"serial", req.Serial,
			"device", deviceSignature,
			"fps", req.MaxFPS,
			"width", req.MaxWidth,
			"bitrate", req.Bitrate,
			"video_encoder", req.VideoEncoder,
			"codec_level", req.CodecLevel,
			"ignore_encoder_constraints", ignoreEncoderConstraints(req),
			"low_latency", req.LowLatency)
	}
	if err := l.ensureServer(ctx, req.Serial); err != nil {
		return nil, err
	}
	_ = l.killServer(ctx, req.Serial)
	_ = l.removeForward(ctx, req.Serial, req.Port)

	scriptPath, err := l.deployLaunchScript(ctx, req)
	if err != nil {
		return nil, err
	}
	procCtx, cancel := context.WithCancel(context.Background())
	cmd := l.adbCommand(procCtx, req.Serial, "shell", "sh", scriptPath)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		cancel()
		return nil, err
	}
	cmd.Stderr = cmd.Stdout
	if err := cmd.Start(); err != nil {
		cancel()
		return nil, err
	}
	server := &LaunchedServer{
		Serial:       req.Serial,
		Host:         l.cfg.ForwardHost,
		Port:         req.Port,
		SafeProfile:  safeProfile,
		CodecLevel:   req.CodecLevel,
		VideoEncoder: req.VideoEncoder,
		cancel:       cancel,
		cmd:          cmd,
		logger:       l.logger,
	}
	server.cleanup = func(stopCtx context.Context) {
		_ = l.removeForward(stopCtx, server.Serial, server.Port)
		_ = l.killServer(stopCtx, server.Serial)
	}
	go server.logAndWait(stdout)

	port, err := l.ensureForward(ctx, req.Serial, req.Port)
	if err != nil {
		server.Stop(context.Background())
		return nil, err
	}
	server.Port = port
	return server, nil
}

func (l *ADBLauncher) ensureServer(ctx context.Context, serial string) error {
	localInfo, err := os.Stat(l.cfg.ServerPath)
	if err != nil {
		return fmt.Errorf("scrcpy server not found at %s: %w", l.cfg.ServerPath, err)
	}
	key := serial + ":" + l.cfg.ServerPath + ":" + strconv.FormatInt(localInfo.Size(), 10)
	l.mu.Lock()
	readyAt := l.ready[key]
	l.mu.Unlock()
	if !readyAt.IsZero() && time.Since(readyAt) < l.cfg.VerifyTTL {
		return nil
	}
	devicePath := l.deviceServerPath()
	// Compare sizes, not mere existence.
	//
	// This used to accept any non-empty file at the path. The path embeds the
	// configured version, so pointing the adapter at a different scrcpy release
	// made it look for a name a device might already carry from an earlier
	// config — and reuse that stale jar forever. A whole fleet went dark that
	// way: every device kept a 4.1 jar under a 3.3.4 name, the client announced
	// 3.3.4, and every server exited with "The server version (4.1) does not
	// match the client (3.3.4)". Size is a cheap check that would have caught it.
	if out, err := l.run(ctx, serial, 5*time.Second, "shell", "wc -c < "+shellQuote(devicePath)); err == nil {
		fields := strings.Fields(out)
		if len(fields) > 0 {
			if onDevice, convErr := strconv.ParseInt(fields[0], 10, 64); convErr == nil {
				if onDevice == localInfo.Size() {
					l.markReady(key)
					return nil
				}
				l.logLine(slog.LevelInfo, "scrcpy server jar on device differs from asset, re-pushing",
					"serial", serial, "path", devicePath,
					"want_bytes", localInfo.Size(), "device_bytes", onDevice)
			}
		}
	}
	if _, err := l.run(ctx, serial, 5*time.Second, "shell", "mkdir", "-p", l.cfg.DeviceDir); err != nil {
		return err
	}
	if _, err := l.run(ctx, serial, 30*time.Second, "push", l.cfg.ServerPath, devicePath); err != nil {
		return err
	}
	if _, err := l.run(ctx, serial, 5*time.Second, "shell", "chmod", "644", devicePath); err != nil {
		return err
	}
	l.markReady(key)
	return nil
}

func (l *ADBLauncher) markReady(key string) {
	l.mu.Lock()
	l.ready[key] = time.Now()
	l.mu.Unlock()
}

// InvalidateServer forgets that a device has the scrcpy jar, forcing the next
// launch to check for it and re-push if needed.
//
// ensureServer skips the existence check entirely while its cache is warm, so
// a jar that disappears mid-window — device storage cleaned, /data/local/tmp
// wiped, a reset — leaves every launch failing in complete silence: app_process
// exits immediately, the socket never opens, and the session retries forever.
// Observed on a live device: the jar was gone and the adapter spun for minutes,
// logging only "handshake not ready ... EOF" with empty scrcpy output.
//
// Without this the device only recovers when the TTL expires (5 minutes by
// default). Called from the failure path so recovery takes one retry instead.
func (l *ADBLauncher) InvalidateServer(serial string) {
	prefix := serial + ":"
	l.mu.Lock()
	for key := range l.ready {
		if strings.HasPrefix(key, prefix) {
			delete(l.ready, key)
		}
	}
	l.mu.Unlock()
}

func (l *ADBLauncher) deployLaunchScript(ctx context.Context, req StartRequest) (string, error) {
	args := scrcpyServerArgs(l.cfg, req)
	body := "#!/system/bin/sh\n" +
		"export CLASSPATH=" + shellQuote(l.deviceServerPath()) + "\n" +
		"exec app_process / com.genymobile.scrcpy.Server " + shellJoin(args) + "\n"
	sum := sha256.Sum256([]byte(body))
	scriptPath := filepath.Join(
		l.cfg.DeviceDir,
		"scrcpy-start-"+l.cfg.ServerVersion+"-"+hex.EncodeToString(sum[:])[:12]+".sh",
	)
	scriptKey := req.Serial + ":" + scriptPath
	l.mu.Lock()
	scriptReadyAt := l.scripts[scriptKey]
	l.mu.Unlock()
	if !scriptReadyAt.IsZero() && time.Since(scriptReadyAt) < l.cfg.VerifyTTL {
		return scriptPath, nil
	}
	local, err := os.CreateTemp("", "device-farm-scrcpy-start-*.sh")
	if err != nil {
		return "", err
	}
	defer os.Remove(local.Name())
	if _, err := io.WriteString(local, body); err != nil {
		_ = local.Close()
		return "", err
	}
	if err := local.Close(); err != nil {
		return "", err
	}
	if _, err := l.run(ctx, req.Serial, 5*time.Second, "shell", "mkdir", "-p", l.cfg.DeviceDir); err != nil {
		return "", err
	}
	if _, err := l.run(ctx, req.Serial, 10*time.Second, "push", local.Name(), scriptPath); err != nil {
		return "", err
	}
	if _, err := l.run(ctx, req.Serial, 5*time.Second, "shell", "chmod", "700", scriptPath); err != nil {
		return "", err
	}
	l.mu.Lock()
	l.scripts[scriptKey] = time.Now()
	l.mu.Unlock()
	return scriptPath, nil
}

func (l *ADBLauncher) ensureForward(ctx context.Context, serial string, requestedPort int) (int, error) {
	if requestedPort > 0 {
		if _, err := l.run(ctx, serial, 10*time.Second, "forward", "tcp:"+strconv.Itoa(requestedPort), "localabstract:scrcpy"); err != nil {
			return 0, err
		}
		return requestedPort, nil
	}
	out, err := l.run(ctx, serial, 10*time.Second, "forward", "tcp:0", "localabstract:scrcpy")
	if err != nil {
		return 0, err
	}
	port, err := strconv.Atoi(strings.TrimSpace(out))
	if err != nil || port <= 0 {
		return 0, fmt.Errorf("adb forward returned invalid port %q", strings.TrimSpace(out))
	}
	return port, nil
}

func (l *ADBLauncher) killServer(ctx context.Context, serial string) error {
	_, err := l.run(ctx, serial, 5*time.Second, "shell", "pkill", "-f", "app_process.*com.genymobile.scrcpy.Server")
	return err
}

func (l *ADBLauncher) removeForward(ctx context.Context, serial string, port int) error {
	if port <= 0 {
		return nil
	}
	_, err := l.run(ctx, serial, 5*time.Second, "forward", "--remove", "tcp:"+strconv.Itoa(port))
	return err
}

func (l *ADBLauncher) deviceServerPath() string {
	return filepath.Join(l.cfg.DeviceDir, "scrcpy-server-"+l.cfg.ServerVersion+".jar")
}

// deviceSignature returns the `getprop` fingerprint used to pick a device safe
// profile, cached per serial.
//
// This probe decides whether a Note 10+ gets c2.android.avc.encoder, and it
// used to run on every launch with a 3s budget and no memory. A device that is
// busy — mid-reconnect, ADB congested, the very moments the codec ladder is
// retrying — returned "", which reads exactly like "not a Note 10+": the safe
// profile was skipped and scrcpy started on the device's default encoder, the
// one that fails on this model. The same phone would then flip between profiles
// from one retry to the next, so the bug looked intermittent.
//
// The model of a phone does not change, so a successful probe is cached and
// reused. It is re-probed after VerifyTTL only to catch a serial that now
// points at different hardware (an ADB-over-WiFi address reassigned to another
// phone). A failed probe falls back to the last known value at any age: stale
// truth beats a blank that silently downgrades the launch.
func (l *ADBLauncher) deviceSignature(ctx context.Context, serial string) string {
	l.mu.Lock()
	cached, seen := l.signatures[serial]
	l.mu.Unlock()
	if seen && cached.value != "" && time.Since(cached.probedAt) < l.cfg.VerifyTTL {
		return cached.value
	}
	out, err := l.run(ctx, serial, deviceSignatureProbeTimeout,
		"shell",
		"printf '%s %s %s %s\\n' \"$(getprop ro.product.model)\" \"$(getprop ro.boot.qemu.avd_name)\" \"$(getprop ro.product.manufacturer)\" \"$(getprop ro.board.platform)\"",
	)
	if err != nil {
		if seen && cached.value != "" {
			l.logLine(slog.LevelInfo, "scrcpy device signature probe failed, reusing cached signature",
				"serial", serial, "device", cached.value, "error", err)
			return cached.value
		}
		// Nothing cached: the launch proceeds without a safe profile. On a
		// device that needs one this is the failure, so say so at Warn.
		l.logLine(slog.LevelWarn, "scrcpy device signature probe failed with no cached value",
			"serial", serial, "error", err)
		return ""
	}
	signature := strings.TrimSpace(out)
	if signature == "" {
		if seen && cached.value != "" {
			return cached.value
		}
		return ""
	}
	l.mu.Lock()
	if l.signatures == nil {
		l.signatures = make(map[string]deviceProbe)
	}
	l.signatures[serial] = deviceProbe{value: signature, probedAt: time.Now()}
	l.mu.Unlock()
	return signature
}

func (l *ADBLauncher) run(ctx context.Context, serial string, timeout time.Duration, args ...string) (string, error) {
	runCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	cmd := l.adbCommand(runCtx, serial, args...)
	var stdout bytes.Buffer
	var stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		msg := strings.TrimSpace(stdout.String() + "\n" + stderr.String())
		if msg == "" {
			msg = err.Error()
		}
		return stdout.String(), fmt.Errorf("adb %s failed: %s", strings.Join(args, " "), msg)
	}
	return stdout.String(), nil
}

func (l *ADBLauncher) adbCommand(ctx context.Context, serial string, args ...string) *exec.Cmd {
	serverArgs := adbserver.ArgsForSerial(ctx, l.cfg.ADBPath, serial)
	argv := make([]string, 0, len(serverArgs)+len(args)+2)
	argv = append(argv, serverArgs...)
	if serial != "" {
		argv = append(argv, "-s", serial)
	}
	argv = append(argv, args...)
	cmd := exec.CommandContext(ctx, l.cfg.ADBPath, argv...)
	cmd.Env = cleanADBEnv(os.Environ())
	return cmd
}

func (l *ADBLauncher) logLine(level slog.Level, msg string, args ...any) {
	if l.logger == nil {
		return
	}
	l.logger.Log(context.Background(), level, msg, args...)
}

func (s *LaunchedServer) Stop(ctx context.Context) {
	if s == nil {
		return
	}
	if s.cancel != nil {
		s.cancel()
	}
	if s.cmd != nil && s.cmd.Process != nil {
		_ = s.cmd.Process.Kill()
	}
	if s.cleanup != nil {
		s.cleanup(ctx)
	}
}

func (s *LaunchedServer) logAndWait(stdout io.Reader) {
	scanner := bufio.NewScanner(stdout)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		s.recordOutput(line)
		if s.logger != nil {
			s.logger.Debug("scrcpy-server", "serial", s.Serial, "line", line)
		}
	}
	if s.cmd != nil {
		_ = s.cmd.Wait()
	}
}

// nativeResolutionLevel is the rung that stops asking the device to scale.
//
// Scaling is what a Samsung Exynos H264 encoder aborts on: it advertises 2px
// alignment, accepts the geometry, then trips -fstack-protector inside
// MediaCodec.configure() and takes the whole server with it. No codec option
// avoids it — the ladder ran to the end and still died. Dropping max_size, and
// only that, turns the identical launch into a working stream.
//
// It is the last rung rather than a device allowlist on purpose. Deciding by
// model needs a getprop probe, and that probe fails exactly when it matters:
// a device stuck in a crash-restart loop saturates ADB, the probe times out,
// the model reads as unknown, and the fix silently does not apply. The ladder
// needs no probe, no serial list, and no maintenance when new hardware with
// the same defect arrives — it simply keeps giving up options until something
// works, then remembers the rung per serial.
const nativeResolutionLevel = 4

// MaxCodecLevel is the last rung of the fallback ladder. Levels above it behave
// the same.
const MaxCodecLevel = nativeResolutionLevel

// LowLatencyEnabled reports whether to ask the encoder for `latency:int=0`.
//
// This used to be hardcoded true at every call site, so an encoder that
// rejects the key had no way out short of rebuilding the image. The ladder
// already drops it after repeated failures; this is the switch for turning it
// off fleet-wide once a device is known to need that.
func LowLatencyEnabled() bool {
	return envBool("MEDIA_ADAPTER_SCRCPY_LOW_LATENCY", true)
}

// ignoreEncoderConstraints reports whether to send
// `ignore_video_encoder_constraints=true` to scrcpy-server.
//
// scrcpy 4.0 started clamping max_size and max_fps against the encoder's
// declared MediaCodecInfo.VideoCapabilities before configuring MediaCodec
// (com.genymobile.scrcpy.video.VideoConstraints, "Applying video encoder
// constraints"). The clamp is only as good as what the encoder declares, and
// Samsung Exynos hardware encoders declare capabilities that do not match what
// they will actually accept — so the step either picks a geometry the encoder
// then rejects, or throws outright. scrcpy 4.1 added this option for exactly
// that regression.
//
// This is a better lever than forcing the software encoder: it addresses why
// the hardware encoder fails instead of avoiding it, and it costs no
// resolution. The Note 10+ safe profile turns it on; the env var forces it
// fleet-wide for operators who hit the same regression on another model.
func ignoreEncoderConstraints(req StartRequest) bool {
	return req.IgnoreEncoderConstraints ||
		envBool("MEDIA_ADAPTER_SCRCPY_IGNORE_ENCODER_CONSTRAINTS", false)
}

// codecOptionsForLevel builds the `video_codec_options` string for a rung of
// the fallback ladder.
//
// These keys go straight into MediaFormat and then MediaCodec.configure().
// They are vendor-dependent: an encoder that does not know a key — or wants a
// different type for it — throws IllegalArgumentException and the whole
// scrcpy-server dies, which the adapter only sees as a socket that never
// opens. Samsung Exynos encoders are the common case.
//
// So the rungs drop the riskiest key first and keep the most valuable one
// longest. i-frame-interval survives to level 2 because the push architecture
// has no way to ask the device for a keyframe: that 1s IDR cadence is the only
// thing that recovers a stream after packet loss.
//
//	0: i-frame-interval, max-bframes, latency   (unchanged default)
//	1: i-frame-interval, max-bframes            (drop latency)
//	2: i-frame-interval                         (drop max-bframes)
//	3: none                                     (let the encoder decide)
//
// MEDIA_ADAPTER_SCRCPY_CODEC_OPTIONS overrides the whole ladder, including
// being set to empty to send nothing — an escape hatch for operators to pin a
// working string without rebuilding the image.
func codecOptionsForLevel(level int, lowLatency bool) string {
	if override, ok := os.LookupEnv("MEDIA_ADAPTER_SCRCPY_CODEC_OPTIONS"); ok {
		return strings.TrimSpace(override)
	}
	if level < 0 {
		level = 0
	}
	opts := make([]string, 0, 3)
	if level <= 2 {
		opts = append(opts, "i-frame-interval:int=1")
	}
	if level <= 1 {
		opts = append(opts, "max-bframes:int=0")
	}
	if level <= 0 && lowLatency {
		opts = append(opts, "latency:int=0")
	}
	return strings.Join(opts, ",")
}

// pinnedSafeVideoEncoder returns the encoder name to force on a device that
// needs the safe profile. Empty — the default — means "do not force one".
//
// This used to hardcode "c2.android.avc.encoder", the AOSP software AVC
// encoder, on the theory that software encoding is the safe fallback when a
// vendor's hardware encoder misbehaves. On a real SM-N975F (Android 12) that
// name makes MediaCodec.createByCodecName() block forever: the server prints
//
//	[server] DEBUG: Creating encoder by name: 'c2.android.avc.encoder'
//
// and never returns. No exception, nothing in logcat, no further output — so
// the adapter sees only a socket that never opens and reports
// "handshake not ready ... EOF" with empty scrcpy output. The device that the
// workaround existed to rescue was the only device the workaround broke.
//
// So: never force a name nobody verified against the actual device. An
// operator who has confirmed a working encoder via `list_encoders=true` can
// pin it here without a rebuild; everyone else lets scrcpy choose.
func pinnedSafeVideoEncoder() string {
	return strings.TrimSpace(os.Getenv("MEDIA_ADAPTER_SCRCPY_SAFE_VIDEO_ENCODER"))
}

// safeProfileMaxSize returns the max_size for a listed device, or 0 to send no
// max_size at all and let the device encode at its native resolution.
//
// Scaling is what actually broke SM-N975F. With any max_size, Exynos aborts the
// whole server inside MediaCodec.configure():
//
//	[server] DEBUG: Video codec size alignment requirement: 2px
//	stack corruption detected (-fstack-protector)
//
// The encoder declares it only needs 2px alignment and then corrupts its own
// stack on a size that honours that. Drop max_size and the identical command,
// same encoder, same jar, reaches "Display: using SurfaceControl API" and
// streams. Native resolution costs bandwidth, but it is the only geometry
// verified to work on the device.
//
// MEDIA_ADAPTER_SCRCPY_SAFE_MAX_SIZE takes a size back once one is confirmed
// safe on real hardware — 16-aligned candidates are the ones worth trying.
func safeProfileMaxSize() int {
	return envInt("MEDIA_ADAPTER_SCRCPY_SAFE_MAX_SIZE", 0)
}

func applyDeviceSafeProfile(req StartRequest, deviceSignature string) StartRequest {
	if !needsDeviceSafeProfile(deviceSignature) {
		return req
	}
	if strings.TrimSpace(req.VideoEncoder) == "" {
		req.VideoEncoder = pinnedSafeVideoEncoder()
	}
	// Not set here on purpose. Turning the constraint clamp off was a guess
	// made before any device log existed, and the configuration proven to work
	// on the hardware does not include it. The env still forces it on for
	// anyone who finds a device that needs it.
	req.IgnoreEncoderConstraints = false
	req.LowLatency = false
	req.CodecLevel = MaxCodecLevel
	// Bitrate is deliberately left alone.
	//
	// It used to be pinned at 900000 here, which quietly deleted the caller's
	// idle/visible/focused throttling for every listed device: a phone nobody
	// was watching still published ~900 kbps around the clock, while unlisted
	// phones idled at 10-24 kbps. Ten of them saturated the site's uplink with
	// video that had no consumers, and opening a few real viewers then had no
	// headroom left. Only drop what makes the encoder abort; everything else
	// stays the caller's decision.
	// Both hints go, not just one. Measured on SM-N975F: max_size alone aborts
	// the encoder, max_fps alone aborts it, and sending neither streams. Each
	// reaches the vendor encoder as its own MediaFormat key, so dropping one
	// and keeping the other only changes which key kills the launch.
	//
	// The cost is real — native resolution and uncapped frame rate — but the
	// bitrate cap still bounds the wire, and a working stream at the wrong
	// quality beats a dead one at the right quality.
	if size := safeProfileMaxSize(); size > 0 {
		req.MaxWidth = size
		req.SkipMaxSize = false
		// Stay one rung below the hint-dropping level, or the pinned value
		// would be built and then discarded.
		req.CodecLevel = nativeResolutionLevel - 1
	} else {
		req.MaxWidth = 0
		req.SkipMaxSize = true
	}
	if fps := safeProfileMaxFPS(); fps > 0 {
		req.MaxFPS = fps
		req.SkipMaxFPS = false
		req.CodecLevel = nativeResolutionLevel - 1
	} else {
		req.MaxFPS = 0
		req.SkipMaxFPS = true
	}
	return req
}

// safeProfileMaxFPS mirrors safeProfileMaxSize for the frame-rate hint. 0 — the
// default — sends no max_fps at all.
func safeProfileMaxFPS() int {
	return envInt("MEDIA_ADAPTER_SCRCPY_SAFE_MAX_FPS", 0)
}

// needsDeviceSafeProfile reports whether a device is on the known-fragile list
// and should launch with the reduced profile.
//
// MEDIA_ADAPTER_SCRCPY_DEVICE_SAFE_PROFILE=0 turns the whole mechanism off, so
// a listed device launches exactly like any other. That switch matters as much
// as the profile itself: the profile is the only thing that makes a Note 10+
// differ from a working device, so when a listed model is the one failing, the
// first question is whether this special-casing is the cause rather than the
// cure — and answering it must not require rebuilding the image.
func needsDeviceSafeProfile(deviceSignature string) bool {
	if !envBool("MEDIA_ADAPTER_SCRCPY_DEVICE_SAFE_PROFILE", true) {
		return false
	}
	value := strings.ToLower(strings.TrimSpace(deviceSignature))
	if value == "" {
		return false
	}
	for _, marker := range []string{
		"sm-n97",
		"sm-n976",
		"note10",
		"note 10",
		"galaxy_note10",
	} {
		if strings.Contains(value, marker) {
			return true
		}
	}
	return false
}

func launchProfileChanged(before StartRequest, after StartRequest) bool {
	return before.MaxFPS != after.MaxFPS ||
		before.MaxWidth != after.MaxWidth ||
		before.Bitrate != after.Bitrate ||
		before.VideoEncoder != after.VideoEncoder ||
		before.SkipMaxSize != after.SkipMaxSize ||
		before.IgnoreEncoderConstraints != after.IgnoreEncoderConstraints ||
		before.LowLatency != after.LowLatency ||
		before.CodecLevel != after.CodecLevel
}

func clampRange(value int, minimum int, maximum int) int {
	if value < minimum {
		return minimum
	}
	if value > maximum {
		return maximum
	}
	return value
}

func scrcpyServerArgs(cfg LauncherConfig, req StartRequest) []string {
	control := "false"
	if req.Control {
		control = "true"
	}
	args := []string{
		cfg.ServerVersion,
		"tunnel_forward=true",
		"video=true",
		"audio=false",
		"control=" + control,
		"video_codec=" + req.VideoCodec,
		"video_bit_rate=" + strconv.Itoa(req.Bitrate),
	}
	// max_size and max_fps are the two hints that reach the vendor encoder as
	// geometry and max-fps-to-encoder. Each one alone is enough to abort the
	// Exynos H264 encoder; sending neither is what actually streams.
	// The last rung drops them for any device, listed or not: a model that is
	// not on the list would otherwise retry the same fatal launch forever.
	dropHints := req.CodecLevel >= nativeResolutionLevel
	if !req.SkipMaxSize && !dropHints && req.MaxWidth > 0 {
		args = append(args, "max_size="+strconv.Itoa(req.MaxWidth))
	}
	if !req.SkipMaxFPS && !dropHints && req.MaxFPS > 0 {
		args = append(args, "max_fps="+strconv.Itoa(req.MaxFPS))
	}
	if strings.TrimSpace(req.VideoEncoder) != "" {
		args = append(args, "video_encoder="+strings.TrimSpace(req.VideoEncoder))
	}
	if ignoreEncoderConstraints(req) {
		args = append(args, "ignore_video_encoder_constraints=true")
	}
	if req.VideoCodec == "h264" {
		if opts := codecOptionsForLevel(req.CodecLevel, req.LowLatency); opts != "" {
			args = append(args, "video_codec_options="+opts)
		}
	}
	args = append(args,
		"stay_awake=true",
		"cleanup="+strconv.FormatBool(cfg.Cleanup),
		"send_device_meta=true",
		"send_stream_meta=true",
		"send_frame_meta=true",
		"send_dummy_byte=true",
	)
	return args
}

func cleanADBEnv(env []string) []string {
	out := make([]string, 0, len(env))
	for _, item := range env {
		if strings.HasPrefix(item, "MallocStackLogging=") ||
			strings.HasPrefix(item, "MallocStackLoggingDirectory=") ||
			strings.HasPrefix(item, "MallocStackLoggingNoCompact=") {
			continue
		}
		out = append(out, item)
	}
	return out
}

func forwardHostFromEnv() string {
	if value := strings.TrimSpace(os.Getenv("MEDIA_ADAPTER_ADB_FORWARD_HOST")); value != "" {
		return value
	}
	socket := strings.TrimSpace(os.Getenv("ADB_SERVER_SOCKET"))
	if strings.HasPrefix(socket, "tcp:") {
		rest := strings.TrimPrefix(socket, "tcp:")
		host, _, err := net.SplitHostPort(rest)
		if err == nil && host != "" {
			return host
		}
		parts := strings.Split(rest, ":")
		if len(parts) >= 2 && parts[0] != "" {
			return parts[0]
		}
	}
	return defaultForwardHost
}

func shellJoin(args []string) string {
	quoted := make([]string, 0, len(args))
	for _, arg := range args {
		quoted = append(quoted, shellQuote(arg))
	}
	return strings.Join(quoted, " ")
}

func shellQuote(value string) string {
	if value == "" {
		return "''"
	}
	return "'" + strings.ReplaceAll(value, "'", "'\\''") + "'"
}

func envBool(name string, fallback bool) bool {
	value := strings.ToLower(strings.TrimSpace(os.Getenv(name)))
	switch value {
	case "1", "true", "yes", "on":
		return true
	case "0", "false", "no", "off":
		return false
	default:
		return fallback
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
	parsed, err := strconv.Atoi(value)
	if err != nil || parsed <= 0 {
		return fallback
	}
	return parsed
}
