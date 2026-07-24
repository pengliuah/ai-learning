import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";

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
      {children}
    </ReactMarkdown>
  );
}