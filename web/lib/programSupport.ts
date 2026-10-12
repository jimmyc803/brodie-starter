import type { ProgramDay } from './parseProgram';

/** A local discussion document, not a support ticket or a promise of tracking. */
export function exerciseReviewBrief(programs: { title: string; days: ProgramDay[] }[]): string {
  const sections = programs.flatMap(program => program.days.flatMap(day => {
    const exercises = day.exercises.filter(exercise => !exercise.supported);
    if (!exercises.length) return [];
    return [`${program.title} — Day ${day.day_number}: ${day.title}\n${exercises.map(exercise =>
      `- ${exercise.name}: ${exercise.sets} sets × ${exercise.reps === 0 ? 'timed / see notes' : `${exercise.reps} reps`}${exercise.notes ? `; ${exercise.notes}` : ''}`
    ).join('\n')}`];
  }));
  return sections.length ? ['Brodie exercise support review', 'These exercises remain in the program but have no video tracking. Discuss the intended movement, camera setup and coaching requirements with the Brodie team before tracking can be added.', ...sections, 'Prepared locally. This brief has not been sent and no appointment has been booked.'].join('\n\n') : '';
}

export function supportBookingUrl(value: string | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}

export function parserFailureMessage(code: string): string {
  switch (code) {
    case 'INVALID_PDF': return 'This file could not be read as a PDF. Export a new PDF from the original program and upload it again.';
    case 'MISSING_KEY': return 'PDF reading is not configured for this workspace yet. Ask the Brodie team to enable the program parser, then retry. No program was saved.';
    case 'PROVIDER_AUTH': return 'The PDF service rejected parser access. The Brodie team needs to check the parser API key and its permissions. No program was saved.';
    case 'PROVIDER_QUOTA': return 'The PDF service has reached its request or quota limit. Retry later; if this continues, the Brodie team needs to check parser quota and billing. No program was saved.';
    case 'PROVIDER_MODEL': return 'The configured PDF parser model is unavailable. The Brodie team needs to update the parser model configuration. No program was saved.';
    case 'PROVIDER_REQUEST': return 'The PDF service rejected this request. Try exporting a new PDF; if it still fails, the Brodie team needs to check the parser request configuration. No program was saved.';
    case 'PROVIDER_TIMEOUT': return 'PDF reading timed out. Retry with a shorter PDF or try again in a moment. No program was saved.';
    case 'PROVIDER_NETWORK': return 'Brodie could not connect to the PDF service. Retry in a moment. No program was saved.';
    case 'INVALID_OUTPUT': return 'We could not read a complete training plan from this PDF. Check that days, exercise names, sets and reps are legible, or export a clearer PDF and retry. No program was saved.';
    default: return 'PDF reading is temporarily unavailable. Please retry in a moment. No program was saved.';
  }
}
