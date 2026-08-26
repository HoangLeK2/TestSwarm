package scrcpy

import (
	"context"
	"fmt"
	"io"
	"net"
	"testing"
	"time"
)

func TestAnnexBContainsIDR(t *testing.T) {
	payload := []byte{
		0x00, 0x00, 0x00, 0x01, 0x67,
		0x00, 0x00, 0x01, 0x65,
	}
	if !annexBContainsIDR(payload) {
		t.Fatal("expected IDR NAL in Annex-B payload")
	}
}

func TestAnnexBContainsIDRReturnsFalseForDelta(t *testing.T) {
	payload := []byte{
		0x00, 0x00, 0x00, 0x01, 0x41,
	}
	if annexBContainsIDR(payload) {
		t.Fatal("did not expect IDR NAL in delta payload")
	}
}

func TestManagerRequestKeyframeReturnsFalseWhenSessionMissing(t *testing.T) {
	manager := NewManager(nil, nil)
	if manager.RequestKeyframe("missing") {
		t.Fatal("expected missing session keyframe request to fail")
	}
}

func TestManagerWaitForFirstFrameRequiresPublishedFrame(t *testing.T) {
	manager := NewManager(nil, nil)
	session := NewSession(StartRequest{Serial: "SERIAL"}, nil, nil, nil)
	session.status.Running = true
	session.markConnected(320, 640)
	manager.sessions["SERIAL"] = session

	if status, ready := manager.WaitForFirstFrame(context.Background(), "SERIAL", 20*time.Millisecond); ready {
		t.Fatalf("ready with no frames: %+v", status)
	}

	go func() {
		time.Sleep(20 * time.Millisecond)
		session.recordFrame(5, false, true)
	}()
	status, ready := manager.WaitForFirstFrame(context.Background(), "SERIAL", time.Second)
	if !ready {
		t.Fatalf("expected first frame readiness, status=%+v", status)
	}
	if status.Frames != 1 {
		t.Fatalf("frames=%d", status.Frames)
	}
}

func TestStartRequestNormalizeDefaultsOwnedLaunchConfig(t *testing.T) {
	req := StartRequest{Serial: "SERIAL", OwnsScrcpy: true}
	req.normalize()

	if req.VideoCodec != "h264" {
		t.Fatalf("codec=%q", req.VideoCodec)
	}
	if req.MaxFPS != 15 {
		t.Fatalf("max fps=%d", req.MaxFPS)
	}
	if req.MaxWidth != 320 {
		t.Fatalf("max width=%d", req.MaxWidth)
	}
	if req.Bitrate != 150000 {
		t.Fatalf("bitrate=%d", req.Bitrate)
	}
}

func TestScrcpyServerArgsCarryRealtimeProfile(t *testing.T) {
	args := scrcpyServerArgs(LauncherConfig{ServerVersion: "4.1"}, StartRequest{
		Serial:     "SERIAL",
		Control:    true,
		MaxFPS:     15,
		MaxWidth:   600,
		Bitrate:    900000,
		VideoCodec: "h264",
		LowLatency: true,
	})
	joined := shellJoin(args)
	for _, want := range []string{
		"'4.1'",
		"'tunnel_forward=true'",
		"'control=true'",
		"'max_fps=15'",
		"'max_size=600'",
		"'video_bit_rate=900000'",
		"'video_codec_options=i-frame-interval:int=1,max-bframes:int=0,latency:int=0'",
		"'send_frame_meta=true'",
	} {
		if !contains(joined, want) {
			t.Fatalf("args missing %s in %s", want, joined)
		}
	}
}

func TestLauncherConfigDefaultServerPathBelongsToMediaAdapter(t *testing.T) {
	launcher := NewADBLauncher(LauncherConfig{})
	if launcher.cfg.ServerPath != defaultLocalServerPath {
		t.Fatalf("server path=%q", launcher.cfg.ServerPath)
	}
	if !contains(launcher.cfg.ServerPath, "/media-adapter/assets/scrcpy-server") {
		t.Fatalf("expected media adapter asset path, got %q", launcher.cfg.ServerPath)
	}
}

func TestManagerOwnedScrcpyStartDoesNotRequireHostPort(t *testing.T) {
	manager := NewManagerWithLauncher(nil, fakeLauncher{}, nil)
	status, err := manager.Start(StartRequest{Serial: "SERIAL", OwnsScrcpy: true})
	if err != nil {
		t.Fatal(err)
	}
	if !status.OwnsScrcpy {
		t.Fatal("expected owned scrcpy status")
	}
	manager.Close()
}

