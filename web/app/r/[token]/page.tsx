import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { RecapView } from "@/components/recap/recap-view";
import { sessionClips } from "@/lib/session-video";
import { getSessionView } from "@/lib/session-view";

// Client recap, opened from /r/<sessions.share_token>. Private link: never indexed.
export async function generateMetadata({ params }: PageProps<"/r/[token]">): Promise<Metadata> {
  const { token } = await params;
  const view = await getSessionView(token);
  if (!view) notFound();
  const title = `${view.client.name}'s workout recap`;
  const description = [view.day?.title, `Coach ${view.coach.name}`, "Brodie for Coaches"].filter(Boolean).join(" · ");
  const image = `/api/recap-image/${encodeURIComponent(token)}`;
  return {
    title,
    description,
    robots: { index: false, follow: false },
    openGraph: { title, description, images: [image] },
    twitter: { card: "summary_large_image", title, description, images: [image] },
  };
}

export default function RecapPage({ params }: PageProps<"/r/[token]">) {
  return (
    <main className="flex-1 overflow-x-clip bg-canvas text-ink">
      <Suspense fallback={<div className="min-h-dvh" />}>
        <Recap params={params} />
      </Suspense>
    </main>
  );
}

async function Recap({ params }: { params: PageProps<"/r/[token]">["params"] }) {
  const { token } = await params;
  const view = await getSessionView(token);
  if (!view) notFound();
  return <RecapView view={view} clips={await sessionClips(view)} />;
}
