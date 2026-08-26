// Concurrency rules for Manager, learned the hard way on a live farm.
//
// Manager.mu and Session.mu form a cycle if either is held across the other:
// Session.Stop waits for run() to exit, and run() reports its codec level back
// through Manager.recordCodecLevel, which needs Manager.mu. Every test here
// exists to keep that cycle open.

package scrcpy

import (
	"context"
	"sync"
	"testing"
	"time"
)

func TestManagerStopDoesNotDeadlockAgainstCodecLevelReport(t *testing.T) {
	manager := NewManagerWithLauncher(nil, fakeLauncher{}, nil)
	defer manager.Close()
	if _, err := manager.Start(StartRequest{Serial: "S", OwnsScrcpy: true}); err != nil {
		t.Fatal(err)
	}
	go manager.recordCodecLevel("S", 2)
	done := make(chan struct{})
	go func() { manager.Stop("S"); close(done) }()
	select {
	case <-done:
	case <-time.After(3 * time.Second):
		t.Fatal("Manager.Stop deadlocked")
	}
}

func TestManagerStartIsSafeUnderConcurrentCallers(t *testing.T) {
	// The relay, every dashboard tile and every control screen call Start for
	// the same serial at once. Measured on a live farm: 339 calls in 3 minutes.
	manager := NewManagerWithLauncher(nil, fakeLauncher{}, nil)
	defer manager.Close()

	var wg sync.WaitGroup
	for i := 0; i < 40; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			req := StartRequest{Serial: "S", OwnsScrcpy: true, VideoCodec: "h264",
				MaxFPS: 1 + i%3, MaxWidth: 320 + i%2*280, Bitrate: 150000 + i%2*750000}
			if _, err := manager.Start(req); err != nil {
				t.Errorf("Start: %v", err)
			}
			manager.Status("S")
		}(i)
	}
	done := make(chan struct{})
	go func() { wg.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(10 * time.Second):
		t.Fatal("concurrent Start calls deadlocked")
	}
	if manager.sessions["S"] == nil {
		t.Fatal("no session survived the storm")
	}
}

// slowLauncher keeps run() inside the launch long enough that a racing caller
// can reach Stop while the session is still being handed out.
type slowLauncher struct{ delay time.Duration }

func (l slowLauncher) Start(ctx context.Context, _ StartRequest) (*LaunchedServer, error) {
	select {
	case <-time.After(l.delay):
	case <-ctx.Done():
	}
	return &LaunchedServer{Serial: "S", Host: "127.0.0.1", Port: 27183}, nil
}

func TestStopIsSafeOnASessionThatNeverStarted(t *testing.T) {
	// Manager.Start publishes the session and releases the lock before calling
	// Start(), so another caller can Stop it in between. s.done is closed by
	// run() and by nothing else, so waiting on it here used to block until the
	// process exited — one hung HTTP request per race, and ten dashboard tiles
	// hit it often enough to read as "the stream takes forever to appear".
	session := NewSession(StartRequest{Serial: "S"}, nil, nil, nil)

	done := make(chan struct{})
	go func() { session.Stop(); close(done) }()
	select {
	case <-done:
	case <-time.After(3 * time.Second):
		t.Fatal("Stop blocked on a session whose goroutine never ran")
	}

	// Starting afterwards must be harmless: the context is already cancelled.
	session.Start()
	select {
	case <-session.done:
	case <-time.After(3 * time.Second):
		t.Fatal("run() did not exit on an already-cancelled session")
	}
}

func TestConcurrentStartsDoNotHangOnAHandedOverSession(t *testing.T) {
	manager := NewManagerWithLauncher(nil, slowLauncher{delay: 150 * time.Millisecond}, nil)
	defer manager.Close()

	var wg sync.WaitGroup
	for i := 0; i < 24; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			// Every caller asks for strictly more, so each one replaces the
			// session the previous caller just published.
			req := StartRequest{Serial: "S", OwnsScrcpy: true, VideoCodec: "h264",
				MaxFPS: 1 + i, MaxWidth: 320 + i, Bitrate: 150000 + i*1000}
			if _, err := manager.Start(req); err != nil {
				t.Errorf("Start: %v", err)
			}
		}(i)
	}
	finished := make(chan struct{})
	go func() { wg.Wait(); close(finished) }()
	select {
	case <-finished:
	case <-time.After(15 * time.Second):
		t.Fatal("a Start call hung stopping a session that had not been launched")
	}
}
