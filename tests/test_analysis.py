import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from analyze_results import analyze


def test_analyzer_extracts_long_tail_and_errors():
    stats = [
        {
            "Name": "GET /api/products?q",
            "Request Count": "100",
            "Failure Count": "2",
            "Median Response Time": "40",
            "Average Response Time": "90",
            "95%": "180",
            "99%": "300",
            "Requests/s": "10",
        },
        {
            "Name": "POST /api/orders",
            "Request Count": "20",
            "Failure Count": "1",
            "Median Response Time": "120",
            "Average Response Time": "210",
            "95%": "620",
            "99%": "1200",
            "Requests/s": "2",
        },
        {"Name": "Aggregated", "Request Count": "120", "Failure Count": "3"},
    ]
    history = [{"Requests/s": "10"}, {"Requests/s": "12"}]
    report = analyze(stats, history, min_requests=100)
    assert report["summary"]["total_requests"] == 120
    assert report["summary"]["total_failures"] == 3
    assert report["summary"]["peak_rps"] == 12
    assert report["worst_latency"][0]["name"] == "POST /api/orders"
    assert report["worst_errors"][0]["error_rate_percent"] == 5.0
    assert report["summary"]["verdict"] == "FAIL"


def test_analyzer_marks_tiny_smoke_inconclusive():
    report = analyze(
        [{
            "Name": "GET /health",
            "Request Count": "3",
            "Failure Count": "0",
            "Median Response Time": "10",
            "Average Response Time": "10",
            "95%": "20",
            "99%": "20",
            "Requests/s": "1",
        }],
        [{"Requests/s": "1"}],
        min_requests=100,
    )
    assert report["summary"]["verdict"] == "INCONCLUSIVE"
    assert report["summary"]["sample_sufficient"] is False


def test_analyzer_marks_tiny_smoke_with_errors_failed():
    report = analyze(
        [{
            "Name": "GET /health",
            "Request Count": "3",
            "Failure Count": "1",
            "Median Response Time": "10",
            "Average Response Time": "10",
            "95%": "20",
            "99%": "20",
            "Requests/s": "1",
        }],
        [{"Requests/s": "1"}],
        min_requests=100,
    )
    assert report["summary"]["verdict"] == "FAIL"
