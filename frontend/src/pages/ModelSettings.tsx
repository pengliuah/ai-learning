import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Eye, EyeOff, Save, Loader2, Settings2 } from "lucide-react";
import { useModelSettings, useUpdateModelSettings, useUsageSummary } from "../hooks/useSettings";
import { useToast } from "../components/Toast";
import type { UsageStat } from "../api/types";

function formatTokens(n: number): string {
  return n.toLocaleString("zh-CN");
}

/** 今日 / 本月 / 累计 token 用量卡片（来自后端 token_usage 统计表）。 */
function UsageCard() {
  const { data } = useUsageSummary();
  if (!data) return null;

  const cells: [string, UsageStat][] = [
    ["今日", data.today],
    ["本月", data.month],
    ["累计", data.allTime],
  ];

  return (
    <section className="mb-6 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
      <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Token 用量</h2>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
        本账号调用模型的 token 消耗统计（统计自本系统，余额请到对应模型服务商控制台查看）。
      </p>
      <div className="mt-3 grid grid-cols-3 gap-3">
        {cells.map(([label, stat]) => (
          <div
            key={label}
            className="rounded-md border border-gray-100 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-900"
          >
            <p className="text-xs text-gray-500 dark:text-gray-400">{label}</p>
            <p className="mt-1 text-lg font-semibold text-gray-900 dark:text-gray-100">
              {formatTokens(stat.totalTokens)}
            </p>
            <p className="text-xs text-gray-400 dark:text-gray-500">
              输入 {formatTokens(stat.inputTokens)} / 输出 {formatTokens(stat.outputTokens)}
            </p>
            <p className="text-xs text-gray-400 dark:text-gray-500">{stat.requests} 次调用</p>
          </div>
        ))}
      </div>
    </section>
  );
}

export function ModelSettings() {
  const navigate = useNavigate();
  const { data, isLoading } = useModelSettings();
  const updateMutation = useUpdateModelSettings();
  const { toast } = useToast();
  const [showKey, setShowKey] = useState(false);
  const [showEmbeddingKey, setShowEmbeddingKey] = useState(false);

  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [maxTokens, setMaxTokens] = useState(8192);
  const [embeddingApiKey, setEmbeddingApiKey] = useState("");
  const [embeddingModel, setEmbeddingModel] = useState("");
  const [embeddingBaseUrl, setEmbeddingBaseUrl] = useState("");

  useEffect(() => {
    if (data) {
      setApiKey(data.apiKey);
      setModel(data.model);
      setBaseUrl(data.baseUrl);
      if (data.maxTokens !== undefined) setMaxTokens(data.maxTokens);
      setEmbeddingApiKey(data.embeddingApiKey ?? "");
      setEmbeddingModel(data.embeddingModel ?? "");
      setEmbeddingBaseUrl(data.embeddingBaseUrl ?? "");
    }
  }, [data]);

  const handleSave = () => {
    updateMutation.mutate(
      { apiKey, model, baseUrl, maxTokens, embeddingApiKey, embeddingModel, embeddingBaseUrl },
      {
        onSuccess: () => toast("模型设置已保存", "success"),
        onError: (e) => toast(`保存失败：${(e as Error).message}`, "error"),
      },
    );
  };

  if (isLoading) {
    return <p className="text-sm text-gray-500 dark:text-gray-400">加载中...</p>;
  }

  return (
    <div className="mx-auto w-full max-w-2xl">
      <button
        onClick={() => navigate(-1)}
        className="mb-4 inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
      >
        <ArrowLeft className="h-4 w-4" />
        返回
      </button>

      <h1 className="mb-6 flex items-center gap-2 text-lg font-semibold text-gray-900 dark:text-gray-100">
        <Settings2 className="h-5 w-5 text-indigo-600 dark:text-indigo-400" />
        模型设置
      </h1>

      <UsageCard />

      <section className="mb-6 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
        <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">大模型配置</h2>
        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
          对当前账号生效，用于本账号的所有 AI 生成任务。配置只保存在数据库中；未配置时 AI 生成功能不可用。
        </p>

        <label className="mt-3 block text-xs font-medium text-gray-600 dark:text-gray-300">
          API Key
          <div className="relative mt-1">
            <input
              type={showKey ? "text" : "password"}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
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

        <label className="mt-3 block text-xs font-medium text-gray-600 dark:text-gray-300">
          模型名称
          <input
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="doubao-1.5-pro-32k"
            className="mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
          />
        </label>

        <label className="mt-3 block text-xs font-medium text-gray-600 dark:text-gray-300">
          Base URL
          <input
            type="text"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://ark.cn-beijing.volces.com/api/v3"
            className="mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
          />
        </label>

        <label className="mt-3 block text-xs font-medium text-gray-600 dark:text-gray-300">
          最大输出 Token
          <div className="mt-1 flex items-center gap-2">
            <input
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              value={maxTokens}
              onChange={(e) => {
                const v = e.target.value.replace(/\D/g, "");
                setMaxTokens(v ? parseInt(v) : 0);
              }}
              placeholder="8192"
              className="w-32 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
            />
            <span className="text-xs text-gray-400 dark:text-gray-500">
              tokens（模块内容较长时建议适当调大，如 16384 或 32768）
            </span>
          </div>
        </label>
      </section>

      <section className="mb-6 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
        <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">向量模型配置</h2>
        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
          用于长期记忆等向量化任务。API Key 和 Base URL 留空时自动复用上方大模型的对应值（同一服务商下常见）。
        </p>

        <label className="mt-3 block text-xs font-medium text-gray-600 dark:text-gray-300">
          模型名称
          <input
            type="text"
            value={embeddingModel}
            onChange={(e) => setEmbeddingModel(e.target.value)}
            placeholder="如 doubao-embedding、text-embedding-3-small、BAAI/bge-m3"
            className="mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
          />
        </label>

        <label className="mt-3 block text-xs font-medium text-gray-600 dark:text-gray-300">
          API Key
          <span className="ml-1 font-normal text-gray-400 dark:text-gray-500">（选填，留空复用大模型 Key）</span>
          <div className="relative mt-1">
            <input
              type={showEmbeddingKey ? "text" : "password"}
              value={embeddingApiKey}
              onChange={(e) => setEmbeddingApiKey(e.target.value)}
              placeholder="sk-..."
              className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 pr-9 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
            />
            <button
              type="button"
              onClick={() => setShowEmbeddingKey((v) => !v)}
              className="absolute inset-y-0 right-0 flex items-center px-2 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
              aria-label={showEmbeddingKey ? "隐藏" : "显示"}
            >
              {showEmbeddingKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </label>

        <label className="mt-3 block text-xs font-medium text-gray-600 dark:text-gray-300">
          Base URL
          <span className="ml-1 font-normal text-gray-400 dark:text-gray-500">（选填，留空复用大模型 Base URL）</span>
          <input
            type="text"
            value={embeddingBaseUrl}
            onChange={(e) => setEmbeddingBaseUrl(e.target.value)}
            placeholder="https://ark.cn-beijing.volces.com/api/v3"
            className="mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
          />
        </label>
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
