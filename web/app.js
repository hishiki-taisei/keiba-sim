// Race replay viewer. Reads a JSON file written by sim/export.py.

const FRAME_COLORS = [
  ["#ffffff", "#000"], ["#222222", "#fff"], ["#d9312b", "#fff"], ["#2f62c9", "#fff"],
  ["#f2d43a", "#000"], ["#2f9a4b", "#fff"], ["#f08a24", "#000"], ["#f19ac0", "#000"],
];

// JRA frame (枠) number for each post position
function frameOf(gate, n) {
  if (n <= 8) return gate;
  const base = Math.floor(n / 8), extra = n % 8;
  let g = 0;
  for (let f = 1; f <= 8; f++) {
    g += base + (f > 8 - extra ? 1 : 0);
    if (gate <= g) return f;
  }
  return 8;
}

function styleLabel(s) {
  if (s < 0.15) return "逃げ";
  if (s < 0.45) return "先行";
  if (s < 0.75) return "差し";
  return "追込";
}

const pct = (x) => (x * 100).toFixed(1) + "%";

const state = { data: null, t: 0, playing: false, speed: 6, view: "full", last: null, sortKey: "win", sortDir: -1 };
const canvas = document.getElementById("track");
const ctx = canvas.getContext("2d");

async function load() {
  const params = new URLSearchParams(location.search);
  const file = params.get("race") || "demo";
  const res = await fetch(`data/${encodeURIComponent(file)}.json`);
  state.data = await res.json();
  const d = state.data;
  document.title = `${d.title} | 競馬シミュレーター`;
  document.getElementById("subtitle").textContent = `${d.title}　${d.course.name}`;
  if (d.note) {
    const note = document.getElementById("note");
    note.textContent = d.note;
    note.hidden = false;
  }
  document.getElementById("nsim").textContent = `（${d.simulations.toLocaleString()}回走らせた結果）`;
  d.horses.forEach((h) => {
    const [bg, fg] = FRAME_COLORS[frameOf(h.gate, d.horses.length) - 1];
    h.bg = bg;
    h.fg = fg;
  });
  renderTable();
  resize();
  draw();
}

function duration() {
  const f = state.data.replay.frames;
  return f[f.length - 1].t;
}

function frameAt(t) {
  const f = state.data.replay.frames;
  let lo = 0, hi = f.length - 1;
  if (t <= f[0].t) return { a: f[0], b: f[0], k: 0 };
  if (t >= f[hi].t) return { a: f[hi], b: f[hi], k: 0 };
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (f[mid].t <= t) lo = mid; else hi = mid;
  }
  return { a: f[lo], b: f[hi], k: (t - f[lo].t) / (f[hi].t - f[lo].t) };
}

const lerp = (a, b, k) => a + (b - a) * k;