func TestSessionRequestKeyframeWritesResetVideoControlMessage(t *testing.T) {
	client, server := net.Pipe()
	defer client.Close()
	defer server.Close()

	session := NewSession(StartRequest{Serial: "SERIAL", Host: "127.0.0.1", Port: 1, Control: true}, nil, nil, nil)
	session.setControl(client)

	done := make(chan byte, 1)
	go func() {
		var buf [1]byte
		_ = server.SetReadDeadline(time.Now().Add(time.Second))
		if _, err := io.ReadFull(server, buf[:]); err == nil {
			done <- buf[0]
		}
	}()

	if !session.RequestKeyframe() {
		t.Fatal("expected keyframe request to be written")
	}
	select {
	case got := <-done:
		if got != resetVideoMsg {
			t.Fatalf("control byte=%d", got)
		}
	case <-time.After(time.Second):
		t.Fatal("timed out waiting for control byte")
	}
}

type fakeLauncher struct{}

func (fakeLauncher) Start(context.Context, StartRequest) (*LaunchedServer, error) {
	return &LaunchedServer{Serial: "SERIAL", Host: "127.0.0.1", Port: 27183}, nil
}

func contains(value string, needle string) bool {
	for i := 0; i+len(needle) <= len(value); i++ {
		if value[i:i+len(needle)] == needle {
			return true
		}
	}
	return false
}

func TestCodecOptionsLadderDropsRiskiestKeyFirst(t *testing.T) {
	// These keys go into MediaFormat and then MediaCodec.configure(). Vendor
	// encoders — Samsung Exynos in particular — throw IllegalArgumentException
	// on ones they do not implement, killing scrcpy-server outright. The ladder
	// sheds them one at a time, keeping i-frame-interval longest because the
	// push architecture has no way to request a keyframe from the device: that
	// 1s IDR cadence is the only recovery path after packet loss.
	for _, tc := range []struct {
		level int
		want  string
	}{
		{0, "i-frame-interval:int=1,max-bframes:int=0,latency:int=0"},
		{1, "i-frame-interval:int=1,max-bframes:int=0"},
		{2, "i-frame-interval:int=1"},
		{3, ""},
		{99, ""},
	} {
		if got := codecOptionsForLevel(tc.level, true); got != tc.want {
			t.Fatalf("level %d = %q, want %q", tc.level, got, tc.want)
		}
	}
	// A negative level must not silently mean "no options"; clamp to the
	// default rung instead.
	if got := codecOptionsForLevel(-1, true); got != "i-frame-interval:int=1,max-bframes:int=0,latency:int=0" {
		t.Fatalf("negative level = %q", got)
	}
	if got := codecOptionsForLevel(0, false); got != "i-frame-interval:int=1,max-bframes:int=0" {
		t.Fatalf("low latency off = %q", got)
	}
}

func TestCodecOptionsEnvOverrideWinsIncludingEmpty(t *testing.T) {
	// The escape hatch has to be able to send NOTHING, so an operator can
	// unblock a device without a rebuild. That means distinguishing "unset"
	// from "set to empty".
	t.Setenv("MEDIA_ADAPTER_SCRCPY_CODEC_OPTIONS", "i-frame-interval:int=2")
	if got := codecOptionsForLevel(0, true); got != "i-frame-interval:int=2" {
		t.Fatalf("override ignored, got %q", got)
	}
	t.Setenv("MEDIA_ADAPTER_SCRCPY_CODEC_OPTIONS", "")
	if got := codecOptionsForLevel(0, true); got != "" {
		t.Fatalf("empty override should send no options, got %q", got)
	}
}

func TestScrcpyServerArgsOmitCodecOptionsAtLastLadderRung(t *testing.T) {
	args := scrcpyServerArgs(LauncherConfig{ServerVersion: "4.1"}, StartRequest{
		Serial: "SERIAL", MaxFPS: 15, MaxWidth: 600, Bitrate: 900000,
		VideoCodec: "h264", LowLatency: true, CodecLevel: MaxCodecLevel,
	})
	if contains(shellJoin(args), "video_codec_options") {
		t.Fatalf("last rung must send no codec options: %s", shellJoin(args))
	}
}

