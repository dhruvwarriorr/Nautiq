import Link from "next/link";
export default function ProductNav() {
  return (
    <header className="product-header">
      <Link className="product-brand" href="/">
        Nautiq
      </Link>
      <nav aria-label="Main navigation">
        <Link href="/map">Ocean map</Link>
        <Link href="/locations">Locations</Link>
        <Link href="/research">Research</Link>
        <Link href="/trips">Timed trips</Link>
        <Link href="/app">My workspace</Link>
        <Link href="/methodology">Methods</Link>
      </nav>
    </header>
  );
}
