package storage

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"sort"
	"sync"
	"time"
)

// Message represents a single message in a conversation.
type Message struct {
	Role      string    `json:"role"`    // "user" or "assistant"
	Content   string    `json:"content"`
	Timestamp time.Time `json:"timestamp"`
}

// Conversation represents a chat conversation with a sliding window of messages.
type Conversation struct {
	ChatID    int64      `json:"chat_id"`
	Messages  []Message  `json:"messages"`
	CreatedAt time.Time  `json:"created_at"`
	UpdatedAt time.Time  `json:"updated_at"`
}

// MemoryStore provides thread-safe per-chat conversation memory with sliding window.
type MemoryStore struct {
	mu            sync.RWMutex
	filePath      string
	conversations map[int64]*Conversation
	windowSize    int
	maxChats      int
	loaded        bool
}

// NewMemoryStore creates a new conversation memory store.
func NewMemoryStore(filePath string, windowSize, maxChats int) (*MemoryStore, error) {
	if windowSize <= 0 {
		windowSize = 20
	}
	if maxChats <= 0 {
		maxChats = 1000
	}

	store := &MemoryStore{
		filePath:      filePath,
		conversations: make(map[int64]*Conversation),
		windowSize:    windowSize,
		maxChats:      maxChats,
	}

	if err := store.load(); err != nil {
		return nil, fmt.Errorf("failed to load memory: %w", err)
	}

	return store, nil
}

// AddMessage appends a message to the conversation for a chat.
func (m *MemoryStore) AddMessage(chatID int64, role, content string) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	conv, ok := m.conversations[chatID]
	if !ok {
		conv = &Conversation{
			ChatID:    chatID,
			Messages:  make([]Message, 0),
			CreatedAt: time.Now(),
		}
		m.conversations[chatID] = conv

		// Evict oldest chat if we exceed max
		if len(m.conversations) > m.maxChats {
			m.evictOldestChat()
		}
	}

	conv.Messages = append(conv.Messages, Message{
		Role:      role,
		Content:   content,
		Timestamp: time.Now(),
	})

	// Enforce sliding window
	if len(conv.Messages) > m.windowSize {
		conv.Messages = conv.Messages[len(conv.Messages)-m.windowSize:]
	}

	conv.UpdatedAt = time.Now()

	return m.save()
}

// GetHistory returns the conversation history for a chat.
func (m *MemoryStore) GetHistory(chatID int64) []Message {
	m.mu.RLock()
	defer m.mu.RUnlock()

	conv, ok := m.conversations[chatID]
	if !ok {
		return nil
	}

	// Return a copy
	result := make([]Message, len(conv.Messages))
	copy(result, conv.Messages)
	return result
}

// GetContext returns the last N messages as context for AI.
func (m *MemoryStore) GetContext(chatID int64, n int) []Message {
	history := m.GetHistory(chatID)
	if n <= 0 || n > len(history) {
		n = len(history)
	}
	return history[len(history)-n:]
}

// ClearChat removes all messages for a chat.
func (m *MemoryStore) ClearChat(chatID int64) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	delete(m.conversations, chatID)
	return m.save()
}

// GetChatCount returns the number of active conversations.
func (m *MemoryStore) GetChatCount() int {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return len(m.conversations)
}

// CleanupOld removes conversations older than the given duration.
func (m *MemoryStore) CleanupOld(maxAge time.Duration) (int, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	cutoff := time.Now().Add(-maxAge)
	removed := 0

	for chatID, conv := range m.conversations {
		if conv.UpdatedAt.Before(cutoff) {
			delete(m.conversations, chatID)
			removed++
		}
	}

	if removed > 0 {
		slog.Info("cleaned up old conversations", "removed", removed)
		return removed, m.save()
	}

	return 0, nil
}

// evictOldestChat removes the least recently updated conversation.
// Must be called with mu held.
func (m *MemoryStore) evictOldestChat() {
	var oldestID int64
	var oldestTime time.Time

	for id, conv := range m.conversations {
		if oldestID == 0 || conv.UpdatedAt.Before(oldestTime) {
			oldestID = id
			oldestTime = conv.UpdatedAt
		}
	}

	if oldestID != 0 {
		delete(m.conversations, oldestID)
		slog.Debug("evicted oldest conversation", "chatID", oldestID)
	}
}

// load reads conversations from the JSON file.
func (m *MemoryStore) load() error {
	data, err := os.ReadFile(m.filePath)
	if os.IsNotExist(err) {
		m.loaded = true
		return nil
	}
	if err != nil {
		return err
	}

	if len(data) == 0 {
		m.loaded = true
		return nil
	}

	var convs []*Conversation
	if err := json.Unmarshal(data, &convs); err != nil {
		return fmt.Errorf("failed to parse memory file: %w", err)
	}

	for _, conv := range convs {
		m.conversations[conv.ChatID] = conv
	}

	slog.Info("conversations loaded", "count", len(m.conversations))
	m.loaded = true
	return nil
}

// save writes conversations to the JSON file atomically.
func (m *MemoryStore) save() error {
	convs := make([]*Conversation, 0, len(m.conversations))
	for _, conv := range m.conversations {
		convs = append(convs, conv)
	}

	// Sort by chat ID for deterministic output
	sort.Slice(convs, func(i, j int) bool {
		return convs[i].ChatID < convs[j].ChatID
	})

	data, err := json.MarshalIndent(convs, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal conversations: %w", err)
	}

	tmpPath := m.filePath + ".tmp"
	if err := os.WriteFile(tmpPath, data, 0644); err != nil {
		return fmt.Errorf("failed to write temp memory file: %w", err)
	}

	if err := os.Rename(tmpPath, m.filePath); err != nil {
		os.Remove(tmpPath)
		return fmt.Errorf("failed to rename temp memory file: %w", err)
	}

	return nil
}
