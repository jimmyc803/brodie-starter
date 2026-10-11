'use client';
import { useState } from 'react';

export function ExerciseSupport({ brief, bookingUrl }: { brief: string; bookingUrl: string | null }) {
  const [message, setMessage] = useState('');
  async function copy() {
    try { await navigator.clipboard.writeText(brief); setMessage('Exercise brief copied. Share it with the Brodie team when discussing support.'); }
    catch { setMessage('Clipboard unavailable. Download the exercise brief or select the text below to copy it.'); }
  }
  function download() {
    const url = URL.createObjectURL(new Blob([brief], { type: 'text/plain;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url; link.download = 'brodie-exercise-review.txt'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setMessage('Exercise brief downloaded. It has not been sent to the Brodie team.');
  }
  const button = 'rounded-full border border-zinc-700 px-4 py-2 text-sm text-zinc-100 hover:bg-zinc-800';
  return <section aria-labelledby="exercise-support-title" className="mt-8 rounded-2xl border border-zinc-800 bg-zinc-900 p-6">
    <h2 id="exercise-support-title" className="text-lg font-semibold">Exercise support review</h2>
    <p className="mt-2 max-w-3xl text-sm leading-relaxed text-zinc-400">Your unsupported exercises are preserved. They have no video tracking or automatic rep counting yet. Discuss these movements with the Brodie team so we can review what is needed to support them properly.</p>
    <div className="mt-4 flex flex-wrap gap-3"><button type="button" className={button} onClick={copy}>Copy exercise brief</button><button type="button" className={button} onClick={download}>Download exercise brief</button>{bookingUrl && <a className={button} href={bookingUrl} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">Book an exercise review</a>}</div>
    <p className="mt-3 text-xs text-zinc-500">{bookingUrl ? 'The booking link opens the team’s scheduling page. Choose and confirm a time there.' : 'Online booking is not configured. Share this brief with your Brodie contact to arrange a discussion.'} Copying or downloading does not send a request or book a call.</p>
    {message && <p role="status" className="mt-3 text-sm text-zinc-300">{message}</p>}
    <details className="mt-4 text-sm text-zinc-400"><summary className="cursor-pointer">Preview exercise brief</summary><pre className="mt-3 whitespace-pre-wrap break-words font-sans text-xs leading-relaxed">{brief}</pre></details>
  </section>;
}
