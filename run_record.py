"""Run records: a lightweight local debug summary of every graph invocation.

Used for the UI debug strip (agent path, tool/LLM counts) and saved to runs/ for quick inspection.
Real observability comes from the Arize instrumentation added in tracing.py.

RunRecorder is a LangChain callback handler. It captures, in order:
  node_events (graph nodes), tool_calls, llm_calls (model, latency, tokens)
and attributes each tool/LLM call to the graph node it ran inside (via parent run ids).
"""
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage

from config import RUNS_DIR, Settings

NODE_NAMES = ["profile_updater", "orchestrator", "meal_advisor", "food_qa", "intake_agent",
              "meal_planner", "recipe_lookup", "constraint_checker", "grocery_agent", "response_composer"]


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _summary(obj: Any, limit: int = 300) -> str:
    content = getattr(obj, "content", obj)
    s = content if isinstance(content, str) else json.dumps(content, default=str)
    return s if len(s) <= limit else s[:limit] + "..."


class RunRecorder(BaseCallbackHandler):
    def __init__(self) -> None:
        self.node_events: List[Dict[str, Any]] = []
        self.tool_calls: List[Dict[str, Any]] = []
        self.llm_calls: List[Dict[str, Any]] = []
        self._parent: Dict[UUID, Optional[UUID]] = {}
        self._node_of_run: Dict[UUID, str] = {}
        self._open: Dict[UUID, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    # -------------------------------------------------------------- attribution helpers
    def _node_for(self, run_id: Optional[UUID]) -> Optional[str]:
        while run_id is not None:
            if run_id in self._node_of_run:
                return self._node_of_run[run_id]
            run_id = self._parent.get(run_id)
        return None

    # -------------------------------------------------------------- graph nodes
    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, metadata=None, **kw):
        name = kw.get("name") or (serialized or {}).get("name")
        with self._lock:
            self._parent[run_id] = parent_run_id
            is_node = name in NODE_NAMES and (metadata or {}).get("langgraph_node") == name
            if is_node and self._node_for(parent_run_id) != name:  # skip the inner wrapper of the same node
                event = {"node": name, "started_at": _iso(), "ended_at": None, "status": "running"}
                self.node_events.append(event)
                self._open[run_id] = event
                self._node_of_run[run_id] = name

    def on_chain_end(self, outputs, *, run_id, **kw):
        with self._lock:
            event = self._open.pop(run_id, None)
            if event:
                event.update(ended_at=_iso(), status="ok")

    def on_chain_error(self, error, *, run_id, **kw):
        with self._lock:
            event = self._open.pop(run_id, None)
            if event:
                event.update(ended_at=_iso(), status=f"error: {type(error).__name__}: {error}"[:300])

    # -------------------------------------------------------------- tools
    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, inputs=None, **kw):
        with self._lock:
            self._parent[run_id] = parent_run_id
            call = {"node": self._node_for(parent_run_id), "tool": kw.get("name") or (serialized or {}).get("name"),
                    "args": inputs if inputs is not None else input_str, "result_summary": None}
            self.tool_calls.append(call)
            self._open[run_id] = call

    def on_tool_end(self, output, *, run_id, **kw):
        with self._lock:
            call = self._open.pop(run_id, None)
            if call:
                call["result_summary"] = _summary(output)

    def on_tool_error(self, error, *, run_id, **kw):
        with self._lock:
            call = self._open.pop(run_id, None)
            if call:
                call["result_summary"] = f"ERROR: {error}"

    # -------------------------------------------------------------- LLMs
    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, metadata=None, **kw):
        md = metadata or {}
        with self._lock:
            self._parent[run_id] = parent_run_id
            run_name = f"{md['agent']}.{md['step']}" if md.get("agent") and md.get("step") else kw.get("name")
            call = {"node": self._node_for(parent_run_id), "run_name": run_name,
                    "model": md.get("ls_model_name") or (kw.get("invocation_params") or {}).get("model"),
                    "prompt_version": md.get("prompt_version"), "latency_ms": None, "tokens": None,
                    "_t0": time.perf_counter()}
            self.llm_calls.append(call)
            self._open[run_id] = call

    def on_llm_end(self, response, *, run_id, **kw):
        with self._lock:
            call = self._open.pop(run_id, None)
            if not call:
                return
            call["latency_ms"] = int((time.perf_counter() - call.pop("_t0")) * 1000)
            usage = (response.llm_output or {}).get("token_usage")
            if not usage and response.generations and response.generations[0]:
                msg = getattr(response.generations[0][0], "message", None)
                usage = getattr(msg, "usage_metadata", None)
            if usage:
                call["tokens"] = {"prompt": usage.get("prompt_tokens", usage.get("input_tokens")),
                                  "completion": usage.get("completion_tokens", usage.get("output_tokens")),
                                  "total": usage.get("total_tokens")}

    def on_llm_error(self, error, *, run_id, **kw):
        with self._lock:
            call = self._open.pop(run_id, None)
            if call:
                call.pop("_t0", None)
                call["error"] = str(error)[:300]


# --------------------------------------------------------------------------- records
FINAL_STATE_KEYS = ["profile", "session_context", "active_task", "week_outline", "current_plan", "shopping_list",
                    "tonight_recommendation",
                    # per-turn extras (handy when debugging)
                    "routing", "advisor_step", "constraint_check", "food_answer", "recipe_details", "intake",
                    "retries", "plan_changes", "final_response"]


def _messages(state: Dict[str, Any]) -> List[Dict[str, str]]:
    out = []
    for m in state.get("messages", []):
        role = "user" if isinstance(m, HumanMessage) else "assistant" if isinstance(m, AIMessage) else m.type
        out.append({"role": role, "content": m.content})
    return out


def build_record(recorder: RunRecorder, state: Dict[str, Any], *, session_id: str, turn_index: int,
                 settings: Settings, user_message: str, error: Optional[str] = None) -> Dict[str, Any]:
    plan = state.get("current_plan")
    final = {k: state.get(k) for k in FINAL_STATE_KEYS}
    final["plan"] = final.pop("current_plan")
    # drop internal timers
    llm_calls = [{k: v for k, v in c.items() if not k.startswith("_")} for c in recorder.llm_calls]
    return {
        "run_id": uuid.uuid4().hex[:12],
        "session_id": session_id,
        "turn_index": turn_index,
        "scenario_id": settings.scenario_id,
        "prompt_version": settings.prompt_version,
        "injected_failures": sorted(settings.failures),
        "now": settings.now.isoformat(),
        "recorded_at": _iso(),
        "user_message": user_message,
        "detected_intent": state.get("detected_intent"),
        "agent_path": [e["node"] for e in recorder.node_events],
        "messages": _messages(state),
        "final_state": final,
        "node_events": recorder.node_events,
        "tool_calls": recorder.tool_calls,
        "llm_calls": llm_calls,
        "error": error,
        "has_plan": bool(plan),
    }


def save_record(record: Dict[str, Any], runs_dir: Path = RUNS_DIR) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"{record['session_id']}_t{record['turn_index']:02d}_{record['run_id']}.json"
    path.write_text(json.dumps(record, indent=2, default=str))
    return path