func TestScrcpyServerArgsIncludeRequestedVideoEncoder(t *testing.T) {
	args := shellJoin(scrcpyServerArgs(LauncherConfig{ServerVersion: "4.1"}, StartRequest{
		Serial: "SERIAL", MaxFPS: 5, MaxWidth: 480, Bitrate: 450000,
		VideoCodec: "h264", VideoEncoder: "c2.android.avc.encoder", CodecLevel: MaxCodecLevel,
	}))
	if !contains(args, "'video_encoder=c2.android.avc.encoder'") {
		t.Fatalf("server args missing video_encoder: %s", args)
	}
}

func TestDeviceSafeProfileForcesNoVideoEncoderByDefault(t *testing.T) {
	// Forcing c2.android.avc.encoder here is what hung a real SM-N975F:
	// MediaCodec.createByCodecName() never returns for that name on Android 12,
	// so the server stops right after logging "Creating encoder by name" and
	// the socket never opens. Never pin an encoder nobody verified on-device.
	got := applyDeviceSafeProfile(StartRequest{
		Serial:     "SERIAL",
		MaxFPS:     15,
		MaxWidth:   600,
		Bitrate:    900000,
		VideoCodec: "h264",
	}, "SM-N975F samsung universal9810")

	if got.VideoEncoder != "" {
		t.Fatalf("safe profile pinned an unverified encoder: %q", got.VideoEncoder)
	}
	if contains(shellJoin(scrcpyServerArgs(LauncherConfig{ServerVersion: "4.1"}, got)), "video_encoder=") {
		t.Fatal("video_encoder must be absent so scrcpy picks the device default")
	}
}

func TestSafeVideoEncoderCanBePinnedByOperator(t *testing.T) {
	t.Setenv("MEDIA_ADAPTER_SCRCPY_SAFE_VIDEO_ENCODER", "OMX.Exynos.AVC.Encoder")

	got := applyDeviceSafeProfile(StartRequest{
		Serial: "SERIAL", MaxFPS: 15, MaxWidth: 600, Bitrate: 900000, VideoCodec: "h264",
	}, "SM-N975F samsung universal9810")

	if got.VideoEncoder != "OMX.Exynos.AVC.Encoder" {
		t.Fatalf("operator pin ignored: %q", got.VideoEncoder)
	}
}

func TestDeviceSafeProfilePreservesRequestedEncoder(t *testing.T) {
	got := applyDeviceSafeProfile(StartRequest{
		Serial:       "SERIAL",
		MaxFPS:       15,
		MaxWidth:     600,
		Bitrate:      900000,
		VideoCodec:   "h264",
		VideoEncoder: "OMX.custom.avc.encoder",
	}, "SM-N975F samsung universal9810")
	if got.VideoEncoder != "OMX.custom.avc.encoder" {
		t.Fatalf("requested video encoder was overwritten: %q", got.VideoEncoder)
	}
}

func TestDeviceSafeProfileStartsNote10WithSafeEncoderAndReadableFocusedProfile(t *testing.T) {
	req := StartRequest{
		Serial:     "SERIAL",
		MaxFPS:     15,
		MaxWidth:   600,
		Bitrate:    900000,
		VideoCodec: "h264",
		LowLatency: true,
		CodecLevel: 0,
	}

	got := applyDeviceSafeProfile(req, "SM-N976B Galaxy Note 10+ samsung universal9810")

	if got.LowLatency {
		t.Fatal("Note 10+ must not start with low-latency encoder option")
	}
	// The rung itself is not the contract; keeping the IDR cadence is.
	if codecOptionsForLevel(got.CodecLevel, got.LowLatency) == "" {
		t.Fatalf("profile left the device with no IDR cadence: %+v", got)
	}
	if got.Bitrate != 900000 || !got.SkipMaxSize || !got.SkipMaxFPS {
		t.Fatalf("profile=%dbps skip_size=%v skip_fps=%v, want 900000bps and no encoder hints",
			got.Bitrate, got.SkipMaxSize, got.SkipMaxFPS)
	}
	// One codec option survives on purpose. Sending none at all is what left the
	// device with a single keyframe at startup and nothing after it, so a lost
	// packet or a late viewer froze the picture until the stream was rebuilt.
	args := shellJoin(scrcpyServerArgs(LauncherConfig{ServerVersion: "4.1"}, got))
	if !contains(args, "'video_codec_options=i-frame-interval:int=1'") {
		t.Fatalf("Note 10+ profile must keep exactly the IDR cadence: %s", args)
	}
}

