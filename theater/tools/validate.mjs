// Check the theater against what actually happened in past races.
//
//   python3 theater/tools/build_field.py --race-id <id> --out <dir>/<id>.json   (for each race)
//   node theater/tools/validate.mjs <dir> [report.json]
//
// For each race: a quick calibration (win rates to the final odds, overall
// speed to the course's par time), then 500 runs. Compared with the real
// race, by rank correlation within each race: position at the first and
// last reported corner, last-600m time, and finishing order. As a
// baseline, the same correlation for the horse's own average first-corner
// position alone (what you would guess without running the race).

import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { availableParallelism } from "node:os";
import { Worker, isMainThread, parentPort, workerData } from "node:worker_threads";
import { tally, runRace } from "../engine.js";

function quickCalibrate(field, N = 300, rounds = 10) {
  const target = field.horses.map(h => h.p_model), H = target.length;
  const lg = target.reduce((a, p) => a + Math.log(p), 0) / H;
  field.horses.forEach((h, i) => { h.ability = 0.15 * (Math.log(target[i]) - lg); });
  for (let r = 0; r < rounds; r++) {
    const res = tally(field, N, { seed: 1 + r * 1e6 });
    field.horses.forEach((h, i) => { h.ability += (r < 5 ? 0.12 : 0.06) * Math.log(target[i] / Math.max(res.win[i], 0.5 / N)); });
    const par = field.pace?.par_time;
    if (par) field.speed_scale = (field.speed_scale ?? 1) * (res.winTimes[res.winTimes.length >> 1] / par) ** 0.9;
    const m = field.horses.reduce((a, h) => a + h.ability, 0) / H;
    field.horses.forEach(h => { h.ability -= m; });
  }
}

function ranks(xs) {
  const idx = xs.map((x, i) => [x, i]).sort((a, b) => a[0] - b[0]);
  const r = new Array(xs.length);
  for (let k = 0; k < idx.length;) {        // average ranks for ties
    let j = k;
    while (j + 1 < idx.length && idx[j + 1][0] === idx[k][0]) j++;
    for (let q = k; q <= j; q++) r[idx[q][1]] = (k + j) / 2;
    k = j + 1;
  }
  return r;
}

function spearman(a, b) {
  const keep = a.map((x, i) => Number.isFinite(x) && Number.isFinite(b[i]));
  const ra = ranks(a.filter((_, i) => keep[i])), rb = ranks(b.filter((_, i) => keep[i]));
  const n = ra.length;
  if (n < 4) return NaN;
  const ma = ra.reduce((x, y) => x + y, 0) / n, mb = rb.reduce((x, y) => x + y, 0) / n;
  let sab = 0, saa = 0, sbb = 0;
  for (let i = 0; i < n; i++) { sab += (ra[i] - ma) * (rb[i] - mb); saa += (ra[i] - ma) ** 2; sbb += (rb[i] - mb) ** 2; }
  return sab / Math.sqrt(saa * sbb);
}

function score(field) {
  quickCalibrate(field);
  const res = tally(field, 500, { seed: 424242 });
  const act = field.horses.map(h => h.actual || {});
  const pass = act.map(a => (a.passing || "").split("-").map(Number).filter(Number.isFinite));
  const first = pass.map(p => p.length ? p[0] : NaN), last = pass.map(p => p.length ? p[p.length - 1] : NaN);
  const t0 = Math.min(...act.map(a => a.time ?? Infinity));
  let spread = 0, margin = 0;     // winner to last horse, and to second, per race
  for (let k = 0; k < 200; k++) {
    const r = runRace(field, { seed: 7 + k * 31 });
    spread += (r.time[r.order[r.order.length - 1]] - r.time[r.order[0]]) / 200;
    margin += (r.time[r.order[1]] - r.time[r.order[0]]) / 200;
  }
  return {
    first: spearman(res.firstCorner, first),
    first_baseline: spearman(field.horses.map(h => h.style ?? 0.5), first),
    last: spearman(res.lastCorner, last),
    last3f: spearman(res.last3f, act.map(a => a.last3f ?? NaN)),
    finish: spearman(res.meanRank, act.map(a => a.finish ?? NaN)),
    finish_odds: spearman(field.horses.map(h => -h.p_model), act.map(a => a.finish ?? NaN)),
    time_err: res.winTimes[res.winTimes.length >> 1] - t0,
    spread_sim: spread, spread_real: Math.max(...act.map(a => (a.time ?? t0) - t0)),
    margin_sim: margin, margin_real: act.map(a => a.time).filter(Number.isFinite).sort((a, b) => a - b)[1] - t0,
  };
}

if (!isMainThread) {
  parentPort.postMessage(workerData.files.map(f => {
    const field = JSON.parse(readFileSync(f, "utf8"));
    return { race: f.split("/").pop().replace(".json", ""), title: field.title, course: field.course, ...score(field) };
  }));
  process.exit(0);
}

const [, , dir, out] = process.argv;
const files = readdirSync(dir).filter(f => f.endsWith(".json")).map(f => `${dir}/${f}`);
const W = Math.min(availableParallelism(), 8);
const shares = Array.from({ length: W }, (_, k) => files.filter((_, i) => i % W === k));
const rows = (await Promise.all(shares.filter(s => s.length).map(s => new Promise((ok, fail) => {
  const w = new Worker(new URL(import.meta.url), { workerData: { files: s } });
  w.once("message", ok); w.once("error", fail);
})))).flat();

const mean = k => { const v = rows.map(r => r[k]).filter(Number.isFinite); return v.reduce((a, b) => a + b, 0) / v.length; };
const summary = {
  races: rows.length,
  first_corner: mean("first"), first_corner_baseline: mean("first_baseline"),
  last_corner: mean("last"), last3f: mean("last3f"), finish: mean("finish"), finish_odds: mean("finish_odds"),
  time_err_mean: mean("time_err"), time_err_abs: rows.reduce((a, r) => a + Math.abs(r.time_err), 0) / rows.length,
  spread_sim: mean("spread_sim"), spread_real: mean("spread_real"),
  margin_sim: mean("margin_sim"), margin_real: mean("margin_real"),
};
for (const [k, v] of Object.entries(summary)) console.log(k.padEnd(22), typeof v === "number" ? v.toFixed(3) : v);
if (out) writeFileSync(out, JSON.stringify({ summary, races: rows }, null, 1));
