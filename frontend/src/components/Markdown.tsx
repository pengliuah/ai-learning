import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";

/**
 * Maximal run of characters that can appear inside a math expression: ASCII
 * alphanumerics, operators, brackets, _ ^ \ , plus Unicode Greek (Α-ω),
 * super/subscripts, arrows, and the math-operators block. CJK characters and
 * CJK/fullwidth punctuation are excluded, so they naturally delimit math runs
 * in mixed CN+formula text like "下一个状态 S_{t+1}」".
 */
const MATH_RUN_RE =
  /[A-Za-z0-9_^{}()\[\]|.,'=+\-*/\\ \u0391-\u03c9\u2070-\u2079\u2080-\u2089\u2190-\u21ff\u2200-\u22ff]+/g;

/** True if the run contains LaTeX syntax that would not appear in prose. */
function hasLatexIndicator(run: string): boolean {
  // Strong indicators (effectively never in prose):
  if (/[_^]\{/.test(run)) return true;        // _{...}, ^{...}
  if (/\\[A-Za-z]/.test(run)) return true;    // \pi, \Sigma
  // Bare _x / ^x (subscript/superscript without braces) -- only treat as math
  // when the run also has an operator/bracket, distinguishing "V^π(s)=E_π[...]"
  // from markdown emphasis like "_italic_" (which has no operators).
  if (/[_^][A-Za-z0-9\u0391-\u03c9]/.test(run) && /[=+\-*/()[\]{}|]/.test(run)) return true;
  return false;
}

/**
 * Wrap LaTeX-like fragments that lack $...$ delimiters so remark-math + KaTeX
 * can render them as typeset math instead of raw text.
 *
 * The grader/quizzer LLMs sometimes emit formulas with LaTeX syntax
 * (S_{t+1}, \pi, V^π(s)) but without wrapping $ delimiters. remark-math only
 * parses $-delimited math, so these show as raw "S_{t+1}" instead of typeset
 * subscripts. This scans non-math segments for runs of math-like characters
 * containing a LaTeX indicator (_{, ^{, \cmd, or bare _/^ with an operator)
 * and wraps them in $...$. Already-delimited $...$ / $$...$$ is untouched.
 */
export function wrapUnwrappedMath(text: string): string {
  if (!text || !text.includes) return text;
  // Split by existing $...$ / $$...$$ to preserve already-wrapped math.
  const segments = text.split(/(\$\$[\s\S]+?\$\$|\$[^$\n]+\$)/g);
  return segments
    .map((seg, i) => {
      if (i % 2 === 1) return seg; // captured math block - leave as-is
      return seg.replace(MATH_RUN_RE, (run) => {
        const trimmed = run.trim();
        if (!trimmed || !hasLatexIndicator(trimmed)) return run;
        // Preserve whitespace outside the $...$ wrapper so the opening/closing
        // $ stays properly delimited from adjacent CJK word characters
        // (remark-math rejects $ adjacent to word chars without a boundary).
        const lead = run.slice(0, run.length - run.trimStart().length);
        const trail = run.slice(run.trimEnd().length);
        return `${lead}$${trimmed}$${trail}`;
      });
    })
    .join("");
}

/**
 * Renders Markdown (GFM + LaTeX math via KaTeX).
 *
 * `inline` maps block elements to spans so the output can sit inside <p>,
 * <span>, or <li> -- used for quiz prompts, options, answers, feedback, and
 * key takeaways where math must render but must not introduce block structure.
 */
export function Markdown({ children, inline = false }: { children: string; inline?: boolean }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[[rehypeKatex, { throwOnError: false }]]}
      components={inline ? { p: ({ children }) => <span>{children}</span> } : undefined}
    >
      {wrapUnwrappedMath(children)}
    </ReactMarkdown>
  );
}
