// Package client provides an HTTP client for communicating with the Python AI service.
package client

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"time"
)

// PythonClient communicates with the Python AI service via HTTP.
type PythonClient struct {
	baseURL    string
	httpClient *http.Client
	maxRetries int
	baseDelay  time.Duration
}

// NewPythonClient creates a new client for the Python AI service.
func NewPythonClient(host string, port int, maxRetries, retryBaseDelayMs int) *PythonClient {
	if maxRetries <= 0 {
		maxRetries = 3
	}
	if retryBaseDelayMs <= 0 {
		retryBaseDelayMs = 500
	}

	return &PythonClient{
		baseURL: fmt.Sprintf("http://%s:%d", host, port),
		httpClient: &http.Client{
			Timeout: 30 * time.Second,
			Transport: &http.Transport{
				MaxIdleConns:        10,
				IdleConnTimeout:     90 * time.Second,
				DisableCompression:  false,
				DisableKeepAlives:   false,
				MaxIdleConnsPerHost: 5,
			},
		},
		maxRetries: maxRetries,
		baseDelay:  time.Duration(retryBaseDelayMs) * time.Millisecond,
	}
}

// ChatRequest represents a request to the Python AI chat endpoint.
type ChatRequest struct {
	ChatID  int64  `json:"chat_id"`
	Message string `json:"message"`
	Context string `json:"context,omitempty"`
}

// ExecuteRequest represents a request to the Python executor.
type ExecuteRequest struct {
	Code    string `json:"code"`
	Command string `json:"command"`
	Timeout int    `json:"timeout"`
}

// Response represents a response from the Python service.
type Response struct {
	OK      bool        `json:"ok"`
	Data    interface{} `json:"data,omitempty"`
	Error   string      `json:"error,omitempty"`
}

// Chat sends a message to the Python AI and returns the response.
func (c *PythonClient) Chat(chatID int64, message string) (interface{}, error) {
	req := ChatRequest{
		ChatID:  chatID,
		Message: message,
	}

	var result interface{}
	err := c.postWithRetry("/chat", req, &result)
	return result, err
}

// Execute sends code to the Python executor.
func (c *PythonClient) Execute(code, command string, timeout int) (interface{}, error) {
	req := ExecuteRequest{
		Code:    code,
		Command: command,
		Timeout: timeout,
	}

	var result interface{}
	err := c.postWithRetry("/execute", req, &result)
	return result, err
}

// IsReachable checks if the Python service is available.
func (c *PythonClient) IsReachable() bool {
	client := &http.Client{Timeout: 3 * time.Second}
	resp, err := client.Get(c.baseURL + "/health")
	if err != nil {
		return false
	}
	resp.Body.Close()
	return resp.StatusCode == http.StatusOK
}

// postWithRetry performs an HTTP POST with exponential backoff retry.
func (c *PythonClient) postWithRetry(path string, body interface{}, result interface{}) error {
	data, err := json.Marshal(body)
	if err != nil {
		return fmt.Errorf("failed to marshal request: %w", err)
	}

	var lastErr error
	for attempt := 0; attempt <= c.maxRetries; attempt++ {
		if attempt > 0 {
			delay := c.baseDelay * time.Duration(1<<(attempt-1))
			slog.Debug("retrying request", "attempt", attempt, "delay", delay)
			time.Sleep(delay)
		}

		resp, err := c.httpClient.Post(
			c.baseURL+path,
			"application/json",
			bytes.NewReader(data),
		)
		if err != nil {
			lastErr = fmt.Errorf("request failed (attempt %d): %w", attempt+1, err)
			slog.Warn("HTTP request failed", "path", path, "attempt", attempt+1, "error", err)
			continue
		}

		respBody, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20)) // 1MB max
		resp.Body.Close()

		if err != nil {
			lastErr = fmt.Errorf("failed to read response: %w", err)
			continue
		}

		if resp.StatusCode >= 500 {
			lastErr = fmt.Errorf("server error %d (attempt %d)", resp.StatusCode, attempt+1)
			slog.Warn("server error", "path", path, "status", resp.StatusCode, "attempt", attempt+1)
			continue
		}

		if resp.StatusCode >= 400 {
			return fmt.Errorf("client error %d: %s", resp.StatusCode, string(respBody))
		}

		// Parse response
		var apiResp Response
		if err := json.Unmarshal(respBody, &apiResp); err != nil {
			// If response is not standard API format, return raw data
			if result != nil {
				if err := json.Unmarshal(respBody, result); err != nil {
					return fmt.Errorf("failed to parse response: %w", err)
				}
			}
			return nil
		}

		if !apiResp.OK && apiResp.Error != "" {
			return fmt.Errorf("API error: %s", apiResp.Error)
		}

		if result != nil && apiResp.Data != nil {
			// Marshal data back to JSON and unmarshal into result
			dataBytes, err := json.Marshal(apiResp.Data)
			if err != nil {
				return fmt.Errorf("failed to re-marshal response data: %w", err)
			}
			if err := json.Unmarshal(dataBytes, result); err != nil {
				return fmt.Errorf("failed to unmarshal response data: %w", err)
			}
		}

		slog.Debug("request successful", "path", path, "attempt", attempt+1)
		return nil
	}

	return fmt.Errorf("all %d retries exhausted: %w", c.maxRetries+1, lastErr)
}
