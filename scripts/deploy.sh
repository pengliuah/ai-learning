#!/usr/bin/env bash
#
# zhixue 自动部署脚本 (Linux)
#
# 流程:
#   1. 停掉以 zhixue-zhixue 镜像构建的旧容器
#   2. 备份 /opt/zhixue/docker-compose.yml 到 /opt
#   3. 拉取最新代码到 /opt/zhixue
#   4. 将 /opt 中的 compose 备份写回 /opt/zhixue/docker-compose.yml
#   5. 构建新镜像并重启服务
#
# 用法:
#   sudo bash scripts/deploy.sh
#
# 首次运行前:
#   - root 需能访问 git@github.com:pengliuah/zhixue.git (部署用 SSH key 放在 /root/.ssh)
#   - 在 /opt/zhixue/.env 填入 ARK_API_KEY (可参考 .env.example)
#
set -euo pipefail

# ===== 可配置项 (可用环境变量覆盖) =====
APP_DIR=${APP_DIR:-/opt/zhixue}
REPO_URL=${REPO_URL:-git@github.com:pengliuah/zhixue.git}
BRANCH=${BRANCH:-master}
BACKUP_DIR=${BACKUP_DIR:-/opt}
IMAGE=${IMAGE:-zhixue-zhixue}
# ========================================

COMPOSE_FILE="$APP_DIR/docker-compose.yml"
BACKUP_FILE="$BACKUP_DIR/docker-compose.yml.bak"

log()  { printf '\033[1;34m[deploy]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }

# 写 /opt 与调用 docker 都需要 root
if [ "$(id -u)" -ne 0 ]; then
  err "请使用 root 或 sudo 运行 (需写 /opt 并调用 docker)"
  exit 1
fi

# 依赖检查
for c in git docker; do
  command -v "$c" >/dev/null 2>&1 || { err "未找到命令: $c"; exit 1; }
done
docker compose version >/dev/null 2>&1 || { err "未找到 'docker compose' (需 Docker Compose v2)"; exit 1; }

# ---- 1. 停掉以 zhixue-zhixue 镜像构建的旧容器 ----
log "1/5 停止并移除基于 $IMAGE 镜像的容器"
old_containers=$(docker ps -aq --filter "ancestor=$IMAGE")
if [ -n "$old_containers" ]; then
  docker rm -f $old_containers
  log "已移除旧容器: $(echo $old_containers | tr '\n' ' ')"
else
  log "无运行中的 $IMAGE 容器, 跳过"
fi

# ---- 2. 备份 docker-compose.yml 到 /opt ----
if [ -f "$COMPOSE_FILE" ]; then
  ts=$(date +%Y%m%d-%H%M%S)
  cp -a "$COMPOSE_FILE" "$BACKUP_DIR/docker-compose.yml.bak.$ts"   # 带时间戳归档, 便于回滚
  cp -a "$COMPOSE_FILE" "$BACKUP_FILE"                             # 稳定副本, 第 4 步从此恢复
  log "2/5 已备份 $COMPOSE_FILE -> $BACKUP_FILE (归档 .bak.$ts)"
else
  log "2/5 $COMPOSE_FILE 不存在 (首次部署?), 跳过备份"
fi

# ---- 3. 拉取最新代码到 /opt/zhixue ----
log "3/5 拉取最新代码到 $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  # 已存在: 用 fetch + reset --hard 把仓库跟踪文件刷新到 origin/$BRANCH.
  # 注意: 这里没有用裸 git clone, 因为目标目录已存在 clone 会失败, 且会清掉
  # gitignored 的持久状态 (.env 密钥, backend/data 学习数据). reset --hard 只覆盖
  # 跟踪文件, 保留上述持久状态; 仓库自带的 docker-compose.yml 会被还原为版本库版本,
  # 随后第 4 步用自定义备份覆盖.
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

# ---- 4. 将备份的 compose 文件写回 ----
if [ -f "$BACKUP_FILE" ]; then
  cp -a "$BACKUP_FILE" "$COMPOSE_FILE"
  log "4/5 已恢复自定义 $COMPOSE_FILE <- $BACKUP_FILE"
else
  log "4/5 无备份可恢复 ($BACKUP_FILE 不存在), 使用仓库自带 compose 文件"
fi

# 密钥提醒: .env 与环境变量都没有时, LLM 端点会 503 (除非 compose 内硬编码了 ARK_API_KEY)
if [ ! -f "$APP_DIR/.env" ] && [ -z "${ARK_API_KEY:-}" ]; then
  warn "未找到 $APP_DIR/.env 且环境变量 ARK_API_KEY 未设置; 若 compose 未硬编码密钥, LLM 端点将返回 503"
fi

# ---- 5. 构建新镜像并重启服务 ----
log "5/5 构建镜像并启动服务"
cd "$APP_DIR"
docker compose build
docker compose up -d

log "部署完成, 当前容器状态:"
docker compose ps