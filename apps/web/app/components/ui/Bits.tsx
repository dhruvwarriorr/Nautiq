import Link from "next/link";
import Icon, { type IconName } from "./Icon";
import { when as whenText, ago, instant } from "../../../lib/humanize";

/** Sea-blue page band: title, one plain sentence, optional actions. */
export function PageHead({
  title,
  lede,
  icon,
  back,
  children,
  compact,
}: {
  title: React.ReactNode;
  lede?: React.ReactNode;
  icon?: IconName;
  back?: { href: string; label: string };
  children?: React.ReactNode;
  compact?: boolean;
}) {
  return (
    <header className="page-head" data-compact={compact || undefined}>
      <div className="page-head-inner">
        {back ? (
          <Link className="page-back" href={back.href}>
            <Icon name="back" size={18} /> {back.label}
          </Link>
        ) : null}
        <div className="page-head-title">
          {icon ? (
            <span className="page-head-icon">
              <Icon name={icon} size={30} />
            </span>
          ) : null}
          <h1>{title}</h1>
        </div>
        {lede ? <p className="page-lede">{lede}</p> : null}
        {children}
      </div>
    </header>
  );
}

/** A friendly time with the exact instant on hover and for machines. */
export function When({ iso, relative }: { iso: string | null | undefined; relative?: boolean }) {
  const d = instant(iso ?? null);
  if (!d) return <span>an unknown time</span>;
  return (
    <time dateTime={d.toISOString()} title={d.toUTCString()} suppressHydrationWarning>
      {relative ? ago(d) : whenText(d)}
    </time>
  );
}

/** Everything a non-expert does not need, one click away. */
export function TechDetail({
  summary = "Technical detail",
  children,
  open,
}: {
  summary?: string;
  children: React.ReactNode;
  open?: boolean;
}) {
  return (
    <details className="tech" open={open}>
      <summary>
        <Icon name="sounding" size={18} />
        <span>{summary}</span>
        <Icon name="down" size={18} className="icon tech-chevron" />
      </summary>
      <div className="tech-body">{children}</div>
    </details>
  );
}

/** Prominent notice in the signal vocabulary. */
export function Notice({
  tone = "info",
  title,
  children,
}: {
  tone?: "info" | "caution" | "warning";
  title?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <div className="notice-box" data-tone={tone} role={tone === "warning" ? "alert" : undefined}>
      <Icon name={tone === "warning" ? "pennant" : tone === "caution" ? "clock" : "info"} size={20} />
      <div>
        {title ? <p className="notice-title">{title}</p> : null}
        {children}
      </div>
    </div>
  );
}

/** A large navigational row: icon, title, one line, arrow. */
export function DoorLink({
  href,
  icon,
  title,
  text,
}: {
  href: string;
  icon: IconName;
  title: string;
  text: string;
}) {
  return (
    <Link className="door" href={href}>
      <span className="door-icon">
        <Icon name={icon} size={28} />
      </span>
      <span className="door-text">
        <span className="door-title">{title}</span>
        <span className="door-line">{text}</span>
      </span>
      <Icon name="arrow" size={22} className="icon door-arrow" />
    </Link>
  );
}

export function Empty({ icon = "buoy", title, children }: { icon?: IconName; title: string; children?: React.ReactNode }) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Icon name={icon} size={34} />
      </span>
      <p className="empty-title">{title}</p>
      {children ? <div className="empty-body">{children}</div> : null}
    </div>
  );
}