func TestDeviceSafeProfileKeepsCallerBitrateForNote10(t *testing.T) {
	// The caller lowers bitrate for a device nobody is watching. Overriding it
	// here made ten listed phones publish ~900 kbps each with zero consumers
	// and left no uplink for the viewers that were real.
	req := StartRequest{
		Serial:     "SERIAL",
		MaxFPS:     1,
		MaxWidth:   320,
		Bitrate:    150000,
		VideoCodec: "h264",
		LowLatency: true,
	}

	got := applyDeviceSafeProfile(req, "SM-N976B Galaxy Note 10+ samsung universal9810")

	if got.Bitrate != 150000 {
		t.Fatalf("idle bitrate=%d, want the caller's 150000", got.Bitrate)
	}
	if !got.SkipMaxSize || !got.SkipMaxFPS {
		t.Fatalf("both encoder hints must stay off for this device: %+v", got)
	}
	if got.LowLatency {
		t.Fatalf("safe encoder settings not applied: %+v", got)
	}
	if contains(codecOptionsForLevel(got.CodecLevel, got.LowLatency), "latency") {
		t.Fatalf("profile kept the riskiest codec option: %+v", got)
	}
}

func TestDeviceSafeProfileMatchesNote10EmulatorName(t *testing.T) {
	req := StartRequest{
		Serial:     "SERIAL",
		MaxFPS:     15,
		MaxWidth:   600,
		Bitrate:    900000,
		VideoCodec: "h264",
		LowLatency: true,
	}

	got := applyDeviceSafeProfile(req, "sdk_gphone64_arm64 galaxy_note10_plus Google")

	// What identifies the profile is the two encoder hints being dropped, not a
	// particular rung. Pinning the rung is what let the IDR cadence disappear
	// unnoticed, so assert the behaviour instead of the number.
	if !got.SkipMaxSize || !got.SkipMaxFPS {
		t.Fatalf("emulator Note 10+ profile not applied: %+v", got)
	}
	if codecOptionsForLevel(got.CodecLevel, got.LowLatency) == "" {
		t.Fatalf("profile left the device with no IDR cadence: %+v", got)
	}
}

func TestDeviceSafeProfileLeavesOtherDevicesUnchanged(t *testing.T) {
	req := StartRequest{
		Serial:     "SERIAL",
		MaxFPS:     15,
		MaxWidth:   600,
		Bitrate:    900000,
		VideoCodec: "h264",
		LowLatency: true,
		CodecLevel: 1,
	}

	got := applyDeviceSafeProfile(req, "Pixel 8 Pro shiba Google")

	if got != req {
		t.Fatalf("non-Note device changed: got %+v want %+v", got, req)
	}
}

func TestDeviceSafeProfileCanBeDisabledWithoutRebuild(t *testing.T) {
	// The profile is the only thing that makes a listed device differ from a
	// working one, so it must be possible to rule it out from .env alone.
	t.Setenv("MEDIA_ADAPTER_SCRCPY_DEVICE_SAFE_PROFILE", "0")

	req := StartRequest{
		Serial: "SERIAL", MaxFPS: 30, MaxWidth: 800, Bitrate: 2000000,
		VideoCodec: "h264", LowLatency: true, CodecLevel: 0,
	}
	got := applyDeviceSafeProfile(req, "SM-N976B Galaxy Note 10+ samsung universal9810")

	if got != req {
		t.Fatalf("safe profile still applied while disabled: got %+v want %+v", got, req)
	}
	if needsDeviceSafeProfile("SM-N976B Galaxy Note 10+ samsung universal9810") {
		t.Fatal("needsDeviceSafeProfile ignored the kill switch")
	}
}

func TestNote10SafeProfileSendsNoMaxSize(t *testing.T) {
	// Any max_size aborts the server on SM-N975F: Exynos reports it needs 2px
	// alignment and then trips -fstack-protector inside MediaCodec.configure().
	// Dropping max_size is the one geometry verified to stream on the hardware.
	got := applyDeviceSafeProfile(StartRequest{
		Serial:     "SERIAL",
		MaxFPS:     15,
		MaxWidth:   600,
		Bitrate:    900000,
		VideoCodec: "h264",
	}, "SM-N976B Galaxy Note 10+ samsung universal9810")

	args := shellJoin(scrcpyServerArgs(LauncherConfig{ServerVersion: "4.1"}, got))
	if contains(args, "max_size") {
		t.Fatalf("Note 10+ must encode at native resolution: %s", args)
	}
	// The constraint bypass was a guess made before any device log existed, and
	// the configuration proven on hardware does not include it.
	if contains(args, "ignore_video_encoder_constraints") {
		t.Fatalf("safe profile reintroduced an unverified option: %s", args)
	}
}

