import Link from "next/link";
export default function SiteFooter() {
  return (
    <footer className="site-footer">
      <p>
        <strong>Nautiq is a private diagnostic product.</strong> It shows
        retained ocean evidence with its limits. It does not tell you a trip is
        safe, and an unknown official-warning state is never an all-clear.
        Always check the issuing authority before going to sea.
      </p>
      <nav aria-label="Footer">
        <Link href="/start">Start here</Link>
        <Link href="/methodology">Methods</Link>
        <Link href="/data-sources">Data sources</Link>
        <Link href="/status">Status</Link>
        <Link href="/advisories">Official warnings</Link>
      </nav>
    </footer>
  );
}
