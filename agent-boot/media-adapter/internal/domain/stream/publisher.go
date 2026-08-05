package stream

import "context"

type Publisher interface {
	Publish(ctx context.Context, packet EncodedPacket) error
	Close(ctx context.Context) error
}
