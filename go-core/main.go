// Package main is the entry point for the Hermes core system.
// It initializes all components and starts the Telegram bot and API server.
package main

import (
	"log/slog"
	"os"
	"time"

	"hermes-core/api"
	"hermes-core/bot"
	"hermes-core/client"
	"hermes-core/config"
	"hermes-core/core"
	"hermes-core/storage"

	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
)

func main() {
	// Structured logging
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	}))
	slog.SetDefault(logger)

	slog.Info("hermes core starting")

	// Load configuration
	cfg, err := config.Load()
	if err != nil {
		slog.Error("failed to load config", "error", err)
		os.Exit(1)
	}

	// Initialize Python client
	pythonClient := client.NewPythonClient(
		cfg.PythonHost, cfg.PythonPort,
		cfg.MaxRetries, cfg.RetryBaseDelay,
	)

	// Initialize storage
	skillsStore, err := storage.NewSkillsStore(cfg.SkillsFile)
	if err != nil {
		slog.Error("failed to initialize skills store", "error", err)
		os.Exit(1)
	}
	slog.Info("skills store initialized", "skills", skillsStore.Count())

	memoryStore, err := storage.NewMemoryStore(cfg.MemoryFile, cfg.MemoryWindowSize, cfg.MemoryMaxChats)
	if err != nil {
		slog.Error("failed to initialize memory store", "error", err)
		os.Exit(1)
	}
	slog.Info("memory store initialized", "chats", memoryStore.GetChatCount())

	// Initialize intent router
	router := core.NewRouter()

	// Initialize health checker
	healthChecker := core.NewHealthChecker(cfg.APIAddr(), cfg.PythonAddr(), cfg.MemoryFile)

	// Initialize shutdown manager
	shutdownMgr := core.NewShutdownManager(time.Duration(cfg.ShutdownTimeoutSec) * time.Second)

	// Initialize process watchdog for Python service
	var watchdog *core.Watchdog
	if cfg.WatchdogEnabled {
		watchdog = core.NewWatchdog(core.WatchdogConfig{
			Command:     cfg.WatchdogPythonCmd,
			CooldownMs:  cfg.WatchdogCooldownMs,
			MaxRestarts: cfg.WatchdogMaxRetries,
			OnStart: func() {
				slog.Info("python service started by watchdog")
			},
			OnCrash: func(err error) {
				slog.Error("python service crashed", "error", err)
			},
			OnStop: func() {
				slog.Info("python service stopped")
			},
		})
		shutdownMgr.RegisterCleanup(func() {
			watchdog.Stop()
		})
	}

	// Message handler: routes messages and forwards to Python AI
	handler := func(update tgbotapi.Update, reply func(string) error) {
		if update.Message == nil {
			return
		}

		msg := update.Message
		chatID := msg.Chat.ID
		text := msg.Text

		slog.Info("message received",
			"chatID", chatID,
			"user", msg.From.UserName,
			"message", text,
		)

		// Add user message to memory
		if err := memoryStore.AddMessage(chatID, "user", text); err != nil {
			slog.Error("failed to store user message", "error", err)
		}

		// Route the message
		intent := router.Route(text)

		switch intent.Type {
		case "direct_answer":
			// Handle simple greetings/help directly
			reply(handleSimpleQuery(text))

		case "memory_query":
			// Handle memory queries
			history := memoryStore.GetContext(chatID, 5)
			result, err := pythonClient.Chat(chatID, text)
			if err != nil {
				reply("❌ Error: " + err.Error())
				return
			}
			_ = history // context available for the AI
			reply(formatResult(result))

		case "skill_exec":
			// Search for matching skills
			skills := skillsStore.Search(text)
			if len(skills) > 0 {
				reply("🔧 Found matching skills: " + formatSkillNames(skills))
			}
			result, err := pythonClient.Chat(chatID, text)
			if err != nil {
				reply("❌ Error: " + err.Error())
				return
			}
			reply(formatResult(result))

		default:
			// Forward to Python AI for complex tasks
			context := memoryStore.GetContext(chatID, 10)
			result, err := pythonClient.Chat(chatID, text)
			if err != nil {
				reply("❌ Error: " + err.Error())
				return
			}
			_ = context
			response := formatResult(result)
			reply(response)

			// Store AI response in memory
			if err := memoryStore.AddMessage(chatID, "assistant", response); err != nil {
				slog.Error("failed to store AI response", "error", err)
			}
		}
	}

	// Initialize Telegram bot
	telegramBot, err := bot.New(bot.BotConfig{
		BotToken:          cfg.TelegramBotToken,
		AdminIDs:          cfg.TelegramAdminIDs,
		RateLimitPerChat:  cfg.RateLimitPerChat,
		RateLimitWindow:   time.Duration(cfg.RateLimitWindowSec) * time.Second,
		ShutdownTimeout:   time.Duration(cfg.ShutdownTimeoutSec) * time.Second,
	}, handler)
	if err != nil {
		slog.Error("failed to create telegram bot", "error", err)
		os.Exit(1)
	}

	// Initialize API server
	apiServer := api.NewServer(cfg, pythonClient)

	// Register shutdown cleanup
	shutdownMgr.RegisterCleanup(func() {
		slog.Info("cleaning up bot")
		telegramBot.Stop()
	})

	// Start components in goroutines
	go func() {
		if err := apiServer.Run(shutdownMgr.Context()); err != nil {
			slog.Error("API server error", "error", err)
			shutdownMgr.Shutdown()
		}
	}()

	if watchdog != nil {
		go func() {
			if err := watchdog.Run(shutdownMgr.Context()); err != nil {
				slog.Error("watchdog error", "error", err)
				shutdownMgr.Shutdown()
			}
		}()
	}

	// Run health checks periodically
	go func() {
		ticker := time.NewTicker(5 * time.Minute)
		defer ticker.Stop()
		for {
			select {
			case <-shutdownMgr.Context().Done():
				return
			case <-ticker.C:
				health := healthChecker.Check()
				if health.Status != "healthy" {
					slog.Warn("health check degraded", "status", health.Status)
				}
			}
		}
	}()

	// Start Telegram bot (blocks until shutdown)
	go func() {
		telegramBot.Run(shutdownMgr.Context())
	}()

	slog.Info("hermes core fully started")

	// Wait for shutdown signal
	shutdownMgr.Wait()
	slog.Info("hermes core stopped")
}

