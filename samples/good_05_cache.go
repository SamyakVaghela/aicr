// Package cache provides a small TTL cache used by the API layer.
//
// SMOKE TEST FIXTURE — clean Go code.
// Expected: PASS with no critical or high findings.
package cache

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"sync"
	"time"
)

type entry struct {
	value     []byte
	expiresAt time.Time
}

// TTLCache is a concurrency-safe in-memory cache with per-entry expiry.
type TTLCache struct {
	mu      sync.RWMutex
	entries map[string]entry
	ttl     time.Duration
}

func New(ttl time.Duration) *TTLCache {
	return &TTLCache{
		entries: make(map[string]entry),
		ttl:     ttl,
	}
}

func (c *TTLCache) Get(key string) ([]byte, bool) {
	c.mu.RLock()
	e, ok := c.entries[key]
	c.mu.RUnlock()

	if !ok || time.Now().After(e.expiresAt) {
		return nil, false
	}
	return e.value, true
}

func (c *TTLCache) Set(key string, value []byte) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.entries[key] = entry{value: value, expiresAt: time.Now().Add(c.ttl)}
}

// Purge removes expired entries. Safe to call from a background goroutine.
func (c *TTLCache) Purge() int {
	now := time.Now()
	c.mu.Lock()
	defer c.mu.Unlock()

	removed := 0
	for k, e := range c.entries {
		if now.After(e.expiresAt) {
			delete(c.entries, k)
			removed++
		}
	}
	return removed
}

// FetchProfile returns a user profile, using the cache when it is warm.
func FetchProfile(ctx context.Context, c *TTLCache, client *http.Client, userID string) (map[string]any, error) {
	if cached, ok := c.Get(userID); ok {
		var profile map[string]any
		if err := json.Unmarshal(cached, &profile); err == nil {
			return profile, nil
		}
		// A corrupt cache entry should not be fatal; fall through and refetch.
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodGet,
		"https://profiles.internal/v1/users/"+userID, nil)
	if err != nil {
		return nil, fmt.Errorf("build profile request: %w", err)
	}

	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("fetch profile %s: %w", userID, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("profile service returned %d for %s", resp.StatusCode, userID)
	}

	var profile map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&profile); err != nil {
		return nil, fmt.Errorf("decode profile %s: %w", userID, err)
	}

	if encoded, err := json.Marshal(profile); err == nil {
		c.Set(userID, encoded)
	}
	return profile, nil
}
