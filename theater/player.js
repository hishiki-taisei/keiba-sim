// <race-theater src="data/kikka2026.json"> — watch a race run on the course.
//
// A self-contained custom element: drop player.js (with engine.js and
// course.js next to it) into any page and point it at a field JSON made by
// tools/build_field.py + tools/calibrate.mjs. Every press of 「もう一回」 runs a
// new race in the browser; 「1000回」 runs a thousand and tallies them.
// Styles are scoped under .rt and can be overridden by the host page.

import { runRace, tallyAsync, courseOf, DT } from "./engine.js";

// JRA frame colours (枠色): background, text
const FRAME = [null, ["#ffffff", "#111"], ["#1a1a1a", "#fff"], ["#d7262e", "#fff"], ["#1f5fbf", "#fff"],
  ["#f2cf1d", "#111"], ["#2f8f3a", "#fff"], ["#f08a1c", "#111"], ["#f3a6c4", "#111"]];

// Post position -> frame, the way JRA splits fields over 8 frames.
export function frameOf(number, runners) {
  if (runners <= 8) return number;
  const base = Math.floor(runners / 8), extra = runners % 8;
  let n = 0;
  for (let f = 1; f <= 8; f++) {
    n += base + (f > 8 - extra ? 1 : 0);
    if (number <= n) return f;
  }
  return 8;
}

// Margin in lengths (1 length = 2.4m) written the way results tables do.
export function marginText(metres) {
  const L = metres / 2.4;
  if (L < 0.08) return "ハナ";
  if (L < 0.2) return "アタマ";
  if (L < 0.35) return "クビ";
  if (L > 10) return "大差";
  const steps = [[0.5, "1/2"], [0.75, "3/4"], [1, "1"], [1.25, "1.1/4"], [1.5, "1.1/2"], [1.75, "1.3/4"],
    [2, "2"], [2.5, "2.1/2"], [3, "3"], [3.5, "3.1/2"], [4, "4"], [5, "5"], [6, "6"], [7, "7"], [8, "8"], [9, "9"], [10, "10"]];
  let best = steps[0];
  for (const st of steps) if (Math.abs(st[0] - L) < Math.abs(best[0] - L)) best = st;
  return best[1];
}

const fmtTime = t => {
  if (!isFinite(t)) return "—";
  const m = Math.floor(t / 60), s = t - 60 * m;
  return m ? `${m}:${s.toFixed(1).padStart(4, "0")}` : s.toFixed(1);
};
const pct = x => (100 * x).toFixed(1);
const GOING_W = { "良": 0, "稍重": 0.4, "重": 0.8, "不良": 1 };   // how much going aptitude counts (engine.js)
const styleWord = s => s < 0.18 ? "逃げ" : s < 0.42 ? "先行" : s < 0.7 ? "差し" : "追込";

const CSS = `
race-theater{display:block;min-width:0;max-width:100%}
/* course view first; controls and tables in a quiet paddock-board neutral */
.rt{--ink:#18211c;--sub:#56625a;--rule:#d3dad3;--line:#e4e9e4;--paper:#eef1ec;--card:#ffffff;--btn:#ffffff;--btn-hover:#e3e9e3;
  --accent:#b3121b;--bar:#18211c;--bar-model:#a3ada6;--sel:#fbeec4;
  font:14px/1.5 "BIZ UDPGothic","Hiragino Sans","Noto Sans JP","Yu Gothic",system-ui,sans-serif;
  color:var(--ink);background:var(--paper);font-variant-numeric:tabular-nums;max-width:1180px;margin:0 auto}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .rt{--ink:#e4ebe6;--sub:#98a59d;--rule:#33413a;--line:#26312b;
  --paper:#111714;--card:#18201c;--btn:#1e2722;--btn-hover:#29342e;--accent:#d8343c;--bar:#e4ebe6;--bar-model:#5f6c65;--sel:#3d3a22;color-scheme:dark}}
:root[data-theme="dark"] .rt{--ink:#e4ebe6;--sub:#98a59d;--rule:#33413a;--line:#26312b;--paper:#111714;--card:#18201c;
  --btn:#1e2722;--btn-hover:#29342e;--accent:#d8343c;--bar:#e4ebe6;--bar-model:#5f6c65;--sel:#3d3a22;color-scheme:dark}
.rt *{box-sizing:border-box}
.rt-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 14px;padding:12px 0 8px}
.rt-head h2{font-size:20px;margin:0;font-weight:700;letter-spacing:.02em}
.rt-head span{color:var(--sub);font-size:13px}
.rt-main{display:grid;grid-template-columns:minmax(0,1fr) 270px;gap:0;border:1px solid var(--rule)}
.rt-stage{position:relative;background:#2f5e27;min-height:300px}
.rt-stage canvas.cv{display:block;width:100%;height:100%}
.rt-mini{position:absolute;right:8px;top:8px;width:170px;height:96px;background:rgba(20,30,18,.55);border:1px solid rgba(255,255,255,.35)}
.rt-clock{position:absolute;left:10px;top:8px;color:#fff;font-size:13px;text-shadow:0 1px 2px #000;line-height:1.35}
.rt-clock b{font-size:22px;font-weight:700;display:block}
.rt-call{padding:7px 10px;border-top:1px solid var(--rule);min-height:36px;background:var(--card);font-size:14px}
.rt-order{border-left:1px solid var(--rule);background:var(--card);overflow:auto;max-height:520px}
.rt-order table{width:100%;border-collapse:collapse;font-size:13px}
.rt-order td{padding:2px 6px;border-bottom:1px solid var(--line);white-space:nowrap}
.rt-order td.g{color:var(--sub);text-align:right;width:52px}
.rt-num{display:inline-block;min-width:22px;padding:0 3px;text-align:center;font-weight:700;font-size:12px;border:1px solid #777;line-height:18px}
.rt-bar{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;padding:8px 0}
.rt-bar label{color:var(--sub);font-size:12px;margin-right:2px}
.rt-bar .grp{display:flex;align-items:center;gap:0}
.rt button{font:inherit;font-size:13px;padding:4px 10px;border:1px solid var(--rule);background:var(--btn);color:var(--ink);cursor:pointer;margin-left:-1px}
.rt button:hover{background:var(--btn-hover)}
.rt button:focus-visible,.rt select:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.rt button.on{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.rt button.go{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:700;padding:5px 16px}
.rt select{font:inherit;font-size:13px;padding:3px 4px;border:1px solid var(--rule);background:var(--btn);color:var(--ink)}
.rt h3{font-size:15px;margin:22px 0 6px}
.rt .note{color:var(--sub);font-size:12px;margin:4px 0}
.rt table.tbl{border-collapse:collapse;width:100%;font-size:13px;background:var(--card)}
.rt table.tbl th{font-weight:400;color:var(--sub);font-size:12px;text-align:right;padding:5px 6px;border-bottom:1px solid var(--rule);white-space:nowrap}
.rt table.tbl th.l,.rt table.tbl td.l{text-align:left}
.rt table.tbl td{padding:4px 6px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
.rt table.tbl tr.top td{font-weight:700}
.rt table.tbl th[data-k]{cursor:pointer;text-decoration:underline dotted}
.rt .meter{display:inline-block;height:8px;background:var(--bar);vertical-align:middle;margin-left:6px}
.rt .meter.m{background:var(--bar-model)}
.rt .wrap{overflow-x:auto}
.rt-strip{position:relative;height:64px;background:#20401b;border-top:1px solid #000}
.rt-strip canvas{display:block;width:100%;height:100%}
.rt-order tr{cursor:pointer}
.rt tr.sel td{background:var(--sel)}
.rt table.tbl td.l.nm{cursor:pointer}
.rt-horse{margin-top:14px;border:1px solid var(--rule);background:var(--card);padding:10px 12px}
.rt-horse h4{margin:0 0 2px;font-size:16px}
.rt-horse .sub{color:var(--sub);font-size:12px}
.rt-horse dl{display:grid;align-content:start;grid-template-columns:7.5em 1fr;gap:3px 12px;margin:10px 0 4px;font-size:13px}
.rt-horse dt{color:var(--sub)}
.rt-horse dd{margin:0}
.rt-horse dd b{font-weight:700}
.rt-horse .cols{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:0 24px}
.rt-how{margin-top:26px;border-top:2px solid var(--ink);padding-top:4px}
.rt-how summary{font-size:15px;font-weight:700;cursor:pointer;padding:6px 0}
.rt-how h4{font-size:14px;margin:16px 0 4px}
.rt-how p,.rt-how li{font-size:13px;line-height:1.75;max-width:46em}
.rt-how ol{padding-left:1.4em;margin:4px 0}
.rt-how table.tbl{max-width:40em}
@media (prefers-reduced-motion:reduce){.rt *{transition:none!important}}
@media (max-width:820px){.rt-main{grid-template-columns:1fr}.rt-order{border-left:0;border-top:1px solid var(--rule);max-height:260px}
  .rt-mini{width:120px;height:68px}.rt{font-size:13px}.rt .meter{display:none}
  .rt-horse .cols{grid-template-columns:1fr}.rt-horse dl{grid-template-columns:6em 1fr;margin:8px 0 0}}
`;

