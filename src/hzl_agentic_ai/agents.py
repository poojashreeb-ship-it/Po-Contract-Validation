"""Builds the LangGraph runner for the four agentic steps, from config/agents.yaml.

Each step is invoked independently by the RPA shell (UiPath decides the
calling order and what happens between calls — see api.py), so this is a
single-node graph reused for all four steps rather than a multi-step
workflow with cross-step state. The graph structure is fixed; only the
system prompt (role/goal/backstory from agents.yaml) and the structured
output schema vary per call.
"""
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, TypedDict

import yaml
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from pydantic import BaseModel

load_dotenv()

_CONFIG_PATH = Path(__file__).parent / "config" / "agents.yaml"


@lru_cache
def _agents_config() -> dict:
    return yaml.safe_load(_CONFIG_PATH.read_text())


def _agent_system_prompt(agent_key: str) -> str:
    cfg = _agents_config()[agent_key]
    return (
        f"Role: {cfg['role'].strip()}\n\n"
        f"Goal: {cfg['goal'].strip()}\n\n"
        f"Backstory: {cfg['backstory'].strip()}"
    )


@lru_cache
def _llm() -> ChatOpenAI:
    # MODEL is an OpenRouter-style "openrouter/vendor/model" string (see
    # README setup); ChatOpenAI just wants the vendor/model part, with
    # OpenRouter's OpenAI-compatible endpoint as the base URL.
    model = os.environ["MODEL"].removeprefix("openrouter/")
    return ChatOpenAI(
        model=model,
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
    )


class _PromptState(TypedDict):
    system_prompt: str
    user_prompt: str
    response_format: type[BaseModel]
    result: Any


def _run_llm(state: _PromptState) -> _PromptState:
    structured_llm = _llm().with_structured_output(
        state["response_format"], method="json_schema"
    )
    result = structured_llm.invoke(
        [
            ("system", state["system_prompt"]),
            ("human", state["user_prompt"]),
        ]
    )
    return {**state, "result": result}


@lru_cache
def _structured_output_graph():
    graph = StateGraph(_PromptState)
    graph.add_node("run_llm", _run_llm)
    graph.set_entry_point("run_llm")
    graph.add_edge("run_llm", END)
    return graph.compile()


async def run_structured_agent(
    agent_key: str, user_prompt: str, response_format: type[BaseModel]
) -> BaseModel:
    """Run one of the four agentic-step agents (see config/agents.yaml) and
    return its output parsed into `response_format`."""
    output = await _structured_output_graph().ainvoke(
        {
            "system_prompt": _agent_system_prompt(agent_key),
            "user_prompt": user_prompt,
            "response_format": response_format,
        }
    )
    return output["result"]
