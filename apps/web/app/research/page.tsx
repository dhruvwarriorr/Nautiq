import ResearchExplorer from "../components/ResearchExplorer";
import { session } from "../../lib/product-server";
import type { ResearchFilter } from "../../lib/product";
import { PageHead } from "../components/ui/Bits";
export const metadata = { title: "Float observations · Nautiq" };
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
    <main>
      <PageHead
        icon="float"
        back={{ href: "/behind-the-data", label: "Behind the data" }}
        title="Float observations"
        lede="Real temperature and salinity readings from Argo floats, by depth, at the positions where they were taken."
      />
      <ResearchExplorer initial={initial} session={await session()} />
    </main>
  );
}
