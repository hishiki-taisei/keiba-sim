import { test } from "node:test";
import assert from "node:assert/strict";
import { courseFor, LAYOUTS } from "../course.js";
import { runRace, tally, sections } from "../engine.js";

const neutral = (H, course) => ({
  course, horses: Array.from({ length: H }, (_, i) => ({ name: `h${i}`, style: i / (H - 1), kick: 0, move: 0, ability: 0 })),
});

test("every layout builds and its hills have no cliffs", () => {
  for (const key of Object.keys(LAYOUTS)) {
    const venue = key.slice(0, 2), surface = key[2], note = key.endsWith("外") ? "外" : "";
    for (const distance of [1200, 1800, 2500, 3200]) {
      const c = courseFor({ venue, surface, distance, note });
      for (let s = 0; s < distance; s += 2) assert.ok(Math.abs(c.grade(s)) < 0.05, `${c.name} grade at ${s}`);
      const [x0, y0] = c.xy(0, 0), [x1, y1] = c.xy(c.lap, 0);
      assert.ok(Math.hypot(x1 - x0, y1 - y0) < 1e-6, `${c.name} closes`);
    }
  }
});

test("Kikuka Sho reports four corners: 1st and 2nd, then 3rd and 4th on the last lap", () => {
  const c = courseFor({ venue: "京都", surface: "芝", distance: 3000, note: "外" });
  assert.deepEqual(c.cornerChecks().map(x => x.corner), [1, 2, 3, 4]);
  assert.ok(c.cornerChecks()[0].s > 1000);
});

test("a race is reproducible from its seed and everyone finishes", () => {
  const f = neutral(18, { venue: "京都", surface: "芝", distance: 3000, note: "外" });
  const a = runRace(f, { seed: 7 }), b = runRace(f, { seed: 7 });
  assert.deepEqual(a.order, b.order);
  assert.ok(a.time.every(Number.isFinite));
  assert.equal(new Set(a.gates).size, 18);
});

test("finishing times are in a sensible range on very different courses", () => {
  const cases = [
    [{ venue: "京都", surface: "芝", distance: 3000, note: "外" }, 178, 192],
    [{ venue: "東京", surface: "ダ", distance: 1600 }, 93, 102],
    [{ venue: "中山", surface: "芝", distance: 1200, note: "外" }, 66, 72],
    [{ venue: "新潟", surface: "芝", distance: 1000, direction: "直線" }, 53, 58],
  ];
  for (const [course, lo, hi] of cases) {
    const r = runRace(neutral(14, course), { seed: 3 });
    const t = r.time[r.order[0]];
    assert.ok(t > lo && t < hi, `${course.venue}${course.distance}: ${t}`);
  }
});

test("a faster horse wins more often, and front runners lead early", () => {
  const f = neutral(10, { venue: "阪神", surface: "芝", distance: 2000 });
  f.horses[3].ability = 0.4;
  const res = tally(f, 300, { seed: 11 });
  assert.equal(res.win.indexOf(Math.max(...res.win)), 3);
  assert.ok(res.firstCorner[0] < res.firstCorner[9]);
  assert.ok(Math.abs(res.win.reduce((a, b) => a + b, 0) - 1) < 1e-9);
});

test("the profile sections cover the race in order", () => {
  for (const D of [1000, 1200, 1600, 2000, 2400, 3000, 3600]) {
    const s = sections(D);
    assert.ok(0 < s.early && s.early <= s.pre && s.pre <= s.last && s.last < D, `${D}`);
  }
});
