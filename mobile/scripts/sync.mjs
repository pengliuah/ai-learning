import { execSync } from "node:child_process";
import { cpSync, mkdirSync, rmSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const mobileDir = resolve(__dirname, "..");
const frontendDir = resolve(mobileDir, "..", "frontend");
const wwwDir = resolve(mobileDir, "www");

// App 端必须指向服务器的绝对地址: Capacitor WebView 的 origin 是 https://localhost,
// 相对 /api 会解析到设备本地而非服务器, 导致 APK 无法取数据。构建时通过 VITE_API_BASE 注入。
const apiBase = process.env.VITE_API_BASE || "";
if (!apiBase) {
  console.error("[sync] VITE_API_BASE 未设置, 中止构建。");
  console.error("[sync] App 端需要后端绝对地址, 例如:");
  console.error(`[sync]   $env:VITE_API_BASE="http://<服务器IP>/api"; npm run build:apk   (PowerShell)`);
  console.error(`[sync]   VITE_API_BASE=http://<服务器IP>/api npm run build:apk            (bash)`);
  console.error("[sync] 网页端不需要此变量 (走 nginx 同源 /api); 仅打包 APK 时需要。");
  process.exit(1);
}
console.log(`[sync] VITE_API_BASE = "${apiBase}"`);

// 1. Build the frontend
console.log("[sync] Building frontend...");
execSync("npm run build", {
  cwd: frontendDir,
  stdio: "inherit",
  env: { ...process.env, VITE_API_BASE: apiBase },
});

// 2. Copy dist -> www
const distDir = resolve(frontendDir, "dist");
if (!existsSync(distDir)) {
  console.error("[sync] frontend/dist not found after build");
  process.exit(1);
}

rmSync(wwwDir, { recursive: true, force: true });
mkdirSync(wwwDir, { recursive: true });
cpSync(distDir, wwwDir, { recursive: true });
console.log("[sync] Copied frontend/dist -> www/");

// 3. cap sync
console.log("[sync] Running cap sync...");
execSync("npx cap sync android", {
  cwd: mobileDir,
  stdio: "inherit",
});

console.log("[sync] Done.");