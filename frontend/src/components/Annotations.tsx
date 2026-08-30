/**
 * Word 式内容批注：选中文本 → 浮出「添加批注」→ 黄色高亮 → 点击弹卡片 → 批注列表。
 *
 * 锚定模型：{quote, prefix, suffix} 三元组在渲染后 DOM 的可见文本里重定位，
 * 与 react-markdown 输出的 DOM 结构解耦（免疫 wrapUnwrappedMath 等源文本变换）。
 * 高亮用 CSS Custom Highlight API（不改 React 管理的 DOM），不支持的浏览器
 * 静默降级为仅列表。内容重新生成后找不到原文的批注标记为失效，数据保留。
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Loader2, MessageSquarePlus, Pencil, StickyNote, Trash2, X } from "lucide-react";
import {
  useAnnotations,
  useCreateAnnotation,
  useDeleteAnnotation,
  useUpdateAnnotation,
} from "../hooks/usePlans";
import type { Annotation } from "../api/types";
import { useToast } from "./Toast";

const HL_NAME = "zhixue-anno";
const HL_ACTIVE_NAME = "zhixue-anno-active";
const CONTEXT_CHARS = 32; // prefix/suffix 截取长度

/** CSS Custom Highlight API 的最小类型（老 TS lib 没有内置）。 */
type HighlightRegistry = Map<string, unknown>;
type HighlightCtor = new (...ranges: Range[]) => unknown;

function highlightRegistry(): HighlightRegistry | null {
  if (typeof window === "undefined" || !("highlights" in CSS)) return null;
  return (CSS as unknown as { highlights: HighlightRegistry }).highlights;
}
function highlightCtor(): HighlightCtor | null {
  const HL = (window as unknown as { Highlight?: HighlightCtor }).Highlight;
  return typeof HL === "function" ? HL : null;
}

interface Anchor {
  quote: string;
  prefix: string;
  suffix: string;
}

type EditorState =
  | { kind: "new"; anchor: Anchor; rect: DOMRect }
  | { kind: "edit"; annotation: Annotation; rect: DOMRect | null };

// --- DOM 文本索引工具 ------------------------------------------------------

interface TextIndex {
  nodes: Text[];
  starts: number[]; // 每个文本节点在拼接文本中的起始偏移
  full: string;
}

function buildTextIndex(container: HTMLElement): TextIndex {
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  const starts: number[] = [];
  let total = 0;
  for (let n = walker.nextNode() as Text | null; n; n = walker.nextNode() as Text | null) {
    if (!n.data) continue;
    starts.push(total);
    nodes.push(n);
    total += n.data.length;
  }
  return { nodes, starts, full: nodes.map((n) => n.data).join("") };
}

function normalize(s: string): string {
  // 渲染文本的换行/连续空白因排版而变，统一成单空格再比较
  return s.replace(/\s+/g, " ").trim();
}

/** 选区端点（可为元素节点）解析为文本节点 + 偏移。 */
function resolveEndpoint(node: Node, offset: number, preferLast: boolean): { text: Text; off: number } | null {
  if (node.nodeType === Node.TEXT_NODE) return { text: node as Text, off: offset };
  const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
  let first: Text | null = null;
  let last: Text | null = null;
  for (let n = walker.nextNode() as Text | null; n; n = walker.nextNode() as Text | null) {
    if (!first) first = n;
    last = n;
  }
  const target = preferLast ? last : first;
  if (!target) return null;
  return { text: target, off: preferLast ? target.data.length : 0 };
}

