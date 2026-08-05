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
)

const (
	defaultScrcpyVersion    = "4.1"
	defaultDeviceDir        = "/data/local/tmp/device-farm"
	defaultLocalServerPath  = "/app/media-adapter/assets/scrcpy-server"
	defaultForwardHost      = "127.0.0.1"
	defaultLaunchVerifyTTLS = 300
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
}

type LaunchedServer struct {
	Serial string
	Host   string
	Port   int

	cancel  context.CancelFunc
	cmd     *exec.Cmd
	logger  *slog.Logger
	cleanup func(context.Context)
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
		cfg:     cfg,
		ready:   make(map[string]time.Time),
		scripts: make(map[string]time.Time),
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
		Serial: req.Serial,
		Host:   l.cfg.ForwardHost,
		Port:   req.Port,
		cancel: cancel,
		cmd:    cmd,
		logger: l.logger,
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
	if out, err := l.run(ctx, serial, 5*time.Second, "shell", "[", "-s", devicePath, "]"); err == nil {
		_ = out
		l.markReady(key)
		return nil
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
	argv := make([]string, 0, len(args)+2)
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
		if line != "" && s.logger != nil {
			s.logger.Debug("scrcpy-server", "serial", s.Serial, "line", line)
		}
	}
	if s.cmd != nil {
		_ = s.cmd.Wait()
	}
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
		"max_fps=" + strconv.Itoa(req.MaxFPS),
		"max_size=" + strconv.Itoa(req.MaxWidth),
		"video_bit_rate=" + strconv.Itoa(req.Bitrate),
	}
	codecOptions := []string{"i-frame-interval:int=1", "max-bframes:int=0"}
	if req.LowLatency {
		codecOptions = append(codecOptions, "latency:int=0")
	}
	if req.VideoCodec == "h264" && len(codecOptions) > 0 {
		args = append(args, "video_codec_options="+strings.Join(codecOptions, ","))
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
