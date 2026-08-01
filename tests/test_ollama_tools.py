"""Ollama tool calling — the translation, which is the part that can be wrong quietly.

`stream_turn` itself needs a live Ollama, so it is not tested here. What *is*
tested is `_to_ollama`, and that is the right boundary: the network call is one
line of SDK usage, while the message translation is where a mistake produces a
turn Ollama accepts and answers wrongly.

The one that would cost a day: Ollama pairs a tool result to its call by
**name**, Anthropic by **id**. The neutral `ToolOutcome` carries only the id,
because that is what the SSE trace needs to match a `tool_result` frame to its
`tool_call`. So the name has to be recovered from the assistant turn that asked,
and if that lookup silently produced "unknown" the model would receive a result
labelled as coming from a tool it never called — and would most likely ignore it
and answer from its own knowledge, with a full trace panel and a wrong answer.
"""

from typing import Any

from app.services.providers.base import (
    AgentMessage,
    ToolOutcome,
    ToolRequest,
    ToolSpec,
)
from app.services.providers.ollama_provider import (
    OllamaChatProvider,
    _to_ollama,  # pyright: ignore[reportPrivateUsage]
    _to_ollama_tool,  # pyright: ignore[reportPrivateUsage]
    forget_model,
)

SEARCH = ToolSpec(
    name="search_documents",
    description="Semantic search over the learner's material.",
    input_schema={
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
)


def test_a_tool_spec_becomes_an_ollama_function_tool() -> None:
    tool = _to_ollama_tool(SEARCH)
    assert tool["type"] == "function"
    assert tool["function"]["name"] == "search_documents"
    # The JSON Schema travels as `parameters`, unchanged — it is the same schema
    # `GET /mcp/tools` shows, so a model and a human read one description.
    assert tool["function"]["parameters"] == SEARCH.input_schema


def test_the_system_prompt_leads_the_message_list() -> None:
    messages = _to_ollama("be helpful", [AgentMessage(role="user", text="hi")])
    assert messages[0] == {"role": "system", "content": "be helpful"}
    assert messages[1] == {"role": "user", "content": "hi"}


def test_a_tool_result_is_labelled_with_the_name_it_answers() -> None:
    """The id→name recovery. This is the test the module exists for."""
    call = ToolRequest(id="ollama_abc123", name="search_documents", input={"query": "x"})
    messages = _to_ollama(
        "system",
        [
            AgentMessage(role="user", text="what did I learn?"),
            AgentMessage(role="assistant", text="let me look", tool_requests=[call]),
            AgentMessage(
                role="user",
                tool_results=[ToolOutcome(id="ollama_abc123", content="1 match", ok=True)],
            ),
        ],
    )

    assistant = messages[2]
    assert assistant["role"] == "assistant"
    assert assistant["tool_calls"] == [
        {"function": {"name": "search_documents", "arguments": {"query": "x"}}}
    ]

    result = messages[3]
    assert result["role"] == "tool"
    # Not "unknown" — the whole point.
    assert result["tool_name"] == "search_documents"
    assert result["content"] == "1 match"


def test_several_results_in_one_turn_keep_their_own_names() -> None:
    """A model may ask for two tools at once, and each answer must find its own call."""
    calls = [
        ToolRequest(id="a", name="search_documents", input={"query": "x"}),
        ToolRequest(id="b", name="tutor_stats", input={}),
    ]
    messages = _to_ollama(
        "system",
        [
            AgentMessage(role="user", text="q"),
            AgentMessage(role="assistant", tool_requests=calls),
            AgentMessage(
                role="user",
                tool_results=[
                    ToolOutcome(id="b", content="3 lessons", ok=True),
                    ToolOutcome(id="a", content="1 match", ok=True),
                ],
            ),
        ],
    )
    tool_messages = [m for m in messages if m["role"] == "tool"]
    # Order follows the results, and each carries the name of the call it answers
    # rather than the position it arrived in.
    assert [(m["tool_name"], m["content"]) for m in tool_messages] == [
        ("tutor_stats", "3 lessons"),
        ("search_documents", "1 match"),
    ]


def test_an_assistant_turn_that_only_called_tools_still_carries_content() -> None:
    """Ollama wants the key present even when the model said nothing first."""
    messages = _to_ollama(
        "system",
        [
            AgentMessage(role="user", text="q"),
            AgentMessage(
                role="assistant",
                tool_requests=[ToolRequest(id="a", name="tutor_stats", input={})],
            ),
        ],
    )
    assistant = messages[-1]
    assert assistant["content"] == ""
    assert "tool_calls" in assistant


def test_a_failed_tool_still_reaches_the_model() -> None:
    """A failure is a result the model can recover from, not an error for the user.

    Ollama has no `is_error` flag, so the text is the whole signal — which is why
    `UnknownToolError`'s message names every tool that does exist.
    """
    messages = _to_ollama(
        "system",
        [
            AgentMessage(role="user", text="q"),
            AgentMessage(
                role="assistant",
                tool_requests=[ToolRequest(id="a", name="serch_docs", input={})],
            ),
            AgentMessage(
                role="user",
                tool_results=[
                    ToolOutcome(id="a", content="No tool 'serch_docs'.", ok=False)
                ],
            ),
        ],
    )
    assert messages[-1]["content"] == "No tool 'serch_docs'."


async def test_capability_is_measured_and_cached(monkeypatch: Any) -> None:
    """`supports_tools` believes Ollama's own answer, and asks once per model."""

    class Shown:
        def __init__(self, capabilities: list[str]) -> None:
            self.capabilities = capabilities

    calls: list[str] = []

    class FakeClient:
        async def show(self, name: str) -> Shown:
            calls.append(name)
            return Shown(["completion", "tools"] if name == "llama3.1" else ["completion"])

    monkeypatch.setattr(
        "app.services.providers.ollama_provider.get_client", lambda: FakeClient()
    )
    forget_model("llama3.1")
    forget_model("gemma3:1b")

    provider = OllamaChatProvider()
    assert await provider.supports_tools("llama3.1") is True
    assert await provider.supports_tools("gemma3:1b") is False
    # Asked once each; the second read comes from the cache.
    assert await provider.supports_tools("llama3.1") is True
    assert calls == ["llama3.1", "gemma3:1b"]

    forget_model("llama3.1")
    forget_model("gemma3:1b")


async def test_an_unreachable_ollama_is_not_a_tool_capability(monkeypatch: Any) -> None:
    """"Cannot confirm" and "cannot do it" lead to the same honest answer here.

    The caller is deciding whether to *offer* the agent. Raising would turn a
    capability question into an outage report at the wrong moment; the real
    outage surfaces on the next call, with a message about the server.
    """

    class DeadClient:
        async def show(self, name: str) -> None:
            raise ConnectionError("connection refused")

    monkeypatch.setattr(
        "app.services.providers.ollama_provider.get_client", lambda: DeadClient()
    )
    forget_model("llama3.1")

    assert await OllamaChatProvider().supports_tools("llama3.1") is False
    # And nothing false was cached, so it is asked again once Ollama is back.
    assert await OllamaChatProvider().supports_tools("llama3.1") is False
