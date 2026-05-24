// Package bot implements the Telegram Bot API client with long polling,
// rate limiting, access control, and auto-reconnect.
package bot

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"sync"
	"time"

	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
)

// MessageHandler is called for each incoming message. It receives the raw
// update and a helper to send replies.
type MessageHandler func(update tgbotapi.Update, reply func(string) error)

// BotConfig holds bot-specific configuration.
type BotConfig struct {
	BotToken          string
	AdminIDs          []int64
	RateLimitPerChat  int
	RateLimitWindow   time.Duration
	ShutdownTimeout   time.Duration
}

// Bot wraps the Telegram Bot API client.
type Bot struct {
	api      *tgbotapi.BotAPI
	config   BotConfig
	handler  MessageHandler

	// rate limiter: chatID -> count
	rateMu      sync.Mutex
	rateCounts  map[int64]int
	rateReset   map[int64]time.Time

	// goroutine tracking
	wg sync.WaitGroup

	// shutdown
	cancel context.CancelFunc
}

// rateKey is used as key in rate limiting maps.
type rateKey struct {
	chatID int64
}

// New creates a new Bot instance.
func New(cfg BotConfig, handler MessageHandler) (*Bot, error) {
	if cfg.BotToken == "" {
		return nil, fmt.Errorf("bot token is required")
	}
	if cfg.RateLimitPerChat <= 0 {
		cfg.RateLimitPerChat = 10
	}
	if cfg.RateLimitWindow <= 0 {
		cfg.RateLimitWindow = time.Minute
	}
	if cfg.ShutdownTimeout <= 0 {
		cfg.ShutdownTimeout = 10 * time.Second
	}

	api, err := tgbotapi.NewBotAPI(cfg.BotToken)
	if err != nil {
		return nil, fmt.Errorf("failed to create bot API: %w", err)
	}

	slog.Info("telegram bot authorized", "username", api.Self.UserName)
	return &Bot{
		api:        api,
		config:     cfg,
		handler:    handler,
		rateCounts: make(map[int64]int),
		rateReset:  make(map[int64]time.Time),
	}, nil
}

// Run starts the long-polling loop. It blocks until ctx is cancelled.
func (b *Bot) Run(ctx context.Context) {
	ctx, cancel := context.WithCancel(ctx)
	b.cancel = cancel
	defer cancel()

	// Cleanup rate limiter periodically
	b.wg.Add(1)
	go b.rateLimiterGC(ctx)

	slog.Info("telegram bot starting long polling")

	uCfg := tgbotapi.NewUpdate(0)
	uCfg.Timeout = 30

	updates := b.api.GetUpdatesChan(uCfg)

	for {
		select {
		case <-ctx.Done():
			slog.Info("telegram bot shutting down")
			b.api.StopReceivingUpdates()
			return
		case update, ok := <-updates:
			if !ok {
				slog.Warn("updates channel closed, reconnecting")
				b.reconnect(ctx, uCfg)
				updates = b.api.GetUpdatesChan(uCfg)
				continue
			}
			b.handleUpdate(ctx, update)
		}
	}
}

// handleUpdate processes a single update in its own goroutine.
func (b *Bot) handleUpdate(ctx context.Context, update tgbotapi.Update) {
	chatID := extractChatID(update)
	if chatID == 0 {
		return // no message to handle
	}

	// Access control
	if !b.isAllowed(chatID) {
		slog.Warn("unauthorized access attempt", "chatID", chatID)
		b.sendText(chatID, "⛔ Access denied.")
		return
	}

	// Rate limiting
	if !b.checkRateLimit(chatID) {
		slog.Warn("rate limit exceeded", "chatID", chatID)
		b.sendText(chatID, "⏳ Rate limit exceeded. Please wait.")
		return
	}

	b.wg.Add(1)
	go func() {
		defer b.wg.Done()
		b.handler(update, func(text string) error {
			return b.sendText(chatID, text)
		})
	}()
}

// sendText sends a text message to the specified chat.
func (b *Bot) sendText(chatID int64, text string) error {
	msg := tgbotapi.NewMessage(chatID, text)
	msg.ParseMode = "Markdown"
	_, err := b.api.Send(msg)
	if err != nil {
		slog.Error("failed to send message", "chatID", chatID, "error", err)
	}
	return err
}

// SendDocument sends a document file to the specified chat.
func (b *Bot) SendDocument(chatID int64, filePath string, caption string) error {
	file, err := os.Open(filePath)
	if err != nil {
		return fmt.Errorf("failed to open file %s: %w", filePath, err)
	}
	defer file.Close()

	doc := tgbotapi.NewDocument(chatID, tgbotapi.FileReader{
		Name:   filePath,
		Reader: file,
	})
	doc.Caption = caption
	_, err = b.api.Send(doc)
	if err != nil {
		slog.Error("failed to send document", "chatID", chatID, "file", filePath, "error", err)
	}
	return err
}

// isAllowed checks if a chat is permitted. If no admins configured, all chats are allowed.
func (b *Bot) isAllowed(chatID int64) bool {
	if len(b.config.AdminIDs) == 0 {
		return true
	}
	for _, id := range b.config.AdminIDs {
		if id == chatID {
			return true
		}
	}
	return false
}

// checkRateLimit enforces per-chat rate limiting. Returns true if request is allowed.
func (b *Bot) checkRateLimit(chatID int64) bool {
	b.rateMu.Lock()
	defer b.rateMu.Unlock()

	now := time.Now()
	if reset, ok := b.rateReset[chatID]; ok && now.After(reset) {
		delete(b.rateCounts, chatID)
		delete(b.rateReset, chatID)
	}

	b.rateCounts[chatID]++
	if _, ok := b.rateReset[chatID]; !ok {
		b.rateReset[chatID] = now.Add(b.config.RateLimitWindow)
	}

	return b.rateCounts[chatID] <= b.config.RateLimitPerChat
}

// rateLimiterGC periodically cleans up expired rate limit entries.
func (b *Bot) rateLimiterGC(ctx context.Context) {
	defer b.wg.Done()
	ticker := time.NewTicker(time.Minute)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			b.rateMu.Lock()
			now := time.Now()
			for chatID, reset := range b.rateReset {
				if now.After(reset) {
					delete(b.rateCounts, chatID)
					delete(b.rateReset, chatID)
				}
			}
			b.rateMu.Unlock()
		}
	}
}

// reconnect handles automatic reconnection after network errors.
func (b *Bot) reconnect(ctx context.Context, uCfg tgbotapi.UpdateConfig) {
	backoff := time.Second
	maxBackoff := 2 * time.Minute

	for {
		select {
		case <-ctx.Done():
			return
		case <-time.After(backoff):
			slog.Info("attempting reconnection", "backoff", backoff)
			api, err := tgbotapi.NewBotAPI(b.config.BotToken)
			if err != nil {
				slog.Error("reconnection failed", "error", err)
				backoff *= 2
				if backoff > maxBackoff {
					backoff = maxBackoff
				}
				continue
			}
			b.api = api
			slog.Info("reconnected successfully")
			return
		}
	}
}

// Stop gracefully shuts down the bot.
func (b *Bot) Stop() {
	if b.cancel != nil {
		b.cancel()
	}
	b.wg.Wait()
	slog.Info("telegram bot stopped")
}

func extractChatID(update tgbotapi.Update) int64 {
	if update.Message != nil {
		return update.Message.Chat.ID
	}
	if update.CallbackQuery != nil {
		return update.CallbackQuery.Message.Chat.ID
	}
	return 0
}
