"""Shared helpers for agents: model factory, stable run names/tags, tool loop, state views.

Every LLM/tool call is made with a stable `run_name` ("<agent>.<step>") and tags
["agent:<agent>", "prompt:<version>"] so traces (and our run records) are easy to read.
"""
import json
from typing import Any, Dict, List, Optional, Sequence, Type, TypeVar

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from config import Settings, model_for

T = TypeVar("T", bound=BaseModel)


# --------------------------------------------------------------------------- LLM plumbing
def chat_model(agent: str) -> ChatOpenAI:
    return ChatOpenAI(model=model_for(agent), temperature=0, max_retries=2, timeout=60)


def call_config(agent: str, step: str, settings: Settings) -> Dict[str, Any]:
    return {"run_name": f"{agent}.{step}",
            "tags": [f"agent:{agent}", f"prompt:{settings.prompt_version}"],
            "metadata": {"agent": agent, "step": step, "prompt_version": settings.prompt_version}}


def structured(agent: str, step: str, schema: Type[T], messages: Sequence[BaseMessage], settings: Settings) -> T:
    """One structured-output LLM call (Pydantic in, Pydantic out)."""
    llm = chat_model(agent).with_structured_output(schema, method="function_calling")
    return llm.invoke(list(messages), config=call_config(agent, step, settings))


def text(agent: str, step: str, messages: Sequence[BaseMessage], settings: Settings) -> str:
    return chat_model(agent).invoke(list(messages), config=call_config(agent, step, settings)).content


def run_tool(tool: BaseTool, args: Dict[str, Any], config: RunnableConfig) -> Any:
    """Invoke a tool from code (deterministic context gathering). Shows up as a tool call."""
    return tool.invoke(args, config=config)


def tool_loop(agent: str, step: str, tools: List[BaseTool], messages: List[BaseMessage],
              settings: Settings, config: RunnableConfig, max_rounds: int = 4) -> List[BaseMessage]:
    """Let the model call tools (ReAct-style) for up to `max_rounds`; returns the transcript."""
    llm = chat_model(agent).bind_tools(tools)
    by_name = {t.name: t for t in tools}
    convo = list(messages)
    for i in range(max_rounds):
        ai: AIMessage = llm.invoke(convo, config=call_config(agent, f"{step}.round{i + 1}", settings))
        convo.append(ai)
        if not ai.tool_calls:
            break
        for tc in ai.tool_calls:
            tool = by_name.get(tc["name"])
            result = tool.invoke(tc["args"], config=config) if tool else {"error": f"unknown tool {tc['name']}"}
            convo.append(ToolMessage(content=dumps(result), tool_call_id=tc["id"], name=tc["name"]))
    return convo


def pick_prompt(prompts: Dict[str, str], settings: Settings) -> str:
    return prompts.get(settings.prompt_version, prompts["v1"])


# --------------------------------------------------------------------------- state views
def dumps(obj: Any) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False)


def last_user_message(state: Dict[str, Any]) -> str:
    for m in reversed(state.get("messages", [])):
        if isinstance(m, HumanMessage):
            return m.content
    return ""


def last_assistant_message(state: Dict[str, Any]) -> str:
    msgs = state.get("messages", [])
    for m in reversed(msgs[:-1] if msgs and isinstance(msgs[-1], HumanMessage) else msgs):
        if isinstance(m, AIMessage):
            return m.content
    return ""


def recent_transcript(state: Dict[str, Any], n: int = 6) -> str:
    lines = []
    for m in state.get("messages", [])[-n:]:
        role = "User" if isinstance(m, HumanMessage) else "Dnner"
        lines.append(f"{role}: {m.content}")
    return "\n".join(lines)


def values(fields: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """{field: {'value':..}} -> {field: value} (drops unknowns)."""
    return {k: v["value"] for k, v in (fields or {}).items() if v and v.get("value") is not None}


def profile_view(state: Dict[str, Any], include_dietary: bool = True) -> Dict[str, Any]:
    p = values(state.get("profile"))
    if not include_dietary:
        p = {k: v for k, v in p.items() if k not in ("allergies", "diet")}
    return p


def dietary_known(state: Dict[str, Any]) -> bool:
    """Allergies AND diet are known (an empty list counts: 'no allergies' is an answer)."""
    p = state.get("profile") or {}
    return all(p.get(k) and p[k].get("value") is not None for k in ("allergies", "diet"))


def system(text_: str) -> SystemMessage:
    return SystemMessage(content=text_.strip())


def human(text_: str) -> HumanMessage:
    return HumanMessage(content=text_.strip())
