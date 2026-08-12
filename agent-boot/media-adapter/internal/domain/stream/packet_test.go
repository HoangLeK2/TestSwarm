package stream

import "testing"

func TestClonePayloadCopiesBorrowedPayload(t *testing.T) {
	payload := []byte{1, 2, 3}
	packet := EncodedPacket{Payload: payload}

	cloned := packet.ClonePayload()
	payload[0] = 9

	if cloned[0] != 1 {
		t.Fatalf("borrowed payload was not copied: %v", cloned)
	}
}

func TestClonePayloadReusesOwnedPayload(t *testing.T) {
	payload := []byte{1, 2, 3}
	packet := EncodedPacket{Payload: payload, Owned: true}

	cloned := packet.ClonePayload()
	payload[0] = 9

	if cloned[0] != 9 {
		t.Fatalf("owned payload should reuse backing array: %v", cloned)
	}
}
