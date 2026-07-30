import { describe, it, expect, beforeEach } from "vitest";
import { getApiBase, setApiBase, DEFAULT_API_BASE } from "../api/client";

beforeEach(() => {
  localStorage.clear();
});

describe("api base storage", () => {
  it("defaults to /api", () => {
    expect(DEFAULT_API_BASE).toBe("/api");
    expect(getApiBase()).toBe(DEFAULT_API_BASE);
  });

  it("setApiBase persists the current base", () => {
    setApiBase("http://1.2.3.4:9001/api");
    expect(getApiBase()).toBe("http://1.2.3.4:9001/api");
  });

  it("setApiBase auto-prepends http:// for URLs without protocol", () => {
    setApiBase("localhost:8000/api");
    expect(getApiBase()).toBe("http://localhost:8000/api");
  });

  it("setApiBase preserves relative paths starting with /", () => {
    setApiBase("/api");
    expect(getApiBase()).toBe("/api");
  });

  it("reset (empty) restores the default", () => {
    setApiBase("http://1.2.3.4:9001/api");
    setApiBase("");
    expect(getApiBase()).toBe(DEFAULT_API_BASE);
  });
});
