package llm

import (
	"reflect"
	"testing"

	"github.com/ollama/ollama/api"
)

// Characterizes the existing native transport that the IFM capability gate now
// reaches. Removing an effort or coercing a named value to a boolean breaks this.
func TestARAIFMNativeTemplateKwargs(t *testing.T) {
	for _, tc := range []struct {
		name  string
		value any
		want  map[string]any
	}{
		{"unset", nil, nil},
		{"disabled", false, map[string]any{"enable_thinking": false}},
		{"enabled retains high template default", true, map[string]any{"enable_thinking": true}},
		{"low", "low", map[string]any{"enable_thinking": true, "reasoning_effort": "low"}},
		{"medium", "medium", map[string]any{"enable_thinking": true, "reasoning_effort": "medium"}},
		{"high", "high", map[string]any{"enable_thinking": true, "reasoning_effort": "high"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var think *api.ThinkValue
			if tc.value != nil {
				think = &api.ThinkValue{Value: tc.value}
			}
			runner := llamaServerRunner{}
			body, err := runner.llamaServerChatRequest(ChatRequest{Messages: []api.Message{{Role: "user", Content: "hello"}}, Think: think}, false)
			if err != nil {
				t.Fatal(err)
			}
			kwargs, _ := body["chat_template_kwargs"].(map[string]any)
			if !reflect.DeepEqual(kwargs, tc.want) {
				t.Fatalf("template kwargs=%#v, want=%#v", kwargs, tc.want)
			}
		})
	}
}