func TestSafeProfileMaxSizeCanBePinnedByOperator(t *testing.T) {
	// Once a size is confirmed safe on real hardware, it goes back without a
	// rebuild — 16-aligned candidates are the ones worth trying.
	t.Setenv("MEDIA_ADAPTER_SCRCPY_SAFE_MAX_SIZE", "608")

	got := applyDeviceSafeProfile(StartRequest{
		Serial: "SERIAL", MaxFPS: 15, MaxWidth: 600, Bitrate: 900000, VideoCodec: "h264",
	}, "SM-N976B Galaxy Note 10+ samsung universal9810")

	if got.SkipMaxSize {
		t.Fatal("operator pin ignored: max_size still omitted")
	}
	if !contains(shellJoin(scrcpyServerArgs(LauncherConfig{ServerVersion: "4.1"}, got)), "'max_size=608'") {
		t.Fatalf("pinned size did not reach server args: %+v", got)
	}
}

func TestEncoderConstraintsKeptForOtherDevicesByDefault(t *testing.T) {
	got := applyDeviceSafeProfile(StartRequest{
		Serial:     "SERIAL",
		MaxFPS:     15,
		MaxWidth:   600,
		Bitrate:    900000,
		VideoCodec: "h264",
	}, "Pixel 8 Pro shiba Google")

	args := shellJoin(scrcpyServerArgs(LauncherConfig{ServerVersion: "4.1"}, got))
	if contains(args, "ignore_video_encoder_constraints") {
		t.Fatalf("non-Note device silently lost encoder constraints: %s", args)
	}
}

func TestEncoderConstraintsBypassCanBeForcedFleetWide(t *testing.T) {
	t.Setenv("MEDIA_ADAPTER_SCRCPY_IGNORE_ENCODER_CONSTRAINTS", "1")

	args := shellJoin(scrcpyServerArgs(LauncherConfig{ServerVersion: "4.1"}, StartRequest{
		Serial: "SERIAL", MaxFPS: 15, MaxWidth: 600, Bitrate: 900000, VideoCodec: "h264",
	}))

	if !contains(args, "'ignore_video_encoder_constraints=true'") {
		t.Fatalf("env override did not reach server args: %s", args)
	}
}

// unprobeableLauncher returns a launcher whose every adb invocation fails, so
// deviceSignature must fall back to whatever it has cached.
func unprobeableLauncher() *ADBLauncher {
	return NewADBLauncher(LauncherConfig{
		ADBPath:   "/nonexistent/device-farm-test-adb",
		VerifyTTL: time.Minute,
	})
}

func TestDeviceSignatureReusesCachedValueWhenProbeFails(t *testing.T) {
	// The failure this guards: a Note 10+ whose getprop probe times out reads
	// as "not a Note 10+", loses c2.android.avc.encoder, and starts on the
	// default encoder that fails on this model.
	launcher := unprobeableLauncher()
	launcher.signatures["SERIAL"] = deviceProbe{
		value:    "SM-N976B Galaxy Note 10+ samsung universal9810",
		probedAt: time.Now().Add(-time.Hour), // stale on purpose
	}

	got := launcher.deviceSignature(context.Background(), "SERIAL")

	if !needsDeviceSafeProfile(got) {
		t.Fatalf("failed probe dropped the safe profile: signature=%q", got)
	}
	if !applyDeviceSafeProfile(StartRequest{Serial: "SERIAL"}, got).SkipMaxSize {
		t.Fatal("Note 10+ lost its safe profile after a failed probe")
	}
}

func TestDeviceSignatureSkipsProbeWhileCacheIsFresh(t *testing.T) {
	launcher := unprobeableLauncher()
	launcher.signatures["SERIAL"] = deviceProbe{
		value:    "SM-N975F samsung universal9810",
		probedAt: time.Now(),
	}

	// adb cannot run here, so a returned value proves the cache was used.
	if got := launcher.deviceSignature(context.Background(), "SERIAL"); got != "SM-N975F samsung universal9810" {
		t.Fatalf("fresh cache not reused: %q", got)
	}
}

