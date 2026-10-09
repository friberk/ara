package server

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"

	"github.com/ollama/ollama/api"
	thinkingparser "github.com/ollama/ollama/thinking"
	"github.com/ollama/ollama/types/model"
)

// This is the complete GGUF Jinja template shared by the retained IFM 7B and
// 3.7B artifacts. An architecture name or a think-tag substring alone is not a
// serving contract. Custom/rendered templates retain their existing behavior.
const araIFMTemplateSHA256 = "f6e3cd6dbf0f95016fff531f41f921dee541025733c14580a881cf5a5f9fa750"

func (m *Model) nativeIFMThinking() *model.Thinking {
	if m == nil || m.Config.RemoteHost != "" || !m.isGGUF() || m.ModelPath == "" ||
		!m.HasChatTemplate || usesOllamaRenderedChat(m) || m.metadata.String("general.architecture") != "k2-horizon" {
		return nil
	}
	tmpl := m.metadata.String("tokenizer.chat_template")
	if fmt.Sprintf("%x", sha256.Sum256([]byte(tmpl))) != araIFMTemplateSHA256 {
		return nil
	}
	return &model.Thinking{Values: []any{false, true, "low", "medium", "high"}, Default: "high"}
}

// Exact IFM efforts must never silently become the default. Unlike the generic
// renderer compatibility fallback, an unknown name is a request error.
func (m *Model) validateNativeIFMThinking(think *api.ThinkValue) error {
	contract := m.nativeIFMThinking()
	if contract == nil || think == nil || contract.Supports(think.Value) {
		return nil
	}
	values, _ := json.Marshal(contract.Values)
	return fmt.Errorf("unsupported think value %v; supported values: %s", think.Value, values)
}

// /api/generate applies Jinja then uses raw completion. Its parser and grammar
// transition must use the closing tag selected by that same template effort.
func (m *Model) thinkingTags(think *api.ThinkValue) (string, string) {
	if m.nativeIFMThinking() != nil {
		tag := "ifm|think"
		if think != nil && think.Bool() {
			switch think.Value {
			case "medium":
				tag = "ifm|think_fast"
			case "low":
				tag = "ifm|think_faster"
			}
		}
		return "<" + tag + ">", "</" + tag + ">"
	}
	return thinkingparser.InferTags(m.Template.Template)
}
