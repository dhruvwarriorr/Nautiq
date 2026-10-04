import Link from "next/link";
import { evidence } from "../../lib/science";
import type { AdvisorySnapshot, AdvisoryState, Bulletin } from "../../lib/advisories";
import type { ProductPolicy } from "../../lib/product";
import { AdvisoryMap } from "./AdvisoryMap";
import { ago, humanizeText, label, sender, when } from "../../lib/humanize";
import { PageHead, TechDetail, Notice, Empty } from "../components/ui/Bits";
import Icon from "../components/ui/Icon";
import { Signal, SignalShape } from "../components/ui/Signal";
export const dynamic = "force-dynamic";
export const metadata = { title: "Official warnings · Nautiq" };

const currentTime = () => Date.now();
const SEA = /\b(sea|coast|coastal|fisher|fishermen|cyclone|depression|surge|swell|wave|high wind|squall|marine|port|beach)\b/i;
const severityRank: Record<string, number> = { Extreme: 0, Severe: 1, Moderate: 2, Minor: 3 };

function inEffect(b: Bulletin, now: number) {
  const info = b.message.infos[0];
  if (b.lifecycle.state !== "active" || !info) return false;
  return !info.expires || Date.parse(info.expires) > now;
}
function area(b: Bulletin) {
  return b.message.infos[0]?.areas.map((a) => a.description).filter(Boolean).join("; ") ?? "";
}
function isSea(b: Bulletin) {
  const i = b.message.infos[0];
  return Boolean(i && SEA.test(`${i.event} ${i.headline} ${i.description}`));
}

