import SignIn from "./SignIn";
import { PageHead } from "../components/ui/Bits";
export const metadata = { title: "Sign in · Nautiq" };
export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const { next } = await searchParams;
  return (
    <main>
      <PageHead icon="logbook" title={"Your workspace"} lede={"Sign in to save routes, places and alerts. Everything public stays open without an account."} />
      <SignIn next={next ?? "/app"} />
    </main>
  );
}
