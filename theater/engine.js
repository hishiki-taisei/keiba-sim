// Race engine for the race theater.
//
// Runs one race at a time, horse by horse, in fixed time steps. The same
// code drives the browser animation, the in-browser "run it 1000 times"
// tally, and the calibration script (tools/calibrate.mjs), so the win rates
// people see are exactly what calibration matched to the win model.
//
// Each horse has:
//   ability   m/s added to its top speed (set by calibration)
//   style     where it likes to sit, 0 = leads ... 1 = last
//   move      tendency to make ground before the straight (まくり), -1..1
//   kick      finishing speed, seconds of last-600m edge over its fields
//   stamina   long-distance aptitude, -1..1
//   going     aptitude for soft ground, -1..1
//   form_sd   how much its form swings from race to race (1 = average)
//
// Mechanics: a pace profile taken from past lap times on the same course
// and distance, horses holding their preferred position, an energy budget
// drained by speed and hills, saving energy tucked in behind others, losing
// ground wide on the bends, getting held up behind slower horses and
// switching out, and a final spurt whose start depends on style, move and
// stamina.

import { courseFor } from "./course.js";

export const DT = 0.25;

const LANE = 1.25;           // lateral spacing between two horses side by side (m)
const LENGTH = 2.6;          // nose-to-nose distance that counts as right behind (m)
const SPREAD = 1.5;          // metres between preferred positions of neighbours in the order
const KICK_GAIN = 0.22;      // m/s of spurt per second of last-600m edge
const START_LOSS = 1.35;     // seconds the engine's standing start costs
const BUDGET_RATIO = 1.027;   // energy budget over the cost of running the par profile
const GOING = {              // overall speed, and how much going aptitude counts
  "芝": { "良": [1.0, 0.0], "稍重": [0.992, 0.4], "重": [0.982, 0.8], "不良": [0.958, 1.0] },
  "ダ": { "良": [1.0, 0.0], "稍重": [1.003, 0.4], "重": [1.006, 0.8], "不良": [1.008, 1.0] },
};
const PACE = { slow: 0.986, mid: 1.0, fast: 1.016 };

// Where the sections of the pace profile end, for a race of D metres.
export function sections(D) {
  const early = Math.min(1000, Math.max(D - 1000, 0.35 * D));
  return { early, pre: Math.max(early, D - 1000), last: D - 600 };
}

// Typical lap speeds when the database has none for this course: the
// leader's average speed in m/s for each section.
export function defaultPace(D, surface = "芝") {
  const v = 17.95 - 0.57 * D / 1000 - (surface === "ダ" ? 0.65 : 0);
  return { early: v, mid: v - 0.5, pre: v + 0.2, last600: v + 0.7 };
}

// Speed profile (m/s) the field runs to, before the race's pace factor.
// `pace` is the median leader speed per section from past races; the
// engine's own standing start is taken out of the early section.
export function makeProfile(pace, D) {
  const sec = sections(D);
  const early = sec.early / (sec.early / pace.early - START_LOSS);
  const mid = pace.mid * 1.004, pre = pace.pre * 1.004;
  return {
    cap: pace.last600 + 0.25,
    at(s) {
      if (s < sec.early) return early;
      if (s < sec.pre) return mid;
      if (s < sec.last) return (sec.pre < sec.last ? mid + (s - sec.pre) / (sec.last - sec.pre) * (pre - mid) : pre);
      return pre;
    },
  };
}

export function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function normal(rand) {
  let u = 0;
  while (u === 0) u = rand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * rand());
}

const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));

const CACHE = new WeakMap();   // field -> its profile and energy budget

export function courseOf(field) {
  return courseFor(field.course || {});
}

// Energy an average horse spends running the par profile, plus the spurt;
// cached per course and profile.
export function parCost(course, prof) {
  const D = course.distance;
  let cost = 0;
  for (let s = 0; s < D; s += 5) {
    const v = D - s < 560 ? prof.cap : prof.at(s);
    cost += (v / 16) ** 3 * (1 + 35 * Math.max(course.grade(s), 0)) * 5 / v;
  }
  return cost;
}

