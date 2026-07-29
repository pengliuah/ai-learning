export function ProgressBar({ value, className = "" }: { value: number; className?: string }) {
  const pct = Math.round(value * 100);
  return (
    <div className={`h-1.5 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700 ${className}`}>
      <div
        className="h-full rounded-full bg-indigo-600 dark:bg-indigo-500 transition-all"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}
