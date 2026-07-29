#!/usr/bin/env bash
#
# zhixue 自动部署脚本 (Linux, 测试环境)
#
# 测试环境: 不启用 SSL, 直接用 IP 访问 (http://<服务器IP>/)。
#
# 流程:
#   1. 停掉旧容器 (zhixue + nginx)
#   2. 拉取最新代码到 /opt/zhixue
#   3. 跳过 SSL 证书检查 (测试环境使用 HTTP)
#   4. 构建新镜像并重启服务
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
BRANCH=${BRANCH:-test-env}
IMAGE=${IMAGE:-zhixue-zhixue}
# ========================================

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
log "1/4 停止并移除旧容器"
cd "$APP_DIR" 2>/dev/null && docker compose down 2>/dev/null || true
# 兜底: 按镜像名清理残留容器
old_containers=$(docker ps -aq --filter "ancestor=$IMAGE")
if [ -n "$old_containers" ]; then
  docker rm -f $old_containers
  log "已移除旧容器: $(echo $old_containers | tr '\n' ' ')"
else
  log "无残留容器, 跳过"
fi

# ---- 2. 拉取最新代码到 /opt/zhixue ----
log "2/4 拉取最新代码到 $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  # 已存在: fetch + reset --hard 刷新到 origin/$BRANCH.
  # reset --hard 只覆盖跟踪文件, 保留 gitignored 持久状态 (.env 密钥, backend/data
  # 学习数据).
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

# 密钥提醒: .env 与环境变量都没有时, LLM 端点会 503
if [ ! -f "$APP_DIR/.env" ] && [ -z "${ARK_API_KEY:-}" ]; then
  warn "未找到 $APP_DIR/.env 且环境变量 ARK_API_KEY 未设置; 若 compose 未硬编码密钥, LLM 端点将返回 503"
fi

# ---- 3. SSL 证书 (测试环境: 不需要) ----
log "3/4 跳过 SSL 证书检查 (测试环境使用 HTTP)"

# ---- 4. 构建新镜像并重启服务 ----
log "4/4 构建镜像并启动服务"
cd "$APP_DIR"
docker compose build
docker compose up -d

log "部署完成, 当前容器状态:"
docker compose ps
