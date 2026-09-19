# 部署说明（测试环境：纯 HTTP，IP 直连）

部署架构：**测试环境**（纯 HTTP、无域名、IP 直连）一套编排。同一份部署同时
服务网页端与 Android App 端。

> 模型 (LLM) 配置**只存数据库**（每个用户登录后在网页「模型设置」页配置），
> 部署时**不需要**任何模型 API Key 环境变量。

## 1. 架构与文件总览

```
                     ┌──────────────────────────────────────────────┐
  浏览器 (网页端) ───►  nginx :80 (HTTP 直连)                        │
                     │   /api  ──► FastAPI :8000 (zhixue 容器)       │
  Android App ──────►  │   /    ──► FastAPI 托管前端 dist (SPA)       │
  (Capacitor APK)    │        ──► postgres:5432 (宿主机 ./pgdata 持久化) │
                     └──────────────────────────────────────────────┘
```

| 文件 | 用途 |
|---|---|
| `Dockerfile` | 两阶段构建：前端 `vite build` + Python 后端（uvicorn 同时托管 API 与前端静态产物） |
| `docker-compose.test.yml` | 部署编排：nginx HTTP 80 + zhixue + postgres(pgvector) |
| `nginx/zhixue-test.conf` | nginx 配置（HTTP；`/api` 反代关闭缓冲以支持 SSE 流式） |
| `scripts/deploy.sh` | 部署脚本：`sudo bash scripts/deploy.sh [日志级别]` |
| `deploy.env.example` | 部署配置模板 → 复制为服务器上的 `.env`（gitignore） |

`/api/health` 需要登录（按当前用户判定模型配置状态），匿名请求返回 **401**
—— 部署脚本的健康检查正是以「收到 401」作为整条链路（nginx → 后端 →
PostgreSQL）就绪的标志。

## 2. 首次部署准备

服务器要求：root 权限、Docker + Docker Compose v2、curl、git。

```bash
# 1. root 能拉取仓库 (SSH key 放 /root/.ssh 或改 deploy.sh 的 REPO_URL 用 https)
ssh -T git@github.com     # 验证

# 2. 准备部署目录并写配置
sudo git clone -b test-deploy git@github.com:pengliuah/zhixue.git /opt/zhixue
cd /opt/zhixue
sudo cp deploy.env.example .env
sudo vi .env
```

`.env` 关键项（完整说明见模板内注释）：

| 变量 | 说明 |
|---|---|
| `POSTGRES_PASSWORD` | 数据库密码。**注意**：数据库已用旧密码初始化过的话，改这里不会改库密码，需保持一致（默认 `123`） |
| `JWT_SECRET` | JWT 签名密钥。不设则每次重启随机生成、所有用户需重新登录。**强烈建议设置**：`python3 -c "import secrets; print(secrets.token_urlsafe(48))"`（不设的话 deploy.sh 首次部署会自动生成并持久化） |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 首次启动引导管理员（仅 users 表为空时创建）。请设置强密码；登录后可在网页「账号设置」页修改 |
| `LOG_LEVEL` | 后端日志级别，默认 INFO；`deploy.sh` 的第 1 个参数会自动改写这里（如 `deploy.sh debug`） |

## 3. 部署

```bash
sudo bash scripts/deploy.sh
```

完成后访问 `http://<服务器IP>/`，用引导管理员账号登录。安全组/防火墙放行 **80**。

## 4. 部署脚本做了什么

`sudo bash scripts/deploy.sh` 依次执行：

1. 备份数据库（pg_dumpall）与附件目录（tar）到 `/opt/`，每类只保留最新一份；
2. `docker compose down` 停掉旧容器（并按镜像名兜底清理残留）；
3. `git fetch + reset --hard origin/test-deploy` 拉取最新代码
   （`.env`、附件目录等均被 gitignore，不受影响）；
4. 恢复 `.env`；`JWT_SECRET` 缺失时自动生成并持久化；写入日志级别；
5. 构建镜像、启动，轮询 `http://127.0.0.1/api/health` 最多 60 秒，
   收到 **401** 即判定部署成功；超时失败会提示
   `docker compose -f docker-compose.test.yml logs zhixue` 排查。

数据库表结构迁移是**自动**的：后端启动时 `init_schema()` 幂等执行增量迁移
（账号系统、每用户设置表等），无需手动执行 SQL；数据库本身由
`docker-entrypoint-initdb.d` 在卷首次初始化时执行 `db/schema.sql`。

## 5. 部署后验证清单

1. 打开站点 → 自动跳转登录页（星空页）→ 用引导管理员登录；
2. **立即修改密码**：右上角点用户名 →「账号设置」→ 修改（会踢掉所有会话，用新密码重登）；
3. **配置模型**：右上角「模型设置」→ 填 API Key / 模型名 / Base URL → 保存。
   首页顶栏不再出现"未配置模型"的黄色提示即生效；
4. 新建一个学习计划验证生成链路（SSE 流式输出正常）；
5. 生成一个邀请码，开无痕窗口走一遍 `/register` 注册流程。

## 6. 日常更新 / 回滚

```bash
# 更新到 test-deploy 分支最新
sudo bash scripts/deploy.sh

# 回滚代码: 在 /opt/zhixue 检出旧 commit 后重新构建
cd /opt/zhixue && git checkout <旧commit>
docker compose -f docker-compose.test.yml build && \
docker compose -f docker-compose.test.yml up -d
```

数据备份（部署脚本每次自动做，也可手动）：

```bash
docker compose -f docker-compose.test.yml exec postgres \
  pg_dump -U postgres zhixue > zhixue_backup_$(date +%F).sql
# 恢复: cat backup.sql | docker compose -f docker-compose.test.yml exec -T postgres psql -U postgres zhixue
```

## 7. App 端打包（在有 Android SDK 的开发机上）

App 跨域访问服务器（WebView origin 是 `https://localhost`，相对 `/api` 会
解析到设备本地，必须注入绝对地址）：

```bash
cd mobile
VITE_API_BASE=http://<服务器IP>/api npm run dev:apk   # 调试 APK
```

- 服务器 IP 变更需重新打包（地址在构建时固化）；
- 后端 CORS 为 `allow_origins=["*"]`（Bearer token 方案，无需 cookie），跨域已就绪。

## 8. 常见问题排查

| 现象 | 排查 |
|---|---|
| 健康检查 000/超时 | `docker compose -f docker-compose.test.yml ps && logs zhixue`；常见为 `.env` 缺失或 DATABASE_URL 密码与已初始化的数据库不一致 |
| 登录后每次重启都要重登 | `.env` 未设 `JWT_SECRET`（每次重启随机生成） |
| 忘记 admin 密码 | 另一个 admin 可在「用户管理」重置；没有其他 admin 时需在数据库重置（bcrypt 哈希，找开发处理） |
| 生成功能 503 | 该用户未配置模型 API Key——右上角「模型设置」页配置（按用户存数据库，不是环境变量） |
