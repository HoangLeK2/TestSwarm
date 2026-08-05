package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"log/slog"
	"os"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"devicefarm/media-adapter/internal/adapters/outbound/rtspserver"
	"devicefarm/media-adapter/internal/domain/stream"
	"github.com/bluenviron/gortsplib/v5"
	"github.com/bluenviron/gortsplib/v5/pkg/base"
	"github.com/bluenviron/gortsplib/v5/pkg/description"
	"github.com/bluenviron/gortsplib/v5/pkg/format"
	"github.com/pion/rtp"
)

type options struct {
	streams                  int
	duration                 time.Duration
	fps                      int
	readersPerStream         int
	readerConnectConcurrency int
	rtspAddress              string
	queueMax                 int
	stalePacketAge           time.Duration
	writeQueueSize           int
	payloadBytes             int
	keyframeInterval         int
	startupTimeout           time.Duration
	maxDropRatio             float64
	minReaderPacketRatio     float64
}

type result struct {
	OK                    bool                      `json:"ok"`
	Streams               int                       `json:"streams"`
	DurationSeconds       float64                   `json:"duration_seconds"`
	FPS                   int                       `json:"fps"`
	ReadersPerStream      int                       `json:"readers_per_stream"`
	TargetPackets         uint64                    `json:"target_packets"`
	AttemptedPackets      uint64                    `json:"attempted_packets"`
	ExpectedReaderPackets uint64                    `json:"expected_reader_packets"`
	ReaderRTPPackets      uint64                    `json:"reader_rtp_packets"`
	ReaderStarts          uint64                    `json:"reader_starts"`
	ReaderFailures        uint64                    `json:"reader_failures"`
	DropRatio             float64                   `json:"drop_ratio"`
	ReaderPacketRatio     float64                   `json:"reader_packet_ratio"`
	Publisher             rtspserver.PublisherStats `json:"publisher"`
	Memory                memoryStats               `json:"memory"`
	Goroutines            int                       `json:"goroutines"`
	Errors                []string                  `json:"errors,omitempty"`
}

type memoryStats struct {
	HeapAllocMB float64 `json:"heap_alloc_mb"`
	HeapSysMB   float64 `json:"heap_sys_mb"`
	SysMB       float64 `json:"sys_mb"`
	NumGC       uint32  `json:"num_gc"`
}

type readerMetrics struct {
	starts   atomic.Uint64
	failures atomic.Uint64
	packets  atomic.Uint64
}

var (
	annexBStartCode = []byte{0x00, 0x00, 0x00, 0x01}
	benchSPS        = []byte{
		0x67, 0x42, 0xc0, 0x28, 0xd9, 0x00, 0x78, 0x02,
		0x27, 0xe5, 0x84, 0x00, 0x00, 0x03, 0x00, 0x04,
		0x00, 0x00, 0x03, 0x00, 0xf0, 0x3c, 0x60, 0xc9,
		0x20,
	}
	benchPPS = []byte{0x08}
)

func main() {
	log.SetOutput(io.Discard)
	opts := parseOptions()
	if err := validateOptions(opts); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}

	res, err := run(context.Background(), opts)
	if err != nil {
		res.Errors = append(res.Errors, err.Error())
		res.OK = false
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	if encodeErr := enc.Encode(res); encodeErr != nil {
		fmt.Fprintln(os.Stderr, encodeErr)
		os.Exit(1)
	}
	if err != nil || !res.OK {
		os.Exit(1)
	}
}