func TestDeviceSignatureReturnsEmptyWhenProbeFailsWithNoCache(t *testing.T) {
	launcher := unprobeableLauncher()

	if got := launcher.deviceSignature(context.Background(), "SERIAL"); got != "" {
		t.Fatalf("signature=%q, want empty when nothing is known", got)
	}
}

func TestSessionDegradesCodecLevelOnlyAfterRepeatedFailures(t *testing.T) {
	// One failure must not cost encoder settings the device may well support —
	// a busy device or an ADB blip is not evidence of an unsupported key.
	session := NewSession(StartRequest{Serial: "SERIAL"}, nil, nil, nil)
	session.degradeCodecLevel()
	if got := session.currentCodecLevel(); got != 0 {
		t.Fatalf("degraded after one failure: level=%d", got)
	}
	session.degradeCodecLevel()
	if got := session.currentCodecLevel(); got != 1 {
		t.Fatalf("level after %d failures = %d, want 1", codecFailuresPerLevel, got)
	}

	// And it must stop at the bottom rather than climbing forever.
	for i := 0; i < 40; i++ {
		session.degradeCodecLevel()
	}
	if got := session.currentCodecLevel(); got != MaxCodecLevel {
		t.Fatalf("level ran past the ladder: %d", got)
	}
}

func TestSessionCoolsDownSafeProfileHandshakeFailures(t *testing.T) {
	session := NewSession(StartRequest{Serial: "SERIAL", CodecLevel: MaxCodecLevel}, nil, nil, nil)
	err := fmt.Errorf("%s at host.docker.internal:58516 after 10s: EOF", scrcpyHandshakeNotReadyFragment)

	if got := session.reconnectSleep(150*time.Millisecond, err); got != safeProfileHandshakeBackoffMin {
		t.Fatalf("sleep=%s, want %s", got, safeProfileHandshakeBackoffMin)
	}
	if got := session.reconnectBackoffCap(err); got != safeProfileHandshakeBackoffMax {
		t.Fatalf("cap=%s, want %s", got, safeProfileHandshakeBackoffMax)
	}

	session = NewSession(StartRequest{Serial: "SERIAL", CodecLevel: MaxCodecLevel - 1}, nil, nil, nil)
	if got := session.reconnectSleep(150*time.Millisecond, err); got != 150*time.Millisecond {
		t.Fatalf("non-safe profile sleep=%s", got)
	}
	if got := session.reconnectBackoffCap(err); got != normalReconnectBackoffMax {
		t.Fatalf("non-safe profile cap=%s", got)
	}
}

func TestSessionAcquireLaunchSlotLimitsColdStarts(t *testing.T) {
	session := NewSession(StartRequest{Serial: "SERIAL"}, nil, nil, nil)
	session.launchLimiter = make(chan struct{}, 1)

	release, err := session.acquireLaunchSlot()
	if err != nil {
		t.Fatal(err)
	}
	secondReady := make(chan func(), 1)
	go func() {
		secondRelease, err := session.acquireLaunchSlot()
		if err != nil {
			return
		}
		secondReady <- secondRelease
	}()

	select {
	case secondRelease := <-secondReady:
		secondRelease()
		t.Fatal("second cold start acquired the slot before the first released it")
	case <-time.After(30 * time.Millisecond):
	}

	release()
	select {
	case secondRelease := <-secondReady:
		secondRelease()
	case <-time.After(time.Second):
		t.Fatal("second cold start did not acquire the slot after release")
	}
}

func TestSessionSuccessResetsFailureRunAndReportsLevel(t *testing.T) {
	session := NewSession(StartRequest{Serial: "SERIAL", CodecLevel: 2}, nil, nil, nil)
	var gotSerial string
	gotLevel := -1
	session.onCodecLevel = func(serial string, level int) {
		gotSerial, gotLevel = serial, level
	}

	session.degradeCodecLevel() // one failure, not yet enough to drop
	session.rememberCodecLevel()
	if gotSerial != "SERIAL" || gotLevel != 2 {
		t.Fatalf("reported %q/%d, want SERIAL/2", gotSerial, gotLevel)
	}
	// The earlier failure must not carry over: the next single failure should
	// not be treated as the second in a row.
	session.degradeCodecLevel()
	if got := session.currentCodecLevel(); got != 2 {
		t.Fatalf("failure run was not reset: level=%d", got)
	}
}

