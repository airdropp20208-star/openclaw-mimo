// Package config provides configuration management for the Hermes core system.
// It loads configuration from environment variables and validates all required fields.
package config

import (
	"fmt"
	"log/slog"
	"os"
	"strconv"
	"strings"
)

// Config holds all configuration for the Hermes core system.
type Config struct {
	// Telegram
	TelegramBotToken string
	TelegramAdminIDs []int64

	// Server
	APIPort     int
	PythonHost  string
	PythonPort  int
	APIHost     string

	// Paths
	SkillsFile string
	MemoryFile string
	LogFile    string

	// Behavior
	RateLimitPerChat   int
	RateLimitWindowSec int
	MemoryWindowSize   int
	MemoryMaxChats     int
	MaxRetries         int
	RetryBaseDelay     int // milliseconds

	// Watchdog
	WatchdogEnabled    bool
	WatchdogCooldownMs int
	WatchdogMaxRetries int
	WatchdogPythonCmd  string

	// Shutdown
	ShutdownTimeoutSec int
}

// Load creates a Config from environment variables. Returns error on missing required fields.
func Load() (*Config, error) {
	cfg := &Config{}

	// Required fields
	cfg.TelegramBotToken = os.Getenv("TELEGRAM_BOT_TOKEN")
	if cfg.TelegramBotToken == "" {
		return nil, fmt.Errorf("TELEGRAM_BOT_TOKEN is required")
	}

	// Telegram admin IDs (comma-separated)
	adminStr := os.Getenv("TELEGRAM_ADMIN_IDS")
	if adminStr == "" {
		slog.Warn("TELEGRAM_ADMIN_IDS not set, all users will be allowed")
	} else {
		ids, err := parseCommaInt64(adminStr)
		if err != nil {
			return nil, fmt.Errorf("invalid TELEGRAM_ADMIN_IDS: %w", err)
		}
		cfg.TelegramAdminIDs = ids
	}

	// Server config
	cfg.APIPort = getEnvInt("API_PORT", 8080)
	cfg.APIHost = getEnvStr("API_HOST", "0.0.0.0")
	cfg.PythonHost = getEnvStr("PYTHON_HOST", "localhost")
	cfg.PythonPort = getEnvInt("PYTHON_PORT", 8080)

	// Paths
	cfg.SkillsFile = getEnvStr("SKILLS_FILE", "data/skills.json")
	cfg.MemoryFile = getEnvStr("MEMORY_FILE", "data/memory.json")
	cfg.LogFile = getEnvStr("LOG_FILE", "")

	// Behavior
	cfg.RateLimitPerChat = getEnvInt("RATE_LIMIT_PER_CHAT", 10)
	cfg.RateLimitWindowSec = getEnvInt("RATE_LIMIT_WINDOW_SEC", 60)
	cfg.MemoryWindowSize = getEnvInt("MEMORY_WINDOW_SIZE", 20)
	cfg.MemoryMaxChats = getEnvInt("MEMORY_MAX_CHATS", 1000)
	cfg.MaxRetries = getEnvInt("MAX_RETRIES", 3)
	cfg.RetryBaseDelay = getEnvInt("RETRY_BASE_DELAY_MS", 500)

	// Watchdog
	cfg.WatchdogEnabled = getEnvBool("WATCHDOG_ENABLED", true)
	cfg.WatchdogCooldownMs = getEnvInt("WATCHDOG_COOLDOWN_MS", 1000)
	cfg.WatchdogMaxRetries = getEnvInt("WATCHDOG_MAX_RETRIES", 10)
	cfg.WatchdogPythonCmd = getEnvStr("WATCHDOG_PYTHON_CMD", "python3")

	// Shutdown
	cfg.ShutdownTimeoutSec = getEnvInt("SHUTDOWN_TIMEOUT_SEC", 30)

	// Ensure data directories exist
	for _, dir := range []string{"data"} {
		if err := os.MkdirAll(dir, 0755); err != nil {
			return nil, fmt.Errorf("failed to create data directory: %w", err)
		}
	}

	slog.Info("configuration loaded", "python_addr", fmt.Sprintf("%s:%d", cfg.PythonHost, cfg.PythonPort))
	return cfg, nil
}

// PythonAddr returns the Python service address.
func (c *Config) PythonAddr() string {
	return fmt.Sprintf("%s:%d", c.PythonHost, c.PythonPort)
}

// APIAddr returns the API server bind address.
func (c *Config) APIAddr() string {
	return fmt.Sprintf("%s:%d", c.APIHost, c.APIPort)
}

// IsAdmin checks if a user ID is in the admin list. If no admins configured, returns true.
func (c *Config) IsAdmin(userID int64) bool {
	if len(c.TelegramAdminIDs) == 0 {
		return true
	}
	for _, id := range c.TelegramAdminIDs {
		if id == userID {
			return true
		}
	}
	return false
}

// --- helpers ---

func getEnvStr(key, defaultVal string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return defaultVal
}

func getEnvInt(key string, defaultVal int) int {
	v := os.Getenv(key)
	if v == "" {
		return defaultVal
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		slog.Warn("invalid env int, using default", "key", key, "val", v, "default", defaultVal)
		return defaultVal
	}
	return n
}

func getEnvBool(key string, defaultVal bool) bool {
	v := os.Getenv(key)
	if v == "" {
		return defaultVal
	}
	b, err := strconv.ParseBool(v)
	if err != nil {
		slog.Warn("invalid env bool, using default", "key", key, "val", v, "default", defaultVal)
		return defaultVal
	}
	return b
}

func parseCommaInt64(s string) ([]int64, error) {
	parts := strings.Split(s, ",")
	var ids []int64
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}
		n, err := strconv.ParseInt(p, 10, 64)
		if err != nil {
			return nil, fmt.Errorf("cannot parse %q as int64: %w", p, err)
		}
		ids = append(ids, n)
	}
	return ids, nil
}