/** 从选区提取 {quote, prefix, suffix}（基于容器拼接文本，跨节点选择也成立）。 */
function extractAnchor(container: HTMLElement, range: Range): Anchor | null {
  const idx = buildTextIndex(container);
  const offsetOf = (node: Node, off: number, preferLast: boolean): number | null => {
    const resolved = resolveEndpoint(node, off, preferLast);
    if (!resolved) return null;
    let pos = 0;
    for (const textNode of idx.nodes) {
      if (textNode === resolved.text) return pos + Math.min(resolved.off, textNode.data.length);
      pos += textNode.data.length;
    }
    return null;
  };
  const start = offsetOf(range.startContainer, range.startOffset, false);
  const end = offsetOf(range.endContainer, range.endOffset, true);
  if (start === null || end === null || end <= start) return null;
  const quote = normalize(idx.full.slice(start, end));
  if (!quote) return null;
  const prefix = normalize(idx.full.slice(Math.max(0, start - CONTEXT_CHARS), start));
  const suffix = normalize(idx.full.slice(end, end + CONTEXT_CHARS));
  return { quote, prefix, suffix };
}

/** 在容器文本中按 quote+prefix+suffix 重找范围，返回原始拼接文本的 [start, end)。 */
function locate(idx: TextIndex, anchor: Anchor): [number, number] | null {
  // 归一化映射：norm 的第 i 个字符对应原始文本 map[i]（折叠空格记首个空白位置）
  let norm = "";
  const map: number[] = [];
  let inWs = false;
  for (let i = 0; i < idx.full.length; i++) {
    const ch = idx.full[i];
    if (/\s/.test(ch)) {
      if (!inWs) {
        norm += " ";
        map.push(i);
        inWs = true;
      }
      continue;
    }
    inWs = false;
    norm += ch;
    map.push(i);
  }
  const quote = normalize(anchor.quote);
  if (!quote) return null;
  const prefix = normalize(anchor.prefix);
  const suffix = normalize(anchor.suffix);
  let from = 0;
  for (;;) {
    const i = norm.indexOf(quote, from);
    if (i === -1) return null;
    from = i + 1;
    // 前后文匹配留 2 字符容差（prefix/suffix 截断处的空格差异）
    if (prefix && !norm.slice(Math.max(0, i - prefix.length - 2), i).trimEnd().endsWith(prefix)) continue;
    const j = i + quote.length;
    if (suffix && !norm.slice(j, j + suffix.length + 2).trimStart().startsWith(suffix)) continue;
    const rawStart = map[i];
    const rawEnd = map[j - 1] + 1;
    return [rawStart, rawEnd];
  }
}

function rangeForSpan(idx: TextIndex, start: number, end: number): Range | null {
  let k = 0;
  while (k < idx.starts.length - 1 && idx.starts[k + 1] <= start) k++;
  if (start - idx.starts[k] > idx.nodes[k].data.length) return null;
  let k2 = 0;
  while (k2 < idx.starts.length - 1 && idx.starts[k2 + 1] <= end) k2++;
  if (end - idx.starts[k2] > idx.nodes[k2].data.length) return null;
  try {
    const r = new Range();
    r.setStart(idx.nodes[k], start - idx.starts[k]);
    r.setEnd(idx.nodes[k2], end - idx.starts[k2]);
    return r;
  } catch {
    return null;
  }
}

function findScrollableAncestor(el: HTMLElement | null): HTMLElement | null {
  let cur: HTMLElement | null = el;
  while (cur) {
    const oy = getComputedStyle(cur).overflowY;
    if (oy === "auto" || oy === "scroll") return cur;
    cur = cur.parentElement;
  }
  return null;
}

// --- 组件 ------------------------------------------------------------------

interface AnnotationsProps {
  /** 批注作用的内容容器（含正文与关键要点）。 */
  containerRef: React.RefObject<HTMLElement | null>;
  planId: string;
  moduleId: string;
  /** 内容标识（如 markdown 原文）：变化时重新锚定高亮。 */
  anchorKey?: string;
}

