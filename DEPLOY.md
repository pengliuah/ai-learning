# 部署方案 (网页端 + App 端)

一份部署同时服务网页端与 Android App 端, 共用同一套后端与 nginx 入口。

## 1. 架构

```
                       ┌───────────────────────────────────────────┐
   浏览器 (网页端) ─────►  nginx :80  ──┐                          │
                       │   (default_server, server_name _)         │
   Android App ───────►  /api  ──► FastAPI :8000 (zhixue 容器)      │
   (Capacitor APK)     │   /    ──► FastAPI 托管前端 dist (SPA)     │
                       └───────────────────────────────────────────┘
```

- **单一入口**: nginx 监听 80, 同时反代 `/api` 与 `/` 到 FastAPI 容器。
- **网页端**: 浏览器从 `http://<服务器IP>/` 加载页面, API 走相对 `/api` (同源, nginx 反代)。
- **App 端**: APK 内嵌前端, 但 Capacitor WebView 的 origin 是 `https://localhost`,
  相对 `/api` 会解析到设备本地而非服务器。因此 App 打包时注入 **绝对地址**
  `VITE_API_BASE=http://<服务器IP>/api`, 跨域请求后端。

## 2. 为什么 App 之前取不到数据

前端 `client.ts` 原本硬编码 `const API_BASE = "/api"`。
- 网页端: 浏览器 origin 就是服务器, `/api` 同源 → 正常。
- App 端: WebView origin 是 `https://localhost`, `/api` 解析到设备本地 → 永远打不到服务器。

修复: `API_BASE` 改为 `import.meta.env.VITE_API_BASE || "/api"`。
- 网页端构建: 不设该变量 → 用 `/api`。
- App 端构建 (`mobile/scripts/sync.mjs`): 必须设 `VITE_API_BASE`, 否则中止构建。

跨域已就绪, 无需改服务端:
- 后端 CORS `allow_origins=["*"]` + `allow_credentials=False`, 自动处理 `https://localhost` 的预检。
- Capacitor 配置 `cleartext: true` + `allowMixedContent: true`, 允许 App 走 HTTP。
- nginx `server_name _` + `default_server`, 接受任意 Host (含纯 IP)。

## 3. 服务器部署 (网页端 + App 的后端)

在 Linux 服务器上 (需 root, 需 docker):

1. 首次: 克隆仓库到 `/opt/zhixue`, 编辑 `docker-compose.yml` 填入 `ARK_API_KEY`。
2. 部署/更新: `sudo bash scripts/deploy.sh`
   - 默认拉取 `origin/master` (`BRANCH` 环境变量可覆盖)。
   - `docker-compose.yml` 会被 `reset --hard` 还原为仓库版, 随后用 `/opt` 中的备份
     (含 `ARK_API_KEY`) 覆盖回去; 首次部署需手动填一次 key。
3. 安全组/防火墙放行 **80 端口** (App 与网页都从此入口)。
4. 验证: `curl http://<服务器IP>/api/health` → `{"configured":true,"model":"..."}`。

> 服务器仅需 80 可达。App 与网页都打 `http://<服务器IP>`。

## 4. App 端打包 (在有 Android SDK 的开发机上)

App 必须知道后端绝对地址, 在 `mobile/` 目录构建时通过 `VITE_API_BASE` 注入:

PowerShell:
```powershell
cd mobile
$env:VITE_API_BASE="http://<服务器IP>/api"
npm run build:apk        # release APK -> mobile/android/app/build/outputs/apk/release/
# 或调试包:
npm run dev:apk
```

bash:
```bash
cd mobile
VITE_API_BASE=http://<服务器IP>/api npm run build:apk
```

注意事项:
- `<服务器IP>` 必须是 App 设备能访问到的地址 (公网 IP, 或与手机同网段的局域网 IP)。
- 服务器 IP 变更需重新打包 APK (地址在构建时固化)。
- 真机与服务器网络不通时, App 会显示健康提示 (连接失败), 属预期行为。

## 5. 升级到 HTTPS / 域名 (生产环境, 可选)

App 上架应用商店前建议改 HTTPS:

1. nginx 增加 SSL 配置 (443 + 证书), 80 跳转 443。
2. App 打包改用 `VITE_API_BASE=https://<域名>/api`。
3. HTTPS 后可移除 Capacitor 的 `cleartext`/`allowMixedContent` 依赖 (当前为兼容 HTTP 测试环境而开)。

## 6. 各端 API 基址对照

| 端        | 构建方式              | VITE_API_BASE            | 运行时 API_BASE        |
|-----------|-----------------------|--------------------------|------------------------|
| 本地开发  | `vite` (代理 /api)    | 不设                     | `/api` (走 vite 代理)  |
| 网页生产  | Docker 内 `vite build`| 不设                     | `/api` (nginx 同源)    |
| App 生产  | `mobile/ sync.mjs`    | `http://<IP>/api` (必填) | 绝对地址 (跨域)        |
