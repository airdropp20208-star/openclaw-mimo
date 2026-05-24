package core

import (
	"context"
	"fmt"
	"log/slog"
	"os/exec"
	"sync"
	"time"
)

// Watchdog monitors and manages a Python subprocess, auto-restarting on crash
// with escalating cooldown periods.
type Watchdog struct {
	cmd          string
	args         []string
	cooldownMs   int
	maxRestarts  int

	mu          sync.Mutex
	cmdObj      *exec.Cmd
	restarts    int
	lastStart   time.Time
	running     bool
	stopCh      chan struct{}

	// Callbacks
	onStart  func()
	onCrash  func(error)
	onStop   func()
}

// WatchdogConfig configures the watchdog behavior.
type WatchdogConfig struct {
	Command      string
	Args         []string
	CooldownMs   int
	MaxRestarts  int
	OnStart      func()
	OnCrash      func(error)
	OnStop       func()
}

// NewWatchdog creates a new process watchdog.
func NewWatchdog(cfg WatchdogConfig) *Watchdog {
	if cfg.CooldownMs <= 0 {
		cfg.CooldownMs = 1000
	}
	if cfg.MaxRestarts <= 0 {
		cfg.MaxRestarts = 10
	}
	return &Watchdog{
		cmd:         cfg.Command,
		args:        cfg.Args,
		cooldownMs:  cfg.CooldownMs,
		maxRestarts: cfg.MaxRestarts,
		stopCh:      make(chan struct{}),
		onStart:     cfg.OnStart,
		onCrash:     cfg.OnCrash,
		onStop:      cfg.OnStop,
	}
}

// Run starts the subprocess and monitors it. Blocks until context is cancelled
// or max restarts is exceeded.
func (w *Watchdog) Run(ctx context.Context) error {
	for {
		select {
		case <-ctx.Done():
			w.Stop()
			return nil
		case <-w.stopCh:
			return nil
		default:
		}

		if err := w.startProcess(ctx); err != nil {
			slog.Error("watchdog: failed to start process", "error", err)
			return fmt.Errorf("failed to start process: %w", err)
		}

		// Monitor the process
		err := w.cmdObj.Wait()

		w.mu.Lock()
		w.running = false
		w.mu.Unlock()

		if ctx.Err() != nil {
			// Context cancelled, clean exit
			return nil
		}

		w.restarts++
		slog.Warn("watchdog: process exited",
			"error", err,
			"restart", w.restarts,
			"max_restarts", w.maxRestarts,
		)

		if w.onCrash != nil {
			w.onCrash(err)
		}

		if w.restarts >= w.maxRestarts {
			return fmt.Errorf("process crashed %d times, giving up", w.restarts)
		}

		// Escalating cooldown
		cooldown := w.calculateCooldown()
		slog.Info("watchdog: waiting before restart", "cooldown", cooldown)
		time.Sleep(cooldown)
	}
}

// startProcess starts the subprocess.
func (w *Watchdog) startProcess(ctx context.Context) error {
	w.mu.Lock()
	defer w.mu.Unlock()

	w.cmdObj = exec.CommandContext(ctx, w.cmd, w.args...)
	w.cmdObj.Stdout = nil   // Could be piped to a logger
	w.cmdObj.Stderr = nil

	if err := w.cmdObj.Start(); err != nil {
		return err
	}

	w.running = true
	w.lastStart = time.Now()

	slog.Info("watchdog: process started", "pid", w.cmdObj.Process.Pid, "cmd", w.cmd)
	if w.onStart != nil {
		w.onStart()
	}
	return nil
}

// Stop gracefully stops the monitored process.
func (w *Watchdog) Stop() {
	w.mu.Lock()
	defer w.mu.Unlock()

	if w.cmdObj != nil && w.cmdObj.Process != nil && w.running {
		slog.Info("watchdog: stopping process", "pid", w.cmdObj.Process.Pid)
		if err := w.cmdObj.Process.Kill(); err != nil {
			slog.Error("watchdog: failed to kill process", "error", err)
		}
		w.running = false
	}

	if w.onStop != nil {
		w.onStop()
	}
	close(w.stopCh)
}

// calculateCooldown returns the cooldown duration with exponential backoff.
func (w *Watchdog) calculateCooldown() time.Duration {
	base := time.Duration(w.cooldownMs) * time.Millisecond
	backoff := base * time.Duration(1<<(w.restarts-1))
	if backoff > 2*time.Minute {
		backoff = 2 * time.Minute
	}
	return backoff
}

// IsRunning returns whether the subprocess is currently running.
func (w *Watchdog) IsRunning() bool {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.running
}

// RestartCount returns the number of times the process has been restarted.
func (w *Watchdog) RestartCount() int {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.restarts
}
