package server

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"reflect"
	"slices"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/ollama/ollama/api"
	gguftest "github.com/ollama/ollama/internal/testutil/gguf"
	"github.com/ollama/ollama/llm"
	"github.com/ollama/ollama/types/model"
)

func araIFMTemplate(t *testing.T) string {
	t.Helper()
	b, err := os.ReadFile("testdata/ara_ifm_chat_template.jinja")
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

// A broad family or tag match must not expose controls on an unverified template.
func TestARAIFMThinkingExactIdentity(t *testing.T) {
	t.Setenv("OLLAMA_GO_TEMPLATE", "")
	tmpl := araIFMTemplate(t)
	want := &model.Thinking{Values: []any{false, true, "low", "medium", "high"}, Default: "high"}
	for _, tc := range []struct {
		name   string
		change func(*Model)
		known  bool
	}{
		{"retained native identity", func(*Model) {}, true},
		{"different architecture", func(m *Model) { m.metadata.KV["general.architecture"] = "llama" }, false},
		{"changed template", func(m *Model) { m.metadata.KV["tokenizer.chat_template"] = tmpl + "\n" }, false},
		{"Go template selected", func(m *Model) { m.HasGoTemplate = true }, false},
		{"custom renderer", func(m *Model) { m.Config.Renderer = "unknown" }, false},
		{"custom parser", func(m *Model) { m.Config.Parser = "unknown" }, false},
		{"remote model", func(m *Model) { m.Config.RemoteHost = "https://example.invalid" }, false},
		{"not GGUF", func(m *Model) { m.Config.ModelFormat = "safetensors" }, false},
		{"missing model blob", func(m *Model) { m.ModelPath = "" }, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			m := &Model{ModelPath: "fixture.gguf", HasChatTemplate: true, metadata: ggufMetadata{KV: map[string]any{
				"general.architecture": "k2-horizon", "tokenizer.chat_template": tmpl,
			}}}
			tc.change(m)
			if got := m.Thinking(); tc.known && !reflect.DeepEqual(got, want) || !tc.known && got != nil {
				t.Fatalf("descriptor = %#v, known=%v want=%#v", got, tc.known, want)
			}
			if got := slices.Contains(m.Capabilities(), model.CapabilityThinking); got != tc.known {
				t.Fatalf("thinking capability = %v, want %v", got, tc.known)
			}
		})
	}
}

// Only inference is replaced; real show, request validation, capability scheduling,
// and native request preparation must preserve every supported control.
func TestARAIFMNativeThinkingRequests(t *testing.T) {
	gin.SetMode(gin.TestMode)
	t.Setenv("OLLAMA_MODELS", t.TempDir())
	t.Setenv("OLLAMA_CONTEXT_LENGTH", "4096")
	t.Setenv("OLLAMA_GO_TEMPLATE", "")
	calls := 0
	runner := mockRunner{ChatFn: func(_ context.Context, req llm.ChatRequest, fn func(llm.ChatResponse)) error {
		calls++
		fn(llm.ChatResponse{Message: api.Message{Role: "assistant", Thinking: "private reasoning", Content: "answer"}, Done: true, DoneReason: llm.DoneReasonStop})
		return nil
	}}
	s := newServerWithMockRunner(t, &runner)
	createMinimalGGUFModel(t, s, "ara-ifm", gguftest.KV{
		"general.architecture": "k2-horizon", "tokenizer.chat_template": araIFMTemplate(t),
	}, "", nil)
	show, err := GetModelInfo(api.ShowRequest{Model: "ara-ifm"})
	if err != nil {
		t.Fatal(err)
	}
	want := &model.Thinking{Values: []any{false, true, "low", "medium", "high"}, Default: "high"}
	if !reflect.DeepEqual(show.Thinking, want) {
		t.Errorf("show descriptor=%#v, want=%#v", show.Thinking, want)
	}
	for _, tc := range []struct{ requested, resolved any }{
		{nil, "high"}, {true, true}, {false, false}, {"low", "low"}, {"medium", "medium"}, {"high", "high"},
	} {
		label, _ := json.Marshal(tc.requested)
		t.Run(string(label), func(t *testing.T) {
			var think *api.ThinkValue
			if tc.requested != nil {
				think = &api.ThinkValue{Value: tc.requested}
			}
			w := createRequest(t, s.ChatHandler, api.ChatRequest{Model: "ara-ifm", Messages: []api.Message{{Role: "user", Content: "hello"}}, Think: think, Stream: &stream})
			if w.Code != http.StatusOK {
				t.Fatalf("status=%d: %s", w.Code, w.Body.String())
			}
			if runner.ChatRequest.Think == nil || runner.ChatRequest.Think.Value != tc.resolved {
				t.Fatalf("native think=%#v, want=%#v", runner.ChatRequest.Think, tc.resolved)
			}
			var resp api.ChatResponse
			if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
				t.Fatal(err)
			}
			if resp.Message.Content != "answer" || resp.Message.Thinking != "private reasoning" {
				t.Fatalf("native fields changed: %#v", resp.Message)
			}
		})
	}
	for _, value := range []string{"", "xhigh", "max", "future", "LOW"} {
		for _, endpoint := range []string{"chat", "generate"} {
			t.Run(endpoint+"/reject/"+value, func(t *testing.T) {
				before := calls
				think := &api.ThinkValue{Value: value}
				var wCode int
				var body string
				if endpoint == "chat" {
					w := createRequest(t, s.ChatHandler, api.ChatRequest{Model: "ara-ifm", Messages: []api.Message{{Role: "user", Content: "hello"}}, Think: think, Stream: &stream})
					wCode, body = w.Code, w.Body.String()
				} else {
					w := createRequest(t, s.GenerateHandler, api.GenerateRequest{Model: "ara-ifm", Prompt: "hello", Think: think, Stream: &stream})
					wCode, body = w.Code, w.Body.String()
				}
				if wCode != 400 || !strings.Contains(body, "supported values") {
					t.Fatalf("status=%d body=%s, want explicit 400", wCode, body)
				}
				if calls != before {
					t.Fatal("unsupported control reached inference")
				}
			})
		}
	}
}

