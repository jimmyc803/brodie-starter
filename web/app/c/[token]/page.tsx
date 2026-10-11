import { Suspense } from "react";

import { ComingSoon } from "@/components/coming-soon";

// Coach dashboard, opened from /c/<coaches.dashboard_token>. Task 6.
export default function CoachDashboardPage({ params }: PageProps<"/c/[token]">) {
  return (
    <main className="flex flex-1 items-center justify-center p-4">
      <Suspense fallback={null}>
        <ComingSoon title="Coach dashboard" params={params} />
      </Suspense>
    </main>
  );
}
