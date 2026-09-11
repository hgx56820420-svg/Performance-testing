"""Analyze Locust CSV output without hiding facts behind an AI model."""

import argparse
import csv
import json
import os
import statistics
from pathlib import Path


def number(row, key, default=0.0):
    value = (row.get(key) or "").strip().replace(",", "")
    try:
        return float(value)
    except ValueError:
        return default


def load_rows(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def analyze(stats_rows, history_rows, p95_limit_ms=500.0, error_rate_limit_percent=1.0, min_requests=100):
    endpoints = []
    for row in stats_rows:
        requests = number(row, "Request Count")
        failures = number(row, "Failure Count")
        if not row.get("Name") or row.get("Name") == "Aggregated":
            continue
        error_rate = failures / requests * 100 if requests else 0
        p95 = number(row, "95%")
        p99 = number(row, "99%")
        endpoints.append(
            {
                "name": row["Name"],
                "requests": int(requests),
                "failures": int(failures),
                "error_rate_percent": round(error_rate, 3),
                "median_ms": number(row, "Median Response Time"),
                "p95_ms": p95,
                "p99_ms": p99,
                "avg_ms": number(row, "Average Response Time"),
                "rps": number(row, "Requests/s"),
            }
        )
    total_requests = sum(e["requests"] for e in endpoints)
    total_failures = sum(e["failures"] for e in endpoints)
    history_rps = [number(r, "Requests/s") for r in history_rows if number(r, "Requests/s")]
    worst_latency = sorted(endpoints, key=lambda x: x["p95_ms"], reverse=True)[:3]
    worst_errors = sorted(endpoints, key=lambda x: x["error_rate_percent"], reverse=True)[:3]
    hypotheses = []
    for item in worst_latency:
        if "products?q" in item["name"]:
            hypotheses.append(f"{item['name']} P95 高，优先核查搜索条件触发的数据库慢查询和索引。");
        elif "orders" in item["name"]:
            hypotheses.append(f"{item['name']} 延迟高，优先拆分支付下游耗时、连接池和重试。");
        elif "cart" in item["name"]:
            hypotheses.append(f"{item['name']} 延迟高，优先核查库存写入、Redis/数据库调用和锁等待。");
        else:
            hypotheses.append(f"{item['name']} 是当前最慢接口，先用 trace 拆分应用与依赖耗时。");
    observed_p95 = max((e["p95_ms"] for e in endpoints), default=0.0)
    error_rate_percent = total_failures / total_requests * 100 if total_requests else 0.0
    sample_sufficient = total_requests >= min_requests
    thresholds_pass = (
        observed_p95 < p95_limit_ms and error_rate_percent < error_rate_limit_percent
    )
    # A small sample cannot establish capacity, but a measured error-rate breach
    # is still an actionable failure. Latency-only failures require enough data.
    verdict = "INCONCLUSIVE"
    if total_requests and error_rate_percent >= error_rate_limit_percent:
        verdict = "FAIL"
    elif sample_sufficient:
        verdict = "PASS" if thresholds_pass else "FAIL"
    report = {
        "summary": {
            "total_requests": total_requests,
            "total_failures": total_failures,
            "error_rate_percent": round(error_rate_percent, 3),
            "peak_rps": round(max(history_rps), 3) if history_rps else 0,
            "avg_rps": round(statistics.mean(history_rps), 3) if history_rps else 0,
            "sla": {"p95_ms_lt": p95_limit_ms, "error_rate_percent_lt": error_rate_limit_percent},
            "min_requests": min_requests,
            "sample_sufficient": sample_sufficient,
            "observed_worst_p95_ms": round(observed_p95, 3),
            "verdict": verdict,
        },
        "endpoints": endpoints,
        "worst_latency": worst_latency,
        "worst_errors": worst_errors,
        "hypotheses": hypotheses,
        "next_tests": [
            "固定用户数做 10 分钟稳定性测试，排除冷启动影响并单独记录稳态窗口。",
            "单独压测搜索接口并切换 q=slow，验证数据库慢查询假设。",
            "提高用户数做阶梯/拐点测试，记录最大稳定吞吐量。",
            "结合 Prometheus 依赖延迟与应用 P95 做同时间窗口关联。",
        ],
    }
    return report


def markdown(report):
    s = report["summary"]
    lines = [
        "# 性能测试结果分析",
        "",
        f"- 判定：**{s['verdict']}**（样本充足：{s['sample_sufficient']}，最少请求：{s['min_requests']}）",
        f"- 总请求：{s['total_requests']}，失败：{s['total_failures']}，错误率：{s['error_rate_percent']}%",
        f"- 平均吞吐：{s['avg_rps']} RPS，峰值吞吐：{s['peak_rps']} RPS",
        f"- 判定阈值：最慢端点 P95 < {s['sla']['p95_ms_lt']} ms，错误率 < {s['sla']['error_rate_percent_lt']}%",
        "",
        "## 端点明细",
        "",
        "| 端点 | 请求数 | 错误率 | P95(ms) | P99(ms) | RPS |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for e in report["endpoints"]:
        lines.append(f"| {e['name']} | {e['requests']} | {e['error_rate_percent']}% | {e['p95_ms']:.1f} | {e['p99_ms']:.1f} | {e['rps']:.2f} |")
    lines += ["", "## 优先排查假设", ""] + [f"- {x}" for x in report["hypotheses"]]
    lines += ["", "## 建议复测", ""] + [f"- {x}" for x in report["next_tests"]]
    return "\n".join(lines) + "\n"


def optional_ai(report):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return ""
    try:
        from openai import OpenAI, OpenAIError

        client = OpenAI(api_key=api_key)
        schema = {
            "type": "object",
            "properties": {
                "observations": {"type": "array", "items": {"type": "string"}},
                "hypotheses": {"type": "array", "items": {"type": "string"}},
                "missing_evidence": {"type": "array", "items": {"type": "string"}},
                "experiments": {"type": "array", "items": {"type": "string"}},
                "recommendations": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "observations",
                "hypotheses",
                "missing_evidence",
                "experiments",
                "recommendations",
            ],
            "additionalProperties": False,
        }
        prompt = (
            "你是性能测试专家。只根据下面 JSON 中的证据输出结构化分析，不能编造未提供的监控数据。"
            "observations 只能写直接观察到的事实；hypotheses 必须写成待验证假设；"
            "missing_evidence 写出阻止根因结论的缺失证据；experiments 必须是可执行的单变量验证；"
            "recommendations 只能针对已有证据，无法判断时明确保守。\n"
            + json.dumps(report, ensure_ascii=False, indent=2)
        )
        result = client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            input=prompt,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "performance_analysis",
                    "strict": True,
                    "schema": schema,
                }
            },
        )
        analysis = json.loads(result.output_text)
        return "\n## AI 辅助分析（结构化）\n\n" + json.dumps(
            analysis, ensure_ascii=False, indent=2
        ) + "\n"
    except (OpenAIError, OSError, ValueError, json.JSONDecodeError) as exc:
        return f"\n## AI 辅助分析\n\n未生成：{exc}\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--history", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ai", action="store_true")
    parser.add_argument("--p95-ms", type=float, default=500.0)
    parser.add_argument("--error-rate-percent", type=float, default=1.0)
    parser.add_argument("--min-requests", type=int, default=100)
    args = parser.parse_args()
    stats_rows = load_rows(args.stats)
    history_rows = load_rows(args.history) if args.history and args.history.exists() else []
    report = analyze(
        stats_rows,
        history_rows,
        p95_limit_ms=args.p95_ms,
        error_rate_limit_percent=args.error_rate_percent,
        min_requests=args.min_requests,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown(report) + (optional_ai(report) if args.ai else ""), encoding="utf-8")
    args.output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
