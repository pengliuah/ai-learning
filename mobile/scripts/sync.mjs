import { execSync } from "node:child_process";
import { cpSync, mkdirSync, rmSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const mobileDir = resolve(__dirname, "..");
const frontendDir = resolve(mobileDir, "..", "frontend");
const wwwDir = resolve(mobileDir, "www");

const apiBase = process.env.VITE_API_BASE || "";
console.log(`[sync] VITE_API_BASE = "${apiBase || "(not set, using /api)"}"`);

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