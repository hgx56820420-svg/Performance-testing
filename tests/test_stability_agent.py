import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from stability_agent import (
    analyze_logs,
    analyze_metrics,
    deterministic_findings,
    redact,
    review_files,
)


def test_redacts_credentials():
    result = redact("Authorization: Bearer abc123 token=secret-value")
    assert "abc123" not in result
    assert "secret-value" not in result


def test_log_and_metric_findings(tmp_path):
    log = tmp_path / "service.log"
    log.write_text("ERROR request timeout status=502\n", encoding="utf-8")
    facts = {
        "logs": analyze_logs([log]),
        "metrics": analyze_metrics("dependency_errors_total{dependency=\"payment\"} 2\n"),
        "code_reviews": [],
        "api_script_reviews": [],
        "locust": None,
    }
    findings = deterministic_findings(facts)
    assert facts["logs"]["counts"]["timeout_lines"] == 1
    assert any(item["source"] == "prometheus" for item in findings)


def test_api_review_flags_missing_assertion(tmp_path):
    script = tmp_path / "api.py"
    script.write_text("requests.get(url)", encoding="utf-8")
    review = review_files([script], "api_script")[0]
    types = {item["type"] for item in review["findings"]}
    assert "missing_assertion" in types
    assert "missing_timeout" in types
