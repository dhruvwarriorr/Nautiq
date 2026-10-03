import { notFound } from "next/navigation";
import { evidence } from "../../../lib/science";
import { session } from "../../../lib/product-server";
import type { ProductPolicy, ResearchFilter } from "../../../lib/product";
import type { TripPolicy } from "../../../lib/trips";
import type { FieldRelease } from "../../../lib/fields";
import PrivateWorkspace from "../../components/PrivateWorkspace";
import SurfaceMap from "../../components/SurfaceMap";
import type { MapOverview } from "../../../lib/product";
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
    <main className="explorer">
      <p className="eyebrow">PRIVATE EVIDENCE WORKSPACE</p>
      <h1>
        {surface === "overview"
          ? "Your Nautiq"
          : surface === "explorer"
            ? "Research explorer"
            : surface[0].toUpperCase() + surface.slice(1)}
      </h1>
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
          <SurfaceMap value={map} />
        ) : (
          <p className="notice">Map evidence is unavailable.</p>
        )
      ) : null}
    </main>
  );
}
