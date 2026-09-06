#!/usr/bin/env bash
#
# zhixue 自动部署脚本 (Linux, 支持 测试/线上 双环境)
#
# 用法:
#   sudo bash scripts/deploy.sh test          # 测试环境: 纯 HTTP, IP 访问 (compose: docker-compose.test.yml)
#   sudo bash scripts/deploy.sh prod          # 线上环境: HTTPS 域名证书 (compose: docker-compose.prod.yml)
#   sudo bash scripts/deploy.sh test debug    # 可选第 2 个参数: 后端日志级别, 默认 INFO (如 info/debug/warning)
#
# 流程:
#   1. 停掉旧容器
#   2. 备份服务器上的 .env (每类只保留最新一份); compose 是 git 跟踪文件, 不备份
#      不恢复 —— 否则旧备份会把新 compose 盖回旧版, 导致存储方式等更新永不生效
#   3. 拉取最新代码到 /opt/zhixue
#   4. 恢复 .env, 环境前置校验
#   5. 构建镜像并启动, 轮询 /api/health 健康检查 (预期 401 = 后端活着且鉴权生效)
#
# 首次部署前 (见 DEPLOY.md):
#   - root 能访问 git@github.com:pengliuah/zhixue.git (SSH key 放 /root/.ssh)
#   - cp deploy.env.example .env && vi .env   # 设置 JWT_SECRET / ADMIN_PASSWORD / POSTGRES_PASSWORD
#   - prod 还需把域名证书放入 nginx/ssl/ (两个文件, 见 DEPLOY.md)
#
set -euo pipefail

# ===== 可配置项 (可用环境变量覆盖) =====
APP_DIR=${APP_DIR:-/opt/zhixue}
REPO_URL=${REPO_URL:-git@github.com:pengliuah/zhixue.git}
BRANCH=${BRANCH:-master}
IMAGE=${IMAGE:-zhixue-zhixue}
BACKUP_DIR=${BACKUP_DIR:-/opt}
# ========================================

