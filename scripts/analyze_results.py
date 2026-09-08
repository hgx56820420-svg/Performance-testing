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


def analyze(stats_rows, history_rows):
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
    report = {
        "summary": {
            "total_requests": total_requests,
            "total_failures": total_failures,
            "error_rate_percent": round(total_failures / total_requests * 100, 3) if total_requests else 0,
            "peak_rps": round(max(history_rps), 3) if history_rps else 0,
            "avg_rps": round(statistics.mean(history_rps), 3) if history_rps else 0,
            "sla": {"p95_ms_lt": 500, "error_rate_percent_lt": 1},
        },
        "endpoints": endpoints,
        "worst_latency": worst_latency,
        "worst_errors": worst_errors,
        "hypotheses": hypotheses,
        "next_tests": [
            "固定用户数做 10 分钟稳定性测试，排除冷启动影响。",
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
        f"- 总请求：{s['total_requests']}，失败：{s['total_failures']}，错误率：{s['error_rate_percent']}%",
        f"- 平均吞吐：{s['avg_rps']} RPS，峰值吞吐：{s['peak_rps']} RPS",
        f"- 判定基线：P95 < {s['sla']['p95_ms_lt']} ms，错误率 < {s['sla']['error_rate_percent_lt']}%",
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
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        prompt = (
            "你是性能测试专家。只根据下面 JSON 中的证据输出中文分析，不能编造未提供的监控数据。"
            "按异常链路、证据、可能原因、验证实验、优化建议输出，明确区分事实和假设。\n"
            + json.dumps(report, ensure_ascii=False, indent=2)
        )
        result = client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            input=prompt,
        )
        return "\n## AI 辅助分析\n\n" + result.output_text.strip() + "\n"
    except Exception as exc:
        return f"\n## AI 辅助分析\n\n未生成：{exc}\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--history", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ai", action="store_true")
    args = parser.parse_args()
    stats_rows = load_rows(args.stats)
    history_rows = load_rows(args.history) if args.history and args.history.exists() else []
    report = analyze(stats_rows, history_rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown(report) + (optional_ai(report) if args.ai else ""), encoding="utf-8")
    args.output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
