"""Chat model for the agent: a Cloudera AI Inference (OpenAI-compatible) endpoint."""

from __future__ import annotations

import json
import re
import uuid

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult
from langchain_openai import ChatOpenAI

from src.config import Settings, get_api_key

_TOOL_CALL_RE = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
_FUNCTION_RE = re.compile(r"<function=([^>\s]+)>(.*?)</function>", re.DOTALL)
_PARAMETER_RE = re.compile(r"<parameter=([^>\s]+)>(.*?)</parameter>", re.DOTALL)


def _parse_value(raw: str):
    raw = raw.strip()
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def parse_text_tool_calls(text: str) -> tuple[list[dict], str]:
    """Tool calls the model wrote as text instead of returning structured ones.

    An endpoint deployed without a tool-call parser passes the model's raw
    output through, e.g. Nemotron's
    <tool_call><function=name><parameter=k>v</parameter></function></tool_call>
    or the JSON form <tool_call>{"name": ..., "arguments": {...}}</tool_call>.
    Returns (tool_calls, text with those blocks removed).
    """
    # Only look after the reasoning: a <think> block may mention a tool call
    # the model then decided against.
    head, sep, tail = text.rpartition("</think>")
    calls = []
    for block in _TOOL_CALL_RE.findall(tail):
        fn = _FUNCTION_RE.search(block)
        if fn:
            args = {k: _parse_value(v) for k, v in _PARAMETER_RE.findall(fn.group(2))}
            calls.append({"name": fn.group(1), "args": args})
            continue
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("name"):
            args = data.get("arguments", data.get("parameters", {}))
            if isinstance(args, str):
                args = _parse_value(args)
            calls.append({"name": data["name"], "args": args if isinstance(args, dict) else {}})
    for call in calls:
        call["id"] = f"call_{uuid.uuid4().hex[:24]}"
        call["type"] = "tool_call"
    return calls, (head + sep + _TOOL_CALL_RE.sub("", tail)).strip() if calls else text


class _TextToolCallChatOpenAI(ChatOpenAI):
    """ChatOpenAI that recovers tool calls written as text, so the agent still
    works against an endpoint whose tool-call parser is not enabled."""

    def _recover(self, result: ChatResult) -> ChatResult:
        for gen in result.generations:
            msg = gen.message
            if isinstance(msg, AIMessage) and not msg.tool_calls and isinstance(msg.content, str):
                calls, rest = parse_text_tool_calls(msg.content)
                if calls:
                    gen.message = msg.model_copy(update={"content": rest, "tool_calls": calls})
        return result

    def _generate(self, *args, **kwargs) -> ChatResult:
        return self._recover(super()._generate(*args, **kwargs))

    async def _agenerate(self, *args, **kwargs) -> ChatResult:
        return self._recover(await super()._agenerate(*args, **kwargs))


def build_chat_model(settings: Settings) -> ChatOpenAI:
    # Built per agent run rather than cached, so each run picks up the
    # current workload JWT (it rotates inside Cloudera AI Workbench).
    return _TextToolCallChatOpenAI(
        base_url=settings.caii_base_url,
        model=settings.caii_model_name,
        api_key=get_api_key(),
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout=120,
        max_retries=2,
    )
