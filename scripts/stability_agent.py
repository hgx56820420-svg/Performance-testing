"""Evidence-bound stability and anomaly analysis for performance test runs.

The deterministic layer collects facts from Locust CSVs, logs, Prometheus text,
application code, and API test scripts. The optional AI layer receives only the
redacted facts and is instructed to keep hypotheses separate from observations.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any

SECRET_RE = re.compile(
    r"(?i)(authorization\s*[:=]\s*bearer\s+|(?:token|password|passwd|secret|cookie|api[_-]?key)\s*[:=]\s*)([^\s,;]+)"
)
ERROR_RE = re.compile(r"(?i)\b(error|critical|fatal|traceback|exception)\b")
TIMEOUT_RE = re.compile(r"(?i)timeout|timed out|deadline exceeded|context deadline")
SERVER_ERROR_RE = re.compile(r"(?<!\d)5\d\d(?!\d)|\bstatus\s*[=:]\s*5\d\d\b")
METRIC_RE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{[^}]*\})?\s+(?P<value>[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?|NaN|[+-]?Inf)\s*$"
)


def redact(text: str) -> str:
    """Remove common credential values before data is placed in a report/prompt."""

    text = re.sub(SECRET_RE, lambda m: m.group(1) + "[REDACTED]", text)
    return re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", text)


def read_limited(path: Path, limit: int = 12000) -> str:
    return redact(path.read_text(encoding="utf-8", errors="replace")[:limit])


def analyze_logs(paths: list[Path], sample_limit: int = 5) -> dict[str, Any]:
    counts = {"error_lines": 0, "timeout_lines": 0, "server_error_lines": 0}
    samples: list[str] = []
    files: list[str] = []
    for path in paths:
        files.append(str(path))
        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = redact(raw_line)
            if ERROR_RE.search(line):
                counts["error_lines"] += 1
            if TIMEOUT_RE.search(line):
                counts["timeout_lines"] += 1
            if SERVER_ERROR_RE.search(line):
                counts["server_error_lines"] += 1
            if (ERROR_RE.search(line) or TIMEOUT_RE.search(line) or SERVER_ERROR_RE.search(line)) and len(samples) < sample_limit:
                samples.append(line[:500])
    return {"files": files, "counts": counts, "samples": samples}


def load_prometheus(source: str | None) -> str:
    if not source:
        return ""
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=10) as response:
            return response.read(1_000_000).decode("utf-8", errors="replace")
    return Path(source).read_text(encoding="utf-8", errors="replace")


def analyze_metrics(text: str) -> dict[str, Any]:
    totals: dict[str, float] = {}
    samples: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        match = METRIC_RE.match(line.strip())
        if not match:
            continue
        name = match.group("name")
        try:
            value = float(match.group("value"))
        except ValueError:
            continue
        totals[name] = totals.get(name, 0.0) + value
        if name in {"dependency_errors_total", "http_requests_total", "process_resident_memory_bytes"} and len(samples) < 20:
            samples.append({"metric": name, "value": value})
    selected = {
        name: round(value, 6)
        for name, value in totals.items()
        if name in {
            "dependency_errors_total",
            "http_requests_total",
            "http_request_duration_seconds_count",
            "http_request_duration_seconds_sum",
            "process_resident_memory_bytes",
            "process_cpu_seconds_total",
        }
    }
    return {"selected_totals": selected, "samples": samples}


def _review_text(path: Path, kind: str) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    redacted = redact(text)
    findings: list[dict[str, str]] = []
    if re.search(r"(?i)(api[_-]?key|password|secret|token|cookie)\s*[:=]\s*[\"'][^\"']+", text):
        findings.append({"severity": "high", "type": "secret", "evidence": "possible credential literal"})
    if re.search(r"(?i)except\s+Exception|catch\s*\(?.*Exception", text):
        findings.append({"severity": "medium", "type": "broad_exception", "evidence": "broad exception handling may hide failures"})
    if kind == "api_script":
        if not re.search(r"(?i)(assert|failure\(|status_code|expected_status|check_response)", text):
            findings.append({"severity": "high", "type": "missing_assertion", "evidence": "no visible response/status assertion"})
        if re.search(r"(?i)(requests\.(get|post|put|delete)|client\.(get|post|put|delete))\(", text) and not re.search(r"(?i)timeout\s*=", text):
            findings.append({"severity": "medium", "type": "missing_timeout", "evidence": "HTTP call appears to have no explicit timeout"})
    return {"file": str(path), "kind": kind, "findings": findings, "content": redacted[:12000]}


def review_files(paths: list[Path], kind: str) -> list[dict[str, Any]]:
    return [_review_text(path, kind) for path in paths]


def build_facts(stats_path: Path | None, history_path: Path | None, log_paths: list[Path], metric_source: str | None, code_paths: list[Path], api_paths: list[Path]) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "logs": analyze_logs(log_paths),
        "metrics": analyze_metrics(load_prometheus(metric_source)),
        "code_reviews": review_files(code_paths, "code"),
        "api_script_reviews": review_files(api_paths, "api_script"),
    }
    if stats_path:
        from analyze_results import analyze, load_rows

        stats = load_rows(stats_path)
        history = load_rows(history_path) if history_path and history_path.exists() else []
        facts["locust"] = analyze(stats, history)["summary"]
    else:
        facts["locust"] = None
    return facts


def deterministic_findings(facts: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    log_counts = facts["logs"]["counts"]
    for key, severity, message in [
        ("error_lines", "medium", "日志中出现错误级别行"),
        ("timeout_lines", "high", "日志中出现超时或 deadline exceeded"),
        ("server_error_lines", "high", "日志中出现 5xx 证据"),
    ]:
        if log_counts[key]:
            findings.append({"severity": severity, "source": "logs", "evidence": f"{message}: {log_counts[key]} 条"})
    selected = facts["metrics"]["selected_totals"]
    if selected.get("dependency_errors_total", 0) > 0:
        findings.append({"severity": "high", "source": "prometheus", "evidence": f"dependency_errors_total={selected['dependency_errors_total']}"})
    for review_key in ("code_reviews", "api_script_reviews"):
        for review in facts[review_key]:
            findings.extend({"severity": item["severity"], "source": review["file"], "evidence": item["evidence"]} for item in review["findings"])
    locust = facts.get("locust") or {}
    if locust.get("verdict") == "FAIL":
        findings.append({"severity": "high", "source": "locust", "evidence": "确定性 Locust 判定为 FAIL"})
    return findings


def ai_analysis(facts: dict[str, Any], findings: list[dict[str, str]]) -> dict[str, Any] | None:
    if not os.getenv("OPENAI_API_KEY"):
        return None
    from openai import OpenAI

    schema = {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["NORMAL", "ANOMALY", "INCONCLUSIVE"]},
            "observations": {"type": "array", "items": {"type": "string"}},
            "hypotheses": {"type": "array", "items": {"type": "string"}},
            "code_risks": {"type": "array", "items": {"type": "string"}},
            "api_script_risks": {"type": "array", "items": {"type": "string"}},
            "missing_evidence": {"type": "array", "items": {"type": "string"}},
            "next_actions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["verdict", "observations", "hypotheses", "code_risks", "api_script_risks", "missing_evidence", "next_actions"],
        "additionalProperties": False,
    }
    prompt = (
        "你是稳定性测试分析师。只使用 facts 和 findings 中的证据。observations 只能写事实，"
        "hypotheses 必须标记为待验证假设，不能把代码审查风险当成线上根因。若证据不足，输出 INCONCLUSIVE。"
        "为每条关键判断保留证据来源；不要复述或泄露任何凭证。\n"
        + json.dumps({"facts": facts, "findings": findings}, ensure_ascii=False)[:40000]
    )
    response = OpenAI(api_key=os.environ["OPENAI_API_KEY"]).responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        input=prompt,
        text={"format": {"type": "json_schema", "name": "stability_analysis", "strict": True, "schema": schema}},
    )
    return json.loads(response.output_text)


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Stability Agent Report",
        "",
        f"- Deterministic findings: **{len(report['findings'])}**",
        f"- AI analysis: **{'available' if report.get('ai_analysis') else 'not requested or unavailable'}**",
        "",
        "## Evidence Findings",
        "",
    ]
    if report["findings"]:
        lines.extend(f"- **{item['severity']}** `{item['source']}`: {item['evidence']}" for item in report["findings"])
    else:
        lines.append("- No deterministic findings were detected.")
    analysis = report.get("ai_analysis")
    if analysis:
        lines += ["", "## AI Analysis", "", f"- Verdict: **{analysis['verdict']}**", "", "### Observations", ""]
        lines.extend(f"- {item}" for item in analysis["observations"])
        lines += ["", "### Hypotheses", ""]
        lines.extend(f"- {item}" for item in analysis["hypotheses"])
        lines += ["", "### Next Actions", ""]
        lines.extend(f"- {item}" for item in analysis["next_actions"])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evidence-bound stability/anomaly agent")
    parser.add_argument("--stats", type=Path)
    parser.add_argument("--history", type=Path)
    parser.add_argument("--log", type=Path, action="append", default=[])
    parser.add_argument("--metrics", help="Prometheus text file or URL")
    parser.add_argument("--code", type=Path, action="append", default=[])
    parser.add_argument("--api-script", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ai", action="store_true")
    args = parser.parse_args()
    facts = build_facts(args.stats, args.history, args.log, args.metrics, args.code, args.api_script)
    findings = deterministic_findings(facts)
    report = {"agent": "stability-agent", "findings": findings, "facts": facts}
    if args.ai:
        try:
            report["ai_analysis"] = ai_analysis(facts, findings)
        except Exception as exc:  # noqa: BLE001 - optional AI must not hide deterministic output.
            report["ai_error"] = f"{type(exc).__name__}: {exc}"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output.with_suffix(".md").write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"findings": len(findings), "ai": bool(report.get("ai_analysis"))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
