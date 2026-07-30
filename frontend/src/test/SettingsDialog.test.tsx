import { describe, it, expect, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SettingsDialog } from "../components/SettingsDialog";
import { addApiBaseHistory, DEFAULT_API_BASE } from "../api/client";

beforeEach(() => {
  localStorage.clear();
});

describe("SettingsDialog", () => {
  it("uses the default backend address as placeholder and example", () => {
    const { container } = render(<SettingsDialog onClose={() => {}} />);
    expect(screen.getByPlaceholderText(DEFAULT_API_BASE)).toBeInTheDocument();
    expect(container.textContent).toContain(DEFAULT_API_BASE);
  });

  it("lists saved addresses in the dropdown and deletes an entry", async () => {
    addApiBaseHistory("http://keep.example/api");
    addApiBaseHistory("http://delete.example/api");

    render(<SettingsDialog onClose={() => {}} />);

    fireEvent.click(screen.getByTitle("选择环境"));
    expect(await screen.findByText("http://delete.example/api")).toBeInTheDocument();
    expect(screen.getByText("http://keep.example/api")).toBeInTheDocument();

    fireEvent.click(screen.getAllByTitle("删除")[0]);
    await waitFor(() =>
      expect(screen.queryByText("http://delete.example/api")).not.toBeInTheDocument(),
    );
    expect(screen.getByText("http://keep.example/api")).toBeInTheDocument();
  });
});
