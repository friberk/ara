#include "chat.h"

#include <algorithm>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>

static void require(bool condition, const std::string & message) {
    if (!condition) throw std::runtime_error(message);
}

static void check_stream(const common_chat_params & params, const std::string & generated,
                         const std::string & reasoning, const std::string & answer) {
    common_peg_arena arena;
    arena.load(params.parser);
    common_chat_parser_params parser(params);
    common_chat_msg previous;
    std::string accumulated_reasoning, accumulated_answer;
    for (size_t i = 1; i <= generated.size(); ++i) {
        auto message = common_chat_peg_parse(arena, generated.substr(0, i), i < generated.size(), parser);
        for (const auto & delta : common_chat_msg_diff::compute_diffs(previous, message)) {
            accumulated_reasoning += delta.reasoning_content_delta;
            accumulated_answer += delta.content_delta;
        }
        previous = message;
    }
    require(accumulated_reasoning == reasoning, "streamed reasoning differs");
    require(accumulated_answer == answer, "streamed answer differs");
}

int main(int argc, char ** argv) {
    require(argc == 2, "expected the retained template fixture path");
    std::ifstream input(argv[1], std::ios::binary);
    require(input.good(), "template fixture is missing");
    std::string source((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
    auto templates = common_chat_templates_init(nullptr, source);
    int failures = 0, cases = 0;
    for (const auto & effort : {std::string("high"), std::string("medium"), std::string("low")}) {
        common_chat_templates_inputs inputs;
        common_chat_msg user;
        user.role = "user";
        user.content = "hello";
        inputs.messages = {user};
        inputs.reasoning_format = COMMON_REASONING_FORMAT_AUTO;
        inputs.chat_template_kwargs["reasoning_effort"] = "\"" + effort + "\"";
        const std::string opening = effort == "medium" ? "<ifm|think_fast>" : effort == "low" ? "<ifm|think_faster>" : "<ifm|think>";
        for (const auto & closing : {"</ifm|think>", "</ifm|think_fast>", "</ifm|think_faster>"}) {
            for (bool structured : {false, true}) {
                ++cases;
                try {
                    inputs.json_schema = structured ? R"({"type":"object","properties":{"answer":{"type":"integer"}},"required":["answer"],"additionalProperties":false})" : "";
                    auto params = common_chat_templates_apply(templates.get(), inputs);
                    require(params.generation_prompt == "<|ifm|im_start|>assistant\n" + opening + "\n", "selected effort prefill changed");
                    require(std::find(params.preserved_tokens.begin(), params.preserved_tokens.end(), closing) != params.preserved_tokens.end(), "legitimate close token would be discarded");
                    if (structured) require(!params.grammar.empty() && !params.grammar_lazy, "schema grammar must be eager");
                    const std::string answer = structured ? "{\"answer\":4}" : "answer";
                    check_stream(params, std::string("private reasoning") + closing + answer, "private reasoning", answer);
                } catch (const std::exception & error) {
                    ++failures;
                    std::cerr << "FAIL " << effort << " / " << closing << " / structured=" << structured << ": " << error.what() << '\n';
                }
            }
        }
        ++cases;
        try {
            inputs.json_schema = "";
            auto params = common_chat_templates_apply(templates.get(), inputs);
            const std::string closing = effort == "medium" ? "</ifm|think_fast>" : effort == "low" ? "</ifm|think_faster>" : "</ifm|think>";
            check_stream(params, "private </ifm|unknown> literal" + closing + "answer", "private </ifm|unknown> literal", "answer");
        } catch (const std::exception & error) {
            ++failures;
            std::cerr << "FAIL " << effort << " / unknown close literal: " << error.what() << '\n';
        }
        ++cases;
        try {
            inputs.json_schema = "";
            inputs.enable_thinking = false;
            inputs.chat_template_kwargs["enable_thinking"] = "false";
            auto params = common_chat_templates_apply(templates.get(), inputs);
            require(params.generation_prompt == "<|ifm|im_start|>assistant\n<ifm|think>\n</ifm|think>\n", "false prefill changed");
            check_stream(params, "answer mentions </ifm|think_fast> literally", "", "answer mentions </ifm|think_fast> literally");
        } catch (const std::exception & error) {
            ++failures;
            std::cerr << "FAIL " << effort << " / disabled: " << error.what() << '\n';
        }
    }
    std::cout << "IFM parser: " << cases << " cases, " << failures << " failures\n";
    return failures ? 1 : 0;
}
