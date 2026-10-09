package server

// ARA's private protocol is intentionally separate from Ollama's public API.
// An operation ID identifies exactly one attempt; resuming uses a fresh UUID.
import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/ollama/ollama/api"
)

type araPullOperation struct {
	cancel context.CancelFunc
	done   chan struct{}
}

type araPullRegistry struct {
	mu         sync.Mutex
	operations map[string]*araPullOperation
}

func (s *Server) araCapabilities(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"protocol_version": 1, "pull_control": true})
}

func (s *Server) araPull(c *gin.Context) {
	var req struct {
		api.PullRequest
		OperationID string `json:"operation_id"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(400, gin.H{"error": "invalid request"})
		return
	}
	id, err := uuid.Parse(req.OperationID)
	if err != nil || id == uuid.Nil {
		c.JSON(400, gin.H{"error": "operation_id must be a nonzero UUID"})
		return
	}
	if _, err := parseNormalizePullModelRef(req.Model); err != nil {
		c.JSON(400, gin.H{"error": "invalid model reference"})
		return
	}
	key := id.String()
	s.araPulls.mu.Lock()
	if s.araPulls.operations == nil {
		s.araPulls.operations = make(map[string]*araPullOperation)
	}
	if _, exists := s.araPulls.operations[key]; exists {
		s.araPulls.mu.Unlock()
		c.JSON(409, gin.H{"error": "operation_id already used; resume with a fresh UUID"})
		return
	}
	// Retain tombstones for this daemon lifetime: a duplicate must never restart I/O.
	// Bound memory rather than silently discarding idempotency information.
	if len(s.araPulls.operations) >= 10000 {
		s.araPulls.mu.Unlock()
		c.JSON(503, gin.H{"error": "operation registry full"})
		return
	}
	ctx, cancel := context.WithCancel(c.Request.Context())
	op := &araPullOperation{cancel: cancel, done: make(chan struct{})}
	s.araPulls.operations[key] = op
	s.araPulls.mu.Unlock()
	defer close(op.done)
	defer cancel()
	payload, _ := json.Marshal(req.PullRequest)
	c.Request = c.Request.WithContext(ctx)
	c.Request.Body = io.NopCloser(bytes.NewReader(payload))
	// Canceling context alone cannot interrupt a socket Write/Flush. A scoped
	// response deadline wakes a non-reading client without stopping the server.
	// Join the watcher before Gin can recycle its ResponseWriter.
	controller := http.NewResponseController(c.Writer)
	stopWatcher, watcherDone := make(chan struct{}), make(chan struct{})
	go func() {
		defer close(watcherDone)
		select {
		case <-ctx.Done():
			// Let a draining client receive the normal terminal HTTP chunk. Force a
			// deadline only if the canceled handler still cannot finish after grace.
			timer := time.NewTimer(100 * time.Millisecond)
			defer timer.Stop()
			select {
			case <-stopWatcher:
				return
			case <-timer.C:
				_ = controller.SetWriteDeadline(time.Now())
			}
		case <-stopWatcher:
		}
	}()
	defer func() { close(stopWatcher); <-watcherDone }()
	s.PullHandler(c)
}

func (s *Server) araPause(c *gin.Context) {
	id, err := uuid.Parse(c.Param("operation_id"))
	if err != nil || id == uuid.Nil {
		c.JSON(400, gin.H{"error": "invalid operation_id"})
		return
	}
	s.araPulls.mu.Lock()
	op := s.araPulls.operations[id.String()]
	if op == nil {
		// After a daemon restart an old worker may still be about to POST its
		// attempt. Acknowledging pause must reserve a tombstone atomically with
		// pull registration, so that late delivery can never start that attempt.
		if len(s.araPulls.operations) >= 10000 {
			s.araPulls.mu.Unlock()
			c.JSON(503, gin.H{"error": "operation registry full"})
			return
		}
		if s.araPulls.operations == nil {
			s.araPulls.operations = make(map[string]*araPullOperation)
		}
		done := make(chan struct{})
		close(done)
		op = &araPullOperation{cancel: func() {}, done: done}
		s.araPulls.operations[id.String()] = op
	}
	s.araPulls.mu.Unlock()
	op.cancel()
	select {
	case <-op.done:
		c.JSON(200, gin.H{"state": "paused"})
	case <-c.Request.Context().Done():
		return
	}
}
