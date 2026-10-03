import ResearchExplorer from "../components/ResearchExplorer";
import { session } from "../../lib/product-server";
import type { ResearchFilter } from "../../lib/product";
export default async function Page() {
  const end = new Date();
  const initial: ResearchFilter = {
    bbox: [45, 0, 100, 30],
    start: new Date(end.getTime() - 365 * 86400000).toISOString(),
    end: end.toISOString(),
    min_depth_m: 0,
    max_depth_m: 2000,
    variable: "temperature_c",
    source: "argo_gdac",
    qc: "accepted",
    limit: 50,
  };
  return (
    <main className="explorer">
      <p className="eyebrow">ORIGINAL OBSERVATIONS</p>
      <h1>Research explorer</h1>
      <p className="intro">
        Inspect instrument depth curves, expected state, diagnostic residuals
        and uncertainty with their exact source and calculation references.
      </p>
      <ResearchExplorer initial={initial} session={await session()} />
    </main>
  );
}
