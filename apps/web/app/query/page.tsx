import Query from "./Query";
export default function Page() {
  return (
    <main className="explorer">
      <p className="eyebrow">TYPED QUERY PREVIEW</p>
      <h1>Ask about retained evidence</h1>
      <p className="intro">
        A bounded parser proposes an inspectable query. Scientific views execute
        the same typed APIs used by the explorer.
      </p>
      <Query />
    </main>
  );
}
