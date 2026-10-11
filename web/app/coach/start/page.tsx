import Link from 'next/link';
import { WorkspaceForm } from './form';
export const metadata = { title: 'Create your coach workspace | Brodie', robots: { index: false, follow: false }, referrer: 'no-referrer' as const };
export default function StartCoachPage() {
  return <main className="min-h-screen bg-zinc-950 px-6 py-14 text-zinc-100"><div className="mx-auto max-w-lg">
    <Link href="/" className="text-sm text-zinc-400 hover:text-zinc-100">Brodie for coaches</Link>
    <p className="mt-12 text-xs font-medium uppercase tracking-widest text-zinc-500">Your coaching workspace</p>
    <h1 className="mt-3 text-3xl font-semibold tracking-tight">Make your program the plan.</h1>
    <p className="mt-4 leading-relaxed text-zinc-400">Create your private space to upload a PDF, review its training days, and assign a client&apos;s next session.</p>
    <WorkspaceForm />
  </div></main>;
}