// handleSimpleQuery responds to simple greetings and help requests.
func handleSimpleQuery(text string) string {
	lower := text
	switch {
	case containsAny(lower, "hello", "hi", "hey"):
		return "👋 Hello! I'm Hermes, your AI assistant. How can I help you?"
	case containsAny(lower, "help", "/help"):
		return "🤖 *Hermes Bot Commands*\n\n/help - Show this help\n/status - System status\n/memory - View memory\n\nJust send me a message and I'll help!"
	case containsAny(lower, "who are you", "what are you"):
		return "🤖 I'm Hermes, a multi-agent AI system powered by OpenManus."
	case containsAny(lower, "/start"):
		return "🚀 Welcome to Hermes! Send me any message to get started."
	default:
		return "🤔 I'm not sure how to respond to that. Try /help for available commands."
	}
}

// formatResult converts a Python AI result to a string response.
func formatResult(result interface{}) string {
	if result == nil {
		return "No response from AI."
	}
	switch v := result.(type) {
	case string:
		return v
	case map[string]interface{}:
		if msg, ok := v["response"]; ok {
			return formatResult(msg)
		}
		if msg, ok := v["message"]; ok {
			return formatResult(msg)
		}
		if msg, ok := v["content"]; ok {
			return formatResult(msg)
		}
		return "AI returned complex result"
	default:
		return "AI returned unexpected format"
	}
}

// formatSkillNames returns comma-separated skill names.
func formatSkillNames(skills []*storage.Skill) string {
	names := make([]string, len(skills))
	for i, s := range skills {
		names[i] = s.Name
	}
	result := ""
	for i, name := range names {
		if i > 0 {
			result += ", "
		}
		result += name
	}
	return result
}

func containsAny(s string, substrs ...string) bool {
	for _, sub := range substrs {
		if len(s) >= len(sub) {
			for i := 0; i <= len(s)-len(sub); i++ {
				if s[i:i+len(sub)] == sub {
					return true
				}
			}
		}
	}
	return false
}
