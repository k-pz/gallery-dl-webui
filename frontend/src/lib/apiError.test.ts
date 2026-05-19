import { describe, expect, it } from "vitest";
import { extractErrorMessage } from "./apiError";

describe("extractErrorMessage", () => {
  it("prefers the FastAPI-style detail field", () => {
    expect(extractErrorMessage({ detail: "url is required" })).toBe("url is required");
  });

  it("falls back to Error.message when detail is absent", () => {
    expect(extractErrorMessage(new Error("boom"))).toBe("boom");
  });

  it("ignores non-string detail values", () => {
    expect(extractErrorMessage({ detail: { nested: "thing" } })).toBe("request failed");
    expect(extractErrorMessage({ detail: 42 })).toBe("request failed");
  });

  it("returns a generic message for null and undefined", () => {
    expect(extractErrorMessage(null)).toBe("request failed");
    expect(extractErrorMessage(undefined)).toBe("request failed");
  });

  it("returns a generic message for plain objects with no usable fields", () => {
    expect(extractErrorMessage({})).toBe("request failed");
    expect(extractErrorMessage({ message: "ignored" })).toBe("request failed");
  });
});
