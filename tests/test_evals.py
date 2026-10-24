import pytest

from support_agent.config import PROJECT_ROOT
from support_agent.evals.cli import main
from support_agent.evals.runner import ScenarioError, load_scenarios, run_all, summary_table

SCENARIOS = PROJECT_ROOT / "evals" / "scenarios.yaml"


def test_scenario_file_shape():
    scenarios = load_scenarios(SCENARIOS)
    assert len(scenarios) >= 40
    assert {"happy_path", "policy_edge", "injection", "cross_customer", "handoff"} <= {
        s["category"] for s in scenarios
    }


def test_full_suite_passes_with_the_offline_model(settings):
    results = run_all(load_scenarios(SCENARIOS), settings)
    failed = {r.id: r.failures for r in results if not r.passed}
    assert failed == {}
    assert "| **total** |" in summary_table(results)


def test_loader_rejects_unknown_expectations(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "- {id: a, category: x, customer: C001, turns: [{user: hi, expect: {toolz: []}}]}\n"
    )
    with pytest.raises(ScenarioError, match="toolz"):
        load_scenarios(bad)
    bad.write_text("- {id: a, category: x, customer: C001, turns: []}\n" * 2)
    with pytest.raises(ScenarioError, match="duplicate"):
        load_scenarios(bad)


def test_cli_ablation_shows_injection_failures(capsys, tmp_path):
    out = tmp_path / "t.json"
    assert (
        main(
            [
                "run",
                "--category",
                "injection",
                "--disable",
                "input_injection",
                "--transcripts",
                str(out),
            ]
        )
        == 1
    )
    text = capsys.readouterr().out
    assert "disabled: input_injection" in text and "Failures" in text
    assert out.exists()
    assert main(["run", "--category", "faq"]) == 0
