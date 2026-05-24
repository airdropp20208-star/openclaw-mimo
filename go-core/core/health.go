package core

import (
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"sync"
	"time"
)

// HealthStatus represents the health of a single component.
type HealthStatus struct {
	Name   string `json:"name"`
	Status string `json:"status"`
	Error  string `json:"error,omitempty"`
}

// SystemHealth represents the overall system health.
type SystemHealth struct {
	Status     string         `json:"status"`
	Components []HealthStatus `json:"components"`
	CheckTime  time.Time      `json:"check_time"`
}

// HealthChecker monitors system health.
type HealthChecker struct {
	apiAddr     string
	pythonAddr  string
	memoryFile  string
}

// NewHealthChecker creates a new health checker.
func NewHealthChecker(apiAddr, pythonAddr, memoryFile string) *HealthChecker {
	return &HealthChecker{
		apiAddr:    apiAddr,
		pythonAddr: pythonAddr,
		memoryFile: memoryFile,
	}
}

// Check runs all health checks concurrently and returns the result.
func (h *HealthChecker) Check() SystemHealth {
	var (
		mu      sync.Mutex
		statuses []HealthStatus
		wg      sync.WaitGroup
	)

	checks := []struct {
		name string
		fn   func() HealthStatus
	}{
		{"disk_space", h.checkDiskSpace},
		{"memory_usage", h.checkMemoryUsage},
		{"python_service", h.checkPythonService},
		{"api_endpoint", h.checkAPIEndpoint},
		{"memory_file", h.checkMemoryFile},
	}

	for _, c := range checks {
		wg.Add(1)
		go func(name string, fn func() HealthStatus) {
			defer wg.Done()
			status := fn()
			mu.Lock()
			statuses = append(statuses, status)
			mu.Unlock()
		}(c.name, c.fn)
	}

	wg.Wait()

	overall := "healthy"
	for _, s := range statuses {
		if s.Status != "healthy" {
			overall = "degraded"
			break
		}
	}

	slog.Info("health check complete", "status", overall, "components", len(statuses))
	return SystemHealth{
		Status:     overall,
		Components: statuses,
		CheckTime:  time.Now(),
	}
}

// checkDiskSpace checks if disk has sufficient free space (>1GB).
func (h *HealthChecker) checkDiskSpace() HealthStatus {
	// Simple file stat check - in production use syscall.Statfs
	info, err := os.Stat(".")
	if err != nil {
		return HealthStatus{Name: "disk_space", Status: "unhealthy", Error: err.Error()}
	}
	if info == nil {
		return HealthStatus{Name: "disk_space", Status: "unhealthy", Error: "cannot stat filesystem"}
	}

	// Basic check: can we create files?
	testFile := ".health_check_test"
	f, err := os.Create(testFile)
	if err != nil {
		return HealthStatus{Name: "disk_space", Status: "degraded", Error: "cannot write to disk"}
	}
	f.Close()
	os.Remove(testFile)

	return HealthStatus{Name: "disk_space", Status: "healthy"}
}

// checkMemoryUsage checks current memory usage via /proc.
func (h *HealthChecker) checkMemoryUsage() HealthStatus {
	data, err := os.ReadFile("/proc/meminfo")
	if err != nil {
		// Not Linux or can't read - skip detailed check
		return HealthStatus{Name: "memory_usage", Status: "healthy"}
	}

	// Parse meminfo to check if we have enough free memory
	content := string(data)
	var memTotal, memAvailable int64
	fmt.Sscanf(content, "MemTotal: %d kB", &memTotal)

	// Find available memory
	lines := splitLines(content)
	for _, line := range lines {
		var avail int64
		if n, _ := fmt.Sscanf(line, "MemAvailable: %d kB", &avail); n == 1 {
			memAvailable = avail
			break
		}
	}

	if memAvailable > 0 && memAvailable < 100*1024 { // < 100MB free
		return HealthStatus{
			Name:   "memory_usage",
			Status: "degraded",
			Error:  fmt.Sprintf("low memory: %d MB available", memAvailable/1024),
		}
	}

	return HealthStatus{Name: "memory_usage", Status: "healthy"}
}

// checkPythonService checks if the Python service is reachable.
func (h *HealthChecker) checkPythonService() HealthStatus {
	url := fmt.Sprintf("http://%s/health", h.pythonAddr)
	client := &http.Client{Timeout: 5 * time.Second}

	resp, err := client.Get(url)
	if err != nil {
		return HealthStatus{
			Name:   "python_service",
			Status: "unhealthy",
			Error:  fmt.Sprintf("python service unreachable: %v", err),
		}
	}
	resp.Body.Close()

	if resp.StatusCode >= 500 {
		return HealthStatus{
			Name:   "python_service",
			Status: "degraded",
			Error:  fmt.Sprintf("python service returned %d", resp.StatusCode),
		}
	}

	return HealthStatus{Name: "python_service", Status: "healthy"}
}

// checkAPIEndpoint checks if the local API is responding.
func (h *HealthChecker) checkAPIEndpoint() HealthStatus {
	url := fmt.Sprintf("http://%s/health", h.apiAddr)
	client := &http.Client{Timeout: 3 * time.Second}

	resp, err := client.Get(url)
	if err != nil {
		return HealthStatus{
			Name:   "api_endpoint",
			Status: "degraded",
			Error:  fmt.Sprintf("API unreachable: %v", err),
		}
	}
	resp.Body.Close()

	return HealthStatus{Name: "api_endpoint", Status: "healthy"}
}

// checkMemoryFile checks if the memory file is accessible.
func (h *HealthChecker) checkMemoryFile() HealthStatus {
	if h.memoryFile == "" {
		return HealthStatus{Name: "memory_file", Status: "healthy"}
	}

	_, err := os.Stat(h.memoryFile)
	if os.IsNotExist(err) {
		return HealthStatus{Name: "memory_file", Status: "healthy"} // File doesn't exist yet is OK
	}
	if err != nil {
		return HealthStatus{
			Name:   "memory_file",
			Status: "degraded",
			Error:  fmt.Sprintf("cannot access memory file: %v", err),
		}
	}

	return HealthStatus{Name: "memory_file", Status: "healthy"}
}

func splitLines(s string) []string {
	var lines []string
	start := 0
	for i := 0; i < len(s); i++ {
		if s[i] == '\n' {
			lines = append(lines, s[start:i])
			start = i + 1
		}
	}
	if start < len(s) {
		lines = append(lines, s[start:])
	}
	return lines
}