// Generate uses raw completion rather than the native chat parser; tagged traces
// must still be consumed using the selected effort's closing token.
func TestARAIFMGenerateThinkingSeparation(t *testing.T) {
	gin.SetMode(gin.TestMode)
	t.Setenv("OLLAMA_MODELS", t.TempDir())
	t.Setenv("OLLAMA_CONTEXT_LENGTH", "4096")
	t.Setenv("OLLAMA_GO_TEMPLATE", "")
	runner := mockRunner{}
	s := newServerWithMockRunner(t, &runner)
	createMinimalGGUFModel(t, s, "ara-ifm", gguftest.KV{
		"general.architecture": "k2-horizon", "tokenizer.chat_template": araIFMTemplate(t),
	}, "", nil)
	for _, tc := range []struct {
		requested   any
		open, close string
	}{
		{nil, "<ifm|think>", "</ifm|think>"}, {true, "<ifm|think>", "</ifm|think>"},
		{"high", "<ifm|think>", "</ifm|think>"}, {"medium", "<ifm|think_fast>", "</ifm|think_fast>"}, {"low", "<ifm|think_faster>", "</ifm|think_faster>"},
	} {
		label, _ := json.Marshal(tc.requested)
		t.Run(string(label), func(t *testing.T) {
			runner.Template = "<|ifm|im_start|>assistant\n" + tc.open + "\n"
			runner.CompletionResponse = llm.CompletionResponse{Content: "private reasoning" + tc.close + "answer", Done: true, DoneReason: llm.DoneReasonStop}
			var think *api.ThinkValue
			if tc.requested != nil {
				think = &api.ThinkValue{Value: tc.requested}
			}
			w := createRequest(t, s.GenerateHandler, api.GenerateRequest{Model: "ara-ifm", Prompt: "hello", Think: think, Stream: &stream})
			if w.Code != 200 {
				t.Fatalf("status=%d: %s", w.Code, w.Body.String())
			}
			var resp api.GenerateResponse
			if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
				t.Fatal(err)
			}
			if resp.Response != "answer" || resp.Thinking != "private reasoning" {
				t.Fatalf("answer=%q thinking=%q", resp.Response, resp.Thinking)
			}
			if !reflect.DeepEqual(runner.CompletionRequest.ThinkingClose, []string{"</ifm|think>", "</ifm|think_fast>", "</ifm|think_faster>"}) {
				t.Fatalf("schema transition closing tokens=%#v, want=%q", runner.CompletionRequest.ThinkingClose, tc.close)
			}
		})
	}
}

