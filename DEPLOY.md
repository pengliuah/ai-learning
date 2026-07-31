# 部署方案 (网页端 + App 端, HTTPS)

一份部署同时服务网页端与 Android App 端, 共用同一套后端与 nginx (HTTPS) 入口。
域名: `www.ailearningagent.xyz`, 证书: 阿里云 Nginx 证书。

## 1. 架构

```
                       ┌─────────────────────────────────────────────┐
   浏览器 (网页端) ─────►  nginx :443 (SSL) ──┐                       │
                       │   80 -> 301 跳 443                           │
   Android App ───────►  /api  ──► FastAPI :8000 (zhixue 容器)         │
   (Capacitor APK)     │   /    ──► FastAPI 托管前端 dist (SPA)        │
                       └─────────────────────────────────────────────┘
```

- **单一入口**: nginx 监听 443 (SSL) + 80 (跳转 443), 反代 `/api` 与 `/` 到 FastAPI。
- **网页端**: 浏览器从 `https://www.ailearningagent.xyz/` 加载页面, API 走相对 `/api` (同源)。
- **App 端**: Capacitor WebView origin 是 `https://localhost`, 相对 `/api` 会解析到设备本地。
  因此 App 打包时注入 **绝对地址** `VITE_API_BASE=https://www.ailearningagent.xyz/api`。

## 2. 为什么 App 需要绝对地址

`client.ts` 的 `API_BASE = import.meta.env.VITE_API_BASE || "/api"`。
- 网页端: 不设该变量 -> `/api` (同源, nginx 反代)。
- App 端 (`mobile/scripts/sync.mjs`): 必须设 `VITE_API_BASE`, 否则中止构建。
  WebView 里 `/api` 解析到设备本地而非服务器, 必须用绝对地址跨域请求。

跨域已就绪: 后端 CORS `allow_origins=["*"]` (自动处理 `https://localhost` 预检)。

## 3. 证书文件

阿里云 SSL 控制台下载 **Nginx** 版证书, 得到两个文件, 放到 `nginx/ssl/` 并命名为:

| 阿里云下载文件 | 放置路径 (服务器 `nginx/ssl/`) |
|---|---|
| `www.ailearningagent.xyz.pem` (证书) | `nginx/ssl/www.ailearningagent.xyz.pem` |
| `www.ailearningagent.xyz.key` (私钥) | `nginx/ssl/www.ailearningagent.xyz.key` |

- 这两个文件已 `.gitignore` (绝不提交)。
- `nginx/zhixue.conf` 里 `ssl_certificate` / `ssl_certificate_key` 指向这两个路径
  (容器内挂载在 `/etc/nginx/ssl/`, 由 `docker-compose.yml` 的 `./nginx/ssl:/etc/nginx/ssl:ro` 映射)。
- 证书到期续签后, 替换这两个文件再 `docker compose restart nginx` 即可。

## 4. 服务器部署 (HTTPS 首次上线)

> 首次从 HTTP 切到 HTTPS 需手动部署一次 (因为 `deploy.sh` 会用服务器上旧的
> `docker-compose.yml` 备份还原, 而旧备份还是 HTTP 配置)。之后 `deploy.sh` 即可正常用。

在服务器 (`/opt/zhixue`, 需 root + docker):

```bash
cd /opt/zhixue
git fetch --all && git reset --hard origin/master     # 拿到含 443+SSL 的新 compose/conf

# 1. 填 API Key: 新 compose 已含 443+SSL, 只需补 ARK_API_KEY
vi docker-compose.yml                                  # 把 ARK_API_KEY= 后面填上真 key

# 2. 放证书
cp <你的证书>.pem nginx/ssl/www.ailearningagent.xyz.pem
cp <你的私钥>.key nginx/ssl/www.ailearningagent.xyz.key

# 3. 启动
docker compose build && docker compose up -d

# 4. 清掉旧的 HTTP 备份, 之后 deploy.sh 会备份这份新的 (含 443+SSL+key)
rm -f /opt/docker-compose.yml.bak*
```

安全组/防火墙放行 **443** (主) 和 **80** (跳转用)。
验证: `curl https://www.ailearningagent.xyz/api/health` -> `{"configured":true,"model":"..."}`。

之后日常更新: `sudo bash scripts/deploy.sh` (默认拉 `origin/master`;
`deploy.sh` 会备份/还原这份含 443+SSL+key 的 compose, 证书文件因 gitignore 不受 `reset --hard` 影响)。

## 5. App 端打包 (在有 Android SDK 的开发机上)

App 用 HTTPS 域名, 在 `mobile/` 构建时注入:

PowerShell:
```powershell
cd mobile
$env:VITE_API_BASE="https://www.ailearningagent.xyz/api"
npm run dev:apk        # 调试签名 APK -> mobile/android/app/build/outputs/apk/debug/app-debug.apk
# release 包需先配签名 keystore (app/build.gradle 的 release 块当前无 signingConfig)
```

bash:
```bash
cd mobile
VITE_API_BASE=https://www.ailearningagent.xyz/api npm run dev:apk
```

注意:
- 域名/证书变更需重新打包 APK (地址构建时固化)。
- HTTPS 后 App 不再依赖明文; `capacitor.config.json` 的 `cleartext`/`allowMixedContent` 可保留 (无害) 也可去掉 (更严格)。
- 服务器 HTTPS 未就绪时, App 会显示健康提示 (连接失败), 属预期。

## 6. 各端 API 基址对照

| 端        | 构建方式              | VITE_API_BASE                          | 运行时 API_BASE        |
|-----------|-----------------------|----------------------------------------|------------------------|
| 本地开发  | `vite` (代理 /api)    | 不设                                   | `/api` (走 vite 代理)  |
| 网页生产  | Docker 内 `vite build`| 不设                                   | `/api` (nginx 同源)    |
| App 生产  | `mobile/ sync.mjs`    | `https://www.ailearningagent.xyz/api`  | 绝对地址 (跨域)        |