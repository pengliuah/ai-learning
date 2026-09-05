// 全局界面字号：按档位调整 <html> 的 font-size。
// 全站尺寸都是 Tailwind 的 rem 单位，改根字号即可整体缩放（含 prose 正文）。
// 属于纯界面偏好，存 localStorage 按设备生效，不走后端。

export type FontSizeStep = "sm" | "md" | "lg" | "xl";

export const FONT_SIZE_OPTIONS: { key: FontSizeStep; label: string; pct: number }[] = [
  { key: "sm", label: "小", pct: 87.5 },
  { key: "md", label: "标准", pct: 100 },
  { key: "lg", label: "大", pct: 112.5 },
  { key: "xl", label: "特大", pct: 125 },
];

const STORAGE_KEY = "zhixue-font-size";

export function getFontSizeStep(): FontSizeStep {
  const v = localStorage.getItem(STORAGE_KEY);
  return FONT_SIZE_OPTIONS.some((o) => o.key === v) ? (v as FontSizeStep) : "md";
}

export function applyFontSize(step: FontSizeStep) {
  const opt = FONT_SIZE_OPTIONS.find((o) => o.key === step) ?? FONT_SIZE_OPTIONS[1];
  document.documentElement.style.fontSize = `${opt.pct}%`;
}

export function setFontSizeStep(step: FontSizeStep) {
  localStorage.setItem(STORAGE_KEY, step);
  applyFontSize(step);
}
