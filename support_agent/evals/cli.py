"""``agent-eval``: run the scenario suite and print pass rates."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

from support_agent.config import PROJECT_ROOT, Settings
from support_agent.evals.runner import (
    guardrail_table,
    load_scenarios,
    run_all,
    summary_table,
    transcripts,
)

DEFAULT_SCENARIOS = PROJECT_ROOT / "evals" / "scenarios.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-eval", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run scenarios and print a pass-rate table")
    run.add_argument("--scenarios", default=str(DEFAULT_SCENARIOS))
    run.add_argument("--category", action="append", help="only these categories (repeatable)")
    run.add_argument("--id", action="append", dest="ids", help="only these scenario ids")
    run.add_argument("--transcripts", help="write full transcripts + traces as JSON")
    run.add_argument("--verbose", "-v", action="store_true", help="print every turn")
    run.add_argument(
        "--disable",
        action="append",
        choices=["input_injection", "tool_output"],
        default=[],
        help="switch off a soft guardrail for an ablation run (repeatable)",
    )
    args = parser.parse_args(argv)

    settings = Settings()
    if args.disable:
        settings = settings.model_copy(update={f"guard_{g}": False for g in args.disable})
    scenarios = load_scenarios(args.scenarios)
    if args.category:
        scenarios = [s for s in scenarios if s["category"] in args.category]
    if args.ids:
        scenarios = [s for s in scenarios if s["id"] in args.ids]
    if not scenarios:
        print("no scenarios selected", file=sys.stderr)
        return 2

    results = run_all(scenarios, settings)
    latencies = [t.latency_ms for r in results for t in r.turns]
    disabled = f" · disabled: {', '.join(args.disable)}" if args.disable else ""
    print(
        f"model: {settings.llm_provider}{disabled} · scenarios: {len(results)} · "
        f"turns: {len(latencies)} · median turn latency: {statistics.median(latencies):.1f} ms\n"
    )
    print(summary_table(results))
    print()
    print(guardrail_table(results))
    failed = [r for r in results if not r.passed]
    if failed:
        print(f"\nFailures ({len(failed)}):")
        for r in failed:
            print(f"  {r.id} [{r.category}]")
            for f in r.failures:
                print(f"    - {f}")
    if args.verbose:
        for r in results:
            print(f"\n## {r.id} ({'pass' if r.passed else 'FAIL'})")
            for t in r.turns:
                tools = [s["name"] for s in t.trace if s["type"] == "tool"]
                print(f"  > {t.user}\n  < {t.reply}\n    tools={tools} state={t.state}")
    if args.transcripts:
        Path(args.transcripts).parent.mkdir(parents=True, exist_ok=True)
        Path(args.transcripts).write_text(
            json.dumps(transcripts(results), ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"\nwrote {args.transcripts}")
    return 0 if not failed else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
