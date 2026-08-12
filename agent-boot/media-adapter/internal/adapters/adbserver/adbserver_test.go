package adbserver

import "testing"

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