func TestManagerStartsAtTheLevelTheDeviceIsKnownToAccept(t *testing.T) {
	// Climbing the ladder costs one scrcpy cold start per rung (~4s measured),
	// so a device that needs a lower rung must not re-pay that every session.
	manager := NewManagerWithLauncher(nil, fakeLauncher{}, nil)
	defer manager.Close()

	manager.recordCodecLevel("SERIAL", 2)
	if got := manager.knownCodecLevel("SERIAL"); got != 2 {
		t.Fatalf("remembered level = %d", got)
	}

	if _, err := manager.Start(StartRequest{Serial: "SERIAL", OwnsScrcpy: true}); err != nil {
		t.Fatal(err)
	}
	manager.mu.Lock()
	session := manager.sessions["SERIAL"]
	manager.mu.Unlock()
	if got := session.currentCodecLevel(); got != 2 {
		t.Fatalf("session started at level %d, want the remembered 2", got)
	}
}

func TestLaunchedServerKeepsRecentOutputForFailureReports(t *testing.T) {
	// The device's own explanation is printed by scrcpy-server and nowhere
	// else; the adapter otherwise sees only a socket that never opens.
	server := &LaunchedServer{Serial: "SERIAL"}
	for i := 0; i < recentOutputCap+5; i++ {
		server.recordOutput(fmt.Sprintf("line-%d", i))
	}
	got := server.RecentOutput()
	if len(got) != recentOutputCap {
		t.Fatalf("kept %d lines, want %d", len(got), recentOutputCap)
	}
	if got[len(got)-1] != fmt.Sprintf("line-%d", recentOutputCap+4) {
		t.Fatalf("ring dropped the newest line: %v", got)
	}
	// Must be safe on the nil path, which is what a failed launch leaves behind.
	var missing *LaunchedServer
	if missing.RecentOutput() != nil {
		t.Fatal("nil server should report no output")
	}
}

func TestLauncherForgetsJarAfterFailureSoRetryRePushes(t *testing.T) {
	// ensureServer skips the existence check while its cache is warm. A jar
	// that vanishes mid-window makes every launch fail in silence — app_process
	// exits at once, the socket never opens — and without invalidation the
	// device stays dead until the TTL expires, five minutes by default.
	// Observed live: the jar was gone and the session spun for minutes logging
	// only "handshake not ready ... EOF" with empty scrcpy output.
	launcher := NewADBLauncher(LauncherConfig{})
	launcher.markReady("SERIAL:/path/to/server:100")
	launcher.markReady("OTHER:/path/to/server:100")

	launcher.InvalidateServer("SERIAL")

	launcher.mu.Lock()
	_, stillCached := launcher.ready["SERIAL:/path/to/server:100"]
	_, otherKept := launcher.ready["OTHER:/path/to/server:100"]
	launcher.mu.Unlock()
	if stillCached {
		t.Fatal("failed device still cached; retry would skip the re-push")
	}
	if !otherKept {
		t.Fatal("invalidation must not clear unrelated devices")
	}
}

func TestSessionInvalidatesServerCacheOnFailure(t *testing.T) {
	launcher := &recordingLauncher{}
	session := NewSession(StartRequest{Serial: "SERIAL"}, nil, launcher, nil)
	session.invalidateServerCache()
	if launcher.invalidated != "SERIAL" {
		t.Fatalf("invalidated %q, want SERIAL", launcher.invalidated)
	}

	// A launcher that does not implement the optional interface must not panic.
	plain := NewSession(StartRequest{Serial: "SERIAL"}, nil, fakeLauncher{}, nil)
	plain.invalidateServerCache()
}

type recordingLauncher struct {
	fakeLauncher
	invalidated string
}

func (r *recordingLauncher) InvalidateServer(serial string) { r.invalidated = serial }

