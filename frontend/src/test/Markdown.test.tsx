import { describe, it, expect } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { Markdown, wrapUnwrappedMath } from "../components/Markdown";

describe("wrapUnwrappedMath", () => {
  it("wraps bare _{...} subscripts in Chinese feedback", () => {
    expect(wrapUnwrappedMath("下一个状态 S_{t+1}」")).toBe("下一个状态 $S_{t+1}$」");
  });

  it("wraps a full expression with _{} and ^ spanning spaces", () => {
    const src = "参考要点：G_t=Σ_{k=0}^∞ γ^k R_{t+k+1}，折扣累积奖励";
    const out = wrapUnwrappedMath(src);
    expect(out).toBe("参考要点：$G_t=Σ_{k=0}^∞ γ^k R_{t+k+1}$，折扣累积奖励");
  });

  it("wraps multiple adjacent formula runs separated by CJK", () => {
    const src = "答对了 S_{t+1} 和 R_{t+1}，但多加了 A_{t+1}";
    const out = wrapUnwrappedMath(src);
    expect(out).toContain("$S_{t+1}$");
    expect(out).toContain("$R_{t+1}$");
    expect(out).toContain("$A_{t+1}$");
  });

  it("wraps LaTeX commands like \\pi without delimiters", () => {
    expect(wrapUnwrappedMath("圆周率 \\pi 约等于 3.14")).toBe("圆周率 $\\pi$ 约等于 3.14");
  });

  it("wraps bare ^/_ subscripts (no braces) when the run has operators", () => {
    const src = "参考要点：V^π(s)=E_π[G_t|S_t=s]，关系 V^π(s)=Σ_a π(a|s)Q^π(s,a)";
    const out = wrapUnwrappedMath(src);
    expect(out).toContain("$V^π(s)=E_π[G_t|S_t=s]$");
    expect(out).toContain("$V^π(s)=Σ_a π(a|s)Q^π(s,a)$");
  });

  it("does not wrap markdown emphasis like _italic_ (no operators)", () => {
    expect(wrapUnwrappedMath("这是 _italic_ 文字")).toBe("这是 _italic_ 文字");
  });

  it("leaves already-delimited $...$ math untouched", () => {
    const src = "浮力公式 $F_{浮} = G - F'$ 正确";
    expect(wrapUnwrappedMath(src)).toBe(src);
  });

  it("leaves already-delimited $$...$$ math untouched", () => {
    const src = "公式\n\n$$F_{浮} = G - F'$$\n\n结束";
    expect(wrapUnwrappedMath(src)).toBe(src);
  });

  it("mixes wrapped and unwrapped math correctly", () => {
    const src = "已知 $F_{浮}$ 且 S_{t+1} 成立";
    const out = wrapUnwrappedMath(src);
    expect(out).toContain("$F_{浮}$");
    expect(out).toContain("$S_{t+1}$");
    // no double-wrapping
    expect(out).not.toContain("$$F_{浮}$$");
    expect(out).not.toContain("$$S_{t+1}$$");
  });

  it("does not wrap plain text without LaTeX indicators", () => {
    const src = "策略π决定了动作的选择，RL处理序列决策数据";
    expect(wrapUnwrappedMath(src)).toBe(src);
  });

  it("does not wrap simple math-like text lacking _{ or ^{ or \\cmd", () => {
    const src = "SMA₅ = (20+22+21+23+24)/5 = 110/5 = 22.00";
    // Unicode subscript ₅ + operators but no _{ / ^{ / \cmd -> not wrapped
    expect(wrapUnwrappedMath(src)).toBe(src);
  });

  it("handles empty / nullish input gracefully", () => {
    expect(wrapUnwrappedMath("")).toBe("");
    expect(wrapUnwrappedMath(null as unknown as string)).toBe(null);
  });

  it("wraps the real grader feedback from the RL module", () => {
    const feedback =
      "学生答对了「下一个状态 S_{t+1}」和「即时奖励 R_{t+1}」，但多加了「下一个动作 A_{t+1}」。" +
      "在RL交互循环中，环境只返回 S_{t+1} 和 R_{t+1}；A_{t+1} 是由智能体根据策略自主选择的，不属于环境返回的内容。";
    const out = wrapUnwrappedMath(feedback);
    expect(out).toContain("$S_{t+1}$");
    expect(out).toContain("$R_{t+1}$");
    expect(out).toContain("$A_{t+1}$");
    // surrounding Chinese text is preserved
    expect(out).toContain("学生答对了「下一个状态");
    expect(out).toContain("是由智能体根据策略自主选择的");
  });
});


describe("Markdown integration", () => {
  it("renders unwrapped LaTeX (grader output) as KaTeX, not raw text", async () => {
    const { container } = render(
      <Markdown inline>{"环境返回 S_{t+1} 和 R_{t+1}，动作 A_{t+1} 由策略决定"}</Markdown>,
    );
    // Three formulas -> three KaTeX renderings
    await waitFor(() => expect(container.querySelectorAll(".katex")).toHaveLength(3), { timeout: 3000 });
    // $ delimiters added by preprocessing are consumed by remark-math
    expect(container.textContent).not.toContain("$");
  });

  it("renders unwrapped \\command LaTeX as KaTeX", async () => {
    const { container } = render(<Markdown inline>{"圆周率 \\pi 约为 3.14"}</Markdown>);
    await waitFor(() => expect(container.querySelectorAll(".katex")).toHaveLength(1), { timeout: 3000 });
    expect(container.textContent).not.toContain("$");
  });
});
