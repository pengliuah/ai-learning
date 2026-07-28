import { describe, it, expect, beforeEach } from "vitest";
import {
  getApiBase,
  setApiBase,
  getApiBaseHistory,
  addApiBaseHistory,
  removeApiBaseHistory,
  DEFAULT_API_BASE,
} from "../api/client";

beforeEach(() => {
  localStorage.clear();
});

describe("api base storage", () => {
  it("defaults to the configured remote backend", () => {
    expect(DEFAULT_API_BASE).toBe("/api");
    expect(getApiBase()).toBe(DEFAULT_API_BASE);
  });

  it("setApiBase persists the current base and records it in history", () => {
    setApiBase("http://1.2.3.4:9001/api");
    expect(getApiBase()).toBe("http://1.2.3.4:9001/api");
    expect(getApiBaseHistory()).toContain("http://1.2.3.4:9001/api");
  });

  it("keeps history most-recent-first and deduped", () => {
    addApiBaseHistory("http://a/api");
    addApiBaseHistory("http://b/api");
    addApiBaseHistory("http://a/api");
    expect(getApiBaseHistory()).toEqual(["http://a/api", "http://b/api"]);
  });

  it("caps history at 10 entries", () => {
    for (let i = 0; i < 12; i++) addApiBaseHistory(`http://h${i}/api`);
    const h = getApiBaseHistory();
    expect(h.length).toBe(10);
    expect(h[0]).toBe("http://h11/api");
  });

  it("removeApiBaseHistory deletes a specific entry", () => {
    addApiBaseHistory("http://a/api");
    addApiBaseHistory("http://b/api");
    removeApiBaseHistory("http://a/api");
    expect(getApiBaseHistory()).toEqual(["http://b/api"]);
  });

  it("reset (empty) restores the default without adding an empty history entry", () => {
    setApiBase("http://1.2.3.4:9001/api");
    setApiBase("");
    expect(getApiBase()).toBe(DEFAULT_API_BASE);
    expect(getApiBaseHistory()).not.toContain("");
  });
});