class RaceTheater extends HTMLElement {
  async connectedCallback() {
    if (!document.getElementById("rt-css")) {
      const st = document.createElement("style");
      st.id = "rt-css"; st.textContent = CSS; document.head.appendChild(st);
    }
    this.innerHTML = `<div class="rt"><p class="note">読み込み中…</p></div>`;
    try {
      const field = this.field || await (await fetch(this.getAttribute("src"))).json();
      this.setField(field);
    } catch (e) {
      this.innerHTML = `<div class="rt"><p class="note">レースデータを読み込めませんでした（${e.message}）</p></div>`;
    }
  }

  setField(field) {
    this.f = field;
    this.course = courseOf(field);
    this.opts = { pace: "auto", going: field.going || "良" };
    this.speed = 4;
    this.view = "follow";
    this.sel = null;
    this.seed = Math.floor(Math.random() * 1e9);
    this.render();
    this.newRace();
  }

  render() {
    const f = this.f, c = f.course || {};
    const H = f.horses.length;
    const drawn = f.horses.every(h => h.gate);
    const dir = this.course.direction === "直線" ? "直線" : `${this.course.direction}回り`;
    this.innerHTML = `<div class="rt">
      <div class="rt-head"><h2>${esc(f.title || "")}</h2>
        <span>${esc(this.course.name)}・${dir}・${H}頭</span>
        <span>${drawn ? "枠順確定" : "枠順未定：毎レース枠を抽選"}</span></div>
      <div class="rt-bar">
        <button class="go" data-a="again">もう一回走らせる</button>
        <button data-a="play">一時停止</button>
        <div class="grp"><label>速さ</label>${[1, 2, 4, 8, 16].map(x => `<button data-speed="${x}">×${x}</button>`).join("")}</div>
        <div class="grp"><label>視点</label><button data-view="follow">馬群を追う</button><button data-view="horse" title="馬名か馬をクリックして選ぶ">選んだ馬</button><button data-view="all">コース全体</button></div>
        <div class="grp"><label>ペース</label><select data-o="pace">
          <option value="auto">おまかせ</option><option value="slow">スロー</option><option value="mid">平均</option><option value="fast">ハイ</option></select></div>
        <div class="grp"><label>馬場</label><select data-o="going">${["良", "稍重", "重", "不良"].map(g =>
          `<option${g === this.opts.going ? " selected" : ""}>${g}</option>`).join("")}</select></div>
      </div>
      <div class="rt-main">
        <div>
          <div class="rt-stage"><canvas class="cv"></canvas><canvas class="rt-mini"></canvas><div class="rt-clock"></div></div>
          <div class="rt-strip"><canvas class="strip"></canvas></div>
          <div class="rt-call"></div>
        </div>
        <div class="rt-order"><table></table></div>
      </div>
      <div class="rt-horse" hidden></div>
      <div class="rt-result"></div>
      <h3>何度も走らせる</h3>
      <div class="rt-bar" style="border:0;padding-top:0">
        <button data-a="tally">1000回走らせる</button><span class="note tally-st"></span></div>
      <p class="note">勝率（モデル）は ${esc(f.model?.source || "予想モデル")} の値。この画面の馬は、ペース・馬場「${esc(f.going || "良")}」・おまかせのとき
        1000回走らせた勝率がモデルの勝率とほぼ同じになるように能力を合わせてあります（ずれの平均 ${f.calibration ? pct(f.calibration.mean_gap) : "—"} ポイント）。
        ペースや馬場を変えると、脚質や道悪の得意不得意で勝率が動きます。</p>
      <div class="wrap"><table class="tbl tally"></table></div>
      ${howItWorks(f, this.course)}
    </div>`;
    this.cv = this.querySelector(".cv");
    this.mini = this.querySelector(".rt-mini");
    this.strip = this.querySelector(".strip");
    // pick a horse: in the running order, the tables, or on the course
    this.addEventListener("click", e => {
      const row = e.target.closest("[data-h]");
      if (row && this.contains(row)) this.select(+row.dataset.h);
    });
    this.cv.addEventListener("click", e => {
      const r = this.cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
      let best = -1, bd = 24;
      (this._pos || []).forEach(([px, py], i) => { const d = Math.hypot(px - x, py - y); if (d < bd) { bd = d; best = i; } });
      if (best >= 0) this.select(best);
    });
    this.querySelectorAll("[data-speed]").forEach(b => b.onclick = () => { this.speed = +b.dataset.speed; this.syncButtons(); });
    this.querySelectorAll("[data-view]").forEach(b => b.onclick = () => {
      if (b.dataset.view === "horse" && this.sel == null) this.select(this.race.order[0]);
      this.view = b.dataset.view; this.syncButtons();
    });
    this.querySelector('[data-a="again"]').onclick = () => this.newRace();
    this.querySelector('[data-a="play"]').onclick = () => { this.paused = !this.paused; this.syncButtons(); };
    this.querySelector('[data-a="tally"]').onclick = () => this.runTally();
    this.querySelectorAll("[data-o]").forEach(s => s.onchange = () => { this.opts[s.dataset.o] = s.value; this.newRace(); this.runTally(); });
    this.syncButtons();
    this.renderTally(null);
    this.runTally();
    this.ro?.disconnect();
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(this.querySelector(".rt-stage"));
    this.resize();
  }

