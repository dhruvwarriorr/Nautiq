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
  topicOptions,
  whenOptions,
  withDates,
  withPlace,
  withWhen,
} from "../../lib/ask.mjs";
import ResearchExplorer from "../components/ResearchExplorer";
import { toReading, headline, when as whenText, humanizeText } from "../../lib/humanize";
import Icon from "../components/ui/Icon";
import { Signal } from "../components/ui/Signal";
import { measureIcon } from "../components/readingIcons";

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
        const r = toReading(f);
        return (
          <li key={i} data-status={f.status}>
            <span className="fact-icon">
              <Icon name={measureIcon[r.measure]} size={22} />
            </span>
            <span className="fact-name">{r.title}</span>
            <div className="fact-main">
              {r.value ? (
                <p className="fact-big" style={{ margin: 0 }}>
                  {r.value}
                  {r.descriptor ? <small>{r.descriptor}</small> : null}
                </p>
              ) : r.descriptor ? (
                <p className="fact-plain">{r.descriptor}</p>
              ) : null}
              {r.value && (r.time || r.outlook) ? <span className="fact-sub">{[r.time, r.outlook].filter(Boolean).join(" · ")}</span> : null}
              {r.note ? (
                <span className="fact-sub">{r.note}</span>
              ) : null}
            </div>
            <div style={{ display: "grid", gap: 6, justifyItems: "end" }}>
              <Signal status={f.status} size={14} />
              {f.href ? (
                <Link className="fact-link" href={f.href}>
                  Evidence <Icon name="arrow" size={14} />
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
    // Safe under StrictMode's mount–unmount–mount: the aborted first run is simply replaced.
    if (initialQuestion && !auto.current) {
      auto.current = true;
      void ask(initialQuestion, browserZone());
    }
    return () => {
      control.current?.abort();
      auto.current = false;
    };
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
  const needsTime = ["conditions", "research", "events", "trip"].includes(
    plan?.intent ?? "",
  );

  return (
    <>
      <form
        className="ask-form"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) void ask(text.trim());
        }}
      >
        <label htmlFor="question" className="visually-hidden">
          Your question
        </label>
        <div className="ask-field">
          <span className="ask-icon">
            <Icon name="hailer" size={24} />
          </span>
          <textarea
            id="question"
            required
            maxLength={512}
            rows={1}
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
          <button className="ask-go" disabled={busy || !text.trim()}>
            {busy ? "Working…" : "Ask"} <Icon name="arrow" size={18} />
          </button>
        </div>
        <ul className="suggestions" aria-label="Example questions">
          {exampleQuestions.map((q: string) => (
            <li key={q}>
              <button
                type="button"
                className="suggestion"
                onClick={() => {
                  setText(q);
                  void ask(q);
                }}
              >
                {q}
              </button>
            </li>
          ))}
        </ul>
      </form>

      <div className="wrap-ask">
        <div aria-live="polite" role="status" className="ask-status" data-busy={busy}>
          {busy ? "Finding the evidence…" : ""}
          {error ? `That didn’t work: ${error.replaceAll("_", " ")}. Try rephrasing, or pick a place below.` : ""}
        </div>

        {plan && frame ? (
          <section className="answer-card" aria-label="Answer">
            <div className="answer-head">
              <h2 ref={heading} tabIndex={-1}>
                {plan.state === "unsupported"
                  ? "I can’t answer that yet"
                  : answer
                    ? headline(answer.headline)
                    : "I need a little more"}
              </h2>
              <div className="understood-bar" aria-label="How Nautiq understood your question">
                <span className="intent-tag">
                  <Icon name="hailer" size={16} />
                  {intentLabels[plan.intent] ?? plan.intent}
                </span>
                {plan.intent !== "explain" && plan.intent !== "unsupported" ? (
                  <label>
                    Place
                    <select value={frame.place ?? ""} onChange={(e) => void run(withPlace(frame, e.target.value))}>
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
                      <select value={frame.variable ?? "temperature_c"} onChange={(e) => void run({ ...frame, variable: e.target.value })}>
                        <option value="temperature_c">Temperature</option>
                        <option value="practical_salinity">Salinity</option>
                      </select>
                    </label>
                    <label className="inline-check">
                      <input type="checkbox" checked={Boolean(frame.unusual)} onChange={(e) => void run({ ...frame, unusual: e.target.checked })} />
                      Unusual only
                    </label>
                  </>
                ) : null}
                {plan.intent === "explain" ? (
                  <label>
                    Topic
                    <select value={frame.topic ?? ""} onChange={(e) => void run({ ...frame, topic: e.target.value })}>
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
                  className="form-grid"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void run(withDates(frame, dates.start, dates.end));
                  }}
                >
                  <label>
                    From
                    <input type="date" value={dates.start || frame.start?.slice(0, 10) || ""} onChange={(e) => setDates({ ...dates, start: e.target.value })} />
                  </label>
                  <label>
                    Until (not included)
                    <input type="date" value={dates.end || frame.end?.slice(0, 10) || ""} onChange={(e) => setDates({ ...dates, end: e.target.value })} />
                  </label>
                  <button className="btn">Apply dates</button>
                </form>
              ) : null}
              {plan.clarifications.length ? (
                <ul className="clarifications">
                  {plan.clarifications.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              ) : null}
            </div>

            {answer ? (
              <>
                <FactList answer={answer} />
                {answer.research ? (
                  showRows ? (
                    <ResearchExplorer key={JSON.stringify(answer.research)} initial={answer.research} />
                  ) : (
                    <button className="btn-ghost" style={{ marginTop: 18 }} onClick={() => setShowRows(true)}>
                      <Icon name="float" size={18} /> Show the float readings and charts
                    </button>
                  )
                ) : null}
                <div className="answer-links">
                  {answer.links.map((l) => (
                    <Link key={l.href} className={answer.state === "handoff" && l.label.startsWith("Open the trip") ? "btn" : "btn-ghost"} href={l.href}>
                      {l.label} <Icon name="arrow" size={16} />
                    </Link>
                  ))}
                </div>
                {answer.cannot_tell_you.length ? (
                  <aside className="limits">
                    <h3>What this can’t tell you</h3>
                    <ul>
                      {answer.cannot_tell_you.map((c) => (
                        <li key={c}>{c}</li>
                      ))}
                    </ul>
                  </aside>
                ) : null}
              </>
            ) : null}
            <details className="tech">
              <summary>
                <Icon name="sounding" size={18} />
                <span>How Nautiq read your question</span>
                <Icon name="down" size={18} className="icon tech-chevron" />
              </summary>
              <div className="tech-body">
                {plan.window ? (
                  <p>
                    <strong>Time understood:</strong> {describeWindow(plan.window)}
                    {plan.window.kind === "past" ? " · in the past" : plan.window.kind === "future" ? " · in the future" : ""}
                  </p>
                ) : null}
                <p>
                  {plan.parser === "language_model"
                    ? "Labelled by a language model, then rebuilt and checked by Nautiq."
                    : plan.parser === "grammar"
                      ? "Matched by Nautiq’s built-in rules."
                      : "Adjusted by you; checked by Nautiq."}{" "}
                  {humanizeText(plan.explanation)}
                </p>
                <p>
                  {languageModel
                    ? "Your question text goes to a language-model provider to label it; Nautiq doesn’t save it."
                    : "Your question is read by rules on Nautiq’s server. It isn’t saved and no language model is involved."}{" "}
                  Times use your device zone ({zone}).
                </p>
                {answer ? (
                  <p className="footnote">
                    Answer put together {whenText(answer.as_of)} from stored evidence using fixed templates ({answer.version}). No language model wrote it.
                  </p>
                ) : null}
              </div>
            </details>
          </section>
        ) : null}

        {!plan && saved ? (
          <section className="saved-answer" aria-label="Last answer on this device">
            <div className="section-head">
              <h2>Your last answer</h2>
              <button onClick={() => setStored(saveKey, null)}>Forget it</button>
            </div>
            <p className="muted">
              Saved {ageText(saved.saved_at)} on this device. It won’t update by itself; ask again for the latest.
            </p>
            <h3>{headline(saved.answer.headline)}</h3>
            <FactList answer={saved.answer} />
          </section>
        ) : null}
      </div>
    </>
  );
}
