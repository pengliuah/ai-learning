# 部署说明（测试环境 / 线上环境）

一份代码，两套编排：**测试环境**（纯 HTTP、无域名、IP 直连）与**线上环境**
（域名 + HTTPS 证书）。由同一个部署脚本 `scripts/deploy.sh` 按 `test|prod`
参数区分。一份部署同时服务网页端与 Android App 端。

> 最后更新：2026-08。模型 (LLM) 配置**只存数据库**（每个用户登录后在网页
> 「模型设置」页配置），部署时**不需要**任何模型 API Key 环境变量。

## 1. 架构与文件总览

```
                     ┌──────────────────────────────────────────────┐
  浏览器 (网页端) ───►  nginx :80 (test: HTTP 直连)                  │
                     │   :80 -> 301 :443 (prod)                     │
  Android App ──────►  /api  ──► FastAPI :8000 (zhixue 容器)         │
  (Capacitor APK)    │   /    ──► FastAPI 托管前端 dist (SPA)        │
                     │        ──► postgres:5432 (pgdata 卷持久化)    │
                     └──────────────────────────────────────────────┘
```

| 文件 | 用途 |
|---|---|
| `Dockerfile` | 两阶段构建：前端 `vite build` + Python 后端（uvicorn 同时托管 API 与前端静态产物） |
| `docker-compose.test.yml` | **测试环境**编排：nginx 纯 HTTP 80，无证书 |
| `docker-compose.prod.yml` | **线上环境**编排：nginx 80 跳 443 + SSL（证书挂载 `./nginx/ssl`） |
| `nginx/zhixue-test.conf` | 测试环境 nginx 配置（HTTP） |
| `nginx/zhixue.conf` | 线上环境 nginx 配置（HTTPS；`/api` 反代关闭缓冲以支持 SSE 流式） |
| `nginx/ssl/` | 线上证书目录（gitignore，绝不提交） |
| `scripts/deploy.sh` | 部署脚本：`sudo bash scripts/deploy.sh test\|prod` |
| `deploy.env.example` | 部署配置模板 → 复制为服务器上的 `.env`（gitignore） |

`/api/health` 现在需要登录（按当前用户判定模型配置状态），匿名请求返回
**401** —— 部署脚本的健康检查正是以「收到 401」作为整条链路（nginx → 后端
→ PostgreSQL）就绪的标志。

## 2. 首次部署准备（两个环境都需要）

服务器要求：root 权限、Docker + Docker Compose v2、curl、git。

```bash
# 1. root 能拉取仓库 (SSH key 放 /root/.ssh 或改 deploy.sh 的 REPO_URL 用 https)
ssh -T git@github.com     # 验证

# 2. 准备部署目录并写配置
sudo git clone git@github.com:pengliuah/zhixue.git /opt/zhixue
cd /opt/zhixue
sudo cp deploy.env.example .env
sudo vi .env
```

`.env` 关键项（完整说明见模板内注释）：

| 变量 | 说明 |
|---|---|
| `POSTGRES_PASSWORD` | 数据库密码。**注意**：`pgdata` 卷已用旧密码初始化过的话，改这里不会改库密码，需与卷保持一致（默认 `123`） |
| `JWT_SECRET` | JWT 签名密钥。不设则每次重启随机生成、所有用户需重新登录。**强烈建议设置**：`python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 首次启动引导管理员（仅 users 表为空时创建）。请设置强密码；登录后可在网页「账号设置」页修改 |
| `LOG_LEVEL` | 后端日志级别，测试环境默认 INFO，线上默认 WARNING |

## 3. 测试环境部署（HTTP，IP 直连）

```bash
sudo bash scripts/deploy.sh test
```

完成后访问 `http://<服务器IP>/`，用引导管理员账号登录。安全组/防火墙放行 **80**。

## 4. 线上环境部署（HTTPS，域名 + 证书）

域名：`www.ailearningagent.xyz`，证书：阿里云 Nginx 版。先完成第 2 节准备，
再放证书：

```bash
cd /opt/zhixue
sudo cp <你的证书>.pem nginx/ssl/www.ailearningagent.xyz.pem
sudo cp <你的私钥>.key nginx/ssl/www.ailearningagent.xyz.key
```

| 阿里云下载文件 | 放置路径 |
|---|---|
| `xxx.pem`（证书 fullchain） | `nginx/ssl/www.ailearningagent.xyz.pem` |
| `xxx.key`（私钥） | `nginx/ssl/www.ailearningagent.xyz.key` |

- 两个文件已被 `.gitignore` 忽略，绝不提交；`reset --hard` 不会碰它们。
- 证书续期后替换这两个文件，`docker compose -f docker-compose.prod.yml restart nginx` 即可。
- `deploy.sh prod` 启动前会校验这两个文件存在，缺失会拒绝部署（nginx 无证书起不来）。

```bash
sudo bash scripts/deploy.sh prod
```

安全组/防火墙放行 **443**（主）和 **80**（跳转 443）。完成后访问
`https://www.ailearningagent.xyz/`。

