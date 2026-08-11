import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Eye, EyeOff, Save, Loader2 } from "lucide-react";
import { useImaSettings, useUpdateImaSettings } from "../hooks/useSettings";
import { useToast } from "../components/Toast";

export function ImaSettings() {
  const navigate = useNavigate();
  const { data, isLoading } = useImaSettings();
  const updateMutation = useUpdateImaSettings();
  const { toast } = useToast();
  const [showKey, setShowKey] = useState(false);

  // Local form state, synced when server data arrives.
  const [clientId, setClientId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [skillPrompt, setSkillPrompt] = useState("");

  useEffect(() => {
    if (data) {
      setClientId(data.imaClientId);
      setApiKey(data.imaApiKey);
      setSkillPrompt(data.imaSkillPrompt);
    }
  }, [data]);

  const handleSave = () => {
    updateMutation.mutate(
      { imaClientId: clientId, imaApiKey: apiKey, imaSkillPrompt: skillPrompt },
      {
        onSuccess: () => toast("设置已保存", "success"),
        onError: (e) => toast(`保存失败：${(e as Error).message}`, "error"),
      },
    );
  };

  if (isLoading) {
    return <p className="text-sm text-gray-500 dark:text-gray-400">加载中...</p>;
  }

  return (
    <div className="mx-auto max-w-2xl">
      <button
        onClick={() => navigate(-1)}
        className="mb-4 inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
      >
        <ArrowLeft className="h-4 w-4" />
        返回
      </button>

      <h1 className="mb-6 text-lg font-semibold text-gray-900 dark:text-gray-100">保存到 IMA 设置</h1>

      <section className="mb-6 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
        <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">IMA 凭证</h2>
        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
          凭证可从{" "}
          <a
            href="https://ima.qq.com/agent-interface"
            target="_blank"
            rel="noreferrer"
            className="text-indigo-600 hover:underline dark:text-indigo-400"
          >
            ima.qq.com/agent-interface
          </a>{" "}
          获取。保存到 IMA 功能需后端支持，即将上线。
        </p>

        <label className="mt-3 block text-xs font-medium text-gray-600 dark:text-gray-300">
          Client ID
          <input
            type="text"
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            placeholder="IMA_OPENAPI_CLIENTID"
            className="mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
          />
        </label>

        <label className="mt-3 block text-xs font-medium text-gray-600 dark:text-gray-300">
          API Key
          <div className="relative mt-1">
            <input
              type={showKey ? "text" : "password"}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="IMA_OPENAPI_APIKEY"
              className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 pr-9 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
            />
            <button
              type="button"
              onClick={() => setShowKey((v) => !v)}
              className="absolute inset-y-0 right-0 flex items-center px-2 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
              aria-label={showKey ? "隐藏" : "显示"}
            >
              {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </label>
      </section>

      <section className="mb-6 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
        <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">IMA Skill 控制</h2>
        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
          用自然语言描述保存策略，例如保存范围、格式、目标笔记本等。保存时会用 LLM 按此策略整理内容后再保存到 IMA。
        </p>
        <textarea
          value={skillPrompt}
          onChange={(e) => setSkillPrompt(e.target.value)}
          rows={6}
          placeholder="例如：将当前计划的学习内容与关键要点整理为 Markdown 笔记，保存到「学习计划」笔记本，标题使用计划名加日期。"
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
    </div>
  );
}