"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";
import Icon, { NautiqMark, type IconName } from "./ui/Icon";

const primary: [string, string, IconName][] = [
  ["/ask", "Ask", "hailer"],
  ["/locations", "Conditions", "buoy"],
  ["/map", "Map", "chart"],
  ["/trips", "Trips", "voyage"],
  ["/advisories", "Warnings", "pennant"],
];
export const behind: { title: string; links: [string, string, string, IconName][] }[] = [
  {
    title: "Understand",
    links: [
      ["/start", "Two-minute guide", "What the signals mean", "compass"],
      ["/methodology", "How it works", "From raw data to an answer", "sounding"],
      ["/data-sources", "Data sources", "Who provides what, and the terms", "outbound"],
      ["/status", "System status", "Is every feed running right now?", "clock"],
    ],
  },
  {
    title: "Explore the evidence",
    links: [
      ["/research", "Float observations", "Temperature and salinity by depth", "float"],
      ["/events", "Regional events", "Unusual patches found in past data", "ripple"],
      ["/anomalies", "Unusual floats", "Profiles that stand out", "pin"],
      ["/fields", "Forecast layers", "The raw forecast grids", "layers"],
      ["/models", "Models", "What was tested and what is used", "logbook"],
      ["/climatology", "Historical normal", "The seasonal baseline", "waves"],
    ],
  },
];
const behindPaths = behind.flatMap((g) => g.links.map((l) => l[0])).concat([
  "/behind-the-data", "/insights", "/uncertainty", "/data", "/models/monitoring", "/profiles", "/calculations", "/training-snapshots", "/compare", "/regions", "/query",
]);

export default function ProductNav() {
  const path = usePathname() ?? "/";
  const here = (href: string) => path === href || path.startsWith(href + "/");
  const behindActive = behindPaths.some(here);
  const panels = useRef<HTMLDetailsElement[]>([]);
  useEffect(() => {
    panels.current.forEach((d) => d && (d.open = false));
  }, [path]);
  const panel = (
    <div className="nav-panel">
      <div className="nav-panel-intro">
        <Icon name="sounding" size={26} />
        <p>
          <strong>Behind the data</strong>
          The sources, models and raw evidence behind every answer, for when you want to dig.
        </p>
      </div>
      {behind.flatMap((g) =>
        g.links.map(([href, title, line, icon]) => (
          <Link key={href} href={href} aria-current={here(href) ? "page" : undefined}>
            <Icon name={icon} size={20} />
            <b>{title}</b>
            <span>{line}</span>
          </Link>
        )),
      )}
      <Link href="/behind-the-data">
        <Icon name="arrow" size={20} />
        <b>Everything behind the data</b>
        <span>All technical pages in one place</span>
      </Link>
    </div>
  );
  return (
    <>
      <header className="site-nav" data-home={path === "/"}>
        <div className="site-nav-inner">
          <Link className="brand" href="/" aria-label="Nautiq home">
            <NautiqMark size={30} />
            Nautiq
          </Link>
          <nav aria-label="Main">
            <ul className="nav-links">
              {primary.map(([href, label, icon]) => (
                <li key={href}>
                  <Link href={href} aria-current={here(href) ? "page" : undefined}>
                    <Icon name={icon} size={19} />
                    {label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
          <div className="nav-end">
            <details className="nav-more" data-active={behindActive} ref={(el) => { if (el) panels.current[0] = el; }}>
              <summary>
                <Icon name="sounding" size={19} />
                Behind the data
                <Icon name="down" size={16} />
              </summary>
              {panel}
            </details>
            <Link className="workspace-button" href="/app" aria-current={here("/app") ? "page" : undefined} aria-label="My workspace">
              <Icon name="logbook" size={19} />
              <span>My workspace</span>
            </Link>
            <details className="nav-toggle" ref={(el) => { if (el) panels.current[1] = el; }}>
              <summary aria-label="Behind the data menu">
                <Icon name="menu" size={22} />
              </summary>
              {panel}
            </details>
          </div>
        </div>
      </header>
      <nav className="tabbar" aria-label="Main (mobile)">
        {primary.map(([href, label, icon]) => (
          <Link key={href} href={href} aria-current={here(href) ? "page" : undefined}>
            <Icon name={icon} size={22} />
            {label}
          </Link>
        ))}
      </nav>
    </>
  );
}