// opts: seed, pace ("auto" | "slow" | "mid" | "fast"), going ("良" ...),
//       trace (record every step for animation), gates (array of post
//       positions, one per horse; default: the field's own, or a random draw)
export function runRace(field, opts = {}) {
  const course = opts.course || courseOf(field);
  const rand = mulberry32(opts.seed ?? 1);
  const horses = field.horses;
  const H = horses.length;
  const D = course.distance;
  const surface = course.surface || (field.course && field.course.surface === "ダ" ? "ダ" : "芝");
  const goingTable = GOING[surface] || GOING["芝"];
  const [goingSpeed, goingWeight] = goingTable[opts.going || field.going || "良"] || goingTable["良"];
  let cached = CACHE.get(field);
  if (!cached || cached.course !== course.name) {
    const prof = makeProfile(field.pace || defaultPace(D, surface), D);
    cached = { course: course.name, prof, budget: BUDGET_RATIO * parCost(course, prof) };
    CACHE.set(field, cached);
  }
  const { prof, budget } = cached;
  const longish = Math.min(1, D / 3000);

  let gates = opts.gates;
  if (!gates) {
    if (horses.every(h => h.gate)) gates = horses.map(h => h.gate);
    else {
      gates = horses.map((_, i) => i + 1);
      for (let i = H - 1; i > 0; i--) {
        const j = Math.floor(rand() * (i + 1));
        [gates[i], gates[j]] = [gates[j], gates[i]];
      }
    }
  }

  const pace = (opts.pace && opts.pace !== "auto" ? PACE[opts.pace] : 1 + 0.012 * normal(rand)) * goingSpeed;

  // per-horse, per-race draws
  const cap = new Float64Array(H), want = new Float64Array(H), spurtAt = new Float64Array(H),
    moveAt = new Float64Array(H), kickV = new Float64Array(H), e0 = new Float64Array(H);
  for (let i = 0; i < H; i++) {
    const h = horses[i];
    const form = 0.16 * (h.form_sd ?? 1) * normal(rand);
    cap[i] = (prof.cap + (h.ability ?? 0) + 0.12 * goingWeight * (h.going ?? 0) + form) * goingSpeed;
    want[i] = clamp((h.style ?? 0.5) + 0.08 * normal(rand), 0, 1);
    const move = h.move ?? 0, stam = h.stamina ?? 0;
    moveAt[i] = Math.min(900, 0.45 * D) + 250 * longish * move + 80 * normal(rand);
    spurtAt[i] = clamp(540 + longish * (120 * want[i] + 90 * move + 60 * stam) + 50 * normal(rand), 380, Math.min(850, 0.6 * D));
    kickV[i] = KICK_GAIN * clamp(h.kick ?? 0, -1.2, 1.5) * goingSpeed;
    e0[i] = budget * (1 + 0.03 * stam) * (1 + 0.015 * normal(rand));
  }

  const s = new Float64Array(H), y = new Float64Array(H), v = new Float64Array(H),
    e = Float64Array.from(e0), tFin = new Float64Array(H).fill(Infinity), t600 = new Float64Array(H).fill(NaN);
  const done = new Uint8Array(H);
  for (let i = 0; i < H; i++) { y[i] = (gates[i] - 1) * LANE * 0.9; v[i] = 1.5; }

  const tab = tables(course);
  const checks = course.cornerChecks();
  const corners = checks.map(() => new Int16Array(H));
  let nextCheck = 0;
  const splits = {};
  const marks = [1000, 2000, D - 600];
  let nextMark = 0;

  const trace = opts.trace ? { dt: DT, s: [], y: [], v: [], e: [] } : null;
  const idx = Array.from({ length: H }, (_, i) => i);
  const rank = new Int16Array(H);
  let t = 0, finished = 0;

  while (finished < H && t < 400) {
    for (let a = 1; a < H; a++) {             // insertion sort: the order barely changes per step
      const x = idx[a], sx = s[x];
      let b = a - 1;
      while (b >= 0 && s[idx[b]] < sx) { idx[b + 1] = idx[b]; b--; }
      idx[b + 1] = x;
    }
    for (let r = 0; r < H; r++) rank[idx[r]] = r;
    const leadS = s[idx[0]];

    while (nextMark < marks.length && leadS >= marks[nextMark]) { splits[marks[nextMark]] = t; nextMark++; }
    while (nextCheck < checks.length && s[idx[H - 1]] >= checks[nextCheck].s) {
      // passing order once the whole field is past the corner's midpoint:
      // order by time is approximated by order of distance run now
      for (let r = 0; r < H; r++) corners[nextCheck][idx[r]] = r + 1;
      nextCheck++;
    }

    for (let r = 0; r < H; r++) {
      const i = idx[r];
      if (done[i]) continue;
      const rem = D - s[i];
      const m = s[i] | 0, grade = tab.grade[m];
      const straight = tab.home[m] === 1 && rem < 600;

      // where it wants to be: a gap behind the leader set by its style,
      // closed up from moveAt by horses that like to make ground
      let target = pace * prof.at(s[i]);
      const spurting = rem < spurtAt[i];
      if (spurting) {
        target = cap[i] + kickV[i];
      } else {
        let gapWant = want[i] * SPREAD * (H - 1);
        const move = horses[i].move ?? 0;
        if (rem < moveAt[i]) {
          const f = clamp((moveAt[i] - rem) / Math.max(moveAt[i] - spurtAt[i], 1), 0, 1);
          gapWant *= 1 - f * clamp(0.8 + 0.25 * move, 0.3, 0.95);
        }
        const push = s[i] < 700 ? 1.0 : rem < moveAt[i] ? 0.7 : 0.35;
        target += clamp((rem < moveAt[i] ? 0.12 : 0.07) * (leadS - s[i] - gapWant), -0.5, push);
      }
      target = Math.min(target, cap[i] + kickV[i]);
      target -= 22 * grade;

      // an empty tank caps the speed
      const ef = e[i] / e0[i];
      if (ef < 0.2) target = Math.min(target, cap[i] * (0.88 + 0.12 * Math.max(ef, 0) / 0.2));

      // traffic: nearest horse just ahead and overlapping
      let block = -1, gapAhead = Infinity, drafting = false;
      for (let k = r - 1; k >= 0; k--) {
        const j = idx[k];
        const ds = s[j] - s[i];
        if (ds > 8) break;
        const dy = Math.abs(y[j] - y[i]);
        if (dy < LANE * 0.9 && ds < gapAhead) { gapAhead = ds; block = j; }
        if (dy < LANE * 1.5 && ds > 0.5 && ds < 6) drafting = true;
      }
      const held = block >= 0 && gapAhead < LENGTH && v[block] < target;
      if (held) target = Math.min(target, v[block] + 0.1 * (gapAhead - 1.2));

      // lateral movement
      let dy = 0;
      if (held || (spurting && block >= 0 && gapAhead < 3 * LENGTH && v[block] < target)) {
        // look for room one horse wider; inside if it is clearer
        const out = roomAt(i, y[i] + LANE, s, y, idx, r), inside = y[i] >= LANE && roomAt(i, y[i] - LANE, s, y, idx, r);
        if (out) dy = 1.4; else if (inside) dy = -1.4;
      } else if (!straight) {
        if (y[i] > 0.05 && roomAt(i, y[i] - LANE * 0.6, s, y, idx, r)) dy = -(t < 20 ? 0.7 : 0.25);
      }
      y[i] = clamp(y[i] + dy * DT, 0, course.width - 2);

      const accel = t < 4 ? 6.0 : 0.9;
      const decel = 0.7;
      v[i] += clamp(target - v[i], -decel * DT, accel * DT);

      let cost = (v[i] / 16) ** 3 * (1 + 35 * Math.max(grade, 0)) * DT;
      if (drafting && !spurting) cost *= 0.9;
      e[i] -= cost;

      let step = v[i] * DT;
      if (tab.bend[m]) step *= course.radius / (course.radius + y[i]);
      const ns = s[i] + step;
      if (s[i] < D - 600 && ns >= D - 600) t600[i] = t + (D - 600 - s[i]) / step * DT;
      if (ns >= D) {
        tFin[i] = t + (D - s[i]) / step * DT;
        done[i] = 1; finished++;
        s[i] = D;
      } else s[i] = ns;
    }
    t += DT;
    if (trace) {
      trace.s.push(Float32Array.from(s)); trace.y.push(Float32Array.from(y));
      trace.v.push(Float32Array.from(v));
      trace.e.push(Float32Array.from(e, (x, i) => Math.max(0, x / e0[i])));
    }
  }

  const order = Array.from({ length: H }, (_, i) => i).sort((a, b) => tFin[a] - tFin[b]);
  return {
    order, time: Array.from(tFin), last3f: Array.from(tFin, (x, i) => x - t600[i]),
    corners: corners.map(c => Array.from(c)), cornerNames: checks.map(c => c.corner),
    splits, gates, pace, trace, course,
  };
}

