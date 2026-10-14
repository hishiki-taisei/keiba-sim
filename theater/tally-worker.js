// Runs tally() off the main thread so the race animation keeps playing.
import { tally, mergeTallies } from "./engine.js";

self.onmessage = ({ data: { field, n, opts, chunk } }) => {
  const parts = [];
  for (let k = 0; k < n; k += chunk) {
    const m = Math.min(chunk, n - k);
    parts.push(tally(field, m, { ...opts, seed: opts.seed + k * 7919 }));
    self.postMessage({ progress: k + m });
  }
  self.postMessage({ done: mergeTallies(parts) });
};
