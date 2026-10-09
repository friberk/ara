package server

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"github.com/ollama/ollama/api"
	"github.com/ollama/ollama/types/model"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestARACapabilities(t *testing.T) {
	t.Setenv("OLLAMA_MODELS", t.TempDir())
	s := &Server{}
	router, err := s.GenerateRoutes()
	if err != nil {
		t.Fatal(err)
	}
	r := httptest.NewRecorder()
	router.ServeHTTP(r, httptest.NewRequest(http.MethodGet, "/api/ara/capabilities", nil))
	if r.Code != 200 {
		t.Fatalf("capabilities status = %d, want 200: %s", r.Code, r.Body.String())
	}
}

func TestARAPauseStopsTransferAndResumesRange(t *testing.T) {
	t.Setenv("OLLAMA_MODELS", t.TempDir())
	t.Setenv("OLLAMA_NOPRUNE", "true")
	data := bytes.Repeat([]byte("ara-download-fixture-"), 400000)
	digest := fmt.Sprintf("sha256:%x", sha256.Sum256(data))
	var active, sent atomic.Int64
	var mu sync.Mutex
	var ranges []int
	var registry *httptest.Server
	registry = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.Contains(r.URL.Path, "/manifests/"):
			json.NewEncoder(w).Encode(map[string]any{"schemaVersion": 2, "layers": []any{map[string]any{"mediaType": "application/vnd.ollama.image.model", "digest": digest, "size": len(data)}}})
		case r.Method == http.MethodHead:
			w.Header().Set("Content-Length", strconv.Itoa(len(data)))
		case strings.Contains(r.URL.Path, "/blobs/"):
			w.Header().Set("Location", registry.URL+"/data")
		case r.URL.Path == "/data":
			start, stop := 0, len(data)-1
			fmt.Sscanf(r.Header.Get("Range"), "bytes=%d-%d", &start, &stop)
			mu.Lock()
			ranges = append(ranges, start)
			mu.Unlock()
			active.Add(1)
			defer active.Add(-1)
			w.Header().Set("Content-Length", strconv.Itoa(stop-start+1))
			w.WriteHeader(http.StatusPartialContent)
			for pos := start; pos <= stop; pos += 32768 {
				select {
				case <-r.Context().Done():
					return
				default:
				}
				end := min(pos+32768, stop+1)
				n, err := w.Write(data[pos:end])
				sent.Add(int64(n))
				if err != nil {
					return
				}
				w.(http.Flusher).Flush()
				time.Sleep(5 * time.Millisecond)
			}
		default:
			http.NotFound(w, r)
		}
	}))
	defer registry.Close()
	s := &Server{}
	router, err := s.GenerateRoutes()
	if err != nil {
		t.Fatal(err)
	}
	runtime := httptest.NewServer(router)
	defer runtime.Close()
	model := registry.URL + "/library/fixture:latest"
	operation := "a1c50d75-6b25-4fe1-9f8f-a7405b201600"
	post := func(path string, body any) *http.Response {
		t.Helper()
		payload, _ := json.Marshal(body)
		response, err := http.Post(runtime.URL+path, "application/json", bytes.NewReader(payload))
		if err != nil {
			t.Fatal(err)
		}
		return response
	}
	req := map[string]any{"model": model, "operation_id": operation, "insecure": true}
	response := post("/api/ara/pull", req)
	if response.StatusCode != 200 {
		b, _ := io.ReadAll(response.Body)
		response.Body.Close()
		t.Fatalf("pull status=%d body=%s", response.StatusCode, b)
	}
	finished := make(chan struct{})
	streamError := make(chan error, 1)
	go func() {
		_, err := io.Copy(io.Discard, response.Body)
		streamError <- err
		response.Body.Close()
		close(finished)
	}()
	deadline := time.Now().Add(5 * time.Second)
	for sent.Load() < 262144 && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if sent.Load() < 262144 {
		t.Fatal("transfer did not start")
	}
	duplicate := post("/api/ara/pull", req)
	duplicate.Body.Close()
	if duplicate.StatusCode != 409 {
		t.Fatalf("duplicate status=%d want409", duplicate.StatusCode)
	}
	started := time.Now()
	pause := post("/api/ara/pulls/"+operation+"/pause", map[string]any{})
	var ack map[string]any
	json.NewDecoder(pause.Body).Decode(&ack)
	pause.Body.Close()
	if pause.StatusCode != 200 || ack["state"] != "paused" {
		t.Fatalf("pause status=%d body=%v", pause.StatusCode, ack)
	}
	if time.Since(started) > 2*time.Second {
		t.Fatal("pause exceeded 2 seconds on deterministic slow registry")
	}
	select {
	case <-finished:
	case <-time.After(2 * time.Second):
		t.Fatal("pull goroutine did not terminate")
	}
	if err := <-streamError; err != nil {
		t.Errorf("reading client received truncated HTTP response: %v", err)
	}
	time.Sleep(100 * time.Millisecond)
	if active.Load() != 0 {
		t.Fatalf("transfer active after acknowledgement: %d", active.Load())
	}
	checkpoint := sent.Load()
	time.Sleep(100 * time.Millisecond)
	if sent.Load() != checkpoint {
		t.Fatal("bytes still transfer after pause")
	}
	again := post("/api/ara/pulls/"+operation+"/pause", map[string]any{})
	again.Body.Close()
	if again.StatusCode != 200 {
		t.Fatalf("idempotent pause=%d", again.StatusCode)
	}
	req["operation_id"] = "b1c50d75-6b25-4fe1-9f8f-a7405b201601"
	resume := post("/api/ara/pull", req)
	body, _ := io.ReadAll(resume.Body)
	resume.Body.Close()
	if !bytes.Contains(body, []byte(`"status":"success"`)) {
		t.Fatalf("resume failed: %s", body)
	}
	mu.Lock()
	defer mu.Unlock()
	found := false
	for _, n := range ranges {
		if n > 0 {
			found = true
		}
	}
	if !found {
		t.Fatalf("resume restarted from zero: ranges=%v", ranges)
	}
}

