package adbserver

import (
	"os"
	"path/filepath"
	"runtime"
	"slices"
	"testing"
	"time"
)

func TestFromEnvParsesMultipleADBSockets(t *testing.T) {
	t.Setenv("ADB_SERVER_SOCKETS", "tcp:host.docker.internal:5037,tcp:host.docker.internal:5038")

	servers := FromEnv()
	if len(servers) != 2 {
		t.Fatalf("servers=%v", servers)
	}
	if servers[0].Host != "host.docker.internal" || servers[0].Port != "5037" {
		t.Fatalf("first server=%+v", servers[0])
	}
	if servers[1].Host != "host.docker.internal" || servers[1].Port != "5038" {
		t.Fatalf("second server=%+v", servers[1])
	}
}

func TestParseDeviceOutputRemembersSerialRoute(t *testing.T) {
	server := Server{Host: "host.docker.internal", Port: "5038"}
	serials := parseDeviceOutput("List of devices attached\nPHONE2\tdevice\nOFF\toffline\n", server)
	if len(serials) != 1 || serials[0] != "PHONE2" {
		t.Fatalf("serials=%v", serials)
	}
	args := ArgsForSerial(t.Context(), "adb", "PHONE2")
	want := []string{"-H", "host.docker.internal", "-P", "5038"}
	if len(args) != len(want) {
		t.Fatalf("args=%v", args)
	}
	for i := range want {
		if args[i] != want[i] {
			t.Fatalf("args=%v want=%v", args, want)
		}
	}
}

// fakeADB writes a stub `adb` that reports PHONE9 only on the given port.
func fakeADB(t *testing.T, onPort string) string {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("stub adb is a shell script")
	}
	path := filepath.Join(t.TempDir(), "adb")
	script := "#!/bin/sh\nif [ \"$4\" = \"" + onPort + "\" ]; then\n" +
		"printf 'List of devices attached\\nPHONE9\\tdevice\\n'\nelse\n" +
		"printf 'List of devices attached\\n'\nfi\n"
	if err := os.WriteFile(path, []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	return path
}

// A serial this process has not scanned yet must not silently take the first
// configured server: scrcpy would then start against a server that does not own
// the device while the control path talks to the right one.
func TestArgsForSerialDiscoversOnCacheMiss(t *testing.T) {
	t.Setenv("ADB_SERVER_SOCKETS", "tcp:127.0.0.1:5037,tcp:127.0.0.1:5038")
	serialRoutes.Delete("PHONE9")
	discoverMu.Lock()
	lastDiscoveryAt = time.Time{}
	discoverMu.Unlock()

	args := ArgsForSerial(t.Context(), fakeADB(t, "5038"), "PHONE9")
	want := []string{"-H", "127.0.0.1", "-P", "5038"}
	if !slices.Equal(args, want) {
		t.Fatalf("args=%v want=%v (fell back to the first server)", args, want)
	}
}

// The rescan is rate-limited, so a burst of misses cannot fan out into one
// `adb devices` per call.
func TestArgsForSerialRescanIsRateLimited(t *testing.T) {
	t.Setenv("ADB_SERVER_SOCKETS", "tcp:127.0.0.1:5037,tcp:127.0.0.1:5038")
	serialRoutes.Delete("PHONE9")
	discoverMu.Lock()
	lastDiscoveryAt = time.Now()
	discoverMu.Unlock()

	adb := filepath.Join(t.TempDir(), "adb-must-not-run")
	args := ArgsForSerial(t.Context(), adb, "PHONE9")
	want := []string{"-H", "127.0.0.1", "-P", "5037"}
	if !slices.Equal(args, want) {
		t.Fatalf("args=%v want=%v", args, want)
	}
}
