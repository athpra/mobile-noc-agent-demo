"""Chat model for the agent: a Cloudera AI Inference (OpenAI-compatible) endpoint."""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from src.config import Settings, get_api_key


def build_chat_model(settings: Settings) -> ChatOpenAI:
    # Built per agent run rather than cached, so each run picks up the
    # current workload JWT (it rotates inside Cloudera AI Workbench).
    return ChatOpenAI(
        base_url=settings.caii_base_url,
        model=settings.caii_model_name,
        api_key=get_api_key(),
        temperature=settings.llm_temperature,
        timeout=120,
        max_retries=2,
    )
