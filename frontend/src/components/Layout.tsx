import { useState } from "react";
import { Link } from "react-router-dom";
import { BookOpen, Settings } from "lucide-react";
import { HealthBanner } from "./HealthBanner";
import { SettingsDialog } from "./SettingsDialog";

export function Layout({ children }: { children: React.ReactNode }) {
  const [showSettings, setShowSettings] = useState(false);

  return (
    <div className="min-h-screen">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex h-12 max-w-5xl items-center gap-2 px-4">
          <Link to="/" className="flex items-center gap-2 text-sm font-semibold text-gray-900">
            <BookOpen className="h-4 w-4 text-indigo-600" />
            智学助手
          </Link>
          <button
            onClick={() => setShowSettings(true)}
            className="ml-auto rounded p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-700"
            title="设置"
          >
            <Settings className="h-4 w-4" />
          </button>
        </div>
      </header>
      <HealthBanner />
      <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
      {showSettings && <SettingsDialog onClose={() => setShowSettings(false)} />}
    </div>
  );
}