  syncButtons() {
    this.querySelectorAll("[data-speed]").forEach(b => b.classList.toggle("on", +b.dataset.speed === this.speed));
    this.querySelectorAll("[data-view]").forEach(b => b.classList.toggle("on", b.dataset.view === this.view));
    const p = this.querySelector('[data-a="play"]');
    if (p) p.textContent = this.paused ? "再生" : (this.done ? "最初から" : "一時停止");
  }

  resize() {
    const st = this.querySelector(".rt-stage");
    const w = st.clientWidth, h = Math.max(300, Math.min(520, Math.round(w * 0.56)));
    st.style.height = h + "px";
    const dpr = window.devicePixelRatio || 1;
    for (const c of [this.cv, this.mini, this.strip]) {
      const r = c === this.cv ? [w, h] : [c.clientWidth, c.clientHeight];
      c.width = r[0] * dpr; c.height = r[1] * dpr; c._w = r[0]; c._h = r[1];
    }
    this.draw();
  }

  newRace() {
    this.seed = (this.seed * 1103515245 + 12345) >>> 0;
    this.race = runRace(this.f, { ...this.opts, seed: this.seed, trace: true });
    const H = this.f.horses.length;
    this.frames = this.race.gates.map(g => frameOf(g, H));
    this.t = 0; this.done = false; this.paused = false; this.calls = [];
    this.cam = null;
    this.querySelector(".rt-result").innerHTML = "";
    this.syncButtons();
    this.renderHorse();
    if (!this.loop) {
      let last = performance.now();
      const tick = now => {
        const dt = Math.min(0.1, (now - last) / 1000); last = now;
        if (!this.paused && !this.done) this.advance(dt * this.speed);
        this.draw();
        this.loop = requestAnimationFrame(tick);
      };
      this.loop = requestAnimationFrame(tick);
    }
  }

  disconnectedCallback() { cancelAnimationFrame(this.loop); this.loop = null; this.ro?.disconnect(); }

  advance(dt) {
    const T = this.race.trace, n = T.s.length;
    this.t = Math.min(this.t + dt, n * DT);
    if (this.t >= n * DT) { this.done = true; this.showResult(); this.syncButtons(); }
  }

  // positions at the current playback time, interpolated between steps
  state() {
    const T = this.race.trace, n = T.s.length, H = this.f.horses.length;
    const x = this.t / DT - 1, k = Math.max(0, Math.min(n - 2, Math.floor(x))), a = Math.max(0, Math.min(1, x - k));
    const s = new Float64Array(H), y = new Float64Array(H), v = new Float64Array(H);
    for (let i = 0; i < H; i++) {
      s[i] = T.s[k][i] + (T.s[k + 1][i] - T.s[k][i]) * a;
      y[i] = T.y[k][i] + (T.y[k + 1][i] - T.y[k][i]) * a;
      v[i] = T.v[k][i];
    }
    return { s, y, v, k };
  }

  toWorld(s, y) {
    const [x, yy] = this.course.xy(s, y);
    return [this.course.direction === "左" ? -x : x, yy];
  }

  draw() {
    if (!this.race || !this.cv?._w) return;
    const st = this.state();
    const H = this.f.horses.length, D = this.course.distance;
    const order = Array.from({ length: H }, (_, i) => i).sort((a, b) => st.s[b] - st.s[a]);
    if (this.done) order.splice(0, H, ...this.race.order);
    this.drawStage(this.cv, st, order, this.view);
    this.drawStrip(st, order);
    this.drawStage(this.mini, st, order, "all", true);
    const lead = st.s[order[0]];
    const clock = this.querySelector(".rt-clock");
    const winT = this.race.time[this.race.order[0]];
    clock.innerHTML = `<b>${fmtTime(this.t >= winT ? winT : this.t)}</b>` +
      (lead < D ? `残り ${Math.max(0, Math.ceil((D - lead) / 10) * 10)}m` : "ゴール");
    this.updateCalls(st, order);
    this.drawOrder(st, order);
  }

