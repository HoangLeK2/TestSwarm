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
	"devicefarm/media-adapter/internal/adapters/outbound/controlplane"
	"devicefarm/media-adapter/internal/adapters/outbound/go2rtc"
	"devicefarm/media-adapter/internal/adapters/outbound/rtspserver"
	"devicefarm/media-adapter/internal/adapters/outbound/whip"
	"devicefarm/media-adapter/internal/adapters/scrcpy"
)

func main() {
	logger := slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{
		Level: logLevel(),
	}))
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	publisherCfg := rtspserver.ConfigFromEnv()
	// Transport is chosen by the scheme of the publish template, so switching
	// costs one URL and there is no second flag to keep consistent with it.
	// RTSP stays the default: it needs a single outbound TCP connection and so
	// survives NATs and firewalls that drop the UDP WebRTC requires.
	if whip.Handles(publisherCfg.PublishTemplate) {
		whipCfg := whip.ConfigFromEnv()
		publisherCfg.NewRemoteSink = func(serial string, url string, onKeyframeNeeded func()) rtspserver.RemoteSink {
			return whip.NewSink(whipCfg, serial, url, onKeyframeNeeded, logger)
		}
		logger.Info("media adapter publishing over WHIP", "template", publisherCfg.PublishTemplate)
	}
	publisher := rtspserver.New(publisherCfg, logger)
	scrcpyManager := scrcpy.NewManager(publisher, logger)
	go2rtcClient := go2rtc.New(go2rtc.ConfigFromEnv())
	publisher.SetKeyframeRequester(scrcpyManager.RequestKeyframe)
	defer func() {
		scrcpyManager.Close()
		_ = publisher.Close(context.Background())
	}()

	httpBind := envDefault("MEDIA_ADAPTER_HTTP_BIND", "127.0.0.1")
	httpPort := envDefault("MEDIA_ADAPTER_HTTP_PORT", "8878")
	controlClient := controlplane.New(
		controlplane.ConfigFromEnv(),
		scrcpyManager,
		go2rtcClient,
		logger,
	)
	// Browser-driven keyframes go through the publisher's rate gate, never
	// through scrcpyManager.RequestKeyframe: that one writes RESET_VIDEO with no
	// limit, and a looping client would reconfigure MediaCodec continuously.
	controlClient.SetGatedKeyframeRequester(publisher.RequestKeyframeGated)
	go controlClient.Run(ctx)

	httpServer := httpapi.NewServerWithWebRTC(
		net.JoinHostPort(httpBind, httpPort),
		scrcpyManager,
		go2rtcClient,
		logger,
	)
	httpServer.SetPublisherStatsProvider(publisher)

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