func TestARAMalformedRequests(t *testing.T) {
	t.Setenv("OLLAMA_MODELS", t.TempDir())
	s := &Server{}
	router, err := s.GenerateRoutes()
	if err != nil {
		t.Fatal(err)
	}
	for _, body := range []string{`{}`, `{"model":"valid","operation_id":"no"}`, `{"model":"","operation_id":"a1c50d75-6b25-4fe1-9f8f-a7405b201600"}`} {
		r := httptest.NewRecorder()
		router.ServeHTTP(r, httptest.NewRequest("POST", "/api/ara/pull", strings.NewReader(body)))
		if r.Code != 400 {
			t.Errorf("body=%s status=%d want400", body, r.Code)
		}
	}
}

// A paused retry must join the transfer, not merely stop publishing progress.
func TestARACancelRetrySleep(t *testing.T) {
	t.Setenv("OLLAMA_MODELS", t.TempDir())
	var tries atomic.Int64
	var registry *httptest.Server
	registry = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "HEAD" {
			w.Header().Set("Content-Length", "100000")
			return
		}
		if r.URL.Path == "/data" {
			tries.Add(1)
			w.Header().Set("Content-Length", "100000")
			return
		}
		w.Header().Set("Location", registry.URL+"/data")
	}))
	defer registry.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	digest := "sha256:" + strings.Repeat("b", 64)
	go func() {
		_, err := downloadBlob(ctx, downloadOpts{n: model.ParseName(registry.URL + "/library/retry:latest"), digest: digest, regOpts: &registryOptions{Insecure: true}, fn: func(api.ProgressResponse) {}})
		done <- err
	}()
	deadline := time.Now().Add(10 * time.Second)
	for tries.Load() < 3 && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if tries.Load() < 3 {
		t.Fatal("did not reach the 4-second retry delay")
	}
	time.Sleep(50 * time.Millisecond)
	cancel()
	select {
	case <-done:
	case <-time.After(500 * time.Millisecond):
		t.Fatal("cancellation waited for retry sleep")
	}
	if _, exists := blobDownloadManager.Load(digest); exists {
		t.Fatal("transfer still owns partial files after cancellation returned")
	}
}