export default async function Advisories({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const one = (k: string) => (typeof params[k] === "string" ? (params[k] as string) : "");
  const [snapshot, policy] = await Promise.all([evidence<AdvisorySnapshot>("/advisories"), evidence<ProductPolicy>("/product-policy")]);
  const places = policy?.policy.locations ?? [];
  const place = places.find((p) => p.slug === one("place"));
  const hours = [6, 12, 24, 48, 96].includes(Number(one("hours"))) ? Number(one("hours")) : 24;
  const now = currentTime();
  let state: AdvisoryState | null = null;
  if (place) {
    const q = new URLSearchParams({
      longitude: String(place.longitude),
      latitude: String(place.latitude),
      start: new Date(now).toISOString(),
      end: new Date(now + hours * 3600000).toISOString(),
    });
    state = await evidence<AdvisoryState>(`/advisories/state?${q}`);
  }
  const show = one("show") === "all" ? "all" : "sea";
  const live = (snapshot?.items ?? []).filter((b) => inEffect(b, now));
  const seaCount = live.filter(isSea).length;
  const list = (show === "sea" ? live.filter(isSea) : live).sort(
    (a, b) =>
      (severityRank[a.message.infos[0]?.severity ?? ""] ?? 9) - (severityRank[b.message.infos[0]?.severity ?? ""] ?? 9) ||
      Date.parse(b.message.sent) - Date.parse(a.message.sent),
  );
  const first = list.slice(0, 10);
  const rest = list.slice(10);
  const row = (b: Bulletin) => {
    const info = b.message.infos[0];
    return (
      <li key={b.message.revision_id}>
        <Link className="row" href={`/advisories/${b.message.revision_id}`} data-tone="warning">
          <span className="row-icon">
            <SignalShape status="warning" size={20} />
          </span>
          <span>
            <span className="row-title">
              {info?.event ?? label(b.message.msgType)}
              {area(b) ? ` · ${area(b)}` : ""}
            </span>
            <span className="row-sub" style={{ display: "block" }}>
              {sender(b.message.sender)} · {label(info?.severity)}
            </span>
          </span>
          <span className="row-meta">{info?.expires ? `Until ${when(info.expires)}` : "No end time given"}</span>
        </Link>
      </li>
    );
  };
  return (
    <main>
      <PageHead
        icon="pennant"
        title="Official warnings"
        lede="Bulletins from Indian agencies, in their own words. A missing warning is never treated as an all-clear."
      />

      <section aria-labelledby="check">
        <div className="section-head">
          <h2 id="check">Check a place</h2>
          <p>See whether a mapped official warning covers it.</p>
        </div>
        <form method="get" className="check-form">
          <label>
            Place
            <select name="place" defaultValue={place?.slug ?? ""} required>
              <option value="" disabled>
                Choose a place…
              </option>
              {places.map((p) => (
                <option key={p.slug} value={p.slug}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Over the next
            <select name="hours" defaultValue={String(hours)}>
              {[6, 12, 24, 48, 96].map((h) => (
                <option key={h} value={h}>
                  {h < 48 ? `${h} hours` : `${h / 24} days`}
                </option>
              ))}
            </select>
          </label>
          <button className="btn">
            <Icon name="spyglass" size={18} /> Check
          </button>
        </form>
        {place ? (
          state ? (
            <div className="verdict" data-status={state.status === "official_warning" ? "warning" : state.status === "known_none_intersecting" ? "available" : "unknown"} style={{ marginTop: 18 }}>
              <span className="verdict-shape">
                <SignalShape status={state.status === "official_warning" ? "warning" : state.status === "known_none_intersecting" ? "available" : "unknown"} size={30} />
              </span>
              <div>
                <p className="verdict-title">
                  {state.status === "official_warning"
                    ? `An official warning covers ${place.name}`
                    : state.status === "known_none_intersecting"
                      ? `No mapped warning covers ${place.name}`
                      : `Unknown for ${place.name}`}
                </p>
                <p className="verdict-text">
                  {state.status === "unknown"
                    ? "We couldn’t confirm the warning picture. That is not an all-clear: check the issuing authority."
                    : state.status === "known_none_intersecting"
                      ? "Only within the areas we could check. Coverage of the sea isn’t verified."
                      : `${state.warnings.length} bulletin${state.warnings.length === 1 ? "" : "s"} apply over the next ${hours} hours.`}
                </p>
                {state.warnings.length ? (
                  <ul>
                    {state.warnings.map((w, i) => (
                      <li key={`${w.revision_id}-${i}`}>
                        <Link href={`/advisories/${w.revision_id}`}>
                          {w.event} · {label(w.severity)} · until {w.expires ? when(w.expires) : "no end time given"}
                        </Link>
                      </li>
                    ))}
                  </ul>
                ) : null}
                {state.unknown_reasons.length ? (
                  <details>
                    <summary>Why it’s unknown</summary>
                    <ul>
                      {state.unknown_reasons.slice(0, 8).map((r) => (
                        <li key={r}>{humanizeText(r.replaceAll("_", " "))}</li>
                      ))}
                    </ul>
                  </details>
                ) : null}
              </div>
            </div>
          ) : (
            <Notice tone="caution" title="That check didn’t work">
              <p>The warning service didn’t answer. Treat the state as unknown, not clear.</p>
            </Notice>
          )
        ) : null}
      </section>

      <section className="section" aria-labelledby="feeds">
        <div className="section-head">
          <h2 id="feeds">Where the bulletins come from</h2>
        </div>
        {snapshot?.sources.length ? (
          <ul className="rows">
            {snapshot.sources.map((s) => (
              <li key={s.source_id} className="row">
                <span className="row-icon">
                  <Icon name="bell" size={22} />
                </span>
                <span>
                  <span className="row-title">{s.source_id === "ndma_cap_rss" ? "NDMA national alerts (Sachet)" : s.policy.authority === "INCOIS" ? "INCOIS ocean advisories" : s.policy.authority}</span>
                  <span className="row-sub" style={{ display: "block" }}>
                    {s.transport === "unconfigured"
                      ? "Not connected yet"
                      : s.checked_at
                        ? `Last checked ${ago(s.checked_at)}`
                        : "Never checked"}
                    {s.policy.url ? (
                      <>
                        {" · "}
                        <a href={s.policy.url} target="_blank" rel="noreferrer">
                          Official source
                        </a>
                      </>
                    ) : null}
                  </span>
                </span>
                <Signal status={s.transport === "healthy" ? "available" : s.transport === "stale" ? "stale" : "unavailable"}>
                  {s.transport === "healthy" ? "Up to date" : s.transport === "stale" ? "Not recent" : "Not connected"}
                </Signal>
              </li>
            ))}
          </ul>
        ) : (
          <Notice tone="caution" title="Feed status unavailable">
            <p>Treat every warning state as unknown until this returns.</p>
          </Notice>
        )}
        <Notice tone="caution" title="Coverage of the sea isn’t verified">
          <p>A healthy feed or an empty list doesn’t prove there is no relevant warning. Always check the issuing authority.</p>
        </Notice>
      </section>

      <section className="section" aria-labelledby="now">
        <div className="section-head">
          <h2 id="now">In effect now</h2>
          <nav className="seg" aria-label="Filter bulletins">
            <Link href="/advisories" aria-current={show === "sea" ? "page" : undefined}>
              Sea &amp; coast <span>{seaCount}</span>
            </Link>
            <Link href="/advisories?show=all" aria-current={show === "all" ? "page" : undefined}>
              All <span>{live.length}</span>
            </Link>
          </nav>
        </div>
        {first.length ? (
          <>
            <ul className="rows">{first.map(row)}</ul>
            {rest.length ? (
              <details className="tech">
                <summary>
                  <Icon name="pennant" size={18} />
                  <span>Show {rest.length} more</span>
                  <Icon name="down" size={18} className="icon tech-chevron" />
                </summary>
                <div className="tech-body">
                  <ul className="rows">{rest.map(row)}</ul>
                </div>
              </details>
            ) : null}
          </>
        ) : (
          <>
            <Empty icon="pennant" title={show === "sea" ? "No sea or coast bulletins in effect" : "No bulletins in effect"}>
              <p>That doesn’t mean there is no warning: coverage of the sea isn’t verified. Check IMD and INCOIS before you go.</p>
            </Empty>
            {show === "sea" && live.length ? (
              <details className="tech">
                <summary>
                  <Icon name="pennant" size={18} />
                  <span>{live.length} inland bulletins in effect (floods, storms on land)</span>
                  <Icon name="down" size={18} className="icon tech-chevron" />
                </summary>
                <div className="tech-body">
                  <ul className="rows">{live.slice(0, 30).map(row)}</ul>
                  {live.length > 30 ? (
                    <p className="more-row">
                      <Link className="text-link" href="/advisories?show=all">See all {live.length}</Link>
                    </p>
                  ) : null}
                </div>
              </details>
            ) : null}
          </>
        )}
      </section>

      <TechDetail summary="Bulletin archive and mapped areas">
        {snapshot ? <AdvisoryMap items={snapshot.items} /> : null}
        <p>Expired, test, cancelled and replaced messages stay in the archive. A bulletin with no mapped area can still be relevant.</p>
        {snapshot?.items.length ? (
          <div className="table-scroll" tabIndex={0} role="region" aria-label="Bulletin archive">
            <table>
              <thead>
                <tr>
                  <th>From</th>
                  <th>Issued</th>
                  <th>Type</th>
                  <th>Area</th>
                </tr>
              </thead>
              <tbody>
                {[...snapshot.items].reverse().map((b) => (
                  <tr key={b.message.revision_id}>
                    <td>
                      <Link href={`/advisories/${b.message.revision_id}`}>
                        {sender(b.message.sender)} · {b.message.infos[0]?.event ?? b.message.msgType}
                      </Link>
                    </td>
                    <td>{when(b.message.sent)}</td>
                    <td>
                      {label(b.message.msgType)} · {label(b.lifecycle.state)}
                    </td>
                    <td>
                      {b.message.infos.some((i) => i.areas.some((a) => a.polygons.length || a.circles.length)) ? "Mapped" : "Place names only"}
                      {b.lifecycle.issues.length ? " · revision unclear" : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </TechDetail>
    </main>
  );
}
