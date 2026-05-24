// Package api implements the HTTP API server that acts as a gateway between
// the Telegram bot and the Python AI service.
package api

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"sync"
	"time"

	"hermes-core/client"
	"hermes-core/config"
)

// Server is the HTTP API server.
type Server struct {
	cfg          *config.Config
	pythonClient *client.PythonClient
	httpServer   *http.Server
	mux          *http.ServeMux

	// Status tracking
	mu          sync.RWMutex
	startTime   time.Time
	requestCount int64
	errorCount   int64
}

// StatusResponse represents the system status.
type StatusResponse struct {
	Status      string `json:"status"`
	Uptime      string `json:"uptime"`
	StartTime   string `json:"start_time"`
	Requests    int64  `json:"requests"`
	Errors      int64  `json:"errors"`
	PythonOK    bool   `json:"python_reachable"`
}

// APIResponse is a generic JSON API response wrapper.
type APIResponse struct {
	OK      bool        `json:"ok"`
	Data    interface{} `json:"data,omitempty"`
	Error   string      `json:"error,omitempty"`
}

// NewServer creates a new API server.
func NewServer(cfg *config.Config, pc *client.PythonClient) *Server {
	s := &Server{
		cfg:          cfg,
		pythonClient: pc,
		startTime:    time.Now(),
		mux:          http.NewServeMux(),
	}
	s.registerRoutes()
	return s
}

// registerRoutes sets up all HTTP handlers.
func (s *Server) registerRoutes() {
	s.mux.HandleFunc("/health", s.handleHealth)
	s.mux.HandleFunc("/status", s.handleStatus)
	s.mux.HandleFunc("/chat", s.handleChat)
	s.mux.HandleFunc("/execute", s.handleExecute)
	s.mux.HandleFunc("/skills", s.handleSkills)
	s.mux.HandleFunc("/memory", s.handleMemory)
}

// Run starts the HTTP server. Blocks until ctx is cancelled.
func (s *Server) Run(ctx context.Context) error {
	s.httpServer = &http.Server{
		Addr:              s.cfg.APIAddr(),
		Handler:           s.mux,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       60 * time.Second,
		ReadHeaderTimeout: 5 * time.Second,
	}

	// Wait for shutdown signal
	go func() {
		<-ctx.Done()
		slog.Info("API server shutting down")
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := s.httpServer.Shutdown(shutdownCtx); err != nil {
			slog.Error("API server shutdown error", "error", err)
		}
	}()

	slog.Info("API server starting", "addr", s.cfg.APIAddr())
	if err := s.httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		return fmt.Errorf("API server error: %w", err)
	}
	return nil
}

// handleHealth is the health check endpoint.
func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	pythonOK := s.pythonClient.IsReachable()
	status := "healthy"
	code := http.StatusOK
	if !pythonOK {
		status = "degraded"
		code = http.StatusServiceUnavailable
	}

	writeJSON(w, code, APIResponse{
		OK:   pythonOK,
		Data: map[string]string{"status": status, "python": boolStr(pythonOK)},
	})
}

// handleStatus returns detailed system status.
func (s *Server) handleStatus(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	s.mu.RLock()
	resp := StatusResponse{
		Status:    "running",
		Uptime:    time.Since(s.startTime).Round(time.Second).String(),
		StartTime: s.startTime.Format(time.RFC3339),
		Requests:  s.requestCount,
		Errors:    s.errorCount,
		PythonOK:  s.pythonClient.IsReachable(),
	}
	s.mu.RUnlock()

	writeJSON(w, http.StatusOK, APIResponse{OK: true, Data: resp})
}

// handleChat forwards chat messages to the Python AI service.
func (s *Server) handleChat(w http.ResponseWriter, r *http.Request) {
	s.trackRequest()
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20)) // 1MB max
	if err != nil {
		s.trackError()
		writeJSON(w, http.StatusBadRequest, APIResponse{Error: "failed to read request body"})
		return
	}

	var req struct {
		ChatID  int64  `json:"chat_id"`
		Message string `json:"message"`
	}
	if err := json.Unmarshal(body, &req); err != nil {
		s.trackError()
		writeJSON(w, http.StatusBadRequest, APIResponse{Error: "invalid JSON"})
		return
	}

	result, err := s.pythonClient.Chat(req.ChatID, req.Message)
	if err != nil {
		s.trackError()
		writeJSON(w, http.StatusBadGateway, APIResponse{Error: fmt.Sprintf("python service error: %v", err)})
		return
	}

	writeJSON(w, http.StatusOK, APIResponse{OK: true, Data: result})
}

// handleExecute forwards execution requests to the Python executor.
func (s *Server) handleExecute(w http.ResponseWriter, r *http.Request) {
	s.trackRequest()
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
	if err != nil {
		s.trackError()
		writeJSON(w, http.StatusBadRequest, APIResponse{Error: "failed to read request body"})
		return
	}

	var req struct {
		Code    string `json:"code"`
		Command string `json:"command"`
		Timeout int    `json:"timeout"`
	}
	if err := json.Unmarshal(body, &req); err != nil {
		s.trackError()
		writeJSON(w, http.StatusBadRequest, APIResponse{Error: "invalid JSON"})
		return
	}

	result, err := s.pythonClient.Execute(req.Code, req.Command, req.Timeout)
	if err != nil {
		s.trackError()
		writeJSON(w, http.StatusBadGateway, APIResponse{Error: fmt.Sprintf("execution error: %v", err)})
		return
	}

	writeJSON(w, http.StatusOK, APIResponse{OK: true, Data: result})
}

// handleSkills handles CRUD operations for skills via POST method.
func (s *Server) handleSkills(w http.ResponseWriter, r *http.Request) {
	s.trackRequest()
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
	if err != nil {
		s.trackError()
		writeJSON(w, http.StatusBadRequest, APIResponse{Error: "failed to read request body"})
		return
	}

	// Forward to Python for skill management
	result, err := s.pythonClient.Chat(0, fmt.Sprintf("/skills %s", string(body)))
	if err != nil {
		s.trackError()
		writeJSON(w, http.StatusBadGateway, APIResponse{Error: fmt.Sprintf("skills error: %v", err)})
		return
	}

	writeJSON(w, http.StatusOK, APIResponse{OK: true, Data: result})
}

// handleMemory handles CRUD operations for conversation memory.
func (s *Server) handleMemory(w http.ResponseWriter, r *http.Request) {
	s.trackRequest()
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
	if err != nil {
		s.trackError()
		writeJSON(w, http.StatusBadRequest, APIResponse{Error: "failed to read request body"})
		return
	}

	result, err := s.pythonClient.Chat(0, fmt.Sprintf("/memory %s", string(body)))
	if err != nil {
		s.trackError()
		writeJSON(w, http.StatusBadGateway, APIResponse{Error: fmt.Sprintf("memory error: %v", err)})
		return
	}

	writeJSON(w, http.StatusOK, APIResponse{OK: true, Data: result})
}

func (s *Server) trackRequest() {
	s.mu.Lock()
	s.requestCount++
	s.mu.Unlock()
}

func (s *Server) trackError() {
	s.mu.Lock()
	s.errorCount++
	s.mu.Unlock()
}

func writeJSON(w http.ResponseWriter, code int, data interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	if err := json.NewEncoder(w).Encode(data); err != nil {
		slog.Error("failed to encode JSON response", "error", err)
	}
}

func boolStr(b bool) string {
	if b {
		return "ok"
	}
	return "unreachable"
}
