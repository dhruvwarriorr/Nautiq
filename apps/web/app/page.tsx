import Link from "next/link";
export default function Home() {
  return (
    <main>
      <p className="eyebrow">NAUTIUQ / LOCAL DEVELOPMENT</p>
      <h1>
        Ocean intelligence,
        <br />
        from evidence.
      </h1>
      <p className="intro">
        Explore original Argo temperature and salinity profiles with quality
        flags, depth charts and the exact scientific source files.
      </p>
      <Link className="button" href="/profiles">
        Explore Argo profiles →
      </Link>
      <p className="footnote">
        <Link href="/data">Review source quality and frozen datasets →</Link>
      </p>
    </main>
  );
}