func parseOptions() options {
	var opts options
	flag.IntVar(&opts.streams, "streams", 100, "number of synthetic phone streams")
	flag.DurationVar(&opts.duration, "duration", 20*time.Second, "steady-state benchmark duration")
	flag.IntVar(&opts.fps, "fps", 15, "input frames per stream per second")
	flag.IntVar(&opts.readersPerStream, "readers-per-stream", 0, "RTSP readers to attach to each stream")
	flag.IntVar(&opts.readerConnectConcurrency, "reader-connect-concurrency", 32, "maximum concurrent RTSP reader connects")
	flag.StringVar(&opts.rtspAddress, "rtsp-address", "127.0.0.1:18556", "RTSP listen address for the benchmark publisher")
	flag.IntVar(&opts.queueMax, "queue-max", 8, "per-stream realtime input queue size")
	flag.DurationVar(&opts.stalePacketAge, "stale-age", 160*time.Millisecond, "maximum age for non-key packets before dropping")
	flag.IntVar(&opts.writeQueueSize, "write-queue", 128, "gortsplib per-client write queue size")
	flag.IntVar(&opts.payloadBytes, "payload-bytes", 800, "synthetic H264 NAL payload size")
	flag.IntVar(&opts.keyframeInterval, "keyframe-interval", 30, "publish one IDR frame every N frames")
	flag.DurationVar(&opts.startupTimeout, "startup-timeout", 5*time.Second, "maximum time to attach benchmark readers")
	flag.Float64Var(&opts.maxDropRatio, "max-drop-ratio", 1.0, "fail when publisher drop ratio is above this value")
	flag.Float64Var(&opts.minReaderPacketRatio, "min-reader-packet-ratio", 0.0, "fail when reader RTP packet ratio is below this value")
	flag.Parse()
	return opts
}

func validateOptions(opts options) error {
	switch {
	case opts.streams <= 0:
		return fmt.Errorf("streams must be > 0")
	case opts.duration <= 0:
		return fmt.Errorf("duration must be > 0")
	case opts.fps <= 0:
		return fmt.Errorf("fps must be > 0")
	case opts.readersPerStream < 0:
		return fmt.Errorf("readers-per-stream must be >= 0")
	case opts.readerConnectConcurrency <= 0:
		return fmt.Errorf("reader-connect-concurrency must be > 0")
	case strings.TrimSpace(opts.rtspAddress) == "":
		return fmt.Errorf("rtsp-address is required")
	case opts.queueMax <= 0:
		return fmt.Errorf("queue-max must be > 0")
	case opts.writeQueueSize <= 0:
		return fmt.Errorf("write-queue must be > 0")
	case opts.payloadBytes < 1:
		return fmt.Errorf("payload-bytes must be > 0")
	case opts.keyframeInterval <= 0:
		return fmt.Errorf("keyframe-interval must be > 0")
	case opts.startupTimeout <= 0:
		return fmt.Errorf("startup-timeout must be > 0")
	case opts.maxDropRatio < 0:
		return fmt.Errorf("max-drop-ratio must be >= 0")
	case opts.minReaderPacketRatio < 0 || opts.minReaderPacketRatio > 1:
		return fmt.Errorf("min-reader-packet-ratio must be between 0 and 1")
	}
	return nil
}

func run(parent context.Context, opts options) (result, error) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	publisher := rtspserver.New(rtspserver.Config{
		RTSPAddress:    opts.rtspAddress,
		QueueMax:       opts.queueMax,
		StalePacketAge: opts.stalePacketAge,
		InputFPS:       opts.fps,
		WriteQueueSize: opts.writeQueueSize,
	}, logger)
	defer publisher.Close(context.Background())
	if err := publisher.StartError(); err != nil {
		return resultFrom(opts, publisher, &readerMetrics{}, 0, time.Time{}), err
	}

	serials := make([]string, opts.streams)
	for i := range serials {
		serials[i] = fmt.Sprintf("BENCH%06d", i+1)
		if err := publisher.Publish(parent, stream.EncodedPacket{
			Serial:   serials[i],
			Payload:  configPacket(),
			Owned:    true,
			IsConfig: true,
			IsKey:    true,
			Received: time.Now(),
		}); err != nil {
			return resultFrom(opts, publisher, &readerMetrics{}, 0, time.Time{}), err
		}
	}

	readerCtx, stopReaders := context.WithCancel(parent)
	defer stopReaders()
	readerStats := readerMetrics{}
	var readerWG sync.WaitGroup
	if opts.readersPerStream > 0 {
		if err := startReaders(readerCtx, opts, serials, &readerStats, &readerWG); err != nil {
			return resultFrom(opts, publisher, &readerStats, 0, time.Time{}), err
		}
	}

	benchCtx, stopBench := context.WithTimeout(parent, opts.duration)
	defer stopBench()
	var attempted atomic.Uint64
	var producers sync.WaitGroup
	startedAt := time.Now()
	for i, serial := range serials {
		producers.Add(1)
		go func(index int, serial string) {
			defer producers.Done()
			produceStream(benchCtx, publisher, serial, index, opts, &attempted)
		}(i, serial)
	}
	producers.Wait()
	elapsed := time.Since(startedAt)

	stopReaders()
	readerWG.Wait()
	time.Sleep(200 * time.Millisecond)

	res := resultFrom(opts, publisher, &readerStats, attempted.Load(), startedAt)
	res.DurationSeconds = elapsed.Seconds()
	res.OK = res.DropRatio <= opts.maxDropRatio && res.ReaderPacketRatio >= opts.minReaderPacketRatio
	return res, nil
}

