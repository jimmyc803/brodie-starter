import { Badge } from "@/components/ui/badge";

export default function Home() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-4 p-6 text-center">
      <Badge variant="secondary">IvyHacks · Beat Muse</Badge>
      <h1 className="text-4xl font-semibold tracking-tight">Brodie for Coaches</h1>
      <p className="max-w-md text-muted-foreground">
        Your coach writes the program. Brodie runs the workout over FaceTime. Your coach sees how it went.
      </p>
    </main>
  );
}
