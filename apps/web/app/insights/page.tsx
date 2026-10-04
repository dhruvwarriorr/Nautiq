import { PageHead, DoorLink } from "../components/ui/Bits";
export const metadata = { title: "Insights · Nautiq" };
export default function Page() {
  return (
    <main>
      <PageHead
        icon="ripple"
        back={{ href: "/behind-the-data", label: "Behind the data" }}
        title="Insights"
        lede="How the sea has changed, with the evidence behind each change. An empty list never means nothing is happening."
      />
      <div className="door-list">
        <DoorLink href="/events" icon="ripple" title="Regional events" text="Lasting patches of unusual water found in past data." />
        <DoorLink href="/anomalies" icon="pin" title="Unusual floats" text="Float readings that stand out from the historical normal." />
        <DoorLink href="/research" icon="float" title="Float observations" text="Every reading at its true position, time and depth." />
        <DoorLink href="/methodology" icon="sounding" title="How it works" text="Methods and what still awaits approval." />
      </div>
    </main>
  );
}
