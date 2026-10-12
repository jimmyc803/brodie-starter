/**
 * Trailing debounce with a max wait: calls within `debounceMs` coalesce, but the
 * callback always fires no later than `maxWaitMs` after the first pending call.
 */
export function createMaxWaitDebounce(fn: () => void, debounceMs = 500, maxWaitMs = 1000) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let firstAt = 0;

  const fire = () => {
    timer = undefined;
    firstAt = 0;
    fn();
  };

  const trigger = () => {
    const now = Date.now();
    if (timer === undefined) firstAt = now;
    else clearTimeout(timer);
    const wait = Math.max(0, Math.min(debounceMs, firstAt + maxWaitMs - now));
    timer = setTimeout(fire, wait);
  };

  const cancel = () => {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
    firstAt = 0;
  };

  return { trigger, cancel };
}
