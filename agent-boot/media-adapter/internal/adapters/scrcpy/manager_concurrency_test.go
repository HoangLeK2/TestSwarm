// Concurrency rules for Manager, learned the hard way on a live farm.
//
// Manager.mu and Session.mu form a cycle if either is held across the other:
// Session.Stop waits for run() to exit, and run() reports its codec level back
// through Manager.recordCodecLevel, which needs Manager.mu. Every test here
// exists to keep that cycle open.

package scrcpy

import (
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