  drawStage(cv, st, order, view, mini = false) {
    const follow = view !== "all";
    const ctx = cv.getContext("2d"), dpr = window.devicePixelRatio || 1, W = cv._w, Hh = cv._h;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const c = this.course, H = this.f.horses.length;
    // camera
    let cx, cy, scale;
    if (follow) {
      const pts = order.map(i => this.toWorld(st.s[i], st.y[i]));
      const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
      const minx = Math.min(...xs), maxx = Math.max(...xs), miny = Math.min(...ys), maxy = Math.max(...ys);
      let want = { x: (minx + maxx) / 2, y: (miny + maxy) / 2,
        scale: Math.max(2.2, Math.min(9, Math.min(W * 0.8 / (maxx - minx + 30), Hh * 0.75 / (maxy - miny + 24)))) };
      if (view === "horse" && this.sel != null) {
        const [hx, hy] = this.toWorld(st.s[this.sel], st.y[this.sel]);
        want = { x: hx, y: hy, scale: Math.min(9, Math.max(5, W / 90)) };
      }
      // ease toward the target, by wall-clock time so slow frames do not lag
      const now = performance.now(), dt = this.camT ? Math.min(0.5, (now - this.camT) / 1000) : 1;
      this.camT = now;
      if (!this.cam || Math.hypot(want.x - this.cam.x, want.y - this.cam.y) > 400) this.cam = want;
      const k = 1 - Math.exp(-6 * dt), ks = 1 - Math.exp(-1.5 * dt);
      // the centre follows the field directly at high playback speeds
      const kc = this.speed >= 4 ? 1 : k;
      this.cam = { x: this.cam.x + (want.x - this.cam.x) * kc, y: this.cam.y + (want.y - this.cam.y) * kc,
        scale: this.cam.scale + (want.scale - this.cam.scale) * ks };
      ({ x: cx, y: cy, scale } = this.cam);
    } else {
      const ext = c.direction === "直線" ? [c.distance + 40, c.width + 40] : [c.straight + 2 * c.radius + 2 * c.width + 40, 2 * c.radius + 2 * c.width + 40];
      scale = Math.min(W / ext[0], Hh / ext[1]);
      cx = 0; cy = c.direction === "直線" ? -c.width / 2 : 0;
    }
    const P = (wx, wy) => [W / 2 + (wx - cx) * scale, Hh / 2 - (wy - cy) * scale];
    ctx.clearRect(0, 0, W, Hh);
    if (!mini) { ctx.fillStyle = "#2f5e27"; ctx.fillRect(0, 0, W, Hh); }

    // track surface between the inner rail and the outside rail
    const surf = (c.surface === "ダ") ? "#a8865c" : "#5c9a46";
    const band = (y0, y1, fill) => {
      ctx.beginPath();
      const step = mini ? 30 : 8;
      const us = steps(c.lap, step);
      us.forEach((u, k) => { const [x, y] = P(...this.toWorld(u, y0)); k ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      for (const u of us.reverse()) { const [x, y] = P(...this.toWorld(u, y1)); ctx.lineTo(x, y); }
      ctx.closePath(); ctx.fillStyle = fill; ctx.fill();
    };
    if (c.direction === "直線") {
      const a = P(...this.toWorld(0, 0)), b = P(...this.toWorld(c.distance, c.width));
      ctx.fillStyle = surf; ctx.fillRect(Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1]));
    } else {
      band(0, c.width, surf);
      if (!mini) { // mowing stripes, every 10m along the course
        ctx.globalAlpha = 0.07;
        for (let u = 0; u < c.lap; u += 20) {
          ctx.beginPath();
          for (const [uu, yy] of [[u, 0], [u, c.width], [u + 10, c.width], [u + 10, 0]]) { const [x, y] = P(...this.toWorld(uu, yy)); ctx.lineTo(x, y); }
          ctx.fillStyle = "#fff"; ctx.fill();
        }
        ctx.globalAlpha = 1;
      }
    }
    const line = (y, color, w) => {
      ctx.beginPath();
      const L = c.direction === "直線" ? c.distance : c.lap, step = mini ? 30 : 6;
      steps(L, step).forEach((u, k) => { const [x, yy] = P(...this.toWorld(u, y)); k ? ctx.lineTo(x, yy) : ctx.moveTo(x, yy); });
      ctx.strokeStyle = color; ctx.lineWidth = w; ctx.stroke();
    };
    line(0, "#f4f4f0", mini ? 1 : 2.5);
    line(c.width, "#f4f4f0", mini ? 1 : 2);

    // finish line and furlong posts
    const D = c.distance;
    const fin = [P(...this.toWorld(D, -2)), P(...this.toWorld(D, c.width + 2))];
    ctx.beginPath(); ctx.moveTo(...fin[0]); ctx.lineTo(...fin[1]);
    ctx.strokeStyle = "#d81e1e"; ctx.lineWidth = mini ? 1.5 : 3; ctx.stroke();
    if (!mini) {
      ctx.font = "11px sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      for (let r = 200; r < D; r += 200) {
        if (r > 1200 && r % 400) continue;
        const [x, y] = P(...this.toWorld(D - r, -4));
        if (x < -20 || x > W + 20 || y < -20 || y > Hh + 20) continue;
        const [x0, y0] = P(...this.toWorld(D - r, 0));
        ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x, y); ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5; ctx.stroke();
        if (scale > 1.5) { ctx.fillStyle = "rgba(255,255,255,.85)"; ctx.fillText(String(r), ...P(...this.toWorld(D - r, -9))); }
      }
    }

    // horses, back to front
    if (!mini) this._pos = new Array(H);
    for (let r = H - 1; r >= 0; r--) {
      const i = order[r];
      const [x, y] = P(...this.toWorld(st.s[i], st.y[i] + 0.6));
      const [fb, ft] = FRAME[this.frames[i]];
      if (mini) {
        ctx.beginPath(); ctx.arc(x, y, i === this.sel ? 3.4 : 2.2, 0, 7); ctx.fillStyle = fb; ctx.fill();
        ctx.lineWidth = i === this.sel ? 1.6 : 0.6; ctx.strokeStyle = i === this.sel ? "#ffd400" : "#000"; ctx.stroke(); continue;
      }
      this._pos[i] = [x, y];
      if (i === this.sel) {
        ctx.beginPath(); ctx.arc(x, y, Math.max(9, 1.9 * scale), 0, 7);
        ctx.strokeStyle = "#ffd400"; ctx.lineWidth = 2.5; ctx.stroke();
      }
      const [ax, ay] = this.toWorld(st.s[i] + 1, st.y[i] + 0.6);
      const [bx, by] = this.toWorld(st.s[i] - 1, st.y[i] + 0.6);
      const ang = Math.atan2(-(ay - by), ax - bx);
      const len = Math.max(7, 2.4 * scale), wid = Math.max(4, 0.95 * scale);
      ctx.save(); ctx.translate(x, y); ctx.rotate(ang);
      ctx.beginPath(); ctx.ellipse(0, 0, len / 2, wid / 2, 0, 0, 7);
      ctx.fillStyle = "#4a3324"; ctx.fill();                       // the horse
      ctx.beginPath(); ctx.ellipse(len * 0.05, 0, len * 0.2, wid * 0.42, 0, 0, 7);
      ctx.fillStyle = fb; ctx.fill(); ctx.lineWidth = 1; ctx.strokeStyle = "#000"; ctx.stroke(); // saddle cloth
      ctx.restore();
      if (scale >= 3) {
        const label = String(this.race.gates[i]);
        ctx.font = "bold 11px sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
        const tx = x, ty = y - wid / 2 - 9;
        ctx.fillStyle = fb; ctx.fillRect(tx - 8, ty - 7, 16, 14);
        ctx.strokeStyle = "#000"; ctx.lineWidth = 0.8; ctx.strokeRect(tx - 8, ty - 7, 16, 14);
        ctx.fillStyle = ft; ctx.fillText(label, tx, ty + 0.5);
      }
    }
  }

  // the broadcast-style line of the field: distance behind the leader across,
  // inside rail at the top, outside at the bottom
  drawStrip(st, order) {
    const cv = this.strip;
    if (!cv?._w) return;
    const ctx = cv.getContext("2d"), dpr = window.devicePixelRatio || 1, W = cv._w, Hh = cv._h;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, Hh);
    const lead = st.s[order[0]], back = lead - st.s[order[order.length - 1]];
    const L = 2.4, span = Math.max(12, Math.ceil(back / L / 5) * 5 + 1);   // lengths shown
    const x0 = 34, x1 = W - 22, k = (x1 - x0) / span;
    const X = i => x1 - (lead - st.s[i]) / L * k;
    const ys = order.map(i => st.y[i]), ymax = Math.max(6, ...ys);
    const Y = i => 10 + (Hh - 30) * Math.min(1, st.y[i] / ymax);
    ctx.font = "10px sans-serif"; ctx.textBaseline = "middle";
    ctx.fillStyle = "rgba(255,255,255,.55)"; ctx.textAlign = "left";
    ctx.fillText("内", 6, 10); ctx.fillText("外", 6, Hh - 20);
    for (let l = 5; l < span; l += 5) {
      const x = x1 - l * k;
      ctx.fillStyle = "rgba(255,255,255,.14)"; ctx.fillRect(Math.round(x), 0, 1, Hh);
      ctx.fillStyle = "rgba(255,255,255,.5)"; ctx.textAlign = "center"; ctx.fillText(`${l}馬身`, x, Hh - 5);
      ctx.fillStyle = "rgba(255,255,255,.14)";
    }
    for (let r = order.length - 1; r >= 0; r--) {
      const i = order[r], [fb, ft] = FRAME[this.frames[i]], x = X(i), y = Y(i);
      ctx.fillStyle = fb; ctx.fillRect(x - 8, y - 7, 16, 14);
      ctx.lineWidth = i === this.sel ? 2 : 0.8; ctx.strokeStyle = i === this.sel ? "#ffd400" : "#000";
      ctx.strokeRect(x - 8, y - 7, 16, 14);
      ctx.fillStyle = ft; ctx.textAlign = "center"; ctx.font = "bold 10px sans-serif";
      ctx.fillText(String(this.race.gates[i]), x, y + 0.5);
      ctx.font = "10px sans-serif";
    }
  }

  select(i) {
    this.sel = this.sel === i ? null : i;
    if (this.sel == null && this.view === "horse") this.view = "follow";
    this._orderKey = null;
    this.syncButtons();
    this.renderHorse();
    this.renderTally(this.lastTally);
    if (this.done) this.showResult();
    this.draw();
  }

  // what the horse's numbers mean for how it runs, and how it ran this time
  renderHorse() {
    const box = this.querySelector(".rt-horse");
    if (this.sel == null) { box.hidden = true; return; }
    const i = this.sel, f = this.f, h = f.horses[i], H = f.horses.length, D = this.course.distance;
    const longish = Math.min(1, D / 3000), style = h.style ?? 0.5, move = h.move ?? 0, stam = h.stamina ?? 0;
    const behind = style * 1.5 * (H - 1) / 2.4;
    const spurt = Math.max(380, Math.min(Math.min(850, 0.6 * D), 540 + longish * (120 * style + 90 * move + 60 * stam)));
    const moveAt = Math.min(900, 0.45 * D) + 250 * longish * move;
    const [fb, ft] = FRAME[this.frames[i]];
    const r = this.race, pos = r.order.indexOf(i);
    const lastE = r.trace ? r.trace.e[r.trace.e.length - 1][i] : null;
    const word = (x, pos, neg) => x == null ? "データなし" : x > 0.3 ? `${pos}（かなり）` : x > 0.1 ? pos : x < -0.3 ? `${neg}（かなり）` : x < -0.1 ? neg : "ふつう";
    const recent = (h.recent || []).map(x => `<tr><td class="l">${esc(x.date)}</td><td class="l">${esc(x.race)}</td><td>${x.distance ?? ""}</td>
      <td>${esc(x.going || "")}</td><td>${x.finish ?? "—"}/${x.field ?? ""}</td><td>${esc(x.passing || "")}</td><td>${x.last3f ?? ""}</td></tr>`).join("");
    box.hidden = false;
    box.innerHTML = `<h4><span class="rt-num" style="background:${fb};color:${ft}">${r.gates[i]}</span> ${esc(h.name)}</h4>
      <div class="sub">${esc(h.jockey || "")}　勝率（モデル）${pct(h.p_model)}%　もう一度クリックで選択を外します</div>
      <div class="cols"><dl>
        <dt>脚質</dt><dd><b>${styleWord(style)}</b>（${style.toFixed(2)}）。道中は先頭から約${behind.toFixed(1)}馬身後ろにつけようとします。</dd>
        <dt>仕掛け</dt><dd>残り約${Math.round(spurt / 10) * 10}mからスパート。${move > 0.2 ? `残り約${Math.round(moveAt / 10) * 10}mから外を回って位置を上げます（まくり ${move.toFixed(2)}）。` : move < -0.2 ? "直線まで動かずにじっとしています。" : ""}</dd>
        <dt>末脚</dt><dd>${h.kick == null ? "データなし" : `上がり3Fがそのレースの中央値より平均${Math.abs(h.kick).toFixed(1)}秒${h.kick >= 0 ? "速い" : "遅い"}。スパート時の速さ ${signed(0.22 * Math.max(-1.2, Math.min(1.5, h.kick)), 2)} m/s`}</dd>
        <dt>長距離</dt><dd>${word(h.stamina, "得意", "苦手")}。スタミナの量が${signed(3 * stam)}%、仕掛けが${stam >= 0 ? "早め" : "遅め"}になります。</dd>
        <dt>道悪</dt><dd>${word(h.going, "得意", "苦手")}${this.opts.going === "良" ? "（良馬場では効きません）" : `。${this.opts.going}なので速さ ${signed(0.12 * (GOING_W[this.opts.going] ?? 0) * (h.going ?? 0), 2)} m/s`}</dd>
        <dt>ムラ</dt><dd>レースごとの出来のぶれ ${(h.form_sd ?? 1).toFixed(2)}倍（1が平均）</dd>
        <dt>能力の補正</dt><dd>${signed(h.ability ?? 0, 2)} m/s。1000回走らせた勝率がモデルの勝率に合うように自動で決めた値です。</dd>
      </dl><dl>
        <dt>このレース</dt><dd>${this.done ? `<b>${pos + 1}着</b>（${fmtTime(r.time[i])}）` : "走行中"}</dd>
        <dt>通過順</dt><dd>${this.done ? r.corners.map(c => c[i]).join("-") : "—"}</dd>
        <dt>上がり3F</dt><dd>${this.done ? r.last3f[i].toFixed(1) + "秒" : "—"}</dd>
        <dt>残りスタミナ</dt><dd>${this.done && lastE != null ? Math.round(100 * lastE) + "%（ゴール後）" : "—"}</dd>
        <dt>実際の結果</dt><dd>${h.actual?.finish ? `${h.actual.finish}着、通過 ${esc(h.actual.passing || "—")}、上がり ${h.actual.last3f ?? "—"}` : "まだ走っていません"}</dd>
      </dl></div>
      ${recent ? `<div class="wrap"><table class="tbl"><tr><th class="l">近走</th><th class="l">レース</th><th>距離</th><th>馬場</th><th>着/頭</th><th>通過</th><th>上がり</th></tr>${recent}</table></div>
      <p class="note">脚質・末脚・長距離・道悪・ムラは、この近走（最大8走、新しいほど重く）から計算しています。</p>` : ""}`;
  }

  drawOrder(st, order) {
    const H = this.f.horses.length, lead = st.s[order[0]];
    const rows = order.map((i, r) => {
      const h = this.f.horses[i], [fb, ft] = FRAME[this.frames[i]];
      let gap = r === 0 ? "" : `${((lead - st.s[i]) / 2.4).toFixed(1)}馬身`;
      if (this.done) gap = r === 0 ? fmtTime(this.race.time[i]) : marginText((this.race.time[i] - this.race.time[order[r - 1]]) * 16.5);
      return `<tr data-h="${i}"${i === this.sel ? ' class="sel"' : ""}><td style="width:22px;color:var(--sub)">${r + 1}</td><td><span class="rt-num" style="background:${fb};color:${ft}">${this.race.gates[i]}</span>
        ${esc(h.name)}</td><td class="g">${gap}</td></tr>`;
    }).join("");
    const key = rows;
    if (key !== this._orderKey) { this.querySelector(".rt-order table").innerHTML = rows; this._orderKey = key; }
    void H;
  }

  updateCalls(st, order) {
    const D = this.course.distance, lead = st.s[order[0]], name = i => this.f.horses[i].name;
    const say = (key, text) => {
      if (this.calls.includes(key)) return;
      this.calls.push(key);
      this.querySelector(".rt-call").textContent = text;
    };
    const split = this.race.splits[1000];
    if (lead < 100) say("start", `スタート。${esc(this.course.name)}、${this.f.horses.length}頭。`);
    if (D > 1400 && lead >= 1000 && split != null) {
      const typ = this.f.pace ? 1000 / this.f.pace.early : 61.5;   // the course's usual 1000m split
      const pace = split < typ - 0.8 ? "速いペース" : split > typ + 0.8 ? "ゆったりしたペース" : "平均的なペース";
      say("1000", `1000m通過は${split.toFixed(1)}秒、${pace}。先頭は${name(order[0])}、2番手に${name(order[1])}。`);
    }
    if (lead >= D - 800 && D > 1200) say("800", `残り800m。先頭は${name(order[0])}。後ろでは${name(order[Math.floor(this.f.horses.length * 0.7)])}が外から動く。`);
    if (lead >= D - 400) say("400", `直線。${name(order[0])}、${name(order[1])}、${name(order[2])}の争い。`);
    if (lead >= D - 150) say("150", `残り150m、${name(order[0])}が先頭！`);
    if (this.done) {
      const o = this.race.order, t = this.race.time;
      say("end", `1着は${name(o[0])}。タイム${fmtTime(t[o[0]])}、上がり${this.race.last3f[o[0]].toFixed(1)}。2着${name(o[1])}、3着${name(o[2])}。`);
    }
  }

  showResult() {
    const r = this.race, f = this.f, H = f.horses.length;
    const rows = r.order.map((i, pos) => {
      const h = f.horses[i], [fb, ft] = FRAME[this.frames[i]];
      const margin = pos === 0 ? "" : marginText((r.time[i] - r.time[r.order[pos - 1]]) * 16.5);
      const pass = r.corners.map(c => c[i]).join("-");
      return `<tr data-h="${i}" class="${pos < 3 ? "top" : ""}${i === this.sel ? " sel" : ""}"><td>${pos + 1}</td><td><span class="rt-num" style="background:${fb};color:${ft}">${r.gates[i]}</span></td>
        <td class="l nm">${esc(h.name)}</td><td class="l">${esc(h.jockey || "")}</td><td>${fmtTime(r.time[i])}</td><td>${margin}</td>
        <td>${pass}</td><td>${r.last3f[i].toFixed(1)}</td><td>${pct(h.p_model)}%</td>${h.actual != null ? `<td>${h.actual.finish ?? h.actual}着</td>` : ""}</tr>`;
    }).join("");
    const hasActual = f.horses.some(h => h.actual != null);
    this.querySelector(".rt-result").innerHTML = `<h3>このレースの結果</h3><div class="wrap"><table class="tbl">
      <tr><th>着</th><th>馬番</th><th class="l">馬名</th><th class="l">騎手</th><th>タイム</th><th>着差</th><th>通過</th><th>上がり</th><th>勝率(モデル)</th>${hasActual ? "<th>実際</th>" : ""}</tr>
      ${rows}</table></div><p class="note">通過順は${r.cornerNames.map(n => n ? n + "角" : "中間").join("・")}。ペースは平均より${paceText(r.pace / (f.speed_scale ?? 1) / goingSpeedOf(r))}。</p>`;
    void H;
    if (this.sel != null) this.renderHorse();
  }

  async runTally() {
    const btn = this.querySelector('[data-a="tally"]'), st = this.querySelector(".tally-st");
    const id = this.tallyId = (this.tallyId || 0) + 1;
    btn.disabled = true;
    const n = 1000;
    const opts = { ...this.opts, seed: Math.floor(Math.random() * 1e9) };
    let res;
    try {
      res = await new Promise((ok, fail) => {
        const w = new Worker(new URL("./tally-worker.js", import.meta.url), { type: "module" });
        w.onmessage = ({ data }) => {
          if (id !== this.tallyId) { w.terminate(); return; }
          if (data.progress) st.textContent = `${data.progress} / ${n} レース`;
          if (data.done) { ok(data.done); w.terminate(); }
        };
        w.onerror = e => { w.terminate(); fail(e); };
        w.postMessage({ field: this.f, n, opts, chunk: 50 });
      });
    } catch {
      res = await tallyAsync(this.f, n, opts, k => { st.textContent = `${k} / ${n} レース`; });
    }
    if (id !== this.tallyId) return;
    st.textContent = `${n}レースの集計（ペース：${this.querySelector('[data-o="pace"]').selectedOptions[0].text}、馬場：${this.opts.going}）`;
    btn.disabled = false;
    this.renderTally(res);
  }

  renderTally(res) {
    this.lastTally = res;
    const f = this.f, H = f.horses.length;
    const rows = f.horses.map((h, i) => ({ i, h, model: h.p_model, win: res ? res.win[i] : null, place: res ? res.place[i] : null,
      c4: res ? res.lastCorner[i] : null, rank: res ? res.meanRank[i] : null }));
    const key = this.sortKey || "model";
    rows.sort((a, b) => key === "c4" || key === "rank" ? (a[key] ?? 99) - (b[key] ?? 99) : (b[key] ?? -1) - (a[key] ?? -1));
    const maxp = Math.max(...rows.map(r => Math.max(r.model, r.win || 0)));
    const bar = (p, cls = "") => p == null ? "" : `<span class="meter ${cls}" style="width:${Math.round(60 * p / maxp)}px"></span>`;
    const th = (k, label) => `<th data-k="${k}">${label}</th>`;
    this.querySelector(".tally").innerHTML = `<tr><th class="l">馬名</th><th class="l">脚質</th>${th("model", "勝率(モデル)")}${th("win", "勝率(1000回)")}
      ${th("place", "3着内")}${th("rank", "平均着順")}${th("c4", "4角の位置")}<th>上がり差</th><th>長距離</th><th>道悪</th></tr>` +
      rows.map(r => `<tr data-h="${r.i}"${r.i === this.sel ? ' class="sel"' : ""}><td class="l nm">${esc(r.h.name)}</td><td class="l">${styleWord(r.h.style ?? 0.5)}${(r.h.move ?? 0) > 0.4 ? "・まくり" : ""}</td>
        <td>${pct(r.model)}%${bar(r.model, "m")}</td><td>${r.win == null ? "—" : pct(r.win) + "%"}${bar(r.win)}</td>
        <td>${r.place == null ? "—" : pct(r.place) + "%"}</td><td>${r.rank == null ? "—" : r.rank.toFixed(1)}</td>
        <td>${r.c4 == null ? "—" : r.c4.toFixed(1) + "番手"}</td>
        <td>${signed(r.h.kick)}秒</td><td>${mark(r.h.stamina)}</td><td>${mark(r.h.going)}</td></tr>`).join("");
    this.querySelectorAll(".tally th[data-k]").forEach(t => t.onclick = () => { this.sortKey = t.dataset.k; this.renderTally(res); });
    void H;
  }
}

