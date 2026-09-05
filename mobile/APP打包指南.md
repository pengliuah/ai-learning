# 智学助手 Android App 打包指南

> 本文所有命令都**明确标注了执行目录**。下文用 `<仓库根>` 指仓库所在目录（当前机器是
> `D:\xishan`），如果你的仓库在别的位置，替换成实际路径即可。示例统一用 PowerShell 语法。

## 1. 前置条件（只需配置一次）

| 软件 | 版本要求 | 检查命令（任意目录） | 用途 |
| --- | --- | --- | --- |
| Node.js | ≥ 18 | `node -v` | 构建 H5 / 执行打包脚本 |
| JDK | 17 | `java -version` | gradle 编译安卓工程 |
| Android SDK | API 34+ | 见下方「SDK 位置」 | 安卓构建工具链 |

**SDK 位置**（二选一）：
- 设置环境变量 `ANDROID_HOME` 指向 SDK 目录（如 `C:\Users\<你>\AppData\Local\Android\Sdk`，装了 Android Studio 的默认就在这）；或
- 在 `<仓库根>\mobile\android\` 下新建 `local.properties`，内容一行：
  `sdk.dir=C\:\\Users\\<你>\\AppData\\Local\\Android\\Sdk`（注意冒号要转义成 `\:`）。

**首次使用需要装依赖**（各执行一次）：

```powershell
# 在 <仓库根>\frontend 下执行
PS D:\xishan\frontend> npm install

# 在 <仓库根>\mobile 下执行
PS D:\xishan\mobile> npm install
```

## 2. 打包命令（在 `<仓库根>\mobile` 下执行）

```powershell
PS D:\xishan\mobile> npm run sync        # 仅同步 H5：构建 frontend -> www -> cap sync（不打 APK）
PS D:\xishan\mobile> npm run dev:apk     # debug 包：可直接安装，日常联机测试用
PS D:\xishan\mobile> npm run build:apk   # release 包：未配签名时产出 unsigned 包（见 §5）
```

内部流程：`sync.mjs`（构建 frontend → 拷贝到 `www/` → `cap sync android`）→ gradle assemble →
把 APK 从 `android\app\build\outputs\apk\` 拷到 `mobile\` 根目录。

**产物位置与安装**：

| 命令 | 产物（构建完成后自动拷贝） | 能否直接安装 |
| --- | --- | --- |
| `npm run dev:apk` | `<仓库根>\mobile\zhixue-debug.apk` | ✅ |
| `npm run build:apk` | `<仓库根>\mobile\zhixue-release.apk` | ❌ 需先配签名（§5） |

安装方式：`adb install -r D:\xishan\mobile\zhixue-debug.apk`，或把 APK 文件发到手机上点击安装。

## 3. API 地址

- **默认零配置**：App 固定请求生产地址 `https://www.ailearningagent.xyz/api`，直接 `npm run dev:apk` 即可。
- App 已 HTTPS-only（明文 HTTP 被禁），所以测试包指向测试环境时要临时放行明文并覆盖地址：

  ```powershell
  # 在 <仓库根>\mobile 下执行
  PS D:\xishan\mobile> $env:VITE_API_BASE = "http://192.168.1.184/api"
  PS D:\xishan\mobile> npm run dev:apk        # 打完后建议删掉该环境变量再打正式包
  ```

  同时临时把 `mobile\capacitor.config.json` 里的 `"server"` 加回 `"cleartext": true`。
- 网页端不受影响（走 nginx 同源 `/api`，不需要这个变量）。

## 4. 版本号（文件：`<仓库根>\mobile\android\app\build.gradle`）

```gradle
defaultConfig {
    versionCode 1        // 每次发版 +1（整数，用于升级判断）
    versionName "1.0"    // 用户可见的版本号
}
```

改完重新打包即可；不递增 `versionCode` 的话已安装用户无法覆盖升级。

## 5. 签名（正式分发前必做）

keystore 建议放在**仓库外**并妥善备份（丢了就永远无法给同一应用发更新）。

```powershell
# 任意目录执行；按提示设置密码与信息
PS D:\> keytool -genkeypair -v -keystore D:\keys\zhixue-release.keystore -alias zhixue -keyalg RSA -keysize 2048 -validity 10000
```

然后在 `<仓库根>\mobile\android\app\build.gradle` 中接入签名（密码建议放 `gradle.properties` 或环境变量，不要提交到 git）：

```gradle
android {
    signingConfigs {
        release {
            storeFile file("D:/keys/zhixue-release.keystore")
            storePassword System.getenv("ZX_STORE_PWD")
            keyAlias "zhixue"
            keyPassword System.getenv("ZX_KEY_PWD")
        }
    }
    buildTypes {
        release {
            signingConfig signingConfigs.release   // 加这一行
        }
    }
}
```

配置后 `npm run build:apk` 产出的就是可安装、可覆盖升级的正式包。

## 6. 图标（启动器 icon）

来源是网页同款图标 `<仓库根>\frontend\public\favicon.svg`（微笑小书本）。
`android\` 目录是生成物、不入库，**新机器 clone 后要重新生成图标**：

```powershell
# 先在 <仓库根>\backend 安装 pillow（一次性）
PS D:\xishan\backend> uv pip install pillow

# 再在 <仓库根>\mobile 下执行生成
PS D:\xishan\mobile> ..\backend\.venv\Scripts\python.exe scripts\gen-icons.py
```

脚本用 Edge 无头渲染 SVG，自动产出全部密度的传统图标/圆形图标/自适应前景，
并把自适应背景设为品牌靛蓝。换 logo 后重跑一次即可。

## 7. 常见问题

| 现象 | 原因与处理 |
| --- | --- |
| `'.' 不是内部或外部命令` / `./gradlew` 报错 | 手工执行了 `cd android && ./gradlew`（cmd 不认）。一律用 `npm run dev:apk` / `npm run build:apk`，脚本按平台自动选 `gradlew.bat` |
| `SDK location not found` | 没配 SDK 位置：设 `ANDROID_HOME` 或建 `android\local.properties`（见 §1） |
| gradle 卡在下载依赖 | 给 gradle 配国内镜像：`<仓库根>\mobile\android\build.gradle` 的 `repositories` 里加 `maven { url 'https://maven.aliyun.com/repository/google' }` 和 `maven { url 'https://maven.aliyun.com/repository/central' }` |
| App 白屏 / 请求全部失败 | API 必须是 HTTPS 域名（明文已禁）；或后端域名证书失效 |
| 改了 frontend 代码图标/内容没变 | 重新执行打包命令（sync 会重新构建前端），并确认手机上装的是新包（看 versionCode） |
| 覆盖安装失败提示签名不一致 | 手机上装过别的签名（debug/release）的版本，先卸载再装 |
