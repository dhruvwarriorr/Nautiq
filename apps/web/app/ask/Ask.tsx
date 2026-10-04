"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { publicQuery, type Place } from "../../lib/product";
import { setStored, useDeviceZone, useStored } from "../../lib/device";
import type { Answer, AnswerResponse, AskPlan, Frame } from "../../lib/ask-types";
import {
  ageText,
  browserZone,
  describeWindow,
  exampleQuestions,
  intentLabels,
  statusLabels,
  topicOptions,
  whenOptions,
  withDates,
  withPlace,
  withWhen,
} from "../../lib/ask.mjs";
import ResearchExplorer from "../components/ResearchExplorer";

const saveKey = "nautiq.lastAnswer.v1";
type Saved = { saved_at: string; plan: AskPlan; answer: Answer };
const monthName = (when: string) =>
  new Date(2000, Number(when.slice(6)) - 1, 1).toLocaleString("en", {
    month: "long",
  });

export function FactList({ answer }: { answer: Answer }) {
  return (
    <ul className="fact-list">
      {answer.facts.map((f, i) => {
        const [icon, word] = statusLabels[f.status] ?? ["", f.status];
        return (
          <li key={i} data-status={f.status}>
            <span className="status-chip" data-status={f.status}>
              <span aria-hidden="true">{icon}</span> {word}
            </span>
            <div>
              <strong>{f.label}</strong>
              <p>{f.value}</p>
              {f.detail ? <small>{f.detail}</small> : null}
              {f.href ? (
                <Link className="fact-link" href={f.href}>
                  See the evidence →
                </Link>
              ) : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export default function Ask({
  places,
  languageModel,
  initialQuestion,
}: {
  places: Place[];
  languageModel: boolean;
  initialQuestion: string;
}) {
  const [text, setText] = useState(initialQuestion);
  const zone = useDeviceZone();
  const [plan, setPlan] = useState<AskPlan | null>(null);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showRows, setShowRows] = useState(false);
  const savedRaw = useStored(saveKey);
  const saved = useMemo<Saved | null>(() => {
    try {
      return savedRaw ? (JSON.parse(savedRaw) as Saved) : null;
    } catch {
      return null;
    }
  }, [savedRaw]);
  const [dates, setDates] = useState({ start: "", end: "" });
  const control = useRef<AbortController | null>(null);
  const sequence = useRef(0);
  const heading = useRef<HTMLHeadingElement | null>(null);
  const auto = useRef(false);

  useEffect(() => {
    if (initialQuestion && !auto.current) {
      auto.current = true;
      void ask(initialQuestion, browserZone());
    }
    return () => control.current?.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function reset() {
    control.current?.abort();
    setPlan(null);
    setAnswer(null);
    setError("");
    setShowRows(false);
  }
  function begin() {
    control.current?.abort();
    const c = new AbortController();
    control.current = c;
    const id = ++sequence.current;
    setBusy(true);
    setError("");
    setShowRows(false);
    return { c, id };
  }
  function remember(p: AskPlan, a: Answer | null) {
    if (!a || a.state === "unavailable" || p.intent === "explain") return;
    const value: Saved = { saved_at: new Date().toISOString(), plan: p, answer: a };
    setStored(saveKey, JSON.stringify(value));
  }
  async function run(frame: Frame, z = zone, parser?: AskPlan["parser"]) {
    const { c, id } = begin();
    try {
      const data = await publicQuery<AnswerResponse>(
        "answer",
        { frame, time_zone: z },
        c.signal,
      );
      if (id !== sequence.current) return;
      const shown = parser ? { ...data.plan, parser } : data.plan;
      setPlan(shown);
      setAnswer(data.answer);
      if (data.answer) remember(shown, data.answer);
      queueMicrotask(() => heading.current?.focus());
    } catch (e) {
      if (id === sequence.current && !c.signal.aborted)
        setError(e instanceof Error ? e.message : "answer_unavailable");
    } finally {
      if (id === sequence.current) setBusy(false);
    }
  }
  async function ask(question: string, z = zone) {
    const { c, id } = begin();
    setPlan(null);
    setAnswer(null);
    try {
      const data = await publicQuery<{ plan: AskPlan }>(
        "query",
        { text: question, time_zone: z },
        c.signal,
      );
      if (id !== sequence.current) return;
      setPlan(data.plan);
      if (data.plan.state === "ready") {
        setBusy(false);
        await run(data.plan.frame, z, data.plan.parser);
      } else {
        setBusy(false);
        queueMicrotask(() => heading.current?.focus());
      }
    } catch (e) {
      if (id === sequence.current && !c.signal.aborted)
        setError(e instanceof Error ? e.message : "query_unavailable");
    } finally {
      if (id === sequence.current) setBusy(false);
    }
  }

  const frame = plan?.frame;
  const known = new Set<string>(whenOptions.map((o: string[]) => o[0]));
  const options: string[][] = [...whenOptions];
  if (frame?.when && !known.has(frame.when) && frame.when.startsWith("month_"))
    options.push([frame.when, `In ${monthName(frame.when)}`]);
  const custom = Boolean(frame && !frame.when && frame.start);
  const needsTime = ["conditions", "warnings", "research", "events", "trip"].includes(
    plan?.intent ?? "",
  );

  return (
    <>
      <form
        className="ask-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) void ask(text.trim());
        }}
      >
        <label htmlFor="question" className="ask-label">
          Your question
        </label>
        <div className="ask-row">
          <textarea
            id="question"
            required
            maxLength={512}
            rows={2}
            value={text}
            placeholder="e.g. How are the waves near Goa tomorrow morning?"
            onChange={(e) => {
              reset();
              setText(e.target.value);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (text.trim()) void ask(text.trim());
              }
            }}
          />
          <button className="ask-submit" disabled={busy || !text.trim()}>
            {busy ? "Working…" : "Ask"}
          </button>
        </div>
        <div className="chips" role="group" aria-label="Example questions">
          {exampleQuestions.map((q: string) => (
            <button
              type="button"
              className="chip"
              key={q}
              onClick={() => {
                setText(q);
                void ask(q);
              }}
            >
              {q}
            </button>
          ))}
        </div>
        <p className="ask-privacy">
          {languageModel
            ? "A language model labels your question’s intent, place and time; Nautiq then rebuilds and validates every query itself. Your question text is sent to that provider and is not saved by Nautiq."
            : "Your question is read by Nautiq’s built-in rules on this server. It is not saved, and no language model is involved."}{" "}
          Times use your device zone ({zone}).
        </p>
      </form>

      <div aria-live="polite" role="status" className="ask-status">
        {busy ? "Finding the evidence…" : ""}
        {error ? `Could not complete: ${error.replaceAll("_", " ")}.` : ""}
      </div>

      {plan && frame ? (
        <section className="understood" aria-label="How Nautiq understood the question">
          <h2 ref={heading} tabIndex={-1}>
            {plan.state === "unsupported"
              ? "I can’t answer that yet"
              : answer
                ? answer.headline
                : "I need a little more"}
          </h2>
          <div className="understood-controls">
            <span className="chip-static">
              {intentLabels[plan.intent] ?? plan.intent}
            </span>
            {plan.intent !== "explain" && plan.intent !== "unsupported" ? (
              <label>
                Place
                <select
                  value={frame.place ?? ""}
                  onChange={(e) =>
                    void run(withPlace(frame, e.target.value))
                  }
                >
                  <option value="">Choose…</option>
                  {places.map((p) => (
                    <option key={p.slug} value={p.slug}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            {needsTime ? (
              <label>
                When
                <select
                  value={custom ? "custom" : (frame.when ?? "now")}
                  onChange={(e) => {
                    if (e.target.value === "custom") {
                      const t = new Date().toISOString().slice(0, 10);
                      setDates({ start: dates.start || t, end: dates.end || t });
                      void run({ ...frame, when: undefined, start: dates.start || t, end: dates.end || t });
                    } else void run(withWhen(frame, e.target.value));
                  }}
                >
                  {options.map((o) => (
                    <option key={o[0]} value={o[0]}>
                      {o[1]}
                    </option>
                  ))}
                  <option value="custom">Specific dates…</option>
                </select>
              </label>
            ) : null}
            {plan.intent === "research" ? (
              <>
                <label>
                  Measure
                  <select
                    value={frame.variable ?? "temperature_c"}
                    onChange={(e) => void run({ ...frame, variable: e.target.value })}
                  >
                    <option value="temperature_c">Temperature</option>
                    <option value="practical_salinity">Salinity</option>
                  </select>
                </label>
                <label className="inline-check">
                  <input
                    type="checkbox"
                    checked={Boolean(frame.unusual)}
                    onChange={(e) => void run({ ...frame, unusual: e.target.checked })}
                  />
                  Unusual only
                </label>
              </>
            ) : null}
            {plan.intent === "explain" ? (
              <label>
                Topic
                <select
                  value={frame.topic ?? ""}
                  onChange={(e) => void run({ ...frame, topic: e.target.value })}
                >
                  <option value="">Choose…</option>
                  {topicOptions.map((o: string[]) => (
                    <option key={o[0]} value={o[0]}>
                      {o[1]}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
          </div>
          {custom ? (
            <form
              className="understood-dates"
              onSubmit={(e) => {
                e.preventDefault();
                void run(withDates(frame, dates.start, dates.end));
              }}
            >
              <label>
                From (UTC date)
                <input type="date" value={dates.start || frame.start?.slice(0, 10) || ""} onChange={(e) => setDates({ ...dates, start: e.target.value })} />
              </label>
              <label>
                Until, not included
                <input type="date" value={dates.end || frame.end?.slice(0, 10) || ""} onChange={(e) => setDates({ ...dates, end: e.target.value })} />
              </label>
              <button>Apply dates</button>
            </form>
          ) : null}
          {plan.window ? (
            <p className="window-line">
              <strong>Time understood:</strong> {describeWindow(plan.window)}
              {plan.window.kind === "past" ? " · in the past" : plan.window.kind === "future" ? " · in the future" : ""}
            </p>
          ) : null}
          <p className="parser-note">
            {plan.parser === "language_model"
              ? "Question labelled by a language model, then rebuilt and validated by Nautiq."
              : plan.parser === "grammar"
                ? "Question matched by Nautiq’s built-in rules."
                : "Adjusted by you; validated by Nautiq."}{" "}
            {plan.explanation}
          </p>
          {plan.clarifications.length ? (
            <ul className="clarifications">
              {plan.clarifications.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}

      {answer && plan ? (
        <section className="answer" aria-label="Answer">
          <FactList answer={answer} />
          {answer.research ? (
            <>
              {showRows ? (
                <ResearchExplorer key={JSON.stringify(answer.research)} initial={answer.research} />
              ) : (
                <button className="button-secondary" onClick={() => setShowRows(true)}>
                  Show the profiles and charts
                </button>
              )}
            </>
          ) : null}
          <div className="answer-links">
            {answer.links.map((l) => (
              <Link
                key={l.href}
                className={answer.state === "handoff" && l.label.startsWith("Open the trip") ? "button" : ""}
                href={l.href}
              >
                {l.label}
              </Link>
            ))}
          </div>
          {answer.cannot_tell_you.length ? (
            <aside className="cannot">
              <h3>What this does not tell you</h3>
              <ul>
                {answer.cannot_tell_you.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </aside>
          ) : null}
          <p className="answer-meta">
            Answer assembled {new Date(answer.as_of).toISOString().replace("T", " ").slice(0, 16)} UTC from retained evidence using
            fixed templates ({answer.version}). No language model wrote it.
          </p>
        </section>
      ) : null}

      {!plan && saved ? (
        <section className="saved-answer" aria-label="Last answer on this device">
          <h2>Last answer on this device</h2>
          <p className="notice">
            Saved copy from {ageText(saved.saved_at)}. It is historical and is never refreshed automatically; ask again for
            current evidence.
          </p>
          <h3>{saved.answer.headline}</h3>
          <FactList answer={saved.answer} />
          <button
            onClick={() => setStored(saveKey, null)}
          >
            Clear saved copy
          </button>
        </section>
      ) : null}
    </>
  );
}