// Per-metre lookups of the course, built once per course object.
function tables(course) {
  if (course._tables) return course._tables;
  const n = Math.ceil(course.distance) + 2;
  const t = { grade: new Float32Array(n), bend: new Uint8Array(n), home: new Uint8Array(n) };
  for (let m = 0; m < n; m++) {
    t.grade[m] = course.grade(m + 0.5);
    t.bend[m] = course.inBend(m + 0.5) ? 1 : 0;
    t.home[m] = course.inHomeStraight(m + 0.5) ? 1 : 0;
  }
  course._tables = t;
  return t;
}

function roomAt(i, yy, s, y, idx, r) {
  if (yy < 0) return false;
  // nobody within a length either way at that lateral position
  for (let k = Math.max(0, r - 6); k < Math.min(idx.length, r + 7); k++) {
    const j = idx[k];
    if (j === i) continue;
    if (Math.abs(s[j] - s[i]) < LENGTH && Math.abs(y[j] - yy) < LANE * 0.85) return false;
  }
  return true;
}

// Run the race n times and tally win, top-3 and average position.
// onProgress(done, n) is called every `chunk` races when given; the work is
// split with setTimeout in the browser so the page stays responsive.
export function tally(field, n, opts = {}) {
  const H = field.horses.length;
  const win = new Float64Array(H), place = new Float64Array(H), rankSum = new Float64Array(H),
    c4 = new Float64Array(H), c1 = new Float64Array(H);
  const seed0 = opts.seed ?? 1000;
  const course = courseOf(field);
  for (let k = 0; k < n; k++) {
    const res = runRace(field, { ...opts, course, seed: seed0 + k * 7919, trace: false });
    res.order.forEach((h, pos) => {
      if (pos === 0) win[h]++;
      if (pos < 3) place[h]++;
      rankSum[h] += pos + 1;
    });
    const nc = res.corners.length;
    for (let h = 0; h < H; h++) { c1[h] += res.corners[0][h]; c4[h] += res.corners[nc - 1][h]; }
  }
  return {
    n, win: Array.from(win, x => x / n), place: Array.from(place, x => x / n),
    meanRank: Array.from(rankSum, x => x / n),
    firstCorner: Array.from(c1, x => x / n), lastCorner: Array.from(c4, x => x / n),
  };
}

// Same as tally but yields to the browser between chunks.
export async function tallyAsync(field, n, opts = {}, onProgress) {
  const chunk = 50, parts = [];
  for (let k = 0; k < n; k += chunk) {
    const m = Math.min(chunk, n - k);
    parts.push(tally(field, m, { ...opts, seed: (opts.seed ?? 1000) + k * 7919 }));
    onProgress?.(k + m, n);
    await new Promise(r => setTimeout(r, 0));
  }
  const H = field.horses.length, keys = ["win", "place", "meanRank", "firstCorner", "lastCorner"];
  const out = { n };
  for (const key of keys) {
    out[key] = Array.from({ length: H }, (_, h) => parts.reduce((a, p) => a + p[key][h] * p.n, 0) / n);
  }
  return out;
}
