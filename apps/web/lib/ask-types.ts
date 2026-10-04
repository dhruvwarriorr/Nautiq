import type { Place, ResearchFilter } from "./product";
export type Frame = {
  intent: string;
  place?: string;
  variable?: string;
  when?: string;
  start?: string;
  end?: string;
  topic?: string;
  unusual?: boolean;
};
export type ResolvedWindow = {
  phrase: string;
  start: string;
  end: string;
  time_zone: string;
  kind: "past" | "current" | "future";
};
export type AskPlan = {
  version: string;
  parser: "grammar" | "language_model" | "validated_frame";
  intent: string;
  state: "ready" | "clarification_required" | "unsupported";
  clarifications: string[];
  frame: Frame;
  window?: ResolvedWindow;
  research?: ResearchFilter;
  place?: Place;
  topic?: string;
  trip?: { latitude: number; longitude: number; departure?: string; place: string };
  explanation: string;
};
export type Fact = {
  label: string;
  value: string;
  detail?: string;
  status: "available" | "stale" | "unknown" | "unavailable" | "warning";
  href?: string;
};
export type Answer = {
  version: string;
  state: "answered" | "partial" | "handoff" | "unavailable";
  headline: string;
  facts: Fact[];
  cannot_tell_you: string[];
  links: { label: string; href: string }[];
  as_of: string;
  research?: ResearchFilter;
};
export type AnswerResponse = { plan: AskPlan; answer: Answer | null };