function resize() {
  const r = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(r.width * dpr);
  canvas.height = Math.round(r.height * dpr);
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function draw() {
  const d = state.data;
  if (!d) return;
  const W = canvas.width, H = canvas.height;
  const { a, b, k } = frameAt(state.t);
  const n = d.horses.length;
  const pos = d.horses.map((h, i) => ({
    i,
    x: lerp(a.x[i], b.x[i], k),
    y: lerp(a.y[i], b.y[i], k),
    s: lerp(a.s[i], b.s[i], k),
  }));

  // camera
  const [ox, oy] = d.course.outer;
  let cx, cy, scale;
  if (state.view === "follow") {
    const lead = pos.reduce((m, p) => (p.s > m.s ? p : m));
    const pack = pos.filter((p) => lead.s - p.s < 60);
    cx = pack.reduce((s, p) => s + p.x, 0) / pack.length;
    cy = pack.reduce((s, p) => s + p.y, 0) / pack.length;
    scale = Math.min(W, H) / 110;
  } else {
    const minx = Math.min(...ox), maxx = Math.max(...ox), miny = Math.min(...oy), maxy = Math.max(...oy);
    cx = (minx + maxx) / 2;
    cy = (miny + maxy) / 2;
    scale = Math.min(W / (maxx - minx), H / (maxy - miny)) * 0.92;
  }
  const X = (x) => W / 2 + (x - cx) * scale;
  const Y = (y) => H / 2 - (y - cy) * scale;

  ctx.fillStyle = cssVar("--infield");
  ctx.fillRect(0, 0, W, H);

  const path = ([xs, ys]) => {
    ctx.beginPath();
    xs.forEach((x, j) => (j ? ctx.lineTo(X(x), Y(ys[j])) : ctx.moveTo(X(x), Y(ys[j]))));
    ctx.closePath();
  };
  path(d.course.outer);
  ctx.fillStyle = cssVar("--turf");
  ctx.fill();
  ctx.strokeStyle = cssVar("--turf-edge");
  ctx.lineWidth = 2;
  ctx.stroke();
  path(d.course.rail);
  ctx.fillStyle = cssVar("--infield");
  ctx.fill();
  ctx.strokeStyle = cssVar("--rail");
  ctx.lineWidth = Math.max(1.5, scale * 0.3);
  ctx.stroke();

  // finish line
  const [fx, fy] = d.course.finish;
  ctx.strokeStyle = "#c62828";
  ctx.lineWidth = Math.max(2, scale * 0.5);
  ctx.beginPath();
  ctx.moveTo(X(fx[0]), Y(fy[0]));
  ctx.lineTo(X(fx[1]), Y(fy[1]));
  ctx.stroke();

  // horses, back markers first so leaders draw on top
  const rad = state.view === "follow" ? Math.max(8, scale * 0.9) : Math.max(5, W / 160);
  pos.slice().sort((p, q) => p.s - q.s).forEach((p) => {
    const h = d.horses[p.i];
    ctx.beginPath();
    ctx.arc(X(p.x), Y(p.y), rad, 0, Math.PI * 2);
    ctx.fillStyle = h.bg;
    ctx.fill();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = "#0008";
    ctx.stroke();
    if (rad >= 7) {
      ctx.fillStyle = h.fg;
      ctx.font = `bold ${Math.round(rad * 1.1)}px system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(String(h.gate), X(p.x), Y(p.y) + 0.5);
    }
  });

  // HUD and standings
  const lead = Math.max(...pos.map((p) => p.s));
  document.getElementById("clock").textContent = `${state.t.toFixed(1)}秒`;
  document.getElementById("remain").textContent =
    lead >= d.course.distance ? "ゴール" : `残り ${Math.ceil(d.course.distance - lead)}m`;
  renderStandings(pos);
  document.getElementById("scrub").value = Math.round((state.t / duration()) * 1000);
}

function renderStandings(pos) {
  const d = state.data;
  const ft = d.replay.finish_time;
  const ranked = pos.slice().sort((p, q) => {
    const fp = ft[p.i] <= state.t, fq = ft[q.i] <= state.t;
    if (fp && fq) return ft[p.i] - ft[q.i];
    if (fp !== fq) return fp ? -1 : 1;
    return q.s - p.s;
  });
  const leader = ranked[0];
  document.getElementById("standings").innerHTML = ranked.map((p, j) => {
    const h = d.horses[p.i];
    const gap = j === 0 ? "" : ` <small>${(leader.s - p.s).toFixed(0)}m</small>`;
    return `<li><span class="chip" style="background:${h.bg};color:${h.fg}">${h.gate}</span>${escapeHtml(h.name)}${gap}</li>`;
  }).join("");
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function renderTable() {
  const d = state.data;
  const maxWin = Math.max(...d.horses.map((h) => h.win), 1e-9);
  const rows = d.horses.slice().sort((a, b) => {
    const x = a[state.sortKey], y = b[state.sortKey];
    if (typeof x === "string") return state.sortDir * x.localeCompare(y, "ja");
    return state.sortDir * ((x ?? Infinity) - (y ?? Infinity));
  });
  document.querySelector("#table tbody").innerHTML = rows.map((h) => `
    <tr>
      <td><span class="chip" style="background:${h.bg};color:${h.fg}">${h.gate}</span></td>
      <td class="left">${escapeHtml(h.name)}</td>
      <td>${styleLabel(h.style)}</td>
      <td><span class="bar" style="width:${(h.win / maxWin) * 60}px"></span>${pct(h.win)}</td>
      <td>${pct(h.place)}</td>
      <td>${h.mean_rank.toFixed(1)}</td>
      <td>${h.odds ? h.odds.toFixed(1) : "—"}</td>
    </tr>`).join("");
}

function tick(now) {
  if (state.playing) {
    if (state.last != null) state.t += ((now - state.last) / 1000) * state.speed;
    if (state.t >= duration()) {
      state.t = duration();
      setPlaying(false);
    }
    draw();
  }
  state.last = now;
  requestAnimationFrame(tick);
}

function setPlaying(on) {
  state.playing = on;
  document.getElementById("play").textContent = on ? "❚❚ 一時停止" : "▶ 再生";
}

document.getElementById("play").addEventListener("click", () => {
  if (state.t >= duration()) state.t = 0;
  setPlaying(!state.playing);
});
document.getElementById("restart").addEventListener("click", () => {
  state.t = 0;
  draw();
});
document.getElementById("speed").addEventListener("change", (e) => (state.speed = Number(e.target.value)));
document.getElementById("view").addEventListener("change", (e) => {
  state.view = e.target.value;
  draw();
});
document.getElementById("scrub").addEventListener("input", (e) => {
  state.t = (Number(e.target.value) / 1000) * duration();
  draw();
});
document.querySelectorAll("#table th").forEach((th) =>
  th.addEventListener("click", () => {
    const k = th.dataset.k;
    state.sortDir = state.sortKey === k ? -state.sortDir : (k === "gate" || k === "mean_rank" || k === "odds" || k === "name" ? 1 : -1);
    state.sortKey = k;
    renderTable();
  })
);
window.addEventListener("resize", () => {
  resize();
  draw();
});

load();
requestAnimationFrame(tick);
