# zhixue 压测方案

工具：[locust](https://locust.io)（Python，与后端同栈，自带 Web UI）。脚本：`locustfile.py`。

> **压测账号**：用专用账号（已建：`loadtest / loadtest123`），别用管理员。
> 计划详情与 LLM 任务只会打「该账号自己名下的计划」——压测前先用该账号在页面里
> 手动创建一个计划，详情/SSE 任务才有目标（账号无计划时这些任务自动跳过，不报错）。

## 一、先想清楚压什么

| 场景 | 端点 | 说明 |
| --- | --- | --- |
| 只读浏览（主力） | `/api/plans`、`/api/plans/:id`、`/`、书签、用量 | 绝大多数用户行为，重点压这个 |
| SSE 长连接 | 内容/测验/批改生成 | 每个连接持续几十秒~几分钟，吃的是并发连接数与内存，不是 QPS |
| LLM 供应商 | 火山方舟 | 外部瓶颈：计费 + 限流。不要压它，压"我们的链路撑多少并发 SSE" |
| 数据库 | Postgres 连接池 | 每请求一连接的写路径要盯 `pg_stat_activity` |

## 二、运行（对测试环境）

```bash
# 1. 安装（一次性）
cd backend && uv pip install locust && cd ..

# 2. 只读压测（安全：不写数据、不调 LLM），Web UI 模式
LOADTEST_USERNAME=admin LOADTEST_PASSWORD=admin123 \
  uv run --with locust locust -f loadtest/locustfile.py --host http://<服务器IP>
# 浏览器打开 http://localhost:8089，设置并发数开始

# 3. 无界面跑一段（CI/无人值守友好）
LOADTEST_USERNAME=admin LOADTEST_PASSWORD=admin123 \
  uv run --with locust locust -f loadtest/locustfile.py --host http://<服务器IP> \
  --headless -u 30 -r 5 -t 3m --only-summary
#   -u 30 并发30人  -r 每秒加5人  -t 跑3分钟
```

## 三、加压阶梯（建议）

1. **10 人 × 2 分钟** — 冒烟，确认脚本与监控正常
2. **30 人 × 5 分钟** — 日常峰值模拟
3. **50 → 100 人 × 5~10 分钟** — 找拐点

**停止条件**（任一出现就停，记录当时并发数 = 当前容量）：
- p95 响应 > 2s（只读接口）
- 错误率 > 1%
- 服务器内存/CAR 持续 > 85%

## 四、压测时在服务器上看什么

```bash
docker stats                                  # 各容器 CPU/内存
ss -s                                         # 总连接数（SSE 场景重点）
docker compose -f docker-compose.test.yml logs -f --tail=50 zhixue   # 报错/超时
# PG 连接占用（> max_connections 的 70% 就危险）
docker compose -f docker-compose.test.yml exec postgres \
  psql -U postgres -d zhixue -c "SELECT count(*), state FROM pg_stat_activity GROUP BY state;"
```

## 五、LLM/SSE 专项（可选，默认关闭）

```bash
# ⚠️ 开启前务必新建一个专门的"压测计划"：此任务会重新生成并覆盖模块内容，
# 且真实调用 LLM（计费、可能触发供应商限流）。并发控制在 3~5。
LOADTEST_LLM=1 LOADTEST_USERNAME=admin LOADTEST_PASSWORD=admin123 \
  uv run --with locust locust -f loadtest/locustfile.py --host http://<服务器IP> \
  --headless -u 3 -r 1 -t 5m --only-summary --tag sse
```

关注点：nginx 到后端的并发连接数、30s 心跳是否稳定、移动网络断连重连、后端内存是否随长连接增长。

## 六、红线

- **生产环境只做低速率只读探测**（≤5 并发），绝不跑写路径压测。
- 压测账号用测试环境专用账号，不要用管理员在真实数据上做写压测。
- 压测前备份一次测试库（deploy.sh 每次部署前会自动备，也可手动 `pg_dumpall`）。
