import SignIn from "./SignIn";
export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const { next } = await searchParams;
  return (
    <main>
      <p className="eyebrow">PRIVATE WORKSPACE / ACCOUNT ACCESS</p>
      <h1>Your saved ocean evidence.</h1>
      <p className="intro">
        Use an account for saved routes, watchlists, alert rules and private
        reports. Public maps and measured profiles remain open.
      </p>
      <SignIn next={next ?? "/app"} />
    </main>
  );
}