func resultFrom(opts options, publisher *rtspserver.Publisher, readerStats *readerMetrics, attempted uint64, startedAt time.Time) result {
	stats := publisher.Stats()
	drops := stats.QueueDrops + stats.StaleDrops + stats.WriteErrors
	dropRatio := ratio(drops, attempted)
	expectedReaders := attempted * uint64(opts.readersPerStream)
	readerPacketRatio := 1.0
	if opts.readersPerStream > 0 {
		readerPacketRatio = ratio(readerStats.packets.Load(), expectedReaders)
	}
	durationSeconds := 0.0
	if !startedAt.IsZero() {
		durationSeconds = time.Since(startedAt).Seconds()
	}
	return result{
		OK:                    true,
		Streams:               opts.streams,
		DurationSeconds:       durationSeconds,
		FPS:                   opts.fps,
		ReadersPerStream:      opts.readersPerStream,
		TargetPackets:         uint64(float64(opts.streams*opts.fps) * opts.duration.Seconds()),
		AttemptedPackets:      attempted,
		ExpectedReaderPackets: expectedReaders,
		ReaderRTPPackets:      readerStats.packets.Load(),
		ReaderStarts:          readerStats.starts.Load(),
		ReaderFailures:        readerStats.failures.Load(),
		DropRatio:             dropRatio,
		ReaderPacketRatio:     readerPacketRatio,
		Publisher:             stats,
		Memory:                readMemoryStats(),
		Goroutines:            runtime.NumGoroutine(),
	}
}

func produceStream(
	ctx context.Context,
	publisher *rtspserver.Publisher,
	serial string,
	streamIndex int,
	opts options,
	attempted *atomic.Uint64,
) {
	interval := time.Second / time.Duration(opts.fps)
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	frame := uint64(0)
	for {
		select {
		case <-ctx.Done():
			return
		case now := <-ticker.C:
			isKey := frame%uint64(opts.keyframeInterval) == 0
			_ = publisher.Publish(ctx, stream.EncodedPacket{
				Serial:   serial,
				Payload:  videoPacket(isKey, opts.payloadBytes, streamIndex, frame),
				Owned:    true,
				IsKey:    isKey,
				PTSUs:    uint64(frame * uint64(interval/time.Microsecond)),
				Received: now,
			})
			attempted.Add(1)
			frame++
		}
	}
}

func startReaders(
	ctx context.Context,
	opts options,
	serials []string,
	metrics *readerMetrics,
	wg *sync.WaitGroup,
) error {
	sem := make(chan struct{}, opts.readerConnectConcurrency)
	var connectWG sync.WaitGroup
	errCh := make(chan error, 1)
	for _, serial := range serials {
		for readerID := 0; readerID < opts.readersPerStream; readerID++ {
			serial := serial
			readerID := readerID
			connectWG.Add(1)
			go func() {
				defer connectWG.Done()
				select {
				case sem <- struct{}{}:
					defer func() { <-sem }()
				case <-ctx.Done():
					return
				}
				if err := startReaderWithRetry(ctx, opts, serial, readerID, metrics, wg); err != nil {
					metrics.failures.Add(1)
					select {
					case errCh <- err:
					default:
					}
				}
			}()
		}
	}
	connectWG.Wait()
	select {
	case err := <-errCh:
		return err
	default:
		return nil
	}
}

