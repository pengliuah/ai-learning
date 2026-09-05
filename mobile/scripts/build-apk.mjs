// 打包 APK: sync(构建 H5 + cap sync) -> gradle assemble -> 拷贝 APK 到 mobile/ 根目录。
// 用法: node scripts/build-apk.mjs debug|release
// Windows 下 gradlew 是 .bat, npm script 里写死 ./gradlew 在 cmd 会失败, 所以由这里按平台分派。
import { execSync } from "node:child_process";
import { copyFileSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const variant = process.argv[2] === "release" ? "Release" : "Debug";
const task = variant === "Release" ? "assembleRelease" : "assembleDebug";

const __dirname = dirname(fileURLToPath(import.meta.url));
const mobileDir = resolve(__dirname, "..");
const androidDir = resolve(mobileDir, "android");

execSync("node scripts/sync.mjs", { cwd: mobileDir, stdio: "inherit" });

const gradlew = process.platform === "win32" ? "gradlew.bat" : "./gradlew";
console.log(`[apk] gradle ${task} ...`);
execSync(`${gradlew} ${task}`, { cwd: androidDir, stdio: "inherit" });

// release 未配置签名时产物是 app-release-unsigned.apk, 一样拷出来并提示
const lower = variant.toLowerCase();
const candidates =
  variant === "Release"
    ? ["app-release.apk", "app-release-unsigned.apk"]
    : ["app-debug.apk"];
const built = candidates
  .map((n) => resolve(androidDir, "app", "build", "outputs", "apk", lower, n))
  .find(existsSync);
if (!built) {
  console.error(`[apk] 未找到构建产物 (${candidates.join(", ")})`);
  process.exit(1);
}
const dest = resolve(mobileDir, `zhixue-${lower}.apk`);
copyFileSync(built, dest);
console.log(`[apk] 完成: ${dest}`);
if (built.endsWith("unsigned.apk")) {
  console.warn("[apk] ⚠️ 这是未签名 release 包, 无法直接安装; 正式分发需先配置签名 (M1)。");
}
