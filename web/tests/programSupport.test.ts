import { describe, it, expect } from 'vitest';
import { exerciseReviewBrief, supportBookingUrl, parserFailureMessage } from '../lib/programSupport';

describe('exercise support discussion', () => {
  it('preserves unsupported prescriptions and notes without including coach tokens or supported exercises', () => {
    const brief = exerciseReviewBrief([{ title: 'Strength', days: [{ title: 'Upper', day_number: 2, exercises: [
      { name: 'Bench press', sets: 3, reps: 8, notes: 'Pause at the bottom', supported: false, exercise_key: null },
      { name: 'Plank', sets: 2, reps: 0, notes: '45 seconds', supported: false, exercise_key: null },
      { name: 'Squat', sets: 3, reps: 10, notes: '', supported: true, exercise_key: 'squat' },
    ] }] }]);
    expect(brief).toContain('Strength — Day 2: Upper');
    expect(brief).toContain('Bench press: 3 sets × 8 reps; Pause at the bottom');
    expect(brief).toContain('Plank: 2 sets × timed / see notes; 45 seconds');
    expect(brief).not.toContain('Squat');
    expect(brief).toContain('no appointment has been booked');
  });
  it('offers no empty review', () => expect(exerciseReviewBrief([])).toBe(''));
  it('accepts only configured HTTPS booking destinations without credentials', () => {
    for (const value of [undefined, '', 'javascript:alert(1)', 'http://example.org', '/book', 'https://user:password@example.org']) expect(supportBookingUrl(value)).toBeNull();
    expect(supportBookingUrl('https://example.org/book')).toBe('https://example.org/book');
  });
  it('returns actionable safe parser messages', () => {
    expect(parserFailureMessage('MISSING_KEY')).toContain('enable the program parser');
    expect(parserFailureMessage('INVALID_OUTPUT')).toContain('legible');
    expect(parserFailureMessage('INVALID_PDF')).toContain('Export a new PDF');
    expect(parserFailureMessage('provider-secret')).not.toContain('provider-secret');
  });
});
