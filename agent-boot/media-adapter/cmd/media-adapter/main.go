package main

import (
	"context"
	"log/slog"
	"net"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"devicefarm/media-adapter/internal/adapters/inbound/httpapi"
	"devicefarm/media-adapter/internal/adapters/outbound/rtspserver"
	"devicefarm/media-adapter/internal/adapters/scrcpy"
)

func main() {
	logger := slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{
		Level: logLevel(),
	}))
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	publisher := rtspserver.New(rtspserver.ConfigFromEnv(), logger)
	scrcpyManager := scrcpy.NewManager(publisher, logger)
	publisher.SetKeyframeRequester(scrcpyManager.RequestKeyframe)
	defer func() {
		scrcpyManager.Close()
		_ = publisher.Close(context.Background())
	}()

	httpBind := envDefault("MEDIA_ADAPTER_HTTP_BIND", "127.0.0.1")
	httpPort := envDefault("MEDIA_ADAPTER_HTTP_PORT", "8878")
	httpServer := httpapi.NewServer(
		net.JoinHostPort(httpBind, httpPort),
		scrcpyManager,
		logger,
	)

	if err := httpServer.Run(ctx); err != nil {
		logger.Error("media adapter stopped", "error", err)
		os.Exit(1)
	}
}

func logLevel() slog.Level {
	switch strings.ToLower(strings.TrimSpace(os.Getenv("MEDIA_ADAPTER_LOG_LEVEL"))) {
	case "debug":
		return slog.LevelDebug
	case "warn", "warning":
		return slog.LevelWarn
	case "error":
		return slog.LevelError
	default:
		return slog.LevelInfo
	}
}

func envDefault(name string, fallback string) string {
	value := strings.TrimSpace(os.Getenv(name))
	if value == "" {
		return fallback
	}
	return value
}
