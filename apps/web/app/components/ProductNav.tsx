"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const primary: [string, string][] = [
  ["/ask", "Ask"],
  ["/locations", "Conditions"],
  ["/map", "Map"],
  ["/trips", "Plan a trip"],
  ["/research", "Observations"],
];
const groups: { title: string; links: [string, string][] }[] = [
  {
    title: "Learn",
    links: [
      ["/start", "Start here"],
      ["/methodology", "How it works"],
      ["/data-sources", "Data sources and rights"],
      ["/status", "System status"],
    ],
  },
  {
    title: "Evidence",
    links: [
      ["/advisories", "Official warnings"],
      ["/events", "Regional events"],
      ["/anomalies", "Unusual profiles"],
      ["/fields", "Forecast fields"],
      ["/insights", "Insights"],
    ],
  },
  {
    title: "Models and data",
    links: [
      ["/models", "Models"],
      ["/models/monitoring", "Model monitoring"],
      ["/climatology", "Historical normal"],
      ["/uncertainty", "Expected intervals"],
      ["/data", "Datasets and quality"],
    ],
  },
];

export default function ProductNav() {
  const path = usePathname() ?? "/";
  const here = (href: string) =>
    href === "/" ? path === "/" : path === href || path.startsWith(href + "/");
  const moreActive = groups.some((g) => g.links.some(([h]) => here(h)));
  return (
    <header className="product-header">
      <Link className="product-brand" href="/" aria-current={path === "/" ? "page" : undefined}>
        Nautiq
      </Link>
      <nav aria-label="Main navigation">
        {primary.map(([href, label]) => (
          <Link key={href} href={href} aria-current={here(href) ? "page" : undefined}>
            {label}
          </Link>
        ))}
        <details className="nav-more" data-active={moreActive}>
          <summary>More</summary>
          <div className="nav-menu">
            {groups.map((g) => (
              <section key={g.title} aria-label={g.title}>
                <h2>{g.title}</h2>
                <ul>
                  {g.links.map(([href, label]) => (
                    <li key={href}>
                      <Link href={href} aria-current={here(href) ? "page" : undefined}>
                        {label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </details>
      </nav>
      <Link className="workspace-link" href="/app" aria-current={here("/app") ? "page" : undefined}>
        My workspace
      </Link>
    </header>
  );
}
