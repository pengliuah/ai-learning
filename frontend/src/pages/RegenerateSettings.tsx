import { useState, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { ArrowLeft, Save, Loader2, FileText, BookOpen, HelpCircle, ClipboardCheck } from "lucide-react";
import { useRegenSettings, useUpdateRegenSettings } from "../hooks/useSettings";
import { useToast } from "../components/Toast";

type GenType = "plan" | "content" | "quiz" | "grade";

interface FieldDef {
  key: GenType;
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
  {
    key: "grade",
    label: "批改策略",
    desc: "批改测验时附加的评分要求（如评分尺度、给分偏好）。",
    placeholder: "例如：按步骤给分，答对核心概念即可得分；整体评估多给改进建议，语气鼓励一些。",
  },
];

export function RegenerateSettings() {
  const navigate = useNavigate();
  const location = useLocation();
  // 从 ActionBar「设置」入口进来时定位到对应类型；默认计划
  const initialType = ((location.state as any)?.regenType as GenType) || "plan";

  const { data, isLoading } = useRegenSettings();
  const updateMutation = useUpdateRegenSettings();
  const { toast } = useToast();

  const [active, setActive] = useState<GenType>(initialType);
  const [values, setValues] = useState<Record<GenType, string>>({
    plan: "", content: "", quiz: "", grade: "",
  });

  useEffect(() => {
    if (data) {
      setValues({ plan: data.plan, content: data.content, quiz: data.quiz, grade: data.grade });
    }
  }, [data]);

  const handleSave = () => {
    updateMutation.mutate(values, {
      onSuccess: () => toast("设置已保存", "success"),
      onError: (e) => toast(`保存失败：${(e as Error).message}`, "error"),
    });
  };

  if (isLoading) {
    return <p className="text-sm text-gray-500 dark:text-gray-400">加载中...</p>;
  }

  const TAB_ICONS: Record<GenType, React.ReactNode> = {
    plan: <FileText className="h-4 w-4" />,
    content: <BookOpen className="h-4 w-4" />,
    quiz: <HelpCircle className="h-4 w-4" />,
    grade: <ClipboardCheck className="h-4 w-4" />,
  };

  const activeField = FIELDS.find((f) => f.key === active)!;

  return (
    <div className="mx-auto w-full max-w-5xl">
      <button
        onClick={() => navigate(-1)}
        className="mb-4 inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
      >
        <ArrowLeft className="h-4 w-4" />
        返回
      </button>

      <h1 className="mb-6 text-lg font-semibold text-gray-900 dark:text-gray-100">重新生成设置</h1>

      {/* 类型切换 */}
      <div className="mb-4 flex flex-wrap gap-1 rounded-md border border-gray-200 p-0.5 dark:border-gray-700">
        {FIELDS.map((f) => (
          <button
            key={f.key}
            onClick={() => setActive(f.key)}
            className={`inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium transition ${
              active === f.key
                ? "bg-indigo-600 text-white dark:bg-indigo-500"
                : "text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
            }`}
          >
            {TAB_ICONS[f.key]}
            {f.label.replace("生成策略", "").replace("策略", "")}
          </button>
        ))}
      </div>

      <section className="mb-6 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
        <h2 className="mb-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
          <span className="mr-1.5 inline-block align-middle">{TAB_ICONS[activeField.key]}</span>
          {activeField.label}
        </h2>
        <p className="text-xs text-gray-500 dark:text-gray-400">{activeField.desc}</p>
        <textarea
          value={values[activeField.key]}
          onChange={(e) => setValues((v) => ({ ...v, [activeField.key]: e.target.value }))}
          rows={6}
          placeholder={activeField.placeholder}
          className="mt-2 w-full rounded-md border border-gray-300 bg-white p-3 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
        />
      </section>

      <button
        onClick={handleSave}
        disabled={updateMutation.isPending}
        className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 dark:bg-indigo-500 dark:hover:bg-indigo-600"
      >
        {updateMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
        保存设置
      </button>
      <p className="mt-2 text-xs text-gray-400 dark:text-gray-500">
        保存会同时提交全部四类策略（留空表示使用默认行为）。
      </p>
    </div>
  );
}
