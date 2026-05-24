package core

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"
)

// ShutdownManager handles graceful shutdown with signal handling and cleanup callbacks.
type ShutdownManager struct {
	timeout     time.Duration
	cleanupFns  []func()
	mu          sync.Mutex
	shutdownCtx context.Context
	cancel      context.CancelFunc
}

// NewShutdownManager creates a new shutdown manager.
func NewShutdownManager(timeout time.Duration) *ShutdownManager {
	if timeout <= 0 {
		timeout = 30 * time.Second
	}

	ctx, cancel := context.WithCancel(context.Background())
	return &ShutdownManager{
		timeout:     timeout,
		shutdownCtx: ctx,
		cancel:      cancel,
	}
}

// RegisterCleanup adds a cleanup function to be called during shutdown.
func (s *ShutdownManager) RegisterCleanup(fn func()) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.cleanupFns = append(s.cleanupFns, fn)
}

// Context returns the context that is cancelled when shutdown begins.
func (s *ShutdownManager) Context() context.Context {
	return s.shutdownCtx
}

// Wait blocks until a shutdown signal is received, runs cleanup, then exits.
// Should be called as the last thing in main().
func (s *ShutdownManager) Wait() {
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	sig := <-sigCh
	slog.Info("shutdown signal received", "signal", sig)
	s.shutdown()
}

// Shutdown triggers the shutdown sequence manually.
func (s *ShutdownManager) Shutdown() {
	slog.Info("manual shutdown triggered")
	s.shutdown()
}

// shutdown performs the actual shutdown sequence.
func (s *ShutdownManager) shutdown() {
	// Cancel the main context
	s.cancel()

	// Run cleanup with timeout
	done := make(chan struct{})
	go func() {
		s.runCleanup()
		close(done)
	}()

	select {
	case <-done:
		slog.Info("shutdown completed successfully")
	case <-time.After(s.timeout):
		slog.Warn("shutdown timeout exceeded, forcing exit", "timeout", s.timeout)
		os.Exit(1)
	}
}

// runCleanup executes all registered cleanup functions.
func (s *ShutdownManager) runCleanup() {
	s.mu.Lock()
	fns := make([]func(), len(s.cleanupFns))
	copy(fns, s.cleanupFns)
	s.mu.Unlock()

	for i, fn := range fns {
		slog.Info("running cleanup", "index", i+1, "total", len(fns))
		func() {
			defer func() {
				if r := recover(); r != nil {
					slog.Error("cleanup panicked", "index", i+1, "panic", r)
				}
			}()
			fn()
		}()
	}
}
