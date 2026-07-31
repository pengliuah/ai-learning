#!/usr/bin/env bash
#
# zhixue 自动部署脚本 (Linux, 测试环境)
#
# 测试环境: 不启用 SSL, 直接用 IP 访问 (http://<服务器IP>/)。
#
# 流程:
#   1. 停掉旧容器 (zhixue + nginx)
#   2. 备份 /opt/zhixue/docker-compose.yml 到 /opt (保留服务器自定义配置)
#   3. 拉取最新代码到 /opt/zhixue (reset --hard 会还原仓库版 compose)
#   4. 用 /opt 中的 compose 备份覆盖 /opt/zhixue/docker-compose.yml
#   5. 构建新镜像并重启服务
#
# 用法:
#   sudo bash scripts/deploy.sh
#
# 首次运行前:
#   - root 需能访问 git@github.com:pengliuah/zhixue.git (部署用 SSH key 放在 /root/.ssh)
#   - 编辑 /opt/zhixue/docker-compose.yml 填入 ARK_API_KEY
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

# ---- 2. 备份 docker-compose.yml 到 /opt ----
# 保存服务器上当前的自定义 compose 配置 (如已填入 ARK_API_KEY)。
# 第 3 步 reset --hard 会把 compose 还原为仓库版本, 第 4 步用此备份覆盖回去。
if [ -f "$COMPOSE_FILE" ]; then
  ts=$(date +%Y%m%d-%H%M%S)
  cp -a "$COMPOSE_FILE" "$BACKUP_DIR/docker-compose.yml.bak.$ts"   # 带时间戳归档 (第 4 步恢复后会清理)
  cp -a "$COMPOSE_FILE" "$BACKUP_FILE"                             # 稳定副本, 第 4 步从此恢复
  log "2/5 已备份 $COMPOSE_FILE -> $BACKUP_FILE (归档 .bak.$ts)"
else
  log "2/5 $COMPOSE_FILE 不存在 (首次部署?), 跳过备份"
fi

# ---- 3. 拉取最新代码到 /opt/zhixue ----
log "3/5 拉取最新代码到 $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  # fetch + reset --hard 刷新到 origin/$BRANCH.
  # reset --hard 只覆盖跟踪文件, 保留 gitignored 持久状态 (backend/data 学习数据);
  # 仓库自带的 docker-compose.yml 会被还原为版本库版本, 随后第 4 步用自定义备份覆盖。
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

# ---- 4. 用 /opt 中的 compose 备份覆盖 /opt/zhixue/docker-compose.yml ----
if [ -f "$BACKUP_FILE" ]; then
  cp -a "$BACKUP_FILE" "$COMPOSE_FILE"
  log "4/5 已恢复自定义 $COMPOSE_FILE <- $BACKUP_FILE"
  # 恢复后清理 /opt 中所有 docker-compose.yml.bak* 备份文件 (含稳定副本与时间戳归档)
  rm -f "$BACKUP_DIR"/docker-compose.yml.bak*
  log "4/5 已清理备份文件 $BACKUP_DIR/docker-compose.yml.bak*"
else
  log "4/5 无备份可恢复 ($BACKUP_FILE 不存在), 使用仓库自带 compose 文件"
fi

# ---- 5. 构建新镜像并重启服务 ----
log "5/5 构建镜像并启动服务"
cd "$APP_DIR"
docker compose build
docker compose up -d

log "部署完成, 当前容器状态:"
docker compose ps