// A stalled HEAD for digest B must not delay cancellation/checkpoints of A.
func TestARAPauseIndependentOfOtherPreparation(t *testing.T) {
	t.Setenv("OLLAMA_MODELS", t.TempDir())
	stalled := make(chan struct{})
	unblockHead := make(chan struct{})
	transferStarted := make(chan struct{})
	transferStopped := make(chan struct{})
	var registry *httptest.Server
	registry = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "HEAD" {
			if strings.HasSuffix(r.URL.Path, strings.Repeat("d", 64)) {
				close(stalled)
				select {
				case <-unblockHead:
				case <-r.Context().Done():
					return
				}
			}
			w.Header().Set("Content-Length", "10000000")
			return
		}
		if r.URL.Path == "/data" {
			close(transferStarted)
			defer close(transferStopped)
			w.Header().Set("Content-Length", "10000000")
			w.WriteHeader(206)
			w.Write(bytes.Repeat([]byte("a"), 32768))
			w.(http.Flusher).Flush()
			<-r.Context().Done()
			return
		}
		w.Header().Set("Location", registry.URL+"/data")
	}))
	defer registry.Close()
	ctxA, cancelA := context.WithCancel(context.Background())
	ctxB, cancelB := context.WithCancel(context.Background())
	doneA, doneB := make(chan error, 1), make(chan error, 1)
	launch := func(ctx context.Context, digest string, done chan error) {
		_, err := downloadBlob(ctx, downloadOpts{n: model.ParseName(registry.URL + "/library/test:latest"), digest: "sha256:" + strings.Repeat(digest, 64), regOpts: &registryOptions{Insecure: true}, fn: func(api.ProgressResponse) {}})
		done <- err
	}
	defer func() { cancelA(); cancelB(); close(unblockHead); <-doneB }()
	go launch(ctxA, "c", doneA)
	select {
	case <-transferStarted:
	case <-time.After(2 * time.Second):
		t.Fatal("A transfer did not start")
	}
	go launch(ctxB, "d", doneB)
	select {
	case <-stalled:
	case <-time.After(2 * time.Second):
		t.Fatal("B HEAD did not start")
	}
	cancelA()
	select {
	case <-doneA:
	case <-time.After(500 * time.Millisecond):
		t.Error("A cancellation blocked behind unrelated B HEAD")
		cancelB()
		closeWait := time.After(2 * time.Second)
		select {
		case <-doneA:
		case <-closeWait:
			t.Error("A cleanup failed")
		}
	}
	select {
	case <-transferStopped:
	case <-time.After(500 * time.Millisecond):
		t.Error("A transfer still active after cancellation")
	}
}

type araBackpressuredWriter struct {
	*httptest.ResponseRecorder
	blocked     chan struct{}
	unblock     chan struct{}
	once        sync.Once
	blockedOnce sync.Once
}

func (w *araBackpressuredWriter) CloseNotify() <-chan bool { return make(chan bool) }
func (w *araBackpressuredWriter) Write(p []byte) (int, error) {
	if bytes.Contains(p, []byte(`"completed":`)) {
		w.blockedOnce.Do(func() { close(w.blocked) })
		<-w.unblock
		return 0, context.DeadlineExceeded
	}
	return w.ResponseRecorder.Write(p)
}
func (w *araBackpressuredWriter) SetWriteDeadline(deadline time.Time) error {
	if !deadline.IsZero() {
		w.once.Do(func() { close(w.unblock) })
	}
	return nil
}

