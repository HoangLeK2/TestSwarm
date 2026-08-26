package scrcpy

import "testing"

// `wm size` and `wm density` print the panel value and, when the display has
// been resized, an override. The override is what the display actually runs at
// and therefore what scrcpy captures.
func TestEffectiveWMValuePrefersOverride(t *testing.T) {
	out := "Physical size: 1440x2960\nOverride size: 1080x2220\n"
	if got := effectiveWMValue(out, "size"); got != "1080x2220" {
		t.Fatalf("size=%q, want the override", got)
	}
	if got := effectiveWMValue("Physical density: 560\nOverride density: 420\n", "density"); got != "420" {
		t.Fatalf("density=%q, want the override", got)
	}
}

func TestEffectiveWMValueFallsBackToPhysical(t *testing.T) {
	if got := effectiveWMValue("Physical size: 1080x2340\n", "size"); got != "1080x2340" {
		t.Fatalf("size=%q", got)
	}
	if got := effectiveWMValue("noise without a colon\n", "size"); got != "" {
		t.Fatalf("size=%q, want empty", got)
	}
}

func TestParseDisplaySizeRejectsJunk(t *testing.T) {
	for _, bad := range []string{"", "720", "720*1480", "0x1480", "-1x2", "axb"} {
		if _, _, ok := parseDisplaySize(bad); ok {
			t.Fatalf("accepted %q", bad)
		}
	}
	w, h, ok := parseDisplaySize(" 720x1480 ")
	if !ok || w != 720 || h != 1480 {
		t.Fatalf("got %dx%d ok=%v", w, h, ok)
	}
}

// Density must follow width, or the UI is laid out for a screen that is gone.
func TestDensityScalesWithWidth(t *testing.T) {
	density, ok := parseFirstInt(effectiveWMValue("Physical density: 480\n", "density"))
	if !ok {
		t.Fatal("density not parsed")
	}
	wantW, _, _ := parseDisplaySize("720x1480")
	currentW, _, _ := parseDisplaySize("1080x2220")
	if got := density * wantW / currentW; got != 320 {
		t.Fatalf("scaled density=%d, want 320", got)
	}
}

// Nothing may touch the phone unless an operator named a size.
func TestSafeDisplaySizeIsOptOut(t *testing.T) {
	launcher := unprobeableLauncher()
	launcher.applySafeDisplaySize(nil, "SERIAL") //nolint:staticcheck // nil ctx unused on this path
	if launcher.displaySized["SERIAL"] {
		t.Fatal("resized a device with no size configured")
	}
}

func TestNote10SafeProfileSendsNoCodecOptions(t *testing.T) {
	// SM-N975F aborts on a single MediaFormat key. Keyframes are recovered via
	// RESET_VIDEO when a viewer attaches, not by asking the encoder for a
	// cadence it cannot survive being told about.
	got := applyDeviceSafeProfile(StartRequest{
		Serial: "SERIAL", MaxFPS: 15, MaxWidth: 600, Bitrate: 900000, VideoCodec: "h264",
	}, "SM-N976B Galaxy Note 10+ samsung universal9810")

	args := shellJoin(scrcpyServerArgs(LauncherConfig{ServerVersion: "4.1"}, got))
	for _, forbidden := range []string{"video_codec_options", "i-frame-interval", "max-bframes", "latency:int"} {
		if contains(args, forbidden) {
			t.Fatalf("safe profile sent %q to a device that aborts on it: %s", forbidden, args)
		}
	}
}