func TestManagerKeepsLiveStreamWhenOnlyProfileDiffers(t *testing.T) {
	// The relay and each WebRTC viewer pick their own fps/size/bitrate. Tearing
	// the stream down for that disagreement cost a scrcpy cold start, which is
	// longer than the 4s a viewer waits for a first frame — so the viewer got
	// 425, retried, and flipped the numbers back. 339 requests, 10 answers.
	manager := NewManagerWithLauncher(nil, fakeLauncher{}, nil)
	defer manager.Close()

	base := StartRequest{Serial: "SERIAL", OwnsScrcpy: true, Control: true,
		MaxFPS: 15, MaxWidth: 600, Bitrate: 900000, VideoCodec: "h264"}
	if _, err := manager.Start(base); err != nil {
		t.Fatal(err)
	}
	live := manager.sessions["SERIAL"]
	live.markConnected(1080, 2220)
	live.recordFrame(4096, true, true)

	// The idle throttle asking for less must not disturb a viewer.
	idle := base
	idle.MaxFPS, idle.MaxWidth, idle.Bitrate = 1, 320, 150000
	if _, err := manager.Start(idle); err != nil {
		t.Fatal(err)
	}

	if manager.sessions["SERIAL"] != live {
		t.Fatal("a healthy stream was torn down to give the viewer less")
	}
}

func TestManagerRestartsToDeliverAnUpgrade(t *testing.T) {
	// Refusing every profile change made a viewer that asked for 15fps render
	// at whatever the idle throttle had last set — 1fps. scrcpy fixes the rate
	// at launch, so more picture costs exactly one cold start.
	manager := NewManagerWithLauncher(nil, fakeLauncher{}, nil)
	defer manager.Close()

	idle := StartRequest{Serial: "SERIAL", OwnsScrcpy: true, Control: true,
		MaxFPS: 1, MaxWidth: 320, Bitrate: 150000, VideoCodec: "h264"}
	if _, err := manager.Start(idle); err != nil {
		t.Fatal(err)
	}
	live := manager.sessions["SERIAL"]
	live.markConnected(320, 640)
	live.recordFrame(1024, true, true)

	viewer := idle
	viewer.MaxFPS, viewer.MaxWidth, viewer.Bitrate = 15, 600, 900000
	if _, err := manager.Start(viewer); err != nil {
		t.Fatal(err)
	}

	rebuilt := manager.sessions["SERIAL"]
	if rebuilt == live {
		t.Fatal("viewer asking for 15fps was left on the 1fps stream")
	}
	if got := rebuilt.request().MaxFPS; got != 15 {
		t.Fatalf("new session max fps=%d, want 15", got)
	}
}

func TestManagerStillRebuildsWhenSessionIdentityChanges(t *testing.T) {
	// Control socket, endpoint and codec cannot be papered over — those really
	// do need a new session, healthy or not.
	manager := NewManagerWithLauncher(nil, fakeLauncher{}, nil)
	defer manager.Close()

	base := StartRequest{Serial: "SERIAL", OwnsScrcpy: true, Control: false,
		MaxFPS: 15, MaxWidth: 600, Bitrate: 900000, VideoCodec: "h264"}
	if _, err := manager.Start(base); err != nil {
		t.Fatal(err)
	}
	live := manager.sessions["SERIAL"]
	live.markConnected(1080, 2220)
	live.recordFrame(4096, true, true)

	withControl := base
	withControl.Control = true
	if _, err := manager.Start(withControl); err != nil {
		t.Fatal(err)
	}
	if manager.sessions["SERIAL"] == live {
		t.Fatal("enabling control must rebuild the session")
	}
}

func TestManagerKeepsStartingStreamAgainstADowngrade(t *testing.T) {
	// The cold-start window is where a racing downgrade does the most damage:
	// it kills a launch that was about to succeed and leaves another frameless
	// session in its place. Protection must not depend on frames having
	// arrived yet.
	manager := NewManagerWithLauncher(nil, fakeLauncher{}, nil)
	defer manager.Close()

	viewer := StartRequest{Serial: "SERIAL", OwnsScrcpy: true, VideoCodec: "h264",
		MaxFPS: 15, MaxWidth: 600, Bitrate: 900000}
	if _, err := manager.Start(viewer); err != nil {
		t.Fatal(err)
	}
	starting := manager.sessions["SERIAL"] // no frames yet, on purpose

	idle := viewer
	idle.MaxFPS, idle.MaxWidth, idle.Bitrate = 1, 320, 150000
	if _, err := manager.Start(idle); err != nil {
		t.Fatal(err)
	}
	if manager.sessions["SERIAL"] != starting {
		t.Fatal("a launch in progress was killed by the idle throttle")
	}
}