func TestARAPauseInterruptsBackpressuredResponse(t *testing.T) {
	t.Setenv("OLLAMA_MODELS", t.TempDir())
	transferStopped := make(chan struct{})
	var registry *httptest.Server
	registry = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.Contains(r.URL.Path, "/manifests/"):
			json.NewEncoder(w).Encode(map[string]any{"schemaVersion": 2, "layers": []any{map[string]any{"digest": "sha256:" + strings.Repeat("e", 64), "size": 10000000, "mediaType": "application/vnd.ollama.image.model"}}})
		case r.Method == "HEAD":
			w.Header().Set("Content-Length", "10000000")
		case r.URL.Path == "/data":
			defer close(transferStopped)
			w.Header().Set("Content-Length", "10000000")
			w.WriteHeader(206)
			w.Write(bytes.Repeat([]byte("a"), 32768))
			w.(http.Flusher).Flush()
			<-r.Context().Done()
		default:
			w.Header().Set("Location", registry.URL+"/data")
		}
	}))
	defer registry.Close()
	s := &Server{}
	router, err := s.GenerateRoutes()
	if err != nil {
		t.Fatal(err)
	}
	operation := "a1c50d75-6b25-4fe1-9f8f-a7405b201622"
	payload, _ := json.Marshal(map[string]any{"model": registry.URL + "/library/blocked:latest", "operation_id": operation, "insecure": true})
	writer := &araBackpressuredWriter{ResponseRecorder: httptest.NewRecorder(), blocked: make(chan struct{}), unblock: make(chan struct{})}
	handlerDone := make(chan struct{})
	go func() {
		router.ServeHTTP(writer, httptest.NewRequest("POST", "/api/ara/pull", bytes.NewReader(payload)))
		close(handlerDone)
	}()
	defer func() { writer.SetWriteDeadline(time.Now()); <-handlerDone }()
	select {
	case <-writer.blocked:
	case <-time.After(2 * time.Second):
		t.Fatal("pull response did not block")
	}
	pause := httptest.NewRecorder()
	pauseDone := make(chan struct{})
	go func() {
		router.ServeHTTP(pause, httptest.NewRequest("POST", "/api/ara/pulls/"+operation+"/pause", strings.NewReader(`{}`)))
		close(pauseDone)
	}()
	select {
	case <-pauseDone:
	case <-time.After(500 * time.Millisecond):
		t.Error("pause acknowledgement blocked behind response writer")
		writer.SetWriteDeadline(time.Now())
		<-pauseDone
	}
	if pause.Code != 200 {
		t.Errorf("pause status=%d body=%s", pause.Code, pause.Body.String())
	}
	select {
	case <-handlerDone:
	case <-time.After(500 * time.Millisecond):
		t.Error("backpressured handler leaked")
	}
	select {
	case <-transferStopped:
	case <-time.After(500 * time.Millisecond):
		t.Error("transfer active after pause acknowledgement")
	}
}

func TestARASharedPreparationHasIndependentOwners(t *testing.T) {
	t.Setenv("OLLAMA_MODELS", t.TempDir())
	headStarted, headStopped := make(chan struct{}), make(chan struct{})
	var heads atomic.Int32
	registry := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "HEAD" {
			t.Errorf("unexpected request %s", r.Method)
			return
		}
		if heads.Add(1) == 1 {
			close(headStarted)
		}
		<-r.Context().Done()
		if heads.Load() == 1 {
			close(headStopped)
		}
	}))
	defer registry.Close()
	digest := "sha256:" + strings.Repeat("f", 64)
	ctxA, cancelA := context.WithCancel(context.Background())
	defer cancelA()
	ctxB, cancelB := context.WithCancel(context.Background())
	defer cancelB()
	doneA, doneB := make(chan error, 1), make(chan error, 1)
	launch := func(ctx context.Context, done chan error) {
		_, err := downloadBlob(ctx, downloadOpts{n: model.ParseName(registry.URL + "/library/shared:latest"), digest: digest, regOpts: &registryOptions{Insecure: true}, fn: func(api.ProgressResponse) {}})
		done <- err
	}
	go launch(ctxA, doneA)
	select {
	case <-headStarted:
	case <-time.After(time.Second):
		t.Fatal("HEAD did not start")
	}
	go launch(ctxB, doneB)
	deadline := time.Now().Add(time.Second)
	owners := int32(0)
	for time.Now().Before(deadline) {
		if value, ok := blobDownloadManager.Load(digest); ok {
			owners = value.(*blobDownload).references.Load()
		}
		if owners == 2 {
			break
		}
		time.Sleep(time.Millisecond)
	}
	if owners != 2 {
		t.Error("second owner did not join the initializing download")
	}
	cancelA()
	select {
	case <-doneA:
	case <-time.After(500 * time.Millisecond):
		t.Error("first owner blocked on other owner's preparation")
	}
	select {
	case <-headStopped:
		t.Error("first owner canceled shared HEAD")
	default:
	}
	if heads.Load() != 1 {
		t.Errorf("concurrent owners issued %d HEADs", heads.Load())
	}
	cancelB()
	select {
	case <-doneB:
	case <-time.After(time.Second):
		t.Error("last owner failed to join preparation")
	}
	select {
	case <-headStopped:
	case <-time.After(time.Second):
		t.Error("HEAD remained alive after last owner")
	}
	if _, exists := blobDownloadManager.Load(digest); exists {
		t.Error("closed shared download retained")
	}
}

