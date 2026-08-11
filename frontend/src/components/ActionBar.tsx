import { useNavigate } from "react-router-dom";
import { BookmarkPlus, RefreshCw, Settings } from "lucide-react";
import { ActionDropdown, type MenuItem } from "./ActionDropdown";
import { useToast } from "./Toast";

interface Props {
  onRegenerate?: () => void;
  onSaveToIma?: () => void;
  regenerating?: boolean;
  className?: string;
}

/** Shared action bar: 保存到 IMA + 重新生成, each a split button whose caret
 *  opens a dropdown with a 设置 entry. The two buttons open *different*
 *  settings pages -- IMA save config vs. regenerate strategy. Primary actions
 *  fall back to a toast when a page doesn't wire a real handler. */
export function ActionBar({ onRegenerate, onSaveToIma, regenerating, className }: Props) {
  const navigate = useNavigate();
  const { toast } = useToast();

  const imaSettings: MenuItem = {
    label: "设置",
    icon: <Settings className="h-4 w-4" />,
    onClick: () => navigate("/settings/ima"),
  };
  const regenSettings: MenuItem = {
    label: "设置",
    icon: <Settings className="h-4 w-4" />,
    onClick: () => navigate("/settings/regenerate"),
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
      />
    </div>
  );
}