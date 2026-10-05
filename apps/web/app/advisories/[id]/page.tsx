import Link from "next/link";
import { evidence } from "../../../lib/science";
import type { Bulletin, AdvisorySource } from "../../../lib/advisories";
import { AdvisoryMap } from "../AdvisoryMap";
import { coords, label, sender, short, when } from "../../../lib/humanize";
import { PageHead, TechDetail, Notice } from "../../components/ui/Bits";
import Icon from "../../components/ui/Icon";
import { Signal } from "../../components/ui/Signal";
export const metadata = { title: "Warning bulletin · Nautiq" };
const currentTime = () => Date.now();
export const dynamic = "force-dynamic";

export default async function Advisory({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const result = await evidence<{ bulletin: Bulletin; sources: AdvisorySource[] }>(`/advisories/${id}`);
  if (!result)
    return (
      <main>
        <PageHead back={{ href: "/advisories", label: "Official warnings" }} title="Bulletin unavailable" lede="This bulletin couldn’t be loaded. That doesn’t mean the warning was cancelled." />
      </main>
    );
  const b = result.bulletin;
  const info = b.message.infos[0];
  const live = b.lifecycle.state === "active" && (!info?.expires || Date.parse(info.expires) > currentTime());
  return (
    <main>
      <PageHead
        back={{ href: "/advisories", label: "Official warnings" }}
        title={info?.event ?? label(b.message.msgType)}
        lede={`${sender(b.message.sender)} · issued ${when(b.message.sent)}`}
      >
        <div className="head-actions">
          <Signal status={live ? "warning" : "unavailable"}>{live ? "In effect" : b.lifecycle.state === "active" ? "Ended" : label(b.lifecycle.state)}</Signal>
          {info?.severity ? <span className="head-tag">{label(info.severity)}</span> : null}
          {info?.urgency ? <span className="head-tag">{label(info.urgency)}</span> : null}
        </div>
      </PageHead>

      <div className="split">
        <article className="bulletin">
          {b.message.infos.map((i, k) => (
            <section key={k} className={k ? "section" : undefined}>
              {i.headline ? <h2 className="bulletin-head">{i.headline}</h2> : null}
              <dl className="timing">
                <div>
                  <dt>Starts</dt>
                  <dd>{when(i.onset ?? i.effective)}</dd>
                </div>
                <div>
                  <dt>Ends</dt>
                  <dd>{i.expires ? when(i.expires) : "No end time given"}</dd>
                </div>
                <div>
                  <dt>Certainty</dt>
                  <dd>{label(i.certainty)}</dd>
                </div>
              </dl>
              {i.description ? <p className="bulletin-text">{i.description}</p> : null}
              {i.instruction ? (
                <Notice tone="warning" title="What the agency advises">
                  <p style={{ whiteSpace: "pre-wrap" }}>{i.instruction}</p>
                </Notice>
              ) : null}
              <h3>Areas named</h3>
              <ul className="area-list">
                {i.areas.map((a, j) => (
                  <li key={j}>
                    <Icon name="pin" size={18} />
                    <span>
                      {a.description || "Unnamed area"}
                      {a.circles.map((c, m) => (
                        <small key={m}>Circle of {c.radius_km} km around {coords(c.center[1], c.center[0])}</small>
                      ))}
                      {!a.polygons.length && !a.circles.length ? <small>Named only; not drawn on the map.</small> : null}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </article>
        <aside className="aside-card">
          <h3>Read the original</h3>
          <p>This is the agency’s own message, shown as received. Nautiq doesn’t rewrite or shorten it.</p>
          <a className="btn" href={b.source_url} target="_blank" rel="noreferrer">
            Agency document <Icon name="outbound" size={16} />
          </a>
          <p style={{ marginTop: 16 }} className="footnote">
            An archived message is never an all-clear for a trip.
          </p>
        </aside>
      </div>

      <AdvisoryMap items={[b]} />

      <TechDetail>
        <dl>
          <dt>Message type</dt>
          <dd>
            {b.message.msgType} · {b.message.status} · {b.message.scope}
          </dd>
          <dt>Identifier</dt>
          <dd className="digest">{b.message.identifier}</dd>
          <dt>Revision</dt>
          <dd className="digest">{b.message.revision_id}</dd>
          <dt>Raw file fingerprint</dt>
          <dd className="digest">{short(b.raw_sha256, 16)}…</dd>
          <dt>First stored in run</dt>
          <dd className="digest">{b.first_run_id}</dd>
          <dt>Revision issues</dt>
          <dd>{b.lifecycle.issues.join(", ") || "None"}</dd>
        </dl>
        {b.message.references.length ? (
          <>
            <h3>Earlier messages it refers to</h3>
            <ul>
              {b.message.references.map((r, i) => (
                <li key={i} className="digest">
                  {r.sender}, {r.identifier}, {when(r.sent)}
                </li>
              ))}
            </ul>
          </>
        ) : null}
        {b.lifecycle.replaced_by.map((r) => (
          <p key={r}>
            <Link href={`/advisories/${r}`}>Replaced or cancelled by a newer message</Link>
          </p>
        ))}
        {b.message.infos.map((i, k) =>
          i.areas.flatMap((a) => a.geocodes).length ? (
            <p key={k} className="footnote">
              Area codes: {i.areas.flatMap((a) => a.geocodes.map((g) => `${g.name} ${g.value}`)).join(", ")} (not mapped to places).
            </p>
          ) : null,
        )}
      </TechDetail>
    </main>
  );
}
