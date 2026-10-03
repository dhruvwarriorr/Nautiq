import Link from "next/link";
import { evidence } from "../../lib/science";
import type { ProductPolicy } from "../../lib/product";
export default async function Page() {
  const policy = await evidence<ProductPolicy>("/product-policy");
  return (
    <main className="explorer">
      <p className="eyebrow">SOURCES / RIGHTS / COVERAGE</p>
      <h1>Know where the data came from.</h1>
      <p className="intro">
        Source completeness, access, redistribution permission and scientific
        suitability are separate questions.
      </p>
      <section>
        <h2>Argo GDAC</h2>
        <p>
          Original temperature and practical salinity profiles retain raw source
          checksums, retrieval time, parameter modes and QC. Published Argo
          terms permit reuse; private exports attach programme credit and DOI
          10.17882/42182.
        </p>
        <a href="https://argo.ucsd.edu/data/acknowledging-argo/">
          Argo acknowledgement and reuse terms
        </a>{" "}
        · <Link href="/data">Retained datasets and source quality</Link>
      </section>
      <section>
        <h2>Surface forecasts and analyses</h2>
        <p>
          Retained NOAA OISST, NOAA GFS wave and weather, and HYCOM ESPC
          products expose source manifests, native grids, forecast cycles and
          coverage. Source cadence and redistribution review remain release
          gates.
        </p>
        <Link href="/fields">Inspect source releases</Link>
      </section>
      <section>
        <h2>Official authorities</h2>
        <p>
          NDMA CAP/RSS transport evidence is retained separately from verified
          marine coverage. INCOIS machine access is unconfigured. Text-only or
          unresolved bulletin areas cannot be plotted as invented polygons.
        </p>
        <Link href="/advisories">
          Inspect bulletin originals and feed health
        </Link>
      </section>
      <h2>Unavailable capabilities</h2>
      {policy ? (
        <>
          <ul>
            {policy.policy.unavailable_layers.map((v) => (
              <li key={v}>{v.replaceAll("_", " ")}</li>
            ))}
          </ul>
          <ul>
            {policy.policy.limitations.map((v) => (
              <li key={v}>{v}</li>
            ))}
          </ul>
        </>
      ) : (
        <p className="notice">Current policy evidence unavailable.</p>
      )}
      <Link href="/status">Platform and capability health</Link>
    </main>
  );
}
