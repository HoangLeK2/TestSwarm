package stream

import (
	"regexp"
	"strings"
	"time"
)

type EncodedPacket struct {
	Serial   string
	Payload  []byte
	Owned    bool
	IsConfig bool
	IsKey    bool
	PTSUs    uint64
	Width    uint16
	Height   uint16
	Received time.Time
}

func (p EncodedPacket) ClonePayload() []byte {
	if p.Owned {
		return p.Payload
	}
	next := make([]byte, len(p.Payload))
	copy(next, p.Payload)
	return next
}

var unsafeStreamName = regexp.MustCompile(`[^A-Za-z0-9_.-]+`)

const streamNamePrefix = "device-"

func StreamName(serial string) string {
	safe := unsafeStreamName.ReplaceAllString(strings.TrimSpace(serial), "_")
	if safe == "" {
		safe = "unknown"
	}
	return streamNamePrefix + safe
}