// Checked against 120 past races from 2025 on (tools/validate.mjs): rank
// correlation, within each race, between the simulation and what happened.
const VALIDATION = { races: 120, first: 0.40, firstStyle: 0.51, last: 0.42, last3f: 0.34, finish: 0.49, finishOdds: 0.51,
  spread: 3.8, spreadReal: 4.0, margin: 0.30, marginReal: 0.24 };

function howItWorks(f, course) {
  const V = VALIDATION, n2 = x => x.toFixed(2);
  const paceSrc = f.pace_races ? `同じコース・距離で行われた過去${f.pace_races}レース（良馬場）` : "同じコース・距離の過去レース（なければ距離からの目安）";
  return `<details class="rt-how"><summary>このシミュレーションのしくみ</summary>
  <p>サイコロを振って着順を決めているのではありません。${f.horses.length}頭それぞれについて、0.25秒ごとに「どれだけの速さで、コースのどこを走るか」を決めて動かし、その結果として着順が出ます。画面の馬は、その計算の通りに動いています。</p>
  <h4>1. コース</h4>
  <p>${esc(course.name)}は、周長・ゴール前の直線の長さ・坂の位置をJRAの公表値をもとに作っています。各馬は内ラチから何m外にいるかも持っていて、コーナーを外で回ればそのぶん長い距離を走ります。上り坂ではスタミナを多く使い、速度も落ちます。</p>
  <h4>2. ペース</h4>
  <p>${paceSrc}のラップタイムから、序盤・中盤・残り1000m・残り600mの標準的な速さを取り出して基準にしています。毎レース、その基準を1%ほど速くしたり遅くしたりします（上の「ペース」で固定もできます）。</p>
  <h4>3. 馬ごとの数字</h4>
  <p>各馬の近走（最大8走、新しいレースほど重く）から次の数字を計算しています。馬名をクリックすると、その馬の数字と近走が見られます。</p>
  <div class="wrap"><table class="tbl">
    <tr><th class="l">数字</th><th class="l">何から計算するか</th><th class="l">レースでどう効くか</th></tr>
    <tr><td class="l">脚質</td><td class="l">最初のコーナーの位置（前から何割目か）</td><td class="l">道中、先頭から何馬身後ろにつけたいか</td></tr>
    <tr><td class="l">まくり</td><td class="l">最初から最後のコーナーまでに上げた位置</td><td class="l">直線の前から外を回って押し上げる</td></tr>
    <tr><td class="l">末脚</td><td class="l">上がり3Fがそのレースの中央値より何秒速いか（同じ芝・ダートのレースだけ）</td><td class="l">スパート時の最高速</td></tr>
    <tr><td class="l">長距離</td><td class="l">2200m以上での着順と、それより短い距離での着順の差</td><td class="l">スタミナの量と仕掛けの早さ</td></tr>
    <tr><td class="l">道悪</td><td class="l">稍重〜不良での着順と、良での着順の差</td><td class="l">馬場が悪いときだけ速さに足し引き</td></tr>
    <tr><td class="l">ムラ</td><td class="l">近走の着順のばらつき</td><td class="l">その日の出来の振れ幅</td></tr>
  </table></div>
  <h4>4. 道中の動き</h4>
  <ol>
    <li>各馬は脚質で決まる位置（逃げ馬は先頭、追込馬は最後方）を保とうとして、前に行きすぎれば下げ、遅れれば押し上げます。スタート直後は内ラチに向かって寄っていきます。</li>
    <li>スタミナは速さの3乗に比例して減ります。ほかの馬のすぐ後ろにつけると1割節約できます。</li>
    <li>すぐ前の馬が遅いと詰まり、外か内に空いている所を探して持ち出します。持ち出せなければ前の馬の速さで我慢します。</li>
    <li>仕掛ける地点は脚質・まくり・長距離の数字で決まり（後ろの馬、まくる馬ほど早め）、そこから最高速＋末脚で追います。スタミナが2割を切るとバテて速度が落ちます。</li>
    <li>直線で大きく離された馬は、無理に追わなくなります。</li>
  </ol>
  <h4>5. 毎回変わるもの</h4>
  <p>その日の出来（ムラの大きい馬ほど大きく振れる）、位置取りの気分、仕掛けのタイミング、全体のペース、そして枠順が決まっていないときは枠。だから同じメンバーでも毎回結果が違います。</p>
  <h4>6. 予想モデルとのつなぎ方</h4>
  <p>上の数字だけだと強さの差が入らないので、各馬に「能力の補正」（最高速への足し引き）を持たせています。これは、何千回も走らせた勝率が予想モデルの勝率と同じになるまで自動で調整した値です。全体の速さも、このコースの過去の勝ちタイムの中央値に合うように合わせています。なので、何度も走らせたときの勝率はモデルとほぼ同じで、違いが出るのはペースや馬場を変えたときと、1回1回のレース展開です。</p>
  <h4>7. 実際のレースと比べた結果</h4>
  <p>2025年以降の過去${V.races}レース（芝・ダート、8頭以上）を同じ方法で用意し、500回ずつ走らせて、実際の結果とどれくらい順番が合うかを調べました（順位相関。1なら完全一致、0なら無関係）。</p>
  <div class="wrap"><table class="tbl">
    <tr><th class="l">比べたもの</th><th>シミュレーション</th><th class="l">比較の目安</th></tr>
    <tr><td class="l">最初のコーナーの位置</td><td>${n2(V.first)}</td><td class="l">脚質の数字だけで並べると ${n2(V.firstStyle)}</td></tr>
    <tr><td class="l">4コーナーの位置</td><td>${n2(V.last)}</td><td class="l"></td></tr>
    <tr><td class="l">上がり3F</td><td>${n2(V.last3f)}</td><td class="l"></td></tr>
    <tr><td class="l">着順</td><td>${n2(V.finish)}</td><td class="l">単勝オッズの順だと ${n2(V.finishOdds)}</td></tr>
    <tr><td class="l">1着から最下位までの差</td><td>${V.spread.toFixed(1)}秒</td><td class="l">実際は ${V.spreadReal.toFixed(1)}秒</td></tr>
    <tr><td class="l">1着と2着の差</td><td>${V.margin.toFixed(2)}秒</td><td class="l">実際は ${V.marginReal.toFixed(2)}秒</td></tr>
  </table></div>
  <p>着順の当たり方はオッズとほぼ同じです。勝率を予想に合わせているので、走らせることで予想が良くなるわけではありません。どの馬が前に行き、どこで動き、どんな展開なら誰に向くかを目で見るための道具です。序盤の位置は、脚質の数字そのものより少し外れます（枠の内外の影響がまだ実際より強く出ます）。</p>
  <h4>入っていないもの</h4>
  <p>出遅れや落馬、斜行、騎手の作戦の変更、馬体重や調教の状態、当日の内と外の馬場の差は入っていません。</p>
  </details>`;
}

function paceText(p) {
  const d = (p - 1) * 100;
  return Math.abs(d) < 0.3 ? "ほぼ平均" : d > 0 ? `${d.toFixed(1)}%速い` : `${(-d).toFixed(1)}%遅い`;
}
function goingSpeedOf(r) { return r.goingSpeed ?? 1; }
function steps(L, step) {   // 0, step, 2*step, ... and exactly L, so closed shapes meet
  const out = [];
  for (let u = 0; u < L; u += step) out.push(u);
  out.push(L);
  return out;
}
function esc(s) { return String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
function signed(x, d = 1) { return x == null ? "—" : Math.abs(x) < 0.5 * 10 ** -d ? "±0" : (x > 0 ? "+" : "−") + Math.abs(x).toFixed(d); }
function mark(x) { return x == null ? "—" : x > 0.3 ? "◎" : x > 0.1 ? "○" : x < -0.3 ? "×" : x < -0.1 ? "△" : "－"; }

customElements.define("race-theater", RaceTheater);
