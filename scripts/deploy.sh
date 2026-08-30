#!/usr/bin/env bash
#
# zhixue 自动部署脚本 (Linux, 支持 测试/线上 双环境)
#
# 用法:
#   sudo bash scripts/deploy.sh test    # 测试环境: 纯 HTTP, IP 访问 (compose: docker-compose.test.yml)
#   sudo bash scripts/deploy.sh prod    # 线上环境: HTTPS 域名证书 (compose: docker-compose.prod.yml)
#
# 流程:
#   1. 停掉旧容器
#   2. 备份服务器上自定义的 compose / .env (保留服务器侧配置)
#   3. 拉取最新代码到 /opt/zhixue
#   4. 恢复自定义配置 (prod 额外校验证书文件存在)
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
  echo "用法: sudo bash scripts/deploy.sh test|prod"
  exit 1
}

ENV=${1:-}
[ "$ENV" = "test" ] || [ "$ENV" = "prod" ] || usage

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

# ---- 2. 备份服务器自定义配置 (compose 与 .env) ----
# git reset --hard 只覆盖跟踪文件; 这里备份的是服务器侧可能改过的文件。
ts=$(date +%Y%m%d-%H%M%S)
if [ -f "$APP_DIR/$COMPOSE_FILE" ]; then
  cp -a "$APP_DIR/$COMPOSE_FILE" "$BACKUP_DIR/$COMPOSE_FILE.bak.$ts"
  log "2/5 已备份 $COMPOSE_FILE -> $BACKUP_DIR/"
else
  log "2/5 $COMPOSE_FILE 不存在 (首次部署?), 跳过备份"
fi
if [ -f "$APP_DIR/.env" ]; then
  cp -a "$APP_DIR/.env" "$BACKUP_DIR/zhixue.env.bak.$ts"
  log "2/5 已备份 .env -> $BACKUP_DIR/zhixue.env.bak.$ts"
else
  warn "$APP_DIR/.env 不存在 — 部署后将用 deploy.env.example 的默认值 (JWT_SECRET 为空, ADMIN_PASSWORD 为空!)"
fi

# ---- 3. 拉取最新代码 ----
log "3/5 拉取最新代码到 $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  # reset --hard 只覆盖跟踪文件; .env / nginx/ssl / backend/data 均被 gitignore, 不受影响
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

# ---- 4. 恢复自定义配置 + 环境前置校验 ----
if [ -f "$BACKUP_DIR/$COMPOSE_FILE.bak.$ts" ]; then
  cp -a "$BACKUP_DIR/$COMPOSE_FILE.bak.$ts" "$APP_DIR/$COMPOSE_FILE"
  log "4/5 已恢复自定义 $COMPOSE_FILE"
fi
if [ -f "$BACKUP_DIR/zhixue.env.bak.$ts" ]; then
  cp -a "$BACKUP_DIR/zhixue.env.bak.$ts" "$APP_DIR/.env"
  log "4/5 已恢复自定义 .env"
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

# ---- 5. 构建镜像并启动, 健康检查 ----
log "5/5 构建镜像并启动服务 ($ENV)"
cd "$APP_DIR"
docker compose -f "$COMPOSE_FILE" build
docker compose -f "$COMPOSE_FILE" up -d

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
