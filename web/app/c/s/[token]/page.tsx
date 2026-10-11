import { Suspense } from "react";

import { ComingSoon } from "@/components/coming-soon";

// The coach's view of one session, opened from /c/s/<sessions.coach_token>. Task 6.
export default function CoachSessionPage({ params }: PageProps<"/c/s/[token]">) {
  return (
    <main className="flex flex-1 items-center justify-center p-4">
      <Suspense fallback={null}>
        <ComingSoon title="Session review" params={params} />
      </Suspense>
    </main>
  );
}
