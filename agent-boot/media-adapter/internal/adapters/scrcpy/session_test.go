package scrcpy

import (
	"context"
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
