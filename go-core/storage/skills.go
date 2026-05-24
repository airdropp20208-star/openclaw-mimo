// Package storage provides thread-safe JSON storage for skills and conversation memory.
package storage

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

// Skill represents a stored skill definition.
type Skill struct {
	ID          string            `json:"id"`
	Name        string            `json:"name"`
	Description string            `json:"description"`
	Keywords    []string          `json:"keywords"`
	Commands    []string          `json:"commands"`
	Enabled     bool              `json:"enabled"`
	CreatedAt   time.Time         `json:"created_at"`
	UpdatedAt   time.Time         `json:"updated_at"`
	Metadata    map[string]string `json:"metadata,omitempty"`
}

// SkillsStore provides thread-safe storage for skills with fuzzy search.
type SkillsStore struct {
	mu       sync.RWMutex
	filePath string
	skills   map[string]*Skill
	loaded   bool
}

// NewSkillsStore creates a new skills storage backed by a JSON file.
func NewSkillsStore(filePath string) (*SkillsStore, error) {
	dir := filepath.Dir(filePath)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create skills directory: %w", err)
	}

	store := &SkillsStore{
		filePath: filePath,
		skills:   make(map[string]*Skill),
	}

	if err := store.load(); err != nil {
		return nil, fmt.Errorf("failed to load skills: %w", err)
	}

	return store, nil
}

// Add adds a new skill to the store.
func (s *SkillsStore) Add(skill *Skill) error {
	if skill.ID == "" {
		skill.ID = generateSkillID(skill.Name)
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	if _, exists := s.skills[skill.ID]; exists {
		return fmt.Errorf("skill %s already exists", skill.ID)
	}

	now := time.Now()
	skill.CreatedAt = now
	skill.UpdatedAt = now
	if skill.Metadata == nil {
		skill.Metadata = make(map[string]string)
	}

	s.skills[skill.ID] = skill
	return s.save()
}

// Get retrieves a skill by ID.
func (s *SkillsStore) Get(id string) (*Skill, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	skill, ok := s.skills[id]
	if !ok {
		return nil, fmt.Errorf("skill %s not found", id)
	}
	return skill, nil
}

// Update updates an existing skill.
func (s *SkillsStore) Update(id string, updates *Skill) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	existing, ok := s.skills[id]
	if !ok {
		return fmt.Errorf("skill %s not found", id)
	}

	if updates.Name != "" {
		existing.Name = updates.Name
	}
	if updates.Description != "" {
		existing.Description = updates.Description
	}
	if updates.Keywords != nil {
		existing.Keywords = updates.Keywords
	}
	if updates.Commands != nil {
		existing.Commands = updates.Commands
	}
	existing.Enabled = updates.Enabled
	if updates.Metadata != nil {
		existing.Metadata = updates.Metadata
	}
	existing.UpdatedAt = time.Now()

	return s.save()
}

// Delete removes a skill by ID.
func (s *SkillsStore) Delete(id string) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if _, ok := s.skills[id]; !ok {
		return fmt.Errorf("skill %s not found", id)
	}

	delete(s.skills, id)
	return s.save()
}

// List returns all skills.
func (s *SkillsStore) List() []*Skill {
	s.mu.RLock()
	defer s.mu.RUnlock()

	result := make([]*Skill, 0, len(s.skills))
	for _, skill := range s.skills {
		result = append(result, skill)
	}
	return result
}

// Search performs a fuzzy keyword search across all skills.
// It matches if any keyword in the query matches any keyword in the skill.
func (s *SkillsStore) Search(query string) []*Skill {
	s.mu.RLock()
	defer s.mu.RUnlock()

	queryLower := strings.ToLower(query)
	queryWords := strings.Fields(queryLower)

	var matches []*Skill
	for _, skill := range s.skills {
		if !skill.Enabled {
			continue
		}
		if s.skillMatches(skill, queryLower, queryWords) {
			matches = append(matches, skill)
		}
	}
	return matches
}

// skillMatches checks if a skill matches the query using fuzzy matching.
func (s *SkillsStore) skillMatches(skill *Skill, queryLower string, queryWords []string) bool {
	// Check name match
	if strings.Contains(strings.ToLower(skill.Name), queryLower) {
		return true
	}

	// Check description match
	if strings.Contains(strings.ToLower(skill.Description), queryLower) {
		return true
	}

	// Check keyword match (any word must match any skill keyword)
	keywordMatch := 0
	for _, kw := range skill.Keywords {
		kwLower := strings.ToLower(kw)
		for _, qw := range queryWords {
			if strings.Contains(kwLower, qw) || strings.Contains(qw, kwLower) {
				keywordMatch++
				break
			}
		}
	}

	// Require at least one keyword match if there are query words
	return len(queryWords) > 0 && keywordMatch > 0
}

// Count returns the number of stored skills.
func (s *SkillsStore) Count() int {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return len(s.skills)
}

// load reads skills from the JSON file.
func (s *SkillsStore) load() error {
	data, err := os.ReadFile(s.filePath)
	if os.IsNotExist(err) {
		s.loaded = true
		return nil
	}
	if err != nil {
		return err
	}

	if len(data) == 0 {
		s.loaded = true
		return nil
	}

	var skills []*Skill
	if err := json.Unmarshal(data, &skills); err != nil {
		return fmt.Errorf("failed to parse skills file: %w", err)
	}

	for _, skill := range skills {
		s.skills[skill.ID] = skill
	}

	slog.Info("skills loaded", "count", len(s.skills))
	s.loaded = true
	return nil
}

// save writes skills to the JSON file atomically.
func (s *SkillsStore) save() error {
	skills := make([]*Skill, 0, len(s.skills))
	for _, skill := range s.skills {
		skills = append(skills, skill)
	}

	data, err := json.MarshalIndent(skills, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal skills: %w", err)
	}

	// Atomic write: write to temp file then rename
	tmpPath := s.filePath + ".tmp"
	if err := os.WriteFile(tmpPath, data, 0644); err != nil {
		return fmt.Errorf("failed to write temp skills file: %w", err)
	}

	if err := os.Rename(tmpPath, s.filePath); err != nil {
		os.Remove(tmpPath)
		return fmt.Errorf("failed to rename temp skills file: %w", err)
	}

	slog.Debug("skills saved", "count", len(skills))
	return nil
}

func generateSkillID(name string) string {
	id := strings.ToLower(strings.ReplaceAll(name, " ", "-"))
	id = strings.Map(func(r rune) rune {
		if (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') || r == '-' {
			return r
		}
		return -1
	}, id)
	if id == "" {
		id = fmt.Sprintf("skill-%d", time.Now().UnixNano())
	}
	return id
}
