import { useState, useRef, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Loader2, FileText, ListChecks, Sparkles,
  CheckCircle2, XCircle, ArrowRight, RotateCcw, BookOpen,
  BookmarkPlus, Settings, Pencil, Save, X, ClipboardCheck,
} from "lucide-react";
import { Markdown } from "../components/Markdown";
import { Annotations } from "../components/Annotations";
import { ActionBar } from "../components/ActionBar";
import { ActionDropdown } from "../components/ActionDropdown";
import { useToast } from "../components/Toast";
import { usePlan, useGenerateQuiz, useGradeQuiz, useSaveAnswers, useSaveToIma, useUpdateContent, PLAN_KEYS } from "../hooks/usePlans";
import { api } from "../api/client";
import { StatusBadge, DifficultyBadge } from "../components/StatusBadge";
import type { Module, Document } from "../api/types";

export function ModuleDetail() {
  const { planId, moduleId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: doc } = usePlan(planId);

  const module = doc?.plan.modules.find((m) => m.id === moduleId);

  const [tab, setTab] = useState<"content" | "quiz">("content");
  const [redoing, setRedoing] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [streamError, setStreamError] = useState("");
  // 批注作用的内容容器（正文 + 关键要点）
  const contentAreaRef = useRef<HTMLDivElement | null>(null);
  // 内容手工编辑（markdown 源码）
  const [editingContent, setEditingContent] = useState(false);
  const [contentDraft, setContentDraft] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  // answersRef mirrors the latest answers so the debounced autosave always
  // persists the most recent value (avoids the stale-closure that made the
  // saved draft lag behind the input).
  const answersRef = useRef<Record<string, string>>({});
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Only (re)load saved answers when the module identity changes. Re-running
  // on every module.answers change would clobber in-progress typing after each
  // autosave round-trip -- the cause of answers "jumping" mid-edit.
  const loadedKey = useRef<string | null>(null);

  const generateQuiz = useGenerateQuiz();
  const saveToIma = useSaveToIma();
  const updateContent = useUpdateContent();
  const { toast } = useToast();

  const handleSaveToIma = (contentType: "content" | "quiz") => {
    saveToIma.mutate(
      { planId: planId!, moduleId: moduleId!, contentType },
      {
        onSuccess: (res) => {
          if (res.ok) toast(`已保存到 IMA：${res.title}`, "success");
          else toast(res.detail || "保存失败", "error");
        },
        onError: (e) => toast(`保存失败：${(e as Error).message}`, "error"),
      },
    );
  };
  const gradeQuiz = useGradeQuiz();
  const saveAnswersMutation = useSaveAnswers();

  useEffect(() => {
    if (!module) return;
    const key = `${planId}/${moduleId}`;
    if (loadedKey.current !== key) {
      const saved = module.answers ?? {};
      setAnswers(saved);
      answersRef.current = saved;
      loadedKey.current = key;
    }
  }, [module, planId, moduleId]);

  useEffect(() => {
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, []);

  const updateAnswer = (qid: string, value: string) => {
    const next = { ...answersRef.current, [qid]: value };
    answersRef.current = next;
    setAnswers(next);
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      saveAnswersMutation.mutate({ planId: planId!, moduleId: moduleId!, answers: answersRef.current });
    }, 800);
  };

  // 多选题: 作答串以「、」分隔选项原文, 与批改/IMA 展示保持一致
  const toggleMultiOption = (qid: string, opt: string) => {
    const current = (answersRef.current[qid] || "").split("、").filter(Boolean);
    const next = current.includes(opt) ? current.filter((o) => o !== opt) : [...current, opt];
    updateAnswer(qid, next.join("、"));
  };

  const handleGenerateContent = async () => {
    setStreaming(true);
    setStreamText("");
    setStreamError("");
    setEditingContent(false);
    try {
      const updatedDoc = await api.streamContent(planId!, moduleId!, (delta) => {
        setStreamText((prev) => prev + delta);
      });
      queryClient.setQueryData(PLAN_KEYS.detail(planId!), updatedDoc);
      setStreamText("");
    } catch (e) {
      setStreamError((e as Error).message);
    } finally {
      setStreaming(false);
    }
  };

  // Regenerate the quiz via the existing endpoint (no backend change).
  const handleRegenerateQuiz = () => {
    generateQuiz.mutate(
      { planId: planId!, moduleId: moduleId! },
      {
        onSuccess: () => {
          setAnswers({});
          answersRef.current = {};
          loadedKey.current = null;
          setRedoing(false);
        },
      },
    );
  };

  if (!doc || !module) return <p className="text-sm text-gray-500 dark:text-gray-400">加载中...</p>;

  const hasContent = !!module.content;
  const hasQuiz = !!module.quiz;
  const hasResult = !!module.result;

  const startEditContent = () => {
    setContentDraft(module.content?.markdown ?? "");
    setEditingContent(true);
  };

  const handleSaveContent = () => {
    if (!contentDraft.trim()) return;
    updateContent.mutate(
      { planId: planId!, moduleId: moduleId!, markdown: contentDraft },
      {
        onSuccess: () => {
          setEditingContent(false);
          toast("内容已保存", "success");
        },
        onError: (e) => toast(`保存失败：${(e as Error).message}`, "error"),
      },
    );
  };

  const nextModule = doc.plan.modules
    .slice(doc.plan.modules.findIndex((m) => m.id === moduleId) + 1)
    .find((m) => m.status !== "completed");

  return (
    <div>
      <button
        onClick={() => navigate(`/plans/${planId}`)}
        className="mb-4 inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
      >
        <ArrowLeft className="h-4 w-4" />
        返回计划
      </button>

      {/* Module header */}
      <div className="mb-6 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
        <div className="flex items-center gap-2">
          <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">{module.title}</h1>
          <StatusBadge status={module.status} />
        </div>
        <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">{module.summary}</p>
        {module.objectives.length > 0 && (
          <div className="mt-3">
            <p className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">学习目标</p>
            <ul className="list-inside list-disc space-y-0.5 text-sm text-gray-600 dark:text-gray-300">
              {module.objectives.map((obj, i) => <li key={i}>{obj}</li>)}
            </ul>
          </div>
        )}
        <div className="mt-3 flex items-center gap-3 text-xs text-gray-500 dark:text-gray-400">
          <DifficultyBadge difficulty={module.difficulty} />
          <span>{module.minutes} 分钟</span>
        </div>
      </div>

      {/* If graded and not redoing, show results full-width */}
      {hasResult && !redoing ? (
        <ResultsView module={module} planId={planId!} moduleId={moduleId!}
          onNext={nextModule ? () => navigate(`/plans/${planId}/modules/${nextModule.id}`) : undefined}
          onRedo={() => { setRedoing(true); setTab("quiz"); }}
          onRestudy={() => { setRedoing(true); setTab("content"); }}
          onRegrade={() => gradeQuiz.mutate(
            { planId: planId!, moduleId: moduleId! },
            {
              onSuccess: () => setRedoing(false),
              onError: (e) => toast(`重新批改失败：${(e as Error).message}`, "error"),
            },
          )}
          regrading={gradeQuiz.isPending}
        />
      ) : (
        <>
          {/* Tabs */}
          <div className="mb-4 inline-flex rounded-md border border-gray-200 p-0.5 dark:border-gray-700">
            <button
              onClick={() => setTab("content")}
              className={`inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium transition ${
                tab === "content" ? "bg-indigo-600 text-white dark:bg-indigo-500" : "text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
              }`}
            >
              <FileText className="h-3.5 w-3.5" />
              学习内容
            </button>
            <button
              onClick={() => setTab("quiz")}
              className={`inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium transition ${
                tab === "quiz" ? "bg-indigo-600 text-white dark:bg-indigo-500" : "text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
              }`}
            >
              <ListChecks className="h-3.5 w-3.5" />
              测验
            </button>
          </div>

          {/* Content tab */}
          {tab === "content" && (
            <div>
              {!hasContent && !streaming && (
                <button
                  onClick={handleGenerateContent}
                  className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 dark:bg-indigo-500 dark:hover:bg-indigo-600"
                >
                  <Sparkles className="h-4 w-4" />
                  生成学习内容
                </button>
              )}

              {streaming && (
                <div>
                  <div className="mb-2 flex items-center gap-2 text-sm text-indigo-600 dark:text-indigo-400">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    生成中...
                  </div>
                  <div className="prose prose-sm max-w-none dark:prose-invert">
                    <Markdown>{streamText}</Markdown>
                  </div>
                </div>
              )}

              {streamError && (
                <p className="text-sm text-red-600 dark:text-red-400">生成失败：{streamError}</p>
              )}

              {hasContent && !streaming && editingContent && (
                <div>
                  <textarea
                    value={contentDraft}
                    onChange={(e) => setContentDraft(e.target.value)}
                    placeholder="支持 Markdown 语法"
                    className="w-full rounded-md border border-gray-300 bg-white p-3 font-mono text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                    style={{ minHeight: "60vh" }}
                  />
                  <div className="mt-2 flex items-center gap-2">
                    <button
                      onClick={handleSaveContent}
                      disabled={updateContent.isPending || !contentDraft.trim()}
                      className="inline-flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 dark:bg-indigo-500 dark:hover:bg-indigo-600"
                    >
                      {updateContent.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                      保存
                    </button>
                    <button
                      onClick={() => setEditingContent(false)}
                      className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700"
                    >
                      <X className="h-4 w-4" />
                      取消
                    </button>
                    <span className="text-xs text-gray-400 dark:text-gray-500">关键要点不会被修改；重新生成内容会覆盖手工编辑</span>
                  </div>
                </div>
              )}

              {hasContent && !streaming && !editingContent && (
                <div className="relative">
                  <div className="mb-2 flex justify-end">
                    <button
                      onClick={startEditContent}
                      className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-700 dark:hover:text-gray-200"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                      编辑
                    </button>
                  </div>
                  <div ref={contentAreaRef}>
                    <div className="prose prose-sm max-w-none dark:prose-invert">
                      <Markdown>{module.content!.markdown}</Markdown>
                    </div>
                    {module.content!.keyTakeaways.length > 0 && (
                      <div className="mt-4 rounded-lg border border-indigo-100 bg-indigo-50 p-4 dark:border-indigo-800 dark:bg-indigo-900/30">
                        <p className="mb-2 text-sm font-medium text-indigo-900 dark:text-indigo-200">关键要点</p>
                        <ul className="space-y-1 text-sm text-indigo-800 dark:text-indigo-300">
                          {module.content!.keyTakeaways.map((p, i) => (
                            <li key={i} className="flex gap-2">
                              <span className="text-indigo-400 dark:text-indigo-500">{i + 1}.</span>
                              <Markdown inline>{p}</Markdown>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                  <Annotations
                    containerRef={contentAreaRef}
                    planId={planId!}
                    moduleId={moduleId!}
                    anchorKey={module.content!.markdown}
                  />
                </div>
              )}
            </div>
          )}

          {/* Quiz tab */}
          {tab === "quiz" && (
            <div>
              {!hasQuiz && (
                <button
                  onClick={() => generateQuiz.mutate({ planId: planId!, moduleId: moduleId! })}
                  disabled={generateQuiz.isPending}
                  className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 dark:bg-indigo-500 dark:hover:bg-indigo-600"
                >
                  {generateQuiz.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                  {generateQuiz.isPending ? "生成中..." : "生成测验"}
                </button>
              )}

              {generateQuiz.isError && (
                <p className="mt-2 text-sm text-red-600 dark:text-red-400">
                  生成失败：{(generateQuiz.error as Error).message}
                </p>
              )}

              {hasQuiz && (
                <div className="space-y-4">
                  {module.quiz!.questions.map((q, i) => (
                    <div key={q.id} className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
                      <p className="mb-3 text-sm font-medium text-gray-900 dark:text-gray-100">
                        {i + 1}. <Markdown inline>{q.prompt}</Markdown>
                        <span className="ml-2 text-xs text-gray-400 dark:text-gray-500">
                          {q.type === "mcq" ? "单选" : q.type === "mcq_multi" ? "多选" : "简答"}
                        </span>
                      </p>

                      {q.type === "short" ? (
                        <textarea
                          value={answers[q.id] || ""}
                          onChange={(e) => updateAnswer(q.id, e.target.value)}
                          rows={4}
                          placeholder="输入你的答案..."
                          className="w-full rounded-md border border-gray-300 bg-white p-2.5 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                        />
                      ) : (
                        <div className="space-y-2">
                          {q.options.map((opt) => {
                            const checked =
                              q.type === "mcq_multi"
                                ? (answers[q.id] || "").split("、").filter(Boolean).includes(opt)
                                : answers[q.id] === opt;
                            return (
                              <label
                                key={opt}
                                className={`flex cursor-pointer items-center gap-2 rounded-md border p-2 text-sm transition ${
                                  checked
                                    ? "border-indigo-500 bg-indigo-50 dark:border-indigo-500 dark:bg-indigo-900/30"
                                    : "border-gray-200 hover:border-gray-300 dark:border-gray-700 dark:hover:border-gray-600"
                                }`}
                              >
                                <input
                                  type={q.type === "mcq_multi" ? "checkbox" : "radio"}
                                  name={q.id}
                                  checked={checked}
                                  onChange={() =>
                                    q.type === "mcq_multi" ? toggleMultiOption(q.id, opt) : updateAnswer(q.id, opt)
                                  }
                                  className="text-indigo-600 dark:text-indigo-500"
                                />
                                <span className="text-gray-700 dark:text-gray-300"><Markdown inline>{opt}</Markdown></span>
                              </label>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  ))}

                  <button
                    onClick={() => gradeQuiz.mutate(
                      { planId: planId!, moduleId: moduleId! },
                      { onSuccess: () => setRedoing(false) },
                    )}
                    disabled={gradeQuiz.isPending}
                    className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 dark:bg-indigo-500 dark:hover:bg-indigo-600"
                  >
                    {gradeQuiz.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                    {gradeQuiz.isPending ? "批改中..." : "提交批改"}
                  </button>

                  {gradeQuiz.isError && (
                    <p className="text-sm text-red-600 dark:text-red-400">
                      批改失败：{(gradeQuiz.error as Error).message}
                    </p>
                  )}
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* 保存到 IMA / 重新生成：仅在当前页签有内容时显示，固定在页面右下角 */}
      {!(hasResult && !redoing) && ((tab === "content" && hasContent && !streaming) || (tab === "quiz" && hasQuiz)) && (
        <div className="fixed bottom-6 right-6 z-30">
          <ActionBar
            onRegenerate={tab === "content" ? handleGenerateContent : handleRegenerateQuiz}
            regenerating={tab === "content" ? streaming : generateQuiz.isPending}
            onSaveToIma={() => handleSaveToIma(tab)}
            regenType={tab === "content" ? "content" : "quiz"}
            dropUp
          />
        </div>
      )}
    </div>
  );
}

// ============================================================
// ResultsView sub-component
// ============================================================
function ResultsView({
  module, planId, moduleId, onNext, onRedo, onRestudy, onRegrade, regrading,
}: {
  module: Module;
  planId: string;
  moduleId: string;
  onNext?: () => void;
  onRedo: () => void;
  onRestudy: () => void;
  onRegrade: () => void;
  regrading: boolean;
}) {
  const navigate = useNavigate();
  const { toast } = useToast();
  const saveToIma = useSaveToIma();
  const r = module.result!;

  const handleSaveToIma = () => {
    saveToIma.mutate(
      { planId, moduleId, contentType: "result" },
      {
        onSuccess: (res) => {
          if (res.ok) toast(`已保存到 IMA：${res.title}`, "success");
          else toast(res.detail || "保存失败", "error");
        },
        onError: (e) => toast(`保存失败：${(e as Error).message}`, "error"),
      },
    );
  };
  const quiz = module.quiz!;
  const pct = r.maxScore > 0 ? Math.round((r.totalScore / r.maxScore) * 100) : 0;

  return (
    <div className="space-y-4">
      {/* Score */}
      <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-gray-500 dark:text-gray-400">批改结果</p>
            <p className="mt-1 text-3xl font-bold text-gray-900 dark:text-gray-100">
              {r.totalScore}<span className="text-lg text-gray-400 dark:text-gray-500">/{r.maxScore}</span>
              <span className="ml-2 text-base font-normal text-gray-500 dark:text-gray-400">{pct}分</span>
            </p>
          </div>
          <div className={`flex h-16 w-16 items-center justify-center rounded-full text-2xl font-bold ${
            pct >= 80 ? "bg-green-100 text-green-600 dark:bg-green-900/40 dark:text-green-400" : pct >= 60 ? "bg-amber-100 text-amber-600 dark:bg-amber-900/40 dark:text-amber-400" : "bg-red-100 text-red-600 dark:bg-red-900/40 dark:text-red-400"
          }`}>
            {pct}
          </div>
        </div>
      </div>

      {/* Assessment */}
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-green-200 bg-green-50 p-3 dark:border-green-800 dark:bg-green-900/20">
          <p className="mb-2 text-xs font-medium text-green-800 dark:text-green-300">优势</p>
          <ul className="space-y-1 text-xs text-green-700 dark:text-green-400">
            {r.assessment.strengths.map((s, i) => <li key={i}><Markdown inline>{s}</Markdown></li>)}
          </ul>
        </div>
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 dark:border-red-800 dark:bg-red-900/20">
          <p className="mb-2 text-xs font-medium text-red-800 dark:text-red-300">不足</p>
          <ul className="space-y-1 text-xs text-red-700 dark:text-red-400">
            {r.assessment.weaknesses.map((s, i) => <li key={i}><Markdown inline>{s}</Markdown></li>)}
          </ul>
        </div>
        <div className="rounded-lg border border-indigo-200 bg-indigo-50 p-3 dark:border-indigo-800 dark:bg-indigo-900/20">
          <p className="mb-2 text-xs font-medium text-indigo-800 dark:text-indigo-300">建议</p>
          <ul className="space-y-1 text-xs text-indigo-700 dark:text-indigo-400">
            {r.assessment.recommendations.map((s, i) => <li key={i}><Markdown inline>{s}</Markdown></li>)}
          </ul>
        </div>
      </div>

      {/* Per-question review */}
      <div className="space-y-3">
        <p className="text-sm font-medium text-gray-700 dark:text-gray-300">逐题回顾</p>
        {r.results.map((qr, i) => {
          const q = quiz.questions.find((qq) => qq.id === qr.questionId);
          if (!q) return null;
          return (
            <div
              key={qr.questionId}
              className={`rounded-lg border p-4 ${
                qr.correct
                  ? "border-green-200 bg-green-50/50 dark:border-green-800 dark:bg-green-900/20"
                  : "border-red-200 bg-red-50/50 dark:border-red-800 dark:bg-red-900/20"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                  {i + 1}. <Markdown inline>{q.prompt}</Markdown>
                </p>
                <div className="flex items-center gap-1.5 whitespace-nowrap text-xs">
                  {qr.correct ? (
                    <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400" />
                  ) : (
                    <XCircle className="h-4 w-4 text-red-600 dark:text-red-400" />
                  )}
                  <span className="font-medium text-gray-700 dark:text-gray-300">{qr.score}/{qr.maxScore}</span>
                </div>
              </div>

              <div className="mt-2 space-y-1 text-xs text-gray-600 dark:text-gray-400">
                <p><span className="text-gray-400 dark:text-gray-500">你的答案：</span>{qr.studentAnswer ? <Markdown inline>{qr.studentAnswer}</Markdown> : "（未作答）"}</p>
                {q.type === "short" ? (
                  <>
                    <p><span className="text-gray-400 dark:text-gray-500">参考答案：</span>{q.modelAnswer && <Markdown inline>{q.modelAnswer}</Markdown>}</p>
                    {q.keyPoints.length > 0 && (
                      <p><span className="text-gray-400 dark:text-gray-500">要点：</span><Markdown inline>{q.keyPoints.join("、")}</Markdown></p>
                    )}
                  </>
                ) : q.type === "mcq_multi" ? (
                  <p><span className="text-gray-400 dark:text-gray-500">正确答案（多选）：</span>{q.answers.length > 0 && <Markdown inline>{q.answers.join("、")}</Markdown>}</p>
                ) : (
                  <p><span className="text-gray-400 dark:text-gray-500">正确答案：</span>{q.answer && <Markdown inline>{q.answer}</Markdown>}</p>
                )}
                <p><span className="text-gray-400 dark:text-gray-500">反馈：</span><Markdown inline>{qr.feedback}</Markdown></p>
              </div>
            </div>
          );
        })}
      </div>

      {/* Actions */}
      <div className="flex flex-wrap items-center gap-3 pt-2">
        <button
          onClick={onRedo}
          className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700"
        >
          <RotateCcw className="h-4 w-4" />
          重做
        </button>
        <button
          onClick={onRestudy}
          className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700"
        >
          <BookOpen className="h-4 w-4" />
          重新学习
        </button>
        {/* 重新批改：按当前作答再批一次；「更多」里是批改策略设置 */}
        <ActionDropdown
          label="重新批改"
          icon={<ClipboardCheck className="h-4 w-4" />}
          onAction={onRegrade}
          busy={regrading}
          title="按当前作答重新批改（可先在「更多」里调整批改策略）"
          dropUp
          menuItems={[
            {
              label: "批改设置",
              icon: <Settings className="h-4 w-4" />,
              onClick: () => navigate("/settings/regenerate", { state: { regenType: "grade" } }),
            },
          ]}
        />
        <ActionDropdown
          label="保存到 IMA"
          icon={<BookmarkPlus className="h-4 w-4" />}
          onAction={handleSaveToIma}
          busy={saveToIma.isPending}
          menuItems={[
            {
              label: "设置",
              icon: <Settings className="h-4 w-4" />,
              onClick: () => navigate("/settings/ima"),
            },
          ]}
          title="保存到 IMA"
          dropUp
        />
        {onNext && (
          <button
            onClick={onNext}
            className="inline-flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 dark:bg-indigo-500 dark:hover:bg-indigo-600"
          >
            下一模块
            <ArrowRight className="h-4 w-4" />
          </button>
        )}
      </div>
    </div>
  );
}
