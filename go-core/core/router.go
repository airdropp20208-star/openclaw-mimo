// Package core provides the intent router, health checker, watchdog, and
// graceful shutdown for the Hermes system.
package core

import (
	"log/slog"
	"strings"
	"sync"
	"time"
)

// Intent represents the classified intent of a user message.
type Intent struct {
	Type       string // "direct_answer", "python_ai", "skill_exec", "memory_query"
	Confidence float64
	Cached     bool
}

// Router routes user messages to appropriate handlers.
type Router struct {
	// Cache for routing decisions
	cacheMu sync.RWMutex
	cache   map[string]routingEntry
	maxCache int
}

type routingEntry struct {
	intent    Intent
	expiresAt time.Time
}

// NewRouter creates a new Intent router.
func NewRouter() *Router {
	return &Router{
		cache:    make(map[string]routingEntry),
		maxCache: 1000,
	}
}

// Route determines the intent for a given message. It uses keyword matching
// for fast-path decisions and falls back to Python AI for complex tasks.
func (r *Router) Route(message string) Intent {
	// Check cache first
	if intent, ok := r.checkCache(message); ok {
		slog.Debug("routing cache hit", "message", truncate(message, 50), "intent", intent.Type)
		return intent
	}

	intent := r.classify(message)
	r.cacheDecision(message, intent)
	return intent
}

// classify performs keyword-based intent classification.
func (r *Router) classify(message string) Intent {
	lower := strings.ToLower(message)
	intent := Intent{Confidence: 1.0}

	switch {
	// Memory queries
	case strings.HasPrefix(lower, "/memory"), strings.HasPrefix(lower, "remember that"), strings.HasPrefix(lower, "recall"):
		intent.Type = "memory_query"
		intent.Confidence = 0.95

	// Skill execution
	case strings.HasPrefix(lower, "/skill"), strings.HasPrefix(lower, "use skill"):
		intent.Type = "skill_exec"
		intent.Confidence = 0.90

	// Simple greetings and direct answers
	case isSimpleQuery(lower):
		intent.Type = "direct_answer"
		intent.Confidence = 0.85

	// Default: forward to Python AI
	default:
		intent.Type = "python_ai"
		intent.Confidence = 0.70
	}

	slog.Debug("intent classified",
		"message", truncate(message, 50),
		"type", intent.Type,
		"confidence", intent.Confidence,
	)
	return intent
}

// isSimpleQuery checks if a message is a simple query that can be answered directly.
func isSimpleQuery(lower string) bool {
	simplePatterns := []string{
		"hello", "hi", "hey", "help", "start",
		"what are you", "who are you", "how are you",
		"/help", "/start", "/status",
	}
	for _, p := range simplePatterns {
		if strings.Contains(lower, p) {
			return true
		}
	}
	return false
}

// checkCache looks up a cached routing decision.
func (r *Router) checkCache(message string) (Intent, bool) {
	r.cacheMu.RLock()
	defer r.cacheMu.RUnlock()

	entry, ok := r.cache[message]
	if !ok || time.Now().After(entry.expiresAt) {
		return Intent{}, false
	}
	return entry.intent, true
}

// cacheDecision stores a routing decision for future lookups.
func (r *Router) cacheDecision(message string, intent Intent) {
	r.cacheMu.Lock()
	defer r.cacheMu.Unlock()

	// Evict oldest if cache is full
	if len(r.cache) >= r.maxCache {
		r.evictOldest()
	}

	r.cache[message] = routingEntry{
		intent:    intent,
		expiresAt: time.Now().Add(10 * time.Minute),
	}
}

// evictOldest removes the entry with the earliest expiration.
// Must be called with cacheMu held.
func (r *Router) evictOldest() {
	var oldestKey string
	var oldestTime time.Time

	for k, v := range r.cache {
		if oldestKey == "" || v.expiresAt.Before(oldestTime) {
			oldestKey = k
			oldestTime = v.expiresAt
		}
	}

	if oldestKey != "" {
		delete(r.cache, oldestKey)
	}
}

// ClearCache removes all cached routing decisions.
func (r *Router) ClearCache() {
	r.cacheMu.Lock()
	defer r.cacheMu.Unlock()
	r.cache = make(map[string]routingEntry)
	slog.Info("routing cache cleared")
}

// Stats returns cache statistics.
func (r *Router) Stats() (size int, maxCache int) {
	r.cacheMu.RLock()
	defer r.cacheMu.RUnlock()
	return len(r.cache), r.maxCache
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "..."
}
