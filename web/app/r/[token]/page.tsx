import { Suspense } from "react";

import { ComingSoon } from "@/components/coming-soon";

// Client recap, opened from /r/<sessions.client_token>. Task 4.
export default function RecapPage({ params }: PageProps<"/r/[token]">) {
  return (
    <main className="flex flex-1 items-center justify-center p-4">
      <Suspense fallback={null}>
        <ComingSoon title="Your workout recap" params={params} />
      </Suspense>
    </main>
  );
}
