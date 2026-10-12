import Image from "next/image";
import type { ReactNode } from "react";

// Brodie himself, in three sizes: the round head (logo, recap), the flexing cartoon (empty states, landing),
// and the 3D face clients see on the FaceTime call (rendered from facetime/avatar.py).

export function BrodieHead({ size = 24, className = "" }: { size?: number; className?: string }) {
  return <Image src="/brodie/head.png" alt="" width={size} height={size} className={`shrink-0 rounded-full ${className}`} />;
}

// Brodie's one-line take, signed like a message from him.
export function BrodieSays({ line }: { line: string }) {
  return (
    <section aria-label="Brodie says" className="flex items-start gap-3 rounded-[14px] border border-line bg-surface px-4 py-3.5">
      <BrodieHead size={36} />
      <div className="min-w-0">
        <p className="text-[12.5px] font-medium text-ink-3">Brodie</p>
        <p className="mt-0.5 text-[15px] leading-snug text-ink">{line}</p>
      </div>
    </section>
  );
}

// An empty screen with the flexing cartoon, so "nothing here yet" still feels like a start.
export function BrodieEmpty({ title, children, className = "" }: { title: string; children?: ReactNode; className?: string }) {
  return (
    <div className={`rounded-[14px] border border-dashed border-line-strong p-8 text-center ${className}`}>
      <Image src="/brodie/flex.png" alt="" width={88} height={90} className="mx-auto" />
      <p className="mt-3 font-semibold text-ink">{title}</p>
      {children}
    </div>
  );
}

// The face on the call, in a phone-shaped frame.
export function BrodieCallFace({ className = "" }: { className?: string }) {
  return (
    <div className={`overflow-hidden rounded-[28px] border-[6px] border-ink bg-[#0d1b22] ${className}`}>
      <Image src="/brodie/call-face.png" alt="Brodie on a FaceTime call" width={360} height={360} className="h-auto w-full" priority />
      <div className="flex items-center justify-between px-4 pb-4 pt-1 text-[12px] text-white/70">
        <span>Brodie · FaceTime</span>
        <span className="tabular-nums">Squats · 7 / 10</span>
      </div>
    </div>
  );
}
