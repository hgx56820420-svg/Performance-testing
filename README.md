# 游戏商城关键链路性能测试实验室

这个项目对应简历中的“游戏商城关键链路性能测试与 AI 分析 Workflow”，目标是用一天时间走通一条完整、可解释、可复测的性能测试闭环：

```text
需求/目标
   -> 场景建模与容量假设
   -> Locust 产生真实业务流量
   -> FastAPI 被测服务（缓存/数据库/支付下游）
   -> Prometheus 采集 RED + 依赖指标
   -> Grafana 看趋势和关联
   -> analyze_results.py 计算事实
   -> 可选 AI 分析：异常链路 -> 证据 -> 假设 -> 复测建议
```

## 1. 快速启动

前置条件：Docker Desktop 已启动。

```powershell
git clone https://github.com/hgx56820420-svg/Performance-testing.git
cd Performance-testing
docker compose up --build -d
```

服务地址：

| 组件 | 地址 | 用途 |
| --- | --- | --- |
| 被测 API | http://localhost:8000/docs | 手工验证接口 |
| Locust | http://localhost:8089 | 启动压测、查看实时结果 |
| Prometheus | http://localhost:9090 | 查询指标 |
| Grafana | http://localhost:3000 | admin/admin，查看仪表盘 |

## 1.1 使用你的 YY QA 测试地址（只读起步）

已针对 `https://gamesrv-qa.yy.com/proxy/mall/` 增加只读场景：它压商城 HTML 入口，并压前端 bundle 中实际确认可匿名访问的 `test-gamemarket.yy.com` 分类接口。Locust 不执行浏览器 JavaScript，因此这个场景不是完整 E2E；它用于先确认 QA 环境、TLS、网关和匿名 API 的受控基线。

当前已确认可匿名读取的接口：`/category/querySubCategories`、`/category/queryCategories`、`/category/queryShowCategories`、`/category/queryShowSubCategories`。`/goods/v2/search`、`/goods/v2/detail`、`/mall-home/value-account` 等接口返回 HTTP 200 但业务 `code=100004` 或缺少必填参数，未获得接口契约和专用压测凭证前不加入负载场景。

启动本地监控后运行 1 分钟、最多 5 个用户：

```powershell
docker compose run --rm locust `
  -f /mnt/locust/qa_readonly_locustfile.py `
  --host https://gamesrv-qa.yy.com `
  --headless -u 5 -r 1 -t 1m `
  --csv /mnt/results/yy_qa_readonly
```

这里的 `--host` 只控制页面用户类；分类 API 在脚本中使用 `QA_API_BASE` 绝对地址，因此不会被错误地发到页面域名。

也可以显式覆盖环境：

```powershell
$env:TARGET_ORIGIN = "https://gamesrv-qa.yy.com"
$env:MALL_PATH = "/proxy/mall/"
$env:QA_API_BASE = "https://test-gamemarket.yy.com"
```

我已验证首页返回 HTTP 200；匿名分类接口返回 `code=0`。商品搜索、商品详情、订单提交等接口在没有浏览器 Cookie、ticket 或网关签名时会返回 `100004 网络异常`，不要用猜参数的方式绕过鉴权，也不要把登录 Cookie 放进脚本或仓库。需要这些链路时，应由你们提供已批准的接口契约、专用压测账号/数据和明确的流量上限，再单独建场景。

在 Locust 页面输入：

- Number of users：先填 `20`
- Spawn rate：填 `5`
- Host：保留 `http://service:8000`
- 运行 5 分钟后下载 `*_stats.csv` 和 `*_stats_history.csv`

也可以用无界面模式：

```powershell
docker compose run --rm locust `
  -f /mnt/locust/locustfile.py `
  --host http://service:8000 `
  --headless -u 50 -r 10 -t 5m `
  --csv /mnt/results/baseline
```

生成分析报告：

```powershell
docker compose run --rm analyzer `
  python /app/scripts/analyze_results.py `
  --stats /results/baseline_stats.csv `
  --history /results/baseline_stats_history.csv `
  --output /results/baseline_report.md
```

