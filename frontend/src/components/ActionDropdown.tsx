import { useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";

export interface MenuItem {
  label: string;
  icon?: ReactNode;
  onClick: () => void;
  disabled?: boolean;
}

interface Props {
  label: string;
  icon: ReactNode;
  onAction: () => void;
  menuItems: MenuItem[];
  /** Disables the primary action (e.g. while a request is in flight). */
  busy?: boolean;
  title?: string;
  /** Open the menu upward instead of downward (for buttons near the bottom). */
  dropUp?: boolean;
}

/** A split button: the main area fires `onAction`, the caret opens a small
 *  dropdown of `menuItems`. Closes on outside click or Escape. */
export function ActionDropdown({ label, icon, onAction, menuItems, busy, title, dropUp }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const menuPos = dropUp
    ? "absolute bottom-full right-0 z-20 mb-1"
    : "absolute top-full right-0 z-20 mt-1";

  return (
    <div ref={ref} className="relative inline-flex shadow-sm">
      <button
        type="button"
        onClick={onAction}
        disabled={busy}
        title={title ?? label}
        className="inline-flex items-center gap-1.5 rounded-l-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
      >
        {icon}
        {label}
      </button>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`${label} 选项`}
        className="inline-flex items-center rounded-r-md border-y border-r border-gray-300 bg-white px-1.5 text-gray-500 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700"
      >
        <ChevronDown className="h-4 w-4" />
      </button>
      {open && (
        <div
          role="menu"
          className={`${menuPos} min-w-[10rem] rounded-md border border-gray-200 bg-white py-1 shadow-lg dark:border-gray-700 dark:bg-gray-800`}
        >
          {menuItems.map((item) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              disabled={item.disabled}
              onClick={() => {
                item.onClick();
                setOpen(false);
              }}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm text-gray-700 hover:bg-gray-100 disabled:opacity-50 dark:text-gray-200 dark:hover:bg-gray-700"
            >
              {item.icon}
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}