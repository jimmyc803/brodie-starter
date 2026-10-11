import Link from "next/link";

import { Badge } from "@/components/ui/badge";

export default function Home() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-5 bg-zinc-950 p-6 text-center text-white">
      <Badge variant="secondary">IvyHacks · Beat Muse</Badge>
      <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">Brodie for Coaches</h1>
      <p className="max-w-md text-zinc-400">
        Your coach writes the program. Brodie runs the workout over FaceTime. Your coach sees how it went.
      </p>
      <div className="flex flex-wrap justify-center gap-3 text-sm">
        <Link href="/r/demo" className="rounded-full bg-white px-4 py-2 font-medium text-zinc-950">
          Sample client recap
        </Link>
        <Link href="/c/demo" className="rounded-full border border-zinc-700 px-4 py-2 font-medium">
          Sample coach dashboard
        </Link>
      </div>
    </main>
  );
}
