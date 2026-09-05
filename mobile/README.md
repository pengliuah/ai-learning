# 智学助手 App（Android）打包指南

Capacitor 6 Android 壳：H5（`frontend/`）打进 WebView，API 直连生产 HTTPS 域名。

## 前置条件

- Node 18+，且 `frontend/node_modules`、`mobile/node_modules` 已安装
- JDK 17 + Android SDK（`ANDROID_HOME` 已配置或 `android/local.properties` 指向 SDK）
- 首次构建 gradle 会自动下载依赖，需要网络

## 打包命令（在 `mobile/` 目录下）

```bash
npm run sync        # 只同步 H5：构建 frontend -> www -> cap sync（不打 APK，用于调试工程配置）
npm run dev:apk     # debug 包：产物 mobile/zhixue-debug.apk，可直接安装
npm run build:apk   # release 包：未配置签名时产出 zhixue-release.apk（unsigned，无法直接安装，见下文签名）
```

流程都是：`sync.mjs`（构建 frontend → 拷贝到 `www/` → `cap sync android`）→ gradle assemble →
把产物从 `android/app/build/outputs/apk/` 拷到 `mobile/` 根目录。

安装到手机：`adb install -r zhixue-debug.apk`，或直接把 APK 发到手机点击安装。

## API 地址

- **默认零配置**：固定生产地址 `https://www.ailearningagent.xyz/api`（App 已 HTTPS-only，明文被禁）。
- 打测试包时才需要覆盖（PowerShell 示例）：

  ```powershell
  $env:VITE_API_BASE = "http://192.168.1.184/api"; npm run dev:apk
  ```

  注意测试环境若是 HTTP 明文地址，需要临时把 `capacitor.config.json` 的 `cleartext` 打开再打包。
- 网页端不受影响（走 nginx 同源 `/api`，无需此变量）。

## 图标（启动器 icon）

来源是网页同款图标 `frontend/public/favicon.svg`（微笑小书本）。`android/` 目录是生成物不入库，
新机器 `npx cap add android` 后需要重新生成图标：

```bash
cd ../backend && uv pip install pillow
cd ../mobile && ../backend/.venv/Scripts/python.exe scripts/gen-icons.py
```

脚本用 Edge 无头渲染 SVG，自动产出传统图标（ic_launcher / round，mdpi..xxxhdpi）、
自适应图标前景（图形居中 66% 安全区）并把背景色设为品牌靛蓝。换 logo 时重跑即可。

## 签名（正式分发前必做）

```bash
keytool -genkeypair -v -keystore zhixue-release.keystore -alias zhixue \
  -keyalg RSA -keysize 2048 -validity 10000
```

- **keystore 与密码务必备份**：丢了就无法再对同一应用发布更新。
- 生成后接 gradle signingConfig（见 `docs/mobile-app-plan.md` M1 项），之后 `npm run build:apk`
  产出的才是可安装、可升级的正式包。

## 常见问题

- **`'.' 不是内部或外部命令` / `./gradlew` 报错**：别手工 `cd android && ./gradlew`（cmd 下不可执行），
  一律用 `npm run dev:apk` / `npm run build:apk`——新脚本按平台自动选 `gradlew.bat`。
- **App 白屏 / 请求失败**：确认 API 是 HTTPS 域名；明文 HTTP 已在配置中禁用。
- **改了 frontend 代码**：重跑 `npm run dev:apk` 即可，sync 会重新构建前端。
