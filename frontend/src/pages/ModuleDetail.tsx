import { useState, useRef, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Loader2, FileText, ListChecks, Sparkles,
  CheckCircle2, XCircle, ArrowRight, RotateCcw, BookOpen,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { usePlan, useGenerateQuiz, useGradeQuiz, useSaveAnswers, PLAN_KEYS } from "../hooks/usePlans";
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

  const handleGenerateContent = async () => {
    setStreaming(true);
    setStreamText("");
    setStreamError("");
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

  if (!doc || !module) return <p className="text-sm text-gray-500">加载中...</p>;

  const hasContent = !!module.content;
  const hasQuiz = !!module.quiz;
  const hasResult = !!module.result;
  const nextModule = doc.plan.modules
    .slice(doc.plan.modules.findIndex((m) => m.id === moduleId) + 1)
    .find((m) => m.status !== "completed");

  return (
    <div>
      <button
        onClick={() => navigate(`/plans/${planId}`)}
        className="mb-4 inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900"
      >
        <ArrowLeft className="h-4 w-4" />
        返回计划
      </button>

      {/* Module header */}
      <div className="mb-6 rounded-lg border border-gray-200 bg-white p-4">
        <div className="flex items-center gap-2">
          <h1 className="text-lg font-semibold text-gray-900">{module.title}</h1>
          <StatusBadge status={module.status} />
        </div>
        <p className="mt-1 text-sm text-gray-600">{module.summary}</p>
        {module.objectives.length > 0 && (
          <div className="mt-3">
            <p className="mb-1 text-xs font-medium text-gray-500">学习目标</p>
            <ul className="list-inside list-disc space-y-0.5 text-sm text-gray-600">
              {module.objectives.map((obj, i) => <li key={i}>{obj}</li>)}
            </ul>
          </div>
        )}
        <div className="mt-3 flex items-center gap-3 text-xs text-gray-500">
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
        />
      ) : (
        <>
          {/* Tabs */}
          <div className="mb-4 inline-flex rounded-md border border-gray-200 p-0.5">
            <button
              onClick={() => setTab("content")}
              className={`inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium transition ${
                tab === "content" ? "bg-indigo-600 text-white" : "text-gray-600 hover:text-gray-900"
              }`}
            >
              <FileText className="h-3.5 w-3.5" />
              学习内容
            </button>
            <button
              onClick={() => setTab("quiz")}
              className={`inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium transition ${
                tab === "quiz" ? "bg-indigo-600 text-white" : "text-gray-600 hover:text-gray-900"
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
                  className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
                >
                  <Sparkles className="h-4 w-4" />
                  生成学习内容
                </button>
              )}

              {streaming && (
                <div>
                  <div className="mb-2 flex items-center gap-2 text-sm text-indigo-600">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    生成中...
                  </div>
                  <div className="prose prose-sm max-w-none">
                    <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[[rehypeKatex, { throwOnError: false }]]}>{streamText}</ReactMarkdown>
                  </div>
                </div>
              )}

              {streamError && (
                <p className="text-sm text-red-600">生成失败：{streamError}</p>
              )}

              {hasContent && !streaming && (
                <div>
                  <div className="prose prose-sm max-w-none">
                    <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[[rehypeKatex, { throwOnError: false }]]}>
                      {module.content!.markdown}
                    </ReactMarkdown>
                  </div>
                  {module.content!.keyTakeaways.length > 0 && (
                    <div className="mt-4 rounded-lg border border-indigo-100 bg-indigo-50 p-4">
                      <p className="mb-2 text-sm font-medium text-indigo-900">关键要点</p>
                      <ul className="space-y-1 text-sm text-indigo-800">
                        {module.content!.keyTakeaways.map((p, i) => (
                          <li key={i} className="flex gap-2">
                            <span className="text-indigo-400">{i + 1}.</span>
                            <span>{p}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
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
                  className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  {generateQuiz.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                  {generateQuiz.isPending ? "生成中..." : "生成测验"}
                </button>
              )}

              {generateQuiz.isError && (
                <p className="mt-2 text-sm text-red-600">
                  生成失败：{(generateQuiz.error as Error).message}
                </p>
              )}

              {hasQuiz && (
                <div className="space-y-4">
                  {module.quiz!.questions.map((q, i) => (
                    <div key={q.id} className="rounded-lg border border-gray-200 bg-white p-4">
                      <p className="mb-3 text-sm font-medium text-gray-900">
                        {i + 1}. {q.prompt}
                        <span className="ml-2 text-xs text-gray-400">
                          {q.type === "mcq" ? "单选" : "简答"}
                        </span>
                      </p>

                      {q.type === "mcq" ? (
                        <div className="space-y-2">
                          {q.options.map((opt) => (
                            <label
                              key={opt}
                              className={`flex cursor-pointer items-center gap-2 rounded-md border p-2 text-sm transition ${
                                answers[q.id] === opt
                                  ? "border-indigo-500 bg-indigo-50"
                                  : "border-gray-200 hover:border-gray-300"
                              }`}
                            >
                              <input
                                type="radio"
                                name={q.id}
                                checked={answers[q.id] === opt}
                                onChange={() => updateAnswer(q.id, opt)}
                                className="text-indigo-600"
                              />
                              <span className="text-gray-700">{opt}</span>
                            </label>
                          ))}
                        </div>
                      ) : (
                        <textarea
                          value={answers[q.id] || ""}
                          onChange={(e) => updateAnswer(q.id, e.target.value)}
                          rows={4}
                          placeholder="输入你的答案..."
                          className="w-full rounded-md border border-gray-300 p-2.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                        />
                      )}
                    </div>
                  ))}

                  <button
                    onClick={() => gradeQuiz.mutate(
                      { planId: planId!, moduleId: moduleId! },
                      { onSuccess: () => setRedoing(false) },
                    )}
                    disabled={gradeQuiz.isPending}
                    className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                  >
                    {gradeQuiz.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                    {gradeQuiz.isPending ? "批改中..." : "提交批改"}
                  </button>

                  {gradeQuiz.isError && (
                    <p className="text-sm text-red-600">
                      批改失败：{(gradeQuiz.error as Error).message}
                    </p>
                  )}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ============================================================
// ResultsView sub-component
// ============================================================
function ResultsView({
  module, planId, moduleId, onNext, onRedo, onRestudy,
}: {
  module: Module;
  planId: string;
  moduleId: string;
  onNext?: () => void;
  onRedo: () => void;
  onRestudy: () => void;
}) {
  const r = module.result!;
  const quiz = module.quiz!;
  const pct = r.maxScore > 0 ? Math.round((r.totalScore / r.maxScore) * 100) : 0;

  return (
    <div className="space-y-4">
      {/* Score */}
      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-gray-500">批改结果</p>
            <p className="mt-1 text-3xl font-bold text-gray-900">
              {r.totalScore}<span className="text-lg text-gray-400">/{r.maxScore}</span>
              <span className="ml-2 text-base font-normal text-gray-500">{pct}分</span>
            </p>
          </div>
          <div className={`flex h-16 w-16 items-center justify-center rounded-full text-2xl font-bold ${
            pct >= 80 ? "bg-green-100 text-green-600" : pct >= 60 ? "bg-amber-100 text-amber-600" : "bg-red-100 text-red-600"
          }`}>
            {pct}
          </div>
        </div>
      </div>

      {/* Assessment */}
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-green-200 bg-green-50 p-3">
          <p className="mb-2 text-xs font-medium text-green-800">优势</p>
          <ul className="space-y-1 text-xs text-green-700">
            {r.assessment.strengths.map((s, i) => <li key={i}>{s}</li>)}
          </ul>
        </div>
        <div className="rounded-lg border border-red-200 bg-red-50 p-3">
          <p className="mb-2 text-xs font-medium text-red-800">不足</p>
          <ul className="space-y-1 text-xs text-red-700">
            {r.assessment.weaknesses.map((s, i) => <li key={i}>{s}</li>)}
          </ul>
        </div>
        <div className="rounded-lg border border-indigo-200 bg-indigo-50 p-3">
          <p className="mb-2 text-xs font-medium text-indigo-800">建议</p>
          <ul className="space-y-1 text-xs text-indigo-700">
            {r.assessment.recommendations.map((s, i) => <li key={i}>{s}</li>)}
          </ul>
        </div>
      </div>

      {/* Per-question review */}
      <div className="space-y-3">
        <p className="text-sm font-medium text-gray-700">逐题回顾</p>
        {r.results.map((qr, i) => {
          const q = quiz.questions.find((qq) => qq.id === qr.questionId);
          if (!q) return null;
          return (
            <div
              key={qr.questionId}
              className={`rounded-lg border p-4 ${
                qr.correct ? "border-green-200 bg-green-50/50" : "border-red-200 bg-red-50/50"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm font-medium text-gray-900">
                  {i + 1}. {q.prompt}
                </p>
                <div className="flex items-center gap-1.5 whitespace-nowrap text-xs">
                  {qr.correct ? (
                    <CheckCircle2 className="h-4 w-4 text-green-600" />
                  ) : (
                    <XCircle className="h-4 w-4 text-red-600" />
                  )}
                  <span className="font-medium text-gray-700">{qr.score}/{qr.maxScore}</span>
                </div>
              </div>

              <div className="mt-2 space-y-1 text-xs text-gray-600">
                <p><span className="text-gray-400">你的答案：</span>{qr.studentAnswer || "（未作答）"}</p>
                {q.type === "mcq" ? (
                  <p><span className="text-gray-400">正确答案：</span>{q.answer}</p>
                ) : (
                  <>
                    <p><span className="text-gray-400">参考答案：</span>{q.modelAnswer}</p>
                    {q.keyPoints.length > 0 && (
                      <p><span className="text-gray-400">要点：</span>{q.keyPoints.join("、")}</p>
                    )}
                  </>
                )}
                <p><span className="text-gray-400">反馈：</span>{qr.feedback}</p>
              </div>
            </div>
          );
        })}
      </div>

      {/* Actions */}
      <div className="flex flex-wrap items-center gap-3 pt-2">
        <button
          onClick={onRedo}
          className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          <RotateCcw className="h-4 w-4" />
          重做
        </button>
        <button
          onClick={onRestudy}
          className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          <BookOpen className="h-4 w-4" />
          重新学习
        </button>
        {onNext && (
          <button
            onClick={onNext}
            className="inline-flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
          >
            下一模块
            <ArrowRight className="h-4 w-4" />
          </button>
        )}
      </div>
    </div>
  );
}