log()  { printf '\033[1;34m[deploy]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }

usage() {
  echo "用法: sudo bash scripts/deploy.sh test|prod [日志级别]"
  echo "  日志级别: 可选, 默认 INFO (大小写不敏感, 如 debug/warning; 写入 .env 的 LOG_LEVEL)"
  exit 1
}

ENV=${1:-}
[ "$ENV" = "test" ] || [ "$ENV" = "prod" ] || usage
# 日志级别: 默认 INFO; 指定则原样采用 (统一大写), 由 compose 传给后端
LOG_LEVEL_ARG=$(printf '%s' "${2:-INFO}" | tr '[:lower:]' '[:upper:]')
ts=$(date +%Y%m%d-%H%M%S)
PGDATA_DIR="$APP_DIR/pgdata"
OLD_DB_VOLUME="zhixue_pgdata"

COMPOSE_FILE="docker-compose.$ENV.yml"
CERT_PEM="nginx/ssl/www.ailearningagent.xyz.pem"
CERT_KEY="nginx/ssl/www.ailearningagent.xyz.key"

# 写 /opt 与调用 docker 都需要 root
if [ "$(id -u)" -ne 0 ]; then
  err "请使用 root 或 sudo 运行 (需写 /opt 并调用 docker)"
  exit 1
fi

# 依赖检查
for c in git docker curl; do
  command -v "$c" >/dev/null 2>&1 || { err "未找到命令: $c"; exit 1; }
done
docker compose version >/dev/null 2>&1 || { err "未找到 'docker compose' (需 Docker Compose v2)"; exit 1; }

# ---- 0. 部署前数据库备份 (任何持久化变更/翻车都可回) ----
# 按容器名匹配 (项目名-postgres-1), 不按镜像过滤: postgres 镜像已换成
# pgvector/pgvector:pg16, 按 ancestor=postgres:16-alpine 匹配会漏掉新镜像
running_pg=$(docker ps -q --filter "name=postgres" | head -1)
if [ -n "$running_pg" ]; then
  mkdir -p "$BACKUP_DIR"
  if docker exec "$running_pg" pg_dumpall -U postgres 2>/dev/null | gzip > "$BACKUP_DIR/zhixue-db-$ts.sql.gz"; then
    log "0/5 已备份数据库 -> $BACKUP_DIR/zhixue-db-$ts.sql.gz ($(du -h "$BACKUP_DIR/zhixue-db-$ts.sql.gz" | cut -f1))"
  else
    warn "数据库备份失败 (pg_dumpall), 继续部署但数据不可回滚!"
  fi
else
  warn "0/5 未发现运行中的 postgres 容器, 跳过数据库备份"
fi

# ---- 1. 停掉旧容器 ----
log "1/5 停止并移除旧容器"
cd "$APP_DIR" 2>/dev/null && docker compose down 2>/dev/null || true
# 兜底: 按镜像名清理残留容器
old_containers=$(docker ps -aq --filter "ancestor=$IMAGE")
if [ -n "$old_containers" ]; then
  docker rm -f $old_containers
  log "已移除旧容器: $(echo $old_containers | tr '\n' ' ')"
else
  log "无残留容器, 跳过"
fi

# 一次性迁移: 旧部署的数据库在命名卷 zhixue_pgdata 里, 现改为宿主机
# ./pgdata 持久化; 卷存在且目标目录为空时把数据搬过来 (postgres 已停止, 拷贝安全)
if docker volume inspect "$OLD_DB_VOLUME" >/dev/null 2>&1 && [ ! -f "$PGDATA_DIR/PG_VERSION" ]; then
  log "检测到旧数据库卷 $OLD_DB_VOLUME, 迁移到 $PGDATA_DIR (一次性)..."
  mkdir -p "$PGDATA_DIR"
  docker run --rm -v "$OLD_DB_VOLUME":/from:ro -v "$PGDATA_DIR":/to alpine \
    sh -c 'cp -a /from/. /to/ && chown -R 70:70 /to'
  log "旧卷数据已迁移到 $PGDATA_DIR"
fi

# ---- 2. 备份服务器上的 .env ----
# .env 被 gitignore, 属于服务器侧数据, 覆盖更新前必须备份。
# compose 文件是 git 跟踪的, 不做备份/恢复: 曾经的"恢复旧备份"会把新 compose
# 盖回旧版 (存储方式等改进永不生效, 还会反复清库), 这是刻意移除的行为。
if [ -f "$APP_DIR/.env" ]; then
  cp -a "$APP_DIR/.env" "$BACKUP_DIR/zhixue.env.bak.$ts"
  log "2/5 已备份 .env -> $BACKUP_DIR/zhixue.env.bak.$ts"
else
  warn "$APP_DIR/.env 不存在 — 部署后将用 deploy.env.example 的默认值 (JWT_SECRET 为空, ADMIN_PASSWORD 为空!)"
fi

# 备份清理: 每类备份只保留最新一份 (ls -t 按时间排, 当前这次的最新, 不会被删)。
# 末尾 || true: glob 无匹配时 ls 退出码非 0, 在 pipefail 下会中断整个脚本。
# compose 备份已不再生成, 保留 pattern 以清理历史残留文件。
for pattern in "docker-compose.*.yml.bak.*" "zhixue.env.bak.*" "zhixue-db-*.sql.gz"; do
  ls -1t "$BACKUP_DIR"/$pattern 2>/dev/null | tail -n +2 | while IFS= read -r f; do
    rm -f "$f"
  done || true
done
log "2/5 旧备份已清理: $BACKUP_DIR 下每类备份只保留最新一份"

# ---- 3. 拉取最新代码 ----
log "3/5 拉取最新代码到 $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  # reset --hard 只覆盖跟踪文件; .env / nginx/ssl 均被 gitignore, 不受影响
  git -C "$APP_DIR" fetch --all --prune
  git -C "$APP_DIR" reset --hard "origin/$BRANCH"
  log "已更新现有检出至 origin/$BRANCH"
else
  if [ -e "$APP_DIR" ]; then
    err "$APP_DIR 已存在但不是 git 仓库, 请手动处理后重试"
    exit 1
  fi
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
  log "已克隆到 $APP_DIR"
fi

# ---- 4. 恢复 .env + 环境前置校验 ----
# compose 已由 git reset 更新为最新仓库版本, 不再从备份恢复 (见步骤 2 说明)。
if [ -f "$BACKUP_DIR/zhixue.env.bak.$ts" ]; then
  cp -a "$BACKUP_DIR/zhixue.env.bak.$ts" "$APP_DIR/.env"
  log "4/5 已恢复 .env"
fi

if [ "$ENV" = "prod" ]; then
  # 线上环境必须有证书, 否则 nginx 起不来
  if [ ! -f "$APP_DIR/$CERT_PEM" ] || [ ! -f "$APP_DIR/$CERT_KEY" ]; then
    err "线上环境缺少证书文件:"
    err "  $APP_DIR/$CERT_PEM"
    err "  $APP_DIR/$CERT_KEY"
    err "请把阿里云下载的 Nginx 证书放入 nginx/ssl/ 后重试 (见 DEPLOY.md)"
    exit 1
  fi
  log "4/5 证书文件校验通过"
fi

# JWT_SECRET 为空时给出提醒 (功能可用, 但重启会踢掉所有登录态)
if [ -f "$APP_DIR/.env" ] && grep -qE '^JWT_SECRET=\s*$' "$APP_DIR/.env"; then
  warn "JWT_SECRET 未设置: 每次重启后所有用户需重新登录, 建议在 .env 中配置"
fi

# 日志级别: 写入/更新 .env 的 LOG_LEVEL (无 .env 时先从模板创建)
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/deploy.env.example" "$APP_DIR/.env"
  log "4/5 已从 deploy.env.example 创建 .env (请尽快设置 JWT_SECRET / ADMIN_PASSWORD)"
fi
if grep -qE '^LOG_LEVEL=' "$APP_DIR/.env"; then
  sed -i "s/^LOG_LEVEL=.*/LOG_LEVEL=$LOG_LEVEL_ARG/" "$APP_DIR/.env"
else
  printf '\n# --- 后端日志级别 (deploy.sh 第 2 个参数) ---\nLOG_LEVEL=%s\n' "$LOG_LEVEL_ARG" >> "$APP_DIR/.env"
fi
log "4/5 后端日志级别: $LOG_LEVEL_ARG (已写入 $APP_DIR/.env)"

# ---- 5. 构建镜像并启动, 健康检查 ----
log "5/5 构建镜像并启动服务 ($ENV)"
cd "$APP_DIR"
docker compose -f "$COMPOSE_FILE" build
docker compose -f "$COMPOSE_FILE" up -d

# pgvector 扩展 (幂等): AI 记忆/向量检索依赖; pgvector 镜像自带, 官方镜像没有会 warn
if docker compose -f "$COMPOSE_FILE" exec -T postgres psql -U postgres -d zhixue \
    -c 'CREATE EXTENSION IF NOT EXISTS vector;' >/dev/null 2>&1; then
  log "pgvector 扩展就绪"
else
  warn "CREATE EXTENSION vector 失败 (postgres 镜像可能不含 pgvector, 记忆功能不可用)"
fi

# 健康检查: /api/health 需登录, 401 即代表 nginx→后端→DB 链路活着且鉴权生效。
# prod 必须走 https (80 端口对所有路径 301 跳 443, 打 http 永远拿不到后端应答);
# 证书签给域名而探测用 127.0.0.1, 故加 -k 跳过证书校验。
URL_SCHEME=http
CURL_FLAGS=()
if [ "$ENV" = "prod" ]; then
  URL_SCHEME=https
  CURL_FLAGS=(-k)
fi
log "健康检查: 轮询 $URL_SCHEME://127.0.0.1/api/health (预期 401)..."
ok=""
for i in $(seq 1 30); do
  code=$(curl "${CURL_FLAGS[@]}" -s -o /dev/null -w '%{http_code}' --max-time 3 "$URL_SCHEME://127.0.0.1/api/health" || true)
  if [ "$code" = "401" ]; then
    ok=1
    break
  fi
  sleep 2
done

if [ -n "$ok" ]; then
  log "健康检查通过 (401): 服务已就绪"
else
  err "健康检查未通过 (最后状态码: ${code:-无})。排查:"
  err "  docker compose -f $COMPOSE_FILE ps"
  err "  docker compose -f $COMPOSE_FILE logs zhixue"
  exit 1
fi

log "部署完成 ($ENV), 当前容器状态:"
docker compose -f "$COMPOSE_FILE" ps
if [ "$ENV" = "prod" ]; then
  log "访问入口: https://www.ailearningagent.xyz/  (prod 环境, 详情见 DEPLOY.md)"
else
  log "访问入口: http://localhost/  (test 环境, 详情见 DEPLOY.md)"
fi
