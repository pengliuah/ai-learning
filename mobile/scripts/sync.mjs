import { execSync } from "node:child_process";
import { cpSync, mkdirSync, rmSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const mobileDir = resolve(__dirname, "..");
const frontendDir = resolve(mobileDir, "..", "frontend");
const wwwDir = resolve(mobileDir, "www");

// App 端必须指向服务器的绝对地址: Capacitor WebView 的 origin 是 https://localhost,
// 相对 /api 会解析到设备本地而非服务器, 导致 APK 无法取数据。
// 正式包固定走生产 HTTPS 域名, 无需任何构建配置; 仅打测试包时用 VITE_API_BASE 覆盖。
const DEFAULT_API_BASE = "https://www.ailearningagent.xyz/api";
const apiBase = process.env.VITE_API_BASE || DEFAULT_API_BASE;
if (apiBase === DEFAULT_API_BASE) {
  console.log(`[sync] VITE_API_BASE = "${apiBase}" (默认生产地址)`);
} else {
  console.log(`[sync] VITE_API_BASE = "${apiBase}" (环境变量覆盖, 测试包)`);
}

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