报告不依赖模型即可生成。默认要求至少 100 个请求才给出 PASS/FAIL；样本不足会标记 `INCONCLUSIVE`。可用参数显式调整阈值和最小样本量。如果设置 `OPENAI_API_KEY`，再加 `--ai` 会基于确定性统计结果生成 AI 辅助分析：

```powershell
$env:OPENAI_API_KEY = "你的 key"
docker compose run --rm `
  -e OPENAI_API_KEY `
  analyzer python /app/scripts/analyze_results.py `
  --stats /results/baseline_stats.csv `
  --history /results/baseline_stats_history.csv `
  --output /results/baseline_report.md --min-requests 100 --p95-ms 500 `
  --error-rate-percent 1 --ai
```

## 1.3 稳定性与异常检测 Agent

项目还提供一个小型证据约束 Agent：先用规则统计 Locust 结果、日志、Prometheus 指标，并静态检查系统代码和 API 测试脚本；只有显式传入 `--ai` 且设置 `OPENAI_API_KEY` 时，才让模型基于脱敏后的证据输出观察、待验证假设、缺失证据和下一步实验。模型不能替代指标，也不会直接把假设当作根因。

本地运行示例：

```powershell
python scripts/stability_agent.py `
  --stats results/baseline_stats.csv `
  --history results/baseline_stats_history.csv `
  --metrics http://localhost:9090/metrics `
  --code service/app.py `
  --api-script locust/locustfile.py `
  --output results/stability_agent.json
```

使用 analyzer 容器时：

```powershell
docker compose run --rm analyzer `
  python /app/scripts/stability_agent.py `
  --stats /results/baseline_stats.csv `
  --history /results/baseline_stats_history.csv `
  --metrics http://prometheus:9090/metrics `
  --code /app/service/app.py `
  --api-script /app/locust/locustfile.py `
  --output /results/stability_agent.json
```

输入日志和脚本会在进入报告或模型提示词前脱敏常见的 token、密码、Cookie 和 Authorization 值。输出 JSON 中将 `findings`（确定性证据）与 `ai_analysis`（可选解释）分开，便于复核。

## 2. 目录说明

```text
performance-test-lab/
├─ service/
│  ├─ app.py                 # FastAPI 被测服务和 Prometheus 指标
│  └─ requirements.txt
├─ locust/
│  └─ locustfile.py          # 浏览、搜索、详情、购物车、下单五类业务流量
├─ scripts/
│  ├─ analyze_results.py     # P50/P95/P99、错误率、吞吐量和瓶颈假设
│  └─ stability_agent.py     # 日志/指标/代码/接口脚本的证据约束分析 Agent
├─ monitoring/
│  ├─ prometheus.yml
│  └─ grafana/               # 自动配置数据源和仪表盘
├─ tests/
│  └─ test_service.py
├─ docker-compose.yml
├─ Dockerfile.analyzer
├─ requirements-analysis.txt
├─ run.ps1
└─ ONE_DAY_GUIDE.md          # 一天学习计划、原理、面试题和项目话术
```

## 3. 建议实验顺序

1. 先 `GET /health`、`GET /api/products`，确认被测服务可用。
2. 在 Locust 运行 20 用户的基线，记录 P95、P99、错误率、RPS。
3. 改成 50、100、200 用户，观察拐点，不要只看平均响应时间。
4. 在查询参数中加入 `q=slow`，验证数据库慢查询假设。
5. 观察 Grafana 中 `http_request_duration_seconds`、依赖延迟和错误率的同步变化。
6. 用分析脚本生成报告，人工检查证据是否足够，再决定优化和复测。

## 4. 重要边界

- 这个服务是教学用 mock，不代表真实生产架构；压测前必须确认目标环境、数据脱敏、流量上限和回滚方案。
- AI 只能解释已经采集到的证据，不能替代指标、日志、trace 和代码定位。
- “通过”应由事先约定的 SLA/SLO 判定，例如核心接口 P95 < 500 ms、错误率 < 1%，而不是凭感觉。
- 只读 smoke、基线、负载、压力、峰值、稳定性和容量测试是不同证据等级；请求数很少的 smoke 只能证明脚本与连通性。
