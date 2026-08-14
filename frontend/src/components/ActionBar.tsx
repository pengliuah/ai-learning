import { useNavigate } from "react-router-dom";
import { BookmarkPlus, MoreHorizontal, RefreshCw } from "lucide-react";
import { ActionDropdown, type MenuItem } from "./ActionDropdown";
import { useToast } from "./Toast";

interface Props {
  regenType?: "plan" | "content" | "quiz";
  onRegenerate?: () => void;
  onSaveToIma?: () => void;
  regenerating?: boolean;
  className?: string;
  /** Open caret menus upward (for bars pinned near the page bottom). */
  dropUp?: boolean;
}

/** Shared action bar: 保存到 IMA + 重新生成, each a split button whose caret
 *  opens a dropdown with a 更多 entry. The two buttons open *different*
 *  settings pages -- IMA save config vs. regenerate strategy. Primary actions
 *  fall back to a toast when a page doesn't wire a real handler. */
export function ActionBar({ onRegenerate, onSaveToIma, regenerating, className, regenType = "plan", dropUp }: Props) {
  const navigate = useNavigate();
  const { toast } = useToast();

  const imaSettings: MenuItem = {
    label: "更多",
    icon: <MoreHorizontal className="h-4 w-4" />,
    onClick: () => navigate("/settings/ima"),
  };
  const regenSettings: MenuItem = {
    label: "更多",
    icon: <MoreHorizontal className="h-4 w-4" />,
    onClick: () => navigate("/settings/regenerate", { state: { regenType } }),
  };

  return (
    <div className={`flex items-center gap-2 ${className ?? ""}`}>
      <ActionDropdown
        label="保存到 IMA"
        icon={<BookmarkPlus className="h-4 w-4" />}
        onAction={
          onSaveToIma ?? (() => toast("保存到 IMA 功能开发中，后端支持即将上线"))
        }
        menuItems={[imaSettings]}
        title="保存到 IMA"
        dropUp={dropUp}
      />
      <ActionDropdown
        label="重新生成"
        icon={<RefreshCw className={`h-4 w-4 ${regenerating ? "animate-spin" : ""}`} />}
        onAction={
          onRegenerate ?? (() => toast("重新生成功能开发中"))
        }
        menuItems={[regenSettings]}
        busy={regenerating}
        title="重新生成"
        dropUp={dropUp}
      />
    </div>
  );
}