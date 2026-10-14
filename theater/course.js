// Course geometry for the race theater.
//
// Every oval is modelled as a stadium shape: two straights joined by two
// semicircular bends of the same length as the real course's lap and home
// straight. Positions along the rail use a lap coordinate u: 0 at the
// finish line, growing in the running direction. Segments in running order
// from the finish line: bend 1-2, back straight, bend 3-4, home straight.
// The race starts `distance` metres before the finish, so starts that sit
// in a chute on the real course land on the oval here.
// Lateral position y is metres out from the inside rail. Left-handed
// courses use the same coordinates and are mirrored only when drawn.

export class Course {
  constructor({ name, lap, straight, distance, hills = [], direction = "右", width = 30 }) {
    this.name = name;
    this.lap = lap;
    this.straight = straight;
    this.distance = distance;
    this.direction = direction;
    this.width = width;
    this.radius = (lap - 2 * straight) / (2 * Math.PI);
    this.bend = Math.PI * this.radius;
    this.startU = mod(-distance, lap);
    const b = this.bend, L = straight;
    // Hills as [rise from, top, fall from, end, height] in lap coordinates
    // (the end may pass the finish line and wrap around).
    //   corner3: climb from the back straight, summit early in the 3rd
    //            corner, descent through the 4th (Kyoto)
    //   finish:  a rise in the home straight, given in metres before the
    //            finish line (Nakayama, Hanshin, Tokyo, Chukyo); the ground
    //            falls back gently through the 1st corner
    this.hills = hills.map(h => h.type === "corner3"
      ? [b + L - 150, b + L + 0.35 * b, b + L + 0.35 * b, 2 * b + L, h.height]
      : [lap - h.from, lap - h.to, lap, lap + 0.5 * b, h.height]);
  }

  lapU(s) { return mod(this.startU + s, this.lap); }

  inBend(s) {
    const u = this.lapU(s), b = this.bend, L = this.straight;
    return u < b || (u >= b + L && u < 2 * b + L);
  }

  inHomeStraight(s) { return this.lapU(s) >= 2 * this.bend + this.straight; }

  elevation(s) {
    const u0 = this.lapU(s);
    let e = 0;
    for (const [a, p, q, z, h] of this.hills) {
      const u = z > this.lap && u0 < z - this.lap ? u0 + this.lap : u0;
      if (u >= a && u < p) e += h * (u - a) / (p - a);
      else if (u >= p && u < q) e += h;
      else if (u >= q && u < z) e += h * (z - u) / (z - q);
    }
    return e;
  }

  grade(s) { return (this.elevation(s + 5) - this.elevation(s - 5)) / 10; }

  // Plan-view coordinates (m) at distance run s and y metres off the rail.
  xy(s, y) {
    const u = this.lapU(s), R = this.radius, L = this.straight, b = this.bend;
    const r = R + y;
    if (u < b) {                      // bend 1-2, centre (-L/2, 0)
      const th = -Math.PI / 2 - (u / b) * Math.PI;
      return [-L / 2 + r * Math.cos(th), r * Math.sin(th)];
    }
    if (u < b + L) return [-L / 2 + (u - b), r];             // back straight
    if (u < 2 * b + L) {              // bend 3-4, centre (L/2, 0)
      const th = Math.PI / 2 - ((u - b - L) / b) * Math.PI;
      return [L / 2 + r * Math.cos(th), r * Math.sin(th)];
    }
    return [L / 2 - (u - 2 * b - L), -r];                     // home straight
  }

  // Distance run at which the field reaches lap coordinate u for the k-th time.
  sAtLapU(u, k = 0) { return mod(u - this.startU, this.lap) + k * this.lap; }

  // The corners JRA reports passing order at: the last four corner
  // passings of the race (fewer in short races), each at the corner's middle.
  cornerChecks() {
    const b = this.bend, L = this.straight;
    const mids = [b / 4, 3 * b / 4, b + L + b / 4, b + L + 3 * b / 4]; // corners 1..4
    const all = [];
    for (let k = 0; k < 6; k++) for (const [i, u] of mids.entries()) {
      const s = this.sAtLapU(u, k);
      if (s > 50 && s < this.distance) all.push({ s, corner: i + 1 });
    }
    all.sort((a, z) => a.s - z.s);
    return all.slice(-4);
  }

  outline(y, step = 10) {
    const pts = [];
    for (let u = 0; u <= this.lap + 0.1; u += step) pts.push(this.xy(mod(u - this.startU, this.lap), y));
    return pts;
  }
}

// Niigata's 1000m straight course: one straight, no bends.
export class StraightCourse {
  constructor({ name, distance, width = 30 }) {
    Object.assign(this, { name, distance, width, direction: "直線", lap: distance, straight: distance,
                          radius: Infinity, bend: 0, hills: [] });
  }
  inBend() { return false; }
  inHomeStraight() { return true; }
  elevation() { return 0; }
  grade() { return 0; }
  xy(s, y) { return [this.distance / 2 - s, -y]; }
  cornerChecks() { return [{ s: this.distance / 2, corner: 0 }]; }
  outline(y) { return [[this.distance / 2, -y], [-this.distance / 2, -y]]; }
}

function mod(a, n) { return ((a % n) + n) % n; }

// JRA courses: lap and home straight (m, approximate public figures),
// direction, and hills. Key: venue + surface (+ "外" for an outer course).
export const LAYOUTS = {
  "札幌芝": [1640.9, 266.1, "右", []],
  "函館芝": [1626.6, 262.1, "右", []],
  "福島芝": [1600.0, 292.0, "右", [{ from: 300, to: 200, height: 1.2 }]],
  "新潟芝": [1623.0, 358.7, "左", []],
  "新潟芝外": [2223.0, 658.7, "左", []],
  "東京芝": [2083.1, 525.9, "左", [{ from: 460, to: 300, height: 2.0 }]],
  "中山芝": [1667.1, 310.0, "右", [{ from: 180, to: 70, height: 2.2 }]],
  "中山芝外": [1839.7, 310.0, "右", [{ from: 180, to: 70, height: 2.2 }]],
  "中京芝": [1705.9, 412.5, "左", [{ from: 380, to: 240, height: 2.0 }]],
  "京都芝": [1782.8, 328.4, "右", [{ type: "corner3", height: 3.1 }]],
  "京都芝外": [1894.3, 403.7, "右", [{ type: "corner3", height: 4.3 }]],
  "阪神芝": [1689.0, 356.5, "右", [{ from: 200, to: 80, height: 1.8 }]],
  "阪神芝外": [2089.0, 473.6, "右", [{ from: 200, to: 80, height: 1.8 }]],
  "小倉芝": [1615.1, 293.0, "右", []],
  "札幌ダ": [1487.0, 264.3, "右", []],
  "函館ダ": [1475.8, 260.3, "右", []],
  "福島ダ": [1444.6, 295.7, "右", [{ from: 300, to: 200, height: 1.2 }]],
  "新潟ダ": [1472.5, 353.9, "左", []],
  "東京ダ": [1899.0, 501.6, "左", [{ from: 460, to: 300, height: 2.4 }]],
  "中山ダ": [1493.0, 308.0, "右", [{ from: 180, to: 70, height: 2.2 }]],
  "中京ダ": [1530.0, 410.7, "左", [{ from: 380, to: 240, height: 1.8 }]],
  "京都ダ": [1607.6, 329.1, "右", [{ type: "corner3", height: 3.0 }]],
  "阪神ダ": [1517.6, 352.7, "右", [{ from: 200, to: 80, height: 1.6 }]],
  "小倉ダ": [1445.4, 291.3, "右", []],
};

// A course from the database's race fields: venue (京都), surface (芝/ダ),
// distance, and course_note ("外" for an outer course, "直線" direction for
// Niigata's straight course).
export function courseFor({ venue = "京都", surface = "芝", distance = 3000, note = "", direction = "" } = {}) {
  const sf = surface === "ダート" ? "ダ" : surface;
  const label = `${venue} ${sf === "ダ" ? "ダート" : "芝"}${distance}m`;
  if (direction === "直線") return Object.assign(new StraightCourse({ name: `${label}（直線）`, distance }), { surface: sf });
  const outer = note && note.includes("外");
  const key = `${venue}${sf}${outer ? "外" : ""}`;
  const lay = LAYOUTS[key] || LAYOUTS[`${venue}${sf}`];
  if (!lay) throw new Error(`unknown course: ${key}`);
  const [lap, straight, dir, hills] = lay;
  return Object.assign(new Course({ name: label + (outer && LAYOUTS[key] ? "（外回り）" : ""), lap, straight,
                                    distance, hills, direction: dir }), { surface: sf });
}

export function kyotoTurf3000() {
  return courseFor({ venue: "京都", surface: "芝", distance: 3000, note: "外" });
}
