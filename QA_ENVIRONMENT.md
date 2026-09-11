# YY QA 环境接入记录

目标页面：`https://gamesrv-qa.yy.com/proxy/mall/`

## 已做的低风险验证

| 项目 | 结果 |
| --- | --- |
| 首页 GET | HTTP 200，返回 YY 游仓 HTML |
| 页面标题 | YY 游仓·百度旗下唯一游戏交易平台 |
| `GET https://test-gamemarket.yy.com/category/querySubCategories` | HTTP 200，业务 `code=0` |
| `GET /goods/v2/search` 脱离浏览器上下文 | HTTP 200，但业务 `code=100004` |
| `GET /mall-home/value-account` 脱离浏览器上下文 | HTTP 200，但业务 `code=100004` |
| `GET /goods/v2/detail` 无参数 | HTTP 200，但业务 `code=-2` |

## 2026-09-11 只读接口勘察

从页面加载的 `index.e0304d4b.js` 中提取测试 API 主机和接口定义后，对每个候选 GET 接口只发送 1 次请求；没有登录、Cookie、ticket、签名或写操作。结果如下：

| 接口 | HTTP | 业务 code | 单次耗时 | 响应大小 | 结论 |
| --- | ---: | ---: | ---: | ---: | --- |
| `/category/querySubCategories` | 200 | 0 | 516 ms | 837 B | 可纳入只读场景 |
| `/category/queryCategories` | 200 | 0 | 32 ms | 12,831 B | 可纳入只读场景 |
| `/category/queryShowCategories` | 200 | 0 | 35 ms | 5,330 B | 可纳入只读场景 |
| `/category/queryShowSubCategories` | 200 | 0 | 29 ms | 81 B | 可纳入只读场景 |
| `/mall-home/hot-games` | 200 | 100004 | 40 ms | 42 B | 当前匿名上下文被业务鉴权拒绝 |
| `/search/suggest` | 200 | 100004 | 45 ms | 42 B | 当前匿名上下文被业务鉴权拒绝 |
| `/goods/v2/search` | 200 | 100004 | 32 ms | 42 B | 当前匿名上下文被业务鉴权拒绝 |
| `/mall-home/value-account` | 200 | 100004 | 42 ms | 42 B | 当前匿名上下文被业务鉴权拒绝 |

这些请求是连通性/契约勘察，不是容量结论。耗时、并发和阶梯负载必须在获得压测窗口、上限和停止条件后进行。

## 为什么不能直接压完整商城链路

前端 bundle 显示业务 API 的测试域名是 `https://test-gamemarket.yy.com`，并启用 Cookie/credentials；部分接口还需要 ticket 或签名。直接从 Locust 发请求时，浏览器上下文中的 Cookie、请求参数、签名和前置接口状态都不存在，所以网关会返回业务错误。这个错误本身也是性能测试中要记录的“业务失败”，不能只看 HTTP 200。

## 当前可运行场景

`locust/qa_readonly_locustfile.py` 包含两个用户类：

- `QaMallPageUser`：只 GET `/proxy/mall/`，校验页面标识，权重 3。
- `QaMallAnonymousApiUser`：只 GET 已验证可匿名访问的分类接口，权重 1。

这是安全的连通性/只读基线，不代表真实线上业务比例，也不执行登录、下单、支付、发布、还价、回收或客服写操作。

## 已完成的最小冒烟

在 Docker 中使用 `QaMallAnonymousApiUser`、1 个用户、10 秒运行：3 次分类查询，0 失败，平均响应约 90 ms，P95 约 240 ms，Locust 退出码为 0。样本太小，只能证明脚本、网络和断言可用，不能据此宣称接口容量。

## 获得授权后的下一步

1. 由服务端或前端同学提供 OpenAPI/接口文档、必填参数、鉴权方式、测试账号和可回收数据。
2. 明确压测窗口、最大 RPS/并发、SLO、停止条件、告警联系人和回滚方案。
3. 先录制一次浏览器正常流程，确认每个请求的 URL、方法、参数、Cookie 是否可由专用压测凭证替代。
4. 先做 1-5 用户 1 分钟基线，再做阶梯测试；每次只增加一个变量。
5. 写接口级业务断言，并把 4xx、5xx、超时、业务 `code != 0` 分开统计。

## 明确禁止

- 不要把个人登录 Cookie、ticket、签名密钥、手机号或订单数据提交到脚本、聊天或 Git。
- 不要对生产域名或未批准的 QA 域名执行高并发、长时间或峰值压测。
- 不要用重放订单、支付、发布、还价等写接口来“验证一下”，除非有专用数据和书面授权。
