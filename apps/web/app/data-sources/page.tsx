import Link from "next/link";
import { evidence } from "../../lib/science";
import type { ProductPolicy } from "../../lib/product";
import { label } from "../../lib/humanize";
import { PageHead, TechDetail, Notice } from "../components/ui/Bits";
import Icon, { type IconName } from "../components/ui/Icon";
export const metadata = { title: "Data sources · Nautiq" };
const sources: { name: string; who: string; what: string; icon: IconName; links: [string, string][] }[] = [
  {
    name: "Argo floats",
    who: "International Argo Program",
    what: "Temperature and salinity readings by depth from free-drifting floats. Free to reuse with credit; Nautiq exports include the programme credit and DOI 10.17882/42182.",
    icon: "float",
    links: [["https://argo.ucsd.edu/data/acknowledging-argo/", "Argo reuse terms"], ["/data", "Stored datasets and quality"]],
  },
  {
    name: "Forecasts and sea temperature",
    who: "Copernicus Marine Service and NOAA (GFS)",
    what: "Copernicus Marine global forecasts on a 1/12° grid for waves, surface currents and sea temperature, up to three days ahead; NOAA GFS for wind. Copernicus data is used under its free licence with credit to the E.U. Copernicus Marine Service.",
    icon: "waves",
    links: [["/fields", "Forecast layers"]],
  },
];
export default async function Page() {
  const policy = await evidence<ProductPolicy>("/product-policy");
  return (
    <main>
      <PageHead icon="outbound" title="Data sources" lede="Who provides each piece of data, how complete it is, and the terms for using it." />
      <ul className="rows">
        {sources.map((s) => (
          <li key={s.name} className="row source-row">
            <span className="row-icon"><Icon name={s.icon} size={22} /></span>
            <span>
              <span className="row-title">{s.name}</span>
              <span className="row-sub" style={{ display: "block" }}>{s.who}</span>
              <p className="source-what">{s.what}</p>
              <span className="evidence-links" style={{ margin: "8px 0 0" }}>
                {s.links.map(([href, text]) =>
                  href.startsWith("http") ? (
                    <a key={href} className="text-link" href={href} target="_blank" rel="noreferrer">{text} <Icon name="outbound" size={14} /></a>
                  ) : (
                    <Link key={href} className="text-link" href={href}>{text} <Icon name="arrow" size={14} /></Link>
                  ),
                )}
              </span>
            </span>
          </li>
        ))}
      </ul>
      <section className="section">
        <div className="section-head">
          <h2>Not available yet</h2>
        </div>
        {policy ? (
          <ul className="chips" style={{ listStyle: "none", padding: 0 }}>
            {policy.policy.unavailable_layers.map((v) => (
              <li key={v} className="chip" style={{ cursor: "default" }}>{label(v)}</li>
            ))}
          </ul>
        ) : (
          <Notice tone="caution" title="This list is unavailable right now" />
        )}
      </section>
      {policy ? (
        <TechDetail summary="Account and export limits">
          <ul>
            {policy.policy.limitations.map((v) => (
              <li key={v}>{v}</li>
            ))}
          </ul>
          <Link className="text-link" href="/status">System status <Icon name="arrow" size={14} /></Link>
        </TechDetail>
      ) : null}
    </main>
  );
}