// Named effort only has meaning while the canonical Jinja template is applied.
func TestARAIFMGenerateRejectsNamedThinkingOnTemplateBypass(t *testing.T) {
	gin.SetMode(gin.TestMode)
	t.Setenv("OLLAMA_MODELS", t.TempDir())
	t.Setenv("OLLAMA_CONTEXT_LENGTH", "4096")
	t.Setenv("OLLAMA_GO_TEMPLATE", "")
	calls := 0
	runner := mockRunner{Template: "prompt", CompletionFn: func(_ context.Context, _ llm.CompletionRequest, fn func(llm.CompletionResponse)) error {
		calls++
		fn(llm.CompletionResponse{Content: "answer", Done: true, DoneReason: llm.DoneReasonStop})
		return nil
	}}
	s := newServerWithMockRunner(t, &runner)
	createMinimalGGUFModel(t, s, "ara-ifm", gguftest.KV{
		"general.architecture": "k2-horizon", "tokenizer.chat_template": araIFMTemplate(t),
	}, "", map[string]any{"capabilities": []any{"completion", "insert"}})
	for _, tc := range []struct {
		name   string
		bypass func(*api.GenerateRequest)
	}{
		{"raw", func(r *api.GenerateRequest) { r.Raw = true }},
		{"custom template", func(r *api.GenerateRequest) { r.Template = "{{ .Prompt }}" }},
		{"suffix", func(r *api.GenerateRequest) { r.Suffix = "tail" }},
	} {
		for _, effort := range []string{"low", "medium", "high"} {
			t.Run(tc.name+"/"+effort, func(t *testing.T) {
				req := api.GenerateRequest{Model: "ara-ifm", Prompt: "hello", Think: &api.ThinkValue{Value: effort}, Stream: &stream}
				tc.bypass(&req)
				before := calls
				w := createRequest(t, s.GenerateHandler, req)
				if w.Code != 400 || !strings.Contains(w.Body.String(), "model chat template") {
					t.Fatalf("status=%d body=%s, want unsupported-template 400", w.Code, w.Body.String())
				}
				if calls != before {
					t.Fatal("bypassed named control reached inference")
				}
			})
		}
	}
}

// The real medium weights can close the fast prefill with the high token.
// Every two-chunk split must keep private text out of the answer, including the
// common closing-tag prefix. Inference is the only replaced boundary.
func TestARAIFMGenerateClosingAliases(t *testing.T) {
	gin.SetMode(gin.TestMode)
	t.Setenv("OLLAMA_MODELS", t.TempDir())
	t.Setenv("OLLAMA_CONTEXT_LENGTH", "4096")
	t.Setenv("OLLAMA_GO_TEMPLATE", "")
	runner := mockRunner{}
	s := newServerWithMockRunner(t, &runner)
	createMinimalGGUFModel(t, s, "ara-ifm", gguftest.KV{
		"general.architecture": "k2-horizon", "tokenizer.chat_template": araIFMTemplate(t),
	}, "", nil)
	closes := []string{"</ifm|think>", "</ifm|think_fast>", "</ifm|think_faster>"}
	for _, tc := range []struct{ effort, opening string }{
		{"high", "<ifm|think>"}, {"medium", "<ifm|think_fast>"}, {"low", "<ifm|think_faster>"},
	} {
		for _, close := range closes {
			text := "private reasoning" + close + "answer"
			for split := 0; split <= len(text); split++ {
				t.Run(fmt.Sprintf("%s/%s/split%d", tc.effort, close, split), func(t *testing.T) {
					runner.Template = "<|ifm|im_start|>assistant\n" + tc.opening + "\n"
					runner.CompletionFn = func(_ context.Context, _ llm.CompletionRequest, fn func(llm.CompletionResponse)) error {
						fn(llm.CompletionResponse{Content: text[:split]})
						fn(llm.CompletionResponse{Content: text[split:], Done: true, DoneReason: llm.DoneReasonStop})
						return nil
					}
					w := createRequest(t, s.GenerateHandler, api.GenerateRequest{Model: "ara-ifm", Prompt: "hello", Think: &api.ThinkValue{Value: tc.effort}, Stream: &stream})
					if w.Code != 200 {
						t.Fatalf("status=%d: %s", w.Code, w.Body.String())
					}
					var response api.GenerateResponse
					if err := json.Unmarshal(w.Body.Bytes(), &response); err != nil {
						t.Fatal(err)
					}
					if response.Response != "answer" || response.Thinking != "private reasoning" {
						t.Fatalf("answer=%q thinking=%q", response.Response, response.Thinking)
					}
					if !reflect.DeepEqual(runner.CompletionRequest.ThinkingClose, closes) {
						t.Fatalf("schema closing tokens=%#v, want=%#v", runner.CompletionRequest.ThinkingClose, closes)
					}
				})
			}
		}
	}
	runner.Template = "<|ifm|im_start|>assistant\n<ifm|think>\n</ifm|think>\n"
	runner.CompletionFn = nil
	runner.CompletionResponse = llm.CompletionResponse{Content: "answer mentions </ifm|think_fast> literally", Done: true, DoneReason: llm.DoneReasonStop}
	w := createRequest(t, s.GenerateHandler, api.GenerateRequest{Model: "ara-ifm", Prompt: "hello", Think: &api.ThinkValue{Value: false}, Stream: &stream})
	var response api.GenerateResponse
	if err := json.Unmarshal(w.Body.Bytes(), &response); err != nil {
		t.Fatal(err)
	}
	if w.Code != 200 || response.Thinking != "" || response.Response != runner.CompletionResponse.Content {
		t.Fatalf("disabled response=%#v status=%d", response, w.Code)
	}
}
