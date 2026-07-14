import { Link } from "react-router-dom";
import { BookOpen } from "lucide-react";
import { HealthBanner } from "./HealthBanner";

export function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex h-12 max-w-5xl items-center gap-2 px-4">
          <Link to="/" className="flex items-center gap-2 text-sm font-semibold text-gray-900">
            <BookOpen className="h-4 w-4 text-indigo-600" />
            智学助手
          </Link>
        </div>
      </header>
      <HealthBanner />
      <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
    </div>
  );
}