## 5. 部署脚本做了什么

`sudo bash scripts/deploy.sh test|prod` 依次执行：

1. `docker compose down` 停掉旧容器（并按镜像名兜底清理残留）；
2. 备份服务器上自定义的 `docker-compose.<env>.yml` 与 `.env` 到 `/opt/`（带时间戳）；
3. `git fetch + reset --hard origin/master` 拉取最新代码
   （`.env`、`nginx/ssl/`、`backend/data/` 均被 gitignore，不受影响）；
4. 恢复第 2 步备份的自定义配置；prod 额外校验证书文件存在；
5. 构建镜像、启动，轮询 `/api/health` 最多 60 秒（test 走 `http://127.0.0.1`，
   prod 走 `https://127.0.0.1` 加 `-k`——80 端口会对所有请求 301 跳 HTTPS，
   必须直接探测 443 才能拿到后端应答），收到 **401** 即判定部署成功；
   超时失败会提示用 `docker compose -f docker-compose.<env>.yml logs zhixue` 排查。

数据库表结构迁移是**自动**的：后端启动时 `init_schema()` 幂等执行增量迁移
（账号系统、每用户设置表等），无需手动执行 SQL；数据库本身由
`docker-entrypoint-initdb.d` 在卷首次初始化时执行 `db/schema.sql`。

## 6. 部署后验证清单

1. 打开站点 → 自动跳转登录页（星空页）→ 用引导管理员登录；
2. **立即修改密码**：右上角点用户名 →「账号设置」→ 修改（会踢掉所有会话，用新密码重登）；
3. **配置模型**：右上角「模型设置」→ 填 API Key / 模型名 / Base URL（如
   `doubao-1.5-pro-32k` 或推理端点 ID `ep-xxx`）→ 保存。首页顶栏不再出现
   "未配置模型" 的黄色提示即生效；
4. 新建一个学习计划验证生成链路（SSE 流式输出正常）；
5. （线上）`curl -I https://www.ailearningagent.xyz/` 确认 301/200 与证书有效期。

## 7. 日常更新 / 回滚

```bash
# 更新到最新 master
sudo bash scripts/deploy.sh prod      # 或 test

# 回滚代码: 在 /opt/zhixue 检出旧 commit 后重新构建
cd /opt/zhixue && git checkout <旧commit>
docker compose -f docker-compose.prod.yml build && \
docker compose -f docker-compose.prod.yml up -d
```

数据备份（学习计划都在 PostgreSQL，`backend/data/` 仅剩遗留 plans.json）：

```bash
docker compose -f docker-compose.prod.yml exec postgres \
  pg_dump -U postgres zhixue > zhixue_backup_$(date +%F).sql
# 恢复: cat backup.sql | docker compose -f docker-compose.prod.yml exec -T postgres psql -U postgres zhixue
```

## 8. App 端打包（在有 Android SDK 的开发机上）

App 从 `https://www.ailearningagent.xyz/api` 跨域访问（WebView origin 是
`https://localhost`，相对 `/api` 会解析到设备本地，必须注入绝对地址）：

```bash
cd mobile
VITE_API_BASE=https://www.ailearningagent.xyz/api npm run dev:apk   # 调试 APK
```

- 测试环境（IP + HTTP）也可打包装到手机上，把 `VITE_API_BASE` 换成
  `http://<服务器IP>/api`；
- 域名/证书或 IP 变更需重新打包（地址在构建时固化）；
- 后端 CORS 为 `allow_origins=["*"]`（Bearer token 方案，无需 cookie），跨域已就绪。

## 9. 各端 API 基址对照

| 端 | 构建方式 | `VITE_API_BASE` | 运行时 API_BASE |
|---|---|---|---|
| 本地开发 | `vite`（代理 /api） | 不设 | `/api`（vite 代理到 127.0.0.1:8000） |
| 网页生产（test/prod） | Docker 内 `vite build` | 不设 | `/api`（nginx 同源反代） |
| App 生产 | `mobile/scripts/sync.mjs` | `https://www.ailearningagent.xyz/api` | 绝对地址（跨域） |

## 10. 常见问题排查

| 现象 | 排查 |
|---|---|
| 健康检查 000/超时 | `docker compose -f docker-compose.<env>.yml ps && logs zhixue`；常见为 `.env` 缺失或 DATABASE_URL 密码与 pgdata 卷不一致 |
| prod nginx 起不来 | 证书文件缺失/命名不对（看 `logs nginx`）；`deploy.sh prod` 会提前校验 |
| 登录后每 次重启都要重登 | `.env` 未设 `JWT_SECRET`（每次重启随机生成） |
| 忘记 admin 密码 | 另一个 admin 可在「用户管理」重置；没有其他 admin 时需在数据库重置（bcrypt 哈希，找开发处理） |
| 生成功能 503 | 该用户未配置模型 API Key——右上角「模型设置」页配置（按用户存数据库，不是环境变量） |
| SSE 流式内容卡住不出 | 确认用的是本仓库 nginx 配置（`proxy_buffering off` 是关键） |
