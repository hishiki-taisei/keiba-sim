// Runs tally() off the main thread so the race animation keeps playing.
import { tally } from "./engine.js";

self.onmessage = ({ data: { field, n, opts, chunk } }) => {
  const parts = [];
  for (let k = 0; k < n; k += chunk) {
    const m = Math.min(chunk, n - k);
    parts.push(tally(field, m, { ...opts, seed: opts.seed + k * 7919 }));
    self.postMessage({ progress: k + m });
  }
  const out = { n };
  for (const key of ["win", "place", "meanRank", "firstCorner", "lastCorner"]) {
    out[key] = field.horses.map((_, h) => parts.reduce((a, p) => a + p[key][h] * p.n, 0) / n);
  }
  self.postMessage({ done: out });
};
