package controlplane

import (
	"testing"

	"google.golang.org/grpc/encoding"
)

func TestGRPCGzipCodecIsRegistered(t *testing.T) {
	if encoding.GetCompressor("gzip") == nil {
		t.Fatal("gzip gRPC compressor/decompressor is not registered")
	}
}
