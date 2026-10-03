"use client";
import { useRouter } from "next/navigation";
import AuthForm from "../components/AuthForm";
export default function SignIn({ next }: { next: string }) {
  const router = useRouter();
  return (
    <AuthForm
      onSuccess={() => {
        router.replace(
          next.startsWith("/app") && !next.startsWith("//") ? next : "/app",
        );
        router.refresh();
      }}
    />
  );
}
