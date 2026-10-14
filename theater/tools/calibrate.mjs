// Set each horse's ability so the theater's win rates match the win model.
//
//   node theater/tools/calibrate.mjs theater/data/kikka2026.field.json theater/data/kikka2026.json
//
// Runs the field many times with fixed seeds (the same races every round, so
// rounds differ only by the abilities), compares each horse's win rate with
// its model probability, and nudges its ability by the log ratio. Post
// positions are drawn at random each race unless the field has them.
// Finishes with a check on fresh seeds and stores the result in the output.

import { readFileSync, writeFileSync } from "node:fs";
import { availableParallelism } from "node:os";
import { Worker, isMainThread, parentPort, workerData } from "node:worker_threads";
import { tally } from "../engine.js";

if (!isMainThread) {
  // worker: run one share of the races and send the tally back
  const { field, n, seed } = workerData;
  parentPort.postMessage(tally(field, n, { seed }));
  process.exit(0);
}

// tally() split across CPU cores; seeds follow tally's own sequence, so the
// result is the same as one tally(field, n, { seed }) call
async function tallyParallel(field, n, seed) {
  const W = Math.min(availableParallelism(), 8), per = Math.ceil(n / W), jobs = [];
  for (let k = 0; k < n; k += per) {
    const m = Math.min(per, n - k);
    jobs.push(new Promise((ok, fail) => {
      const w = new Worker(new URL(import.meta.url), { workerData: { field, n: m, seed: seed + k * 7919 } });
      w.once("message", ok); w.once("error", fail);
    }).then(r => ({ r, m })));
  }
  const parts = await Promise.all(jobs);
  const out = { n };
  for (const key of ["win", "place", "meanRank", "firstCorner", "lastCorner"]) {
    out[key] = field.horses.map((_, h) => parts.reduce((a, { r, m }) => a + r[key][h] * m, 0) / n);
  }
  return out;
}

const [, , src, dst, nArg] = process.argv;
if (!src || !dst) {
  console.error("usage: node calibrate.mjs <field.json> <out.json> [races per round]");
  process.exit(1);
}
const N = Number(nArg || 4000);
const ROUNDS = 16;
const field = JSON.parse(readFileSync(src, "utf8"));
const H = field.horses.length;
const target = field.horses.map(h => h.p_model);
const floor = 0.5 / N;

const logGeo = target.reduce((a, p) => a + Math.log(p), 0) / H;
field.horses.forEach((h, i) => { h.ability = 0.15 * (Math.log(target[i]) - logGeo); });

const fmt = x => (100 * x).toFixed(1).padStart(5);
let res;
for (let round = 0; round < ROUNDS; round++) {
  // the same races in early rounds; fresh ones later so the abilities do
  // not fit the noise of one particular set of races
  res = await tallyParallel(field, N, round < 8 ? 1 : 1 + round * 1e6);
  const step = round < 4 ? 0.12 : round < 8 ? 0.08 : 0.04;
  let worst = 0;
  field.horses.forEach((h, i) => {
    const w = Math.max(res.win[i], floor);
    h.ability += step * Math.log(target[i] / w);
    worst = Math.max(worst, Math.abs(res.win[i] - target[i]));
  });
  const mean = field.horses.reduce((a, h) => a + h.ability, 0) / H;
  field.horses.forEach(h => { h.ability -= mean; });
  console.log(`round ${round + 1}: largest gap ${(100 * worst).toFixed(2)} pt`);
}

// check on races the calibration never saw
const check = await tallyParallel(field, 2 * N, 99991);
let mae = 0, worst = 0;
console.log("\n馬                     model   theater   top-3   1角   4角");
field.horses.forEach((h, i) => {
  h.ability = Math.round(h.ability * 1000) / 1000;
  const gap = Math.abs(check.win[i] - target[i]);
  mae += gap / H; worst = Math.max(worst, gap);
  console.log(`${h.name.padEnd(14, "　")} ${fmt(target[i])}% ${fmt(check.win[i])}% ${fmt(check.place[i])}% ` +
              `${check.firstCorner[i].toFixed(1).padStart(5)} ${check.lastCorner[i].toFixed(1).padStart(5)}`);
});
console.log(`\nfresh ${2 * N} races: mean gap ${(100 * mae).toFixed(2)} pt, largest ${(100 * worst).toFixed(2)} pt`);

field.calibration = {
  races_per_round: N, rounds: ROUNDS, check_races: 2 * N,
  mean_gap: Math.round(mae * 1e4) / 1e4, largest_gap: Math.round(worst * 1e4) / 1e4,
  win: check.win.map(x => Math.round(x * 1e4) / 1e4),
  place: check.place.map(x => Math.round(x * 1e4) / 1e4),
};
writeFileSync(dst, JSON.stringify(field, null, 1));
console.log(`wrote ${dst}`);
