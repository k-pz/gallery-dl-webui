export const READING_DIRECTION_OPTIONS = [
  { value: "ltr", label: "Left to right" },
  { value: "rtl", label: "Right to left" },
  { value: "vertical", label: "Vertical" },
  { value: "webtoon", label: "Webtoon" },
] as const;

export const READING_DIRECTION_VALUES = READING_DIRECTION_OPTIONS.map((o) => o.value);

export type ReadingDirection = (typeof READING_DIRECTION_OPTIONS)[number]["value"];

export function readingDirectionLabel(value: string | null | undefined): string {
  const found = READING_DIRECTION_OPTIONS.find((o) => o.value === value);
  return found ? found.label : value || "—";
}