func TestARAFreshDaemonPauseBlocksLatePull(t *testing.T) {
	t.Setenv("OLLAMA_MODELS", t.TempDir())
	s := &Server{}
	router, err := s.GenerateRoutes()
	if err != nil {
		t.Fatal(err)
	}
	operation := "a1c50d75-6b25-4fe1-9f8f-a7405b201633"
	pause := httptest.NewRecorder()
	router.ServeHTTP(pause, httptest.NewRequest("POST", "/api/ara/pulls/"+operation+"/pause", strings.NewReader(`{}`)))
	if pause.Code != 200 || !strings.Contains(pause.Body.String(), `"state":"paused"`) {
		t.Fatalf("unknown operation pause=%d %s, want acknowledged tombstone", pause.Code, pause.Body.String())
	}
	payload := `{"model":"hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M","operation_id":"` + operation + `"}`
	late := httptest.NewRecorder()
	router.ServeHTTP(late, httptest.NewRequest("POST", "/api/ara/pull", strings.NewReader(payload)))
	if late.Code != 409 {
		t.Fatalf("late pull status=%d want409", late.Code)
	}
	again := httptest.NewRecorder()
	router.ServeHTTP(again, httptest.NewRequest("POST", "/api/ara/pulls/"+operation+"/pause", strings.NewReader(`{}`)))
	if again.Code != 200 {
		t.Errorf("repeat unknown pause=%d", again.Code)
	}
}

func TestARAConcurrentPauseTombstonesBlockLatePulls(t *testing.T) {
	t.Setenv("OLLAMA_MODELS", t.TempDir())
	s := &Server{}
	router, err := s.GenerateRoutes()
	if err != nil {
		t.Fatal(err)
	}
	operation := "a1c50d75-6b25-4fe1-9f8f-a7405b201644"
	start := make(chan struct{})
	var wg sync.WaitGroup
	for range 32 {
		wg.Go(func() {
			<-start
			pause := httptest.NewRecorder()
			router.ServeHTTP(pause, httptest.NewRequest("POST", "/api/ara/pulls/"+operation+"/pause", strings.NewReader(`{}`)))
			if pause.Code != 200 {
				t.Errorf("concurrent pause=%d want200", pause.Code)
				return
			}
			payload := `{"model":"hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M","operation_id":"` + operation + `"}`
			late := httptest.NewRecorder()
			router.ServeHTTP(late, httptest.NewRequest("POST", "/api/ara/pull", strings.NewReader(payload)))
			if late.Code != 409 {
				t.Errorf("late pull=%d want409", late.Code)
			}
		})
	}
	close(start)
	wg.Wait()
	if len(s.araPulls.operations) != 1 {
		t.Errorf("tombstone entries=%d want1", len(s.araPulls.operations))
	}
}

func TestARAPauseTombstoneCapacityFailClosed(t *testing.T) {
	t.Setenv("OLLAMA_MODELS", t.TempDir())
	s := &Server{}
	router, err := s.GenerateRoutes()
	if err != nil {
		t.Fatal(err)
	}
	done := make(chan struct{})
	close(done)
	stopped := &araPullOperation{cancel: func() {}, done: done}
	s.araPulls.operations = make(map[string]*araPullOperation)
	for i := range 10000 {
		s.araPulls.operations[fmt.Sprintf("%08d-0000-4000-8000-000000000000", i)] = stopped
	}
	unknown := "a1c50d75-6b25-4fe1-9f8f-a7405b201655"
	pause := httptest.NewRecorder()
	router.ServeHTTP(pause, httptest.NewRequest("POST", "/api/ara/pulls/"+unknown+"/pause", strings.NewReader(`{}`)))
	if pause.Code != 503 {
		t.Errorf("full registry unknown pause=%d want503", pause.Code)
	}
	existing := httptest.NewRecorder()
	router.ServeHTTP(existing, httptest.NewRequest("POST", "/api/ara/pulls/00000000-0000-4000-8000-000000000000/pause", strings.NewReader(`{}`)))
	if existing.Code != 200 {
		t.Errorf("known pause at capacity=%d want200", existing.Code)
	}
	if len(s.araPulls.operations) != 10000 {
		t.Errorf("capacity changed to%d", len(s.araPulls.operations))
	}
}
