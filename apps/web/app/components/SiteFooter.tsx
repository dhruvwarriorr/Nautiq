import Link from "next/link";
import { NautiqMark } from "./ui/Icon";

export default function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="site-footer-inner">
        <div>
          <Link className="brand" href="/">
            <NautiqMark size={32} />
            Nautiq
          </Link>
          <p>
            Plain answers about the sea near India&apos;s coast, with the gaps shown honestly. Nautiq never tells you a
            trip is safe. Always check the issuing authority before going to sea.
          </p>
        </div>
        <div>
          <h2>Use</h2>
          <ul>
            <li><Link href="/ask">Ask a question</Link></li>
            <li><Link href="/locations">Conditions by place</Link></li>
            <li><Link href="/map">Ocean map</Link></li>
            <li><Link href="/trips">Plan a trip</Link></li>
          </ul>
        </div>
        <div>
          <h2>Understand</h2>
          <ul>
            <li><Link href="/start">Two-minute guide</Link></li>
            <li><Link href="/methodology">How it works</Link></li>
            <li><Link href="/data-sources">Data sources</Link></li>
            <li><Link href="/status">System status</Link></li>
          </ul>
        </div>
        <div>
          <h2>Behind the data</h2>
          <ul>
            <li><Link href="/research">Float observations</Link></li>
            <li><Link href="/models">Models</Link></li>
            <li><Link href="/events">Regional events</Link></li>
            <li><Link href="/behind-the-data">All technical pages</Link></li>
          </ul>
        </div>
      </div>
      <div className="site-footer-base">
        <p>Nautiq does not track official warnings. Check INCOIS and IMD before you go. Missing data is shown as missing, never filled in.</p>
        <p>Times shown in India Standard Time.</p>
      </div>
    </footer>
  );
}