func startReaderWithRetry(
	ctx context.Context,
	opts options,
	serial string,
	readerID int,
	metrics *readerMetrics,
	wg *sync.WaitGroup,
) error {
	deadline := time.Now().Add(opts.startupTimeout)
	var lastErr error
	for time.Now().Before(deadline) {
		if err := startReader(ctx, opts.rtspAddress, serial, readerID, metrics, wg); err != nil {
			lastErr = err
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-time.After(50 * time.Millisecond):
			}
			continue
		}
		return nil
	}
	return fmt.Errorf("reader %s/%d failed to start: %w", serial, readerID, lastErr)
}

func startReader(
	ctx context.Context,
	rtspAddress string,
	serial string,
	readerID int,
	metrics *readerMetrics,
	wg *sync.WaitGroup,
) error {
	u, err := base.ParseURL(fmt.Sprintf("rtsp://%s/%s", rtspAddress, stream.StreamName(serial)))
	if err != nil {
		return err
	}
	client := &gortsplib.Client{
		Scheme:      u.Scheme,
		Host:        u.Host,
		ReadTimeout: 3 * time.Second,
	}
	if err := client.Start(); err != nil {
		return err
	}
	desc, _, err := client.Describe(u)
	if err != nil {
		client.Close()
		return err
	}
	if err := client.SetupAll(desc.BaseURL, desc.Medias); err != nil {
		client.Close()
		return err
	}
	client.OnPacketRTPAny(func(_ *description.Media, _ format.Format, _ *rtp.Packet) {
		metrics.packets.Add(1)
	})
	if _, err := client.Play(nil); err != nil {
		client.Close()
		return err
	}
	metrics.starts.Add(1)
	wg.Add(1)
	go func() {
		defer wg.Done()
		done := make(chan struct{})
		go func() {
			_ = client.Wait()
			close(done)
		}()
		select {
		case <-ctx.Done():
			client.Close()
			<-done
		case <-done:
			metrics.failures.Add(1)
			fmt.Fprintf(os.Stderr, "reader stopped early serial=%s reader=%d\n", serial, readerID)
		}
	}()
	return nil
}

func configPacket() []byte {
	out := make([]byte, 0, len(benchSPS)+len(benchPPS)+len(annexBStartCode)*2)
	out = append(out, annexBStartCode...)
	out = append(out, benchSPS...)
	out = append(out, annexBStartCode...)
	out = append(out, benchPPS...)
	return out
}

func videoPacket(isKey bool, payloadBytes int, streamIndex int, frame uint64) []byte {
	header := byte(0x41)
	if isKey {
		header = 0x65
	}
	out := make([]byte, 0, len(annexBStartCode)+1+payloadBytes)
	out = append(out, annexBStartCode...)
	out = append(out, header)
	for i := 0; i < payloadBytes; i++ {
		out = append(out, byte((streamIndex+int(frame)+i)&0xFF))
	}
	return out
}

func ratio(num uint64, den uint64) float64 {
	if den == 0 {
		return 0
	}
	return float64(num) / float64(den)
}

func readMemoryStats() memoryStats {
	var mem runtime.MemStats
	runtime.ReadMemStats(&mem)
	return memoryStats{
		HeapAllocMB: bytesToMB(mem.HeapAlloc),
		HeapSysMB:   bytesToMB(mem.HeapSys),
		SysMB:       bytesToMB(mem.Sys),
		NumGC:       mem.NumGC,
	}
}

func bytesToMB(value uint64) float64 {
	return float64(value) / 1024 / 1024
}
