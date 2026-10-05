import { notFound } from "next/navigation";
import { evidence } from "../../../lib/science";
import { session } from "../../../lib/product-server";
import type { ProductPolicy, ResearchFilter } from "../../../lib/product";
import type { TripPolicy } from "../../../lib/trips";
import type { FieldRelease } from "../../../lib/fields";
import PrivateWorkspace from "../../components/PrivateWorkspace";
import OceanMap from "../../map/OceanMap";
import type { MapOverview } from "../../../lib/product";
import { PageHead } from "../../components/ui/Bits";
export const metadata = { title: "My workspace · Nautiq" };
const titles: Record<string, string> = {
  overview: "Your workspace",
  map: "Your map",
  routes: "Saved routes",
  watchlists: "Watched places",
  alerts: "Alerts",
  explorer: "Research",
  reports: "Reports",
  exports: "Downloads",
  settings: "Settings",
};
const ledes: Record<string, string> = {
  overview: "Your private routes, places, alerts and downloads, in one place.",
  routes: "Timed routes you saved, ready to check again.",
  watchlists: "Places you keep an eye on.",
  alerts: "Your own alert limits. They never override an official warning.",
  reports: "Private reports of trips and readings.",
  exports: "Files you asked for. They expire after 72 hours.",
  settings: "Your account and notification choices.",
};
export default async function Page({
  params,
}: {
  params: Promise<{ surface?: string[] }>;
}) {
  const { surface: parts } = await params;
  const surface = parts?.[0] ?? "overview";
  if (
    (parts?.length ?? 0) > 1 ||
    ![
      "overview",
      "map",
      "routes",
      "watchlists",
      "alerts",
      "explorer",
      "reports",
      "exports",
      "settings",
    ].includes(surface)
  )
    notFound();
  const [initial, policy, tripPolicy, fields] = await Promise.all([
    session(),
    evidence<ProductPolicy>("/product-policy"),
    surface === "routes"
      ? evidence<TripPolicy>("/trip-policy")
      : Promise.resolve(null),
    surface === "routes"
      ? evidence<{ items: FieldRelease[] }>("/fields?limit=100")
      : Promise.resolve(null),
  ]);
  const now = new Date();
  const research: ResearchFilter = {
    bbox: [45, 0, 100, 30],
    start: new Date(now.getTime() - 365 * 86400000).toISOString(),
    end: now.toISOString(),
    min_depth_m: 0,
    max_depth_m: 2000,
    variable: "temperature_c",
    source: "argo_gdac",
    qc: "accepted",
    limit: 50,
  };
  const map =
    surface === "map"
      ? await evidence<MapOverview>(
          `/map/overview?start=${encodeURIComponent(research.start)}&end=${encodeURIComponent(research.end)}`,
        )
      : null;
  return (
    <main>
      <PageHead
        icon="logbook"
        title={titles[surface] ?? "Your workspace"}
        lede={ledes[surface] ?? "Your private routes, places, alerts and downloads."}
        compact
      />
      <PrivateWorkspace
        surface={surface}
        initial={initial}
        policy={policy}
        tripPolicy={tripPolicy}
        releases={fields?.items ?? []}
        research={research}
      />
      {surface === "map" ? (
        map ? (
          <div className="workspace-map">
            <OceanMap value={map} />
          </div>
        ) : (
          <p className="notice">The map data is unavailable right now.</p>
        )
      ) : null}
    </main>
  );
}
