"""Recovery of tool calls that an endpoint returns as text."""

from __future__ import annotations

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from src.llm import _TextToolCallChatOpenAI, parse_text_tool_calls


def test_function_form_without_parameters():
    calls, rest = parse_text_tool_calls("<tool_call> <function=get_network_summary> </function> </tool_call>")
    assert [(c["name"], c["args"]) for c in calls] == [("get_network_summary", {})]
    assert rest == ""


def test_function_form_with_parameters():
    text = (
        "Checking the cell.\n<tool_call>\n<function=get_kpis>\n"
        "<parameter=cell_id>\nGNB1042-C1\n</parameter>\n<parameter=last_n_rops>\n4\n</parameter>\n"
        "</function>\n</tool_call>"
    )
    calls, rest = parse_text_tool_calls(text)
    assert calls[0]["name"] == "get_kpis"
    assert calls[0]["args"] == {"cell_id": "GNB1042-C1", "last_n_rops": 4}
    assert rest == "Checking the cell."


def test_json_form():
    calls, _ = parse_text_tool_calls('<tool_call>{"name": "get_neighbors", "arguments": {"cell_id": "A", "hops": 2}}</tool_call>')
    assert calls[0]["name"] == "get_neighbors" and calls[0]["args"] == {"cell_id": "A", "hops": 2}


def test_ignores_calls_inside_reasoning_and_plain_text():
    calls, rest = parse_text_tool_calls("<think>maybe <tool_call><function=x></function></tool_call></think>Done.")
    assert calls == [] and "Done." in rest
    assert parse_text_tool_calls("No tools needed.") == ([], "No tools needed.")


def test_model_turns_text_into_tool_calls():
    model = _TextToolCallChatOpenAI(base_url="http://unused/v1", model="m", api_key="k")
    result = ChatResult(generations=[ChatGeneration(
        message=AIMessage(content="<tool_call><function=get_alarms></function></tool_call>"))])
    msg = model._recover(result).generations[0].message
    assert msg.tool_calls[0]["name"] == "get_alarms" and msg.content == ""


def test_strip_reasoning_handles_unclosed_think():
    from src.agent import strip_reasoning

    assert strip_reasoning("<think>a</think>\nAnswer") == "Answer"
    assert strip_reasoning("a</think>Answer") == "Answer"
    assert strip_reasoning("<think>ran out of tokens while reaso") == ""
