import { describe, it, expect, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { SettingsDialog } from "../components/SettingsDialog";
import { setApiBase, DEFAULT_API_BASE, PRESET_ENVS } from "../api/client";

beforeEach(() => {
  localStorage.clear();
});

describe("SettingsDialog", () => {
  it("shows all preset environments", () => {
    render(<SettingsDialog onClose={() => {}} />);
    for (const env of PRESET_ENVS) {
      expect(screen.getByText(env.label)).toBeInTheDocument();
    }
  });

  it("clicking a preset fills the input", () => {
    render(<SettingsDialog onClose={() => {}} />);
    const input = screen.getByPlaceholderText(DEFAULT_API_BASE) as HTMLInputElement;
    fireEvent.click(screen.getByText("本地 (直连)"));
    expect(input.value).toBe("http://localhost:8000/api");
  });

  it("shows the current api base in the input on open", () => {
    setApiBase("http://example.com/api");
    render(<SettingsDialog onClose={() => {}} />);
    const input = screen.getByPlaceholderText(DEFAULT_API_BASE) as HTMLInputElement;
    expect(input.value).toBe("http://example.com/api");
  });
});