export function Annotations({ containerRef, planId, moduleId, anchorKey }: AnnotationsProps) {
  const { data: annotations = [], isLoading } = useAnnotations(planId, moduleId);
  const createMutation = useCreateAnnotation(planId, moduleId);
  const updateMutation = useUpdateAnnotation(planId, moduleId);
  const deleteMutation = useDeleteAnnotation(planId, moduleId);
  const { toast } = useToast();

  const [bubble, setBubble] = useState<{ x: number; y: number; anchor: Anchor } | null>(null);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [draft, setDraft] = useState("");
  const [listOpen, setListOpen] = useState(false);
  // 重锚定后强制刷新列表的"是否失效"状态与高亮点击区域
  const [anchorVersion, setAnchorVersion] = useState(0);
  // 宽屏侧边卡片布局：top 相对内容容器，anchorY/X 为高亮处（虚线起点）
  const [sideLayout, setSideLayout] = useState<
    { id: string; top: number; anchorY: number; anchorX: number; orphan: boolean }[]
  >([]);
  const [colX, setColX] = useState(0); // 侧列左缘相对容器的 x（虚线终点）
  const cardRefs = useRef<Map<string, HTMLDivElement | null>>(new Map());

  const rangesRef = useRef<Map<string, Range>>(new Map());
  const editorRef = useRef<HTMLTextAreaElement | null>(null);

  // --- 高亮锚定 ------------------------------------------------------------
  const reanchor = useCallback(() => {
    const container = containerRef.current;
    rangesRef.current = new Map();
    const registry = highlightRegistry();
    if (registry) {
      registry.delete(HL_NAME);
      registry.delete(HL_ACTIVE_NAME);
    }
    if (!container || annotations.length === 0) {
      setAnchorVersion((v) => v + 1);
      return;
    }
    const idx = buildTextIndex(container);
    const HL = highlightCtor();
    if (registry && HL) {
      const ranges: Range[] = [];
      for (const anno of annotations) {
        const span = locate(idx, anno);
        if (!span) continue;
        const range = rangeForSpan(idx, span[0], span[1]);
        if (!range) continue;
        rangesRef.current.set(anno.id, range);
        ranges.push(range);
      }
      if (ranges.length) registry.set(HL_NAME, new HL(...ranges));
    }

    // 侧边卡片布局：与各自高亮垂直对齐；锚点相近时向下避让防压盖
    const base = container.getBoundingClientRect();
    const GAP = 8;
    const EST_H = 100; // 渲染后用实测高度二次校正
    const items = annotations.map((anno) => {
      const range = rangesRef.current.get(anno.id);
      if (!range) {
        // 失效批注：排在内容末尾
        return { id: anno.id, top: container.scrollHeight - 40, anchorY: container.scrollHeight - 40, anchorX: container.clientWidth, orphan: true };
      }
      const r = range.getBoundingClientRect();
      const anchorY = r.top - base.top + Math.min(r.height, 24) / 2;
      return { id: anno.id, top: anchorY - 14, anchorY, anchorX: r.right - base.left, orphan: false };
    });
    items.sort((a, b) => a.top - b.top);
    let prevBottom = -Infinity;
    for (const it of items) {
      it.top = Math.max(it.top, prevBottom + GAP);
      prevBottom = it.top + EST_H;
    }
    setSideLayout(items);
    setColX(container.clientWidth + 24);
    setAnchorVersion((v) => v + 1);
  }, [annotations, containerRef]);

  // 卡片渲染后用实测高度二次校正避让（估算高度不准时收敛到真实布局）
  useLayoutEffect(() => {
    if (sideLayout.length === 0) return;
    const GAP = 8;
    let prevBottom = -Infinity;
    let changed = false;
    const next = [...sideLayout]
      .sort((a, b) => a.top - b.top)
      .map((it) => {
        const top = Math.max(it.top, prevBottom + GAP);
        const h = cardRefs.current.get(it.id)?.offsetHeight ?? 0;
        prevBottom = top + h;
        if (Math.abs(top - it.top) > 1) {
          changed = true;
          return { ...it, top };
        }
        return it;
      });
    if (changed) setSideLayout(next);
  }, [sideLayout, anchorVersion]);

  // 容器尺寸变化（图片加载、窗口缩放）后重新锚定
  useEffect(() => {
    const container = containerRef.current;
    if (!container || typeof ResizeObserver === "undefined") return;
    let raf = 0;
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(reanchor);
    });
    ro.observe(container);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [containerRef, reanchor]);

  useEffect(() => {
    // 等一帧让 react-markdown 完成 DOM 提交后再锚定
    const raf = requestAnimationFrame(reanchor);
    return () => {
      cancelAnimationFrame(raf);
      const registry = highlightRegistry();
      if (registry) {
        registry.delete(HL_NAME);
        registry.delete(HL_ACTIVE_NAME);
      }
      rangesRef.current = new Map();
    };
  }, [reanchor, anchorKey]);

  // --- 选区浮条 ------------------------------------------------------------
  useEffect(() => {
    const onSelectionEnd = () => {
      setTimeout(() => {
        const container = containerRef.current;
        const sel = window.getSelection();
        if (!container || !sel || sel.isCollapsed || sel.rangeCount === 0) {
          setBubble(null);
          return;
        }
        const range = sel.getRangeAt(0);
        if (!container.contains(range.commonAncestorContainer)) {
          setBubble(null);
          return;
        }
        const anchor = extractAnchor(container, range);
        if (!anchor) {
          setBubble(null);
          return;
        }
        const rect = range.getBoundingClientRect();
        setBubble({
          x: Math.min(Math.max(rect.left + rect.width / 2, 60), window.innerWidth - 60),
          y: Math.max(rect.top - 8, 60),
          anchor,
        });
      }, 0);
    };
    document.addEventListener("mouseup", onSelectionEnd);
    document.addEventListener("touchend", onSelectionEnd);
    return () => {
      document.removeEventListener("mouseup", onSelectionEnd);
      document.removeEventListener("touchend", onSelectionEnd);
    };
  }, [containerRef]);

  // 点击已高亮文本 → 弹出编辑卡片
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const onClick = (e: MouseEvent) => {
      if (rangesRef.current.size === 0) return;
      for (const [id, range] of rangesRef.current) {
        const rects = range.getClientRects();
        for (let i = 0; i < rects.length; i++) {
          const r = rects[i];
          if (e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom) {
            const anno = annotations.find((a) => a.id === id);
            if (anno) {
              e.preventDefault();
              e.stopPropagation();
              window.getSelection()?.removeAllRanges();
              setDraft(anno.note);
              setEditor({ kind: "edit", annotation: anno, rect: r });
            }
            return;
          }
        }
      }
    };
    container.addEventListener("click", onClick);
    return () => container.removeEventListener("click", onClick);
  }, [annotations, anchorVersion, containerRef]);

  // 编辑卡打开后聚焦；Escape 关闭浮层
  useEffect(() => {
    if (editor) editorRef.current?.focus();
  }, [editor]);
  useEffect(() => {
    if (!bubble && !editor) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeAll();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bubble, editor]);

  const closeAll = useCallback(() => {
    setBubble(null);
    setEditor(null);
  }, []);

  const scrollAnnoIntoView = useCallback(
    (id: string) => {
      const range = rangesRef.current.get(id);
      const rect = range?.getBoundingClientRect();
      if (!rect) return;
      const scroller = findScrollableAncestor(containerRef.current);
      if (scroller) {
        const er = scroller.getBoundingClientRect();
        scroller.scrollBy({ top: rect.top - er.top - 80, behavior: "smooth" });
      } else {
        window.scrollTo({ top: rect.top + window.scrollY - 80, behavior: "smooth" });
      }
    },
    [containerRef],
  );

  const openEditorFor = (anno: Annotation) => {
    const range = rangesRef.current.get(anno.id);
    const rect = range ? range.getClientRects()[0] ?? null : null;
    setDraft(anno.note);
    setEditor({ kind: "edit", annotation: anno, rect });
    if (rect) scrollAnnoIntoView(anno.id);
  };

  const handleCreate = () => {
    // bubble 在打开编辑卡时已被置空，锚点要从 editor 里取
    if (editor?.kind !== "new") return;
    createMutation.mutate(
      { ...editor.anchor, note: draft.trim() },
      {
        onSuccess: () => {
          toast("批注已添加", "success");
          setDraft("");
          closeAll();
          window.getSelection()?.removeAllRanges();
        },
        onError: (e) => toast(`添加失败：${(e as Error).message}`, "error"),
      },
    );
  };

  const handleSave = () => {
    if (editor?.kind !== "edit") return;
    updateMutation.mutate(
      { annotationId: editor.annotation.id, note: draft },
      {
        onSuccess: () => {
          toast("批注已保存", "success");
          closeAll();
        },
        onError: (e) => toast(`保存失败：${(e as Error).message}`, "error"),
      },
    );
  };

  const handleDelete = (id: string) => {
    if (!window.confirm("确定删除这条批注？")) return;
    deleteMutation.mutate(id, {
      onSuccess: () => {
        toast("批注已删除", "success");
        closeAll();
      },
      onError: (e) => toast(`删除失败：${(e as Error).message}`, "error"),
    });
  };

  // 编辑中的批注高亮加强
  useEffect(() => {
    const registry = highlightRegistry();
    if (!registry) return;
    registry.delete(HL_ACTIVE_NAME);
    if (editor?.kind === "edit") {
      const range = rangesRef.current.get(editor.annotation.id);
      const HL = highlightCtor();
      if (range && HL) registry.set(HL_ACTIVE_NAME, new HL(range));
    }
  }, [editor, anchorVersion]);

  const cardPosition = (rect: DOMRect | null): React.CSSProperties => {
    if (!rect) return { top: "50%", left: "50%", transform: "translate(-50%, -50%)", width: 288 };
    const width = 288;
    const left = Math.min(Math.max(rect.left, 8), window.innerWidth - width - 8);
    const top = rect.bottom + 8 + 240 > window.innerHeight ? Math.max(8, rect.top - 248) : rect.bottom + 8;
    return { top, left, width };
  };

  const cardNode = (a: Annotation, found: boolean) => (
    <div
      className={`rounded-md border p-2.5 text-xs ${
        found
          ? "border-amber-200 bg-amber-50 dark:border-amber-900/60 dark:bg-amber-900/20"
          : "border-gray-200 bg-gray-50 opacity-70 dark:border-gray-700 dark:bg-gray-900"
      }`}
    >
      <p className={`line-clamp-2 border-l-2 pl-2 text-gray-500 dark:text-gray-400 ${found ? "border-amber-400" : "border-gray-300 dark:border-gray-600"}`}>
        {a.quote}
      </p>
      <p className="mt-1.5 whitespace-pre-wrap text-gray-800 dark:text-gray-200">{a.note}</p>
      {!found && (
        <p className="mt-1 text-[11px] text-gray-400 dark:text-gray-500">原文已重新生成，仅保留笔记</p>
      )}
      <div className="mt-1.5 flex justify-end gap-2">
        <button
          onClick={() => openEditorFor(a)}
          className="inline-flex items-center gap-1 text-[11px] text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
        >
          <Pencil className="h-3 w-3" /> 编辑
        </button>
        <button
          onClick={() => handleDelete(a.id)}
          className="inline-flex items-center gap-1 text-[11px] text-gray-500 hover:text-red-600 dark:text-gray-400 dark:hover:text-red-400"
        >
          <Trash2 className="h-3 w-3" /> 删除
        </button>
        {found && (
          <button
            onClick={() => scrollAnnoIntoView(a.id)}
            className="text-[11px] text-indigo-600 hover:text-indigo-800 dark:text-indigo-400 dark:hover:text-indigo-300"
          >
            定位
          </button>
        )}
      </div>
    </div>
  );

  return (
    <>
      {/* 宽屏侧边：卡片与各自高亮位置对齐，虚线连到正文；没有批注时不渲染 */}
      {sideLayout.length > 0 && (
        <>
          <svg className="pointer-events-none absolute inset-0 hidden h-full w-full overflow-visible xl:block">
            {sideLayout
              .filter((it) => !it.orphan)
              .map((it) => (
                <line
                  key={it.id}
                  x1={it.anchorX}
                  y1={it.anchorY}
                  x2={colX - 6}
                  y2={it.top + 18}
                  stroke="#f59e0b"
                  strokeOpacity={0.6}
                  strokeWidth={1}
                  strokeDasharray="4 3"
                />
              ))}
          </svg>
          <div className="hidden xl:block absolute left-full top-0 ml-6 w-64">
            {sideLayout.map((it) => {
              const a = annotations.find((x) => x.id === it.id);
              if (!a) return null;
              return (
                <div
                  key={it.id}
                  ref={(el) => {
                    if (el) cardRefs.current.set(it.id, el);
                    else cardRefs.current.delete(it.id);
                  }}
                  className="absolute left-0 w-full"
                  style={{ top: it.top }}
                >
                  {cardNode(a, !it.orphan)}
                </div>
              );
            })}
          </div>
        </>
      )}

      {/* 窄屏折叠列表 */}
      {annotations.length > 0 && (
        <div className="mt-6 xl:hidden">
          <button
            onClick={() => setListOpen((v) => !v)}
            className="inline-flex items-center gap-1.5 text-xs font-medium text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
          >
            <StickyNote className="h-3.5 w-3.5" />
            批注（{annotations.length}）
          </button>
          {listOpen && (
            <div className="mt-2 space-y-3">
              {annotations.map((a) => cardNode(a, rangesRef.current.has(a.id)))}
            </div>
          )}
        </div>
      )}

      {/* 选区浮条 */}
      {bubble && !editor && (
        <button
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => {
            setDraft("");
            setEditor({ kind: "new", anchor: bubble.anchor, rect: new DOMRect(bubble.x - 40, bubble.y, 80, 20) });
            setBubble(null);
          }}
          className="fixed z-40 inline-flex -translate-x-1/2 -translate-y-full items-center gap-1 rounded-md bg-gray-900 px-2.5 py-1.5 text-xs font-medium text-white shadow-lg hover:bg-gray-700"
          style={{ left: bubble.x, top: bubble.y }}
        >
          <MessageSquarePlus className="h-3.5 w-3.5" /> 添加批注
        </button>
      )}

      {editor && (
        <div
          className="fixed z-40 rounded-lg border border-gray-200 bg-white p-3 shadow-xl dark:border-gray-700 dark:bg-gray-800"
          style={cardPosition(editor.rect)}
        >
          <div className="mb-2 flex items-start justify-between gap-2">
            <p className="line-clamp-2 border-l-2 border-amber-400 pl-2 text-[11px] text-gray-500 dark:text-gray-400">
              {editor.kind === "edit" ? editor.annotation.quote : editor.anchor.quote}
            </p>
            <button onClick={closeAll} aria-label="关闭" className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          <textarea
            ref={editorRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={3}
            placeholder={editor.kind === "new" ? "写点笔记..." : "修改笔记..."}
            className="w-full resize-none rounded-md border border-gray-300 bg-white px-2 py-1.5 text-xs text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
          />
          <div className="mt-2 flex items-center justify-end gap-2">
            {editor.kind === "edit" && (
              <button
                onClick={() => handleDelete(editor.annotation.id)}
                disabled={deleteMutation.isPending}
                className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-900/30"
              >
                <Trash2 className="h-3 w-3" /> 删除
              </button>
            )}
            <button
              onClick={editor.kind === "new" ? handleCreate : handleSave}
              disabled={createMutation.isPending || updateMutation.isPending}
              className="inline-flex items-center gap-1 rounded-md bg-indigo-600 px-3 py-1 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50 dark:bg-indigo-500 dark:hover:bg-indigo-600"
            >
              {(createMutation.isPending || updateMutation.isPending) && <Loader2 className="h-3 w-3 animate-spin" />}
              {editor.kind === "new" ? "添加" : "保存"}
            </button>
          </div>
        </div>
      )}
    </>
  );
}
