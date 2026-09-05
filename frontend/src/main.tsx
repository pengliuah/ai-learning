import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
import "katex/dist/katex.min.css";
import { applyFontSize, getFontSizeStep } from "./utils/fontSize";

// 首屏渲染前应用本地保存的字号档位，避免闪一下默认字号
applyFontSize(getFontSizeStep());

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
