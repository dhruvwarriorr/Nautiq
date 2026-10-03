import Link from "next/link";
export default function Home() {
  return (
    <main>
      <p className="eyebrow">NAUTIQ / OCEAN EVIDENCE</p>
      <h1>
        Ocean intelligence,
        <br />
        from evidence.
      </h1>
      <p className="intro">
        Explore original Argo temperature and salinity profiles with quality
        flags, depth charts and the exact scientific source files.
      </p>
      <Link className="button" href="/map">
        Explore the ocean map →
      </Link>
      <p><Link href="/locations">Choose a location</Link> · <Link href="/research">Research observations</Link> · <Link href="/query">Ask about evidence</Link> · <Link href="/app">Open your workspace</Link></p>
      <p className="footnote">
        <Link href="/data">Review source quality and frozen datasets →</Link>
        <br />
        <Link href="/uncertainty">Inspect predictive interval evidence →</Link>
        <br />
        <Link href="/fields">
          Explore surface fields and forecast timelines →
        </Link>
        <br />
        <Link href="/events">
          Inspect regional events and isolated profile evidence →
        </Link>
        <br />
        <Link href="/advisories">
          Inspect official bulletins and feed health →
        </Link>
        <br />
        <Link href="/trips">Inspect timed trip evidence →</Link>
      </p>
    </main>
  );
}
