import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Save, Loader2 } from "lucide-react";
import { useRegenSettings, useUpdateRegenSettings } from "../hooks/useSettings";
import { useToast } from "../components/Toast";

interface FieldDef {
  key: "plan" | "content" | "quiz";
  label: string;
  desc: string;
  placeholder: string;
}

const FIELDS: FieldDef[] = [
  {
    key: "plan",
    label: "计划生成策略",
    desc: "生成或重新生成学习计划时附加的策略要求。",
    placeholder: "例如：模块数量控制在 4~6 个，侧重实战应用，每个模块给出明确的练习建议。",
  },
  {
    key: "content",
    label: "内容生成策略",
    desc: "生成或重新生成模块学习内容时附加的策略要求。",
    placeholder: "例如：内容更精简，每模块控制在 800 字以内，多使用代码示例和图解，结尾必须有关键要点。",
  },
  {
    key: "quiz",
    label: "测验生成策略",
    desc: "生成或重新生成测验时附加的策略要求。",
    placeholder: "例如：增加简答题比例，侧重易错点和应用场景，每题必须有详细解析。",
  },
];

export function RegenerateSettings() {
  const navigate = useNavigate();
  const { data, isLoading } = useRegenSettings();
  const updateMutation = useUpdateRegenSettings();
  const { toast } = useToast();

  const [plan, setPlan] = useState("");
  const [content, setContent] = useState("");
  const [quiz, setQuiz] = useState("");

  useEffect(() => {
    if (data) {
      setPlan(data.plan);
      setContent(data.content);
      setQuiz(data.quiz);
    }
  }, [data]);

  const handleSave = () => {
    updateMutation.mutate(
      { plan, content, quiz },
      {
        onSuccess: () => toast("设置已保存", "success"),
        onError: (e) => toast(`保存失败：${(e as Error).message}`, "error"),
      },
    );
  };

  if (isLoading) {
    return <p className="text-sm text-gray-500 dark:text-gray-400">加载中...</p>;
  }

  const values: Record<FieldDef["key"], string> = { plan, content, quiz };
  const setters: Record<FieldDef["key"], (v: string) => void> = {
    plan: setPlan,
    content: setContent,
    quiz: setQuiz,
  };

  return (
    <div className="mx-auto max-w-2xl">
      <button
        onClick={() => navigate(-1)}
        className="mb-4 inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
      >
        <ArrowLeft className="h-4 w-4" />
        返回
      </button>

      <h1 className="mb-6 text-lg font-semibold text-gray-900 dark:text-gray-100">重新生成设置</h1>

      {FIELDS.map((field) => (
        <section key={field.key} className="mb-6 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">{field.label}</h2>
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{field.desc}</p>
          <textarea
            value={values[field.key]}
            onChange={(e) => setters[field.key](e.target.value)}
            rows={5}
            placeholder={field.placeholder}
            className="mt-2 w-full rounded-md border border-gray-300 bg-white p-3 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
          />
        </section>
      ))}

      <button
        onClick={handleSave}
        disabled={updateMutation.isPending}
        className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 dark:bg-indigo-500 dark:hover:bg-indigo-600"
      >
        {updateMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
        保存设置
      </button>
    </div>
  );
}