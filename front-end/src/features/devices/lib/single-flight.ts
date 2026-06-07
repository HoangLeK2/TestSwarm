const DEFAULT_SINGLE_FLIGHT_KEY = '__default__';

export function createSingleFlight<TArgs extends unknown[], TResult>(
  fn: (...args: TArgs) => Promise<TResult>,
  keyFn?: (...args: TArgs) => string
): (...args: TArgs) => Promise<TResult> {
  const inFlight = new Map<string, Promise<TResult>>();

  return (...args: TArgs) => {
    const key = keyFn ? keyFn(...args) : DEFAULT_SINGLE_FLIGHT_KEY;
    const active = inFlight.get(key);
    if (active) return active;

    const promise = fn(...args).finally(() => {
      if (inFlight.get(key) === promise) {
        inFlight.delete(key);
      }
    });
    inFlight.set(key, promise);
    return promise;
  };
}
