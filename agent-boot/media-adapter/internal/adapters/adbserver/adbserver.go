package adbserver

import (
	"context"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"
)

type Server struct {
	Host string
	Port string
}

var serialRoutes sync.Map

func FromEnv() []Server {
	raw := strings.TrimSpace(os.Getenv("ADB_SERVER_SOCKETS"))
	if raw == "" {
		raw = strings.TrimSpace(os.Getenv("AGENT_BOOT_ADB_SERVER_SOCKETS"))
	}
	if raw != "" {
		return parseServers(raw)
	}
	host := strings.TrimSpace(os.Getenv("ADB_HOST"))
	port := strings.TrimSpace(os.Getenv("ADB_PORT"))
	socket := strings.TrimSpace(os.Getenv("ADB_SERVER_SOCKET"))
	if strings.HasPrefix(socket, "tcp:") {
		parsed := parseServer(strings.TrimPrefix(socket, "tcp:"))
		if parsed.Host != "" && parsed.Port != "" {
			return []Server{parsed}
		}
	}
	if host != "" && port != "" {
		return []Server{{Host: host, Port: port}}
	}
	return nil
}

func DeviceSerials(ctx context.Context, adbPath string) []string {
	if adbPath == "" {
		adbPath = "adb"
	}
	servers := FromEnv()
	if len(servers) == 0 {
		out, err := exec.CommandContext(ctx, adbPath, "devices").Output()
		if err != nil {
			return nil
		}
		return parseDeviceOutput(string(out), Server{})
	}
	seen := make(map[string]struct{})
	serials := make([]string, 0)
	for _, server := range servers {
		runCtx, cancel := context.WithTimeout(ctx, 1200*time.Millisecond)
		out, err := exec.CommandContext(runCtx, adbPath, "-H", server.Host, "-P", server.Port, "devices").Output()
		cancel()
		if err != nil {
			continue
		}
		for _, serial := range parseDeviceOutput(string(out), server) {
			if _, ok := seen[serial]; ok {
				continue
			}
			seen[serial] = struct{}{}
			serials = append(serials, serial)
		}
	}
	return serials
}

func ArgsForSerial(ctx context.Context, adbPath string, serial string) []string {
	if serial == "" {
		return defaultArgs()
	}
	if value, ok := serialRoutes.Load(serial); ok {
		if server, ok := value.(Server); ok && server.Host != "" && server.Port != "" {
			return server.Args()
		}
	}
	return defaultArgs()
}

func (s Server) Args() []string {
	if s.Host == "" || s.Port == "" {
		return nil
	}
	return []string{"-H", s.Host, "-P", s.Port}
}

func defaultArgs() []string {
	servers := FromEnv()
	if len(servers) > 0 {
		return servers[0].Args()
	}
	return nil
}

func parseServers(raw string) []Server {
	parts := strings.FieldsFunc(raw, func(r rune) bool {
		return r == ',' || r == ';' || r == ' ' || r == '\n' || r == '\t'
	})
	seen := make(map[string]struct{})
	out := make([]Server, 0, len(parts))
	for _, part := range parts {
		server := parseServer(strings.TrimPrefix(strings.TrimSpace(part), "tcp:"))
		if server.Host == "" || server.Port == "" {
			continue
		}
		key := server.Host + ":" + server.Port
		if _, ok := seen[key]; ok {
			continue
		}
		seen[key] = struct{}{}
		out = append(out, server)
	}
	return out
}

func parseServer(value string) Server {
	host, port, ok := strings.Cut(value, ":")
	if !ok || strings.TrimSpace(host) == "" || strings.TrimSpace(port) == "" {
		return Server{}
	}
	port = strings.TrimSpace(port)
	if _, err := strconv.Atoi(port); err != nil {
		return Server{}
	}
	return Server{Host: strings.TrimSpace(host), Port: port}
}

func parseDeviceOutput(out string, server Server) []string {
	lines := strings.Split(out, "\n")
	serials := make([]string, 0, len(lines))
	for _, line := range lines[1:] {
		fields := strings.Fields(line)
		if len(fields) >= 2 && fields[1] == "device" {
			serial := fields[0]
			serials = append(serials, serial)
			if server.Host != "" && server.Port != "" {
				serialRoutes.Store(serial, server)
			}
		}
	}
	return serials
}
