"""Generate traffic: run scripted scenarios headlessly (one session per scenario, one graph call per turn).

Examples:
  python scripts/run_scenarios.py                                    # healthy batch, all scenarios
  python scripts/run_scenarios.py --fail INJECT_ALLERGEN_MISS INJECT_CONSTRAINT_DRIFT
  python scripts/run_scenarios.py --only sc_tonight_tired --now "Tue 5:45pm" --prompt-version v2
  python scripts/run_scenarios.py --list
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import FAILURE_FLAGS, NOW_OVERRIDE, PROMPT_VERSIONS, RUNS_DIR, Settings  # noqa: E402
from graph import get_graph, invoke_turn, new_session_id  # noqa: E402
from tracing import setup_tracing, trace_context  # noqa: E402

SCENARIOS = Path(__file__).resolve().parent.parent / "scenarios" / "scenarios.json"


def run_scenario(graph, scenario, failures, prompt_version, now_override):
    session_id = new_session_id()
    # Scenarios always run at a simulated time (the app itself uses the real clock).
    simulated_now = now_override or scenario.get("now") or NOW_OVERRIDE or "Wed 4:30pm"
    settings = Settings.build(now=simulated_now, prompt_version=prompt_version,
                              failures=failures, scenario_id=scenario["id"])
    lines = []
    for turn in scenario["turns"]:
        metadata = {"prompt_version": settings.prompt_version, "injected_failures": sorted(settings.failures),
                    "scenario_id": scenario["id"], "detected_intent": None}
        with trace_context(session_id, scenario.get("persona"), metadata):
            state, record = invoke_turn(graph, session_id, turn["user"], settings)
            metadata["detected_intent"] = record["detected_intent"]
        expected = turn.get("expected_intent")
        ok = record["detected_intent"] in (expected if isinstance(expected, list) else [expected])
        lines.append(f"  [{'ok' if ok else 'XX'}] t{record['turn_index']} {record['detected_intent']:<26} "
                     f"{' > '.join(record['agent_path'][2:-1]) or '-'}" + (f"  ERROR {record['error']}" if record["error"] else ""))
    return scenario["id"], lines


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fail", nargs="*", default=[], choices=list(FAILURE_FLAGS), metavar="FLAG",
                    help="failure flags to inject: " + ", ".join(FAILURE_FLAGS))
    ap.add_argument("--all-failures", action="store_true", help="inject every failure flag")
    ap.add_argument("--prompt-version", default="v1", choices=PROMPT_VERSIONS)
    ap.add_argument("--now", help="override every scenario's simulated time, e.g. 'Thu 8:15pm'")
    ap.add_argument("--only", nargs="*", help="scenario ids to run")
    ap.add_argument("--workers", type=int, default=4, help="scenarios to run in parallel")
    ap.add_argument("--clear-runs", action="store_true", help=f"delete existing records in {RUNS_DIR} first")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    scenarios = json.loads(SCENARIOS.read_text())
    if args.list:
        for s in scenarios:
            print(f"{s['id']:<26} {len(s['turns'])} turns  {s['description']}")
        return
    if args.only:
        scenarios = [s for s in scenarios if s["id"] in args.only]
    failures = list(FAILURE_FLAGS) if args.all_failures else args.fail
    if args.clear_runs and RUNS_DIR.exists():
        for p in RUNS_DIR.glob("*.json"):
            p.unlink()

    setup_tracing()
    graph = get_graph()
    print(f"Running {len(scenarios)} scenarios | prompt {args.prompt_version} | failures: {failures or 'none (healthy)'}")
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_scenario, graph, s, failures, args.prompt_version, args.now) for s in scenarios]
        for f in futures:
            sid, lines = f.result()
            print(sid)
            print("\n".join(lines))
    print(f"Done in {time.time() - t0:.0f}s. Debug records in {RUNS_DIR}/ - view the traces in Arize AX once tracing.py is filled in.")


if __name__ == "__main__":
    main()
