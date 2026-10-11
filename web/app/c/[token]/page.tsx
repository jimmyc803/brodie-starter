import { Suspense } from "react";
import Link from "next/link";

import { ComingSoon } from "@/components/coming-soon";

async function ProgramLink({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <Link className="rounded-full bg-teal-800 px-6 py-3 text-sm font-semibold text-white" href={`/c/${encodeURIComponent(token)}/program`}>Upload & assign a program</Link>;
}

// Coach dashboard, opened from /c/<coaches.dashboard_token>. Task 6.
export default function CoachDashboardPage({ params }: PageProps<"/c/[token]">) {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-6 p-4">
      <Suspense fallback={null}>
        <ComingSoon title="Coach dashboard" params={params} />
        <ProgramLink params={params} />
      </Suspense>
    </main>
  );
}
