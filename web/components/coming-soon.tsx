import { Surface } from "@/components/ui/apple";

// Placeholder for routes that are not built yet. Shows the token so a link can be checked end to end.
export async function ComingSoon({
  title,
  params,
}: {
  title: string;
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return (
    <Surface className="w-full max-w-md p-6">
      <p className="t-callout font-semibold text-ink-2">Coming soon</p>
      <h1 className="t-title mt-1">{title}</h1>
      <p className="t-callout mt-4 text-ink-2">
        Link token: <code className="break-all">{token}</code>
      </p>
    </Surface>
  );
}
