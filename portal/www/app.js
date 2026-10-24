// うまミル: race list, race card, past performances, course data, results and bets.
// Reads the JSON written by portal/build.py. Plain DOM, one render function per view.

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x, d = 1) => (x == null ? "–" : (x * 100).toFixed(d) + "%");
const store = {
  get(k, d) { try { const v = localStorage.getItem("umamiru:" + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("umamiru:" + k, JSON.stringify(v)); } catch { /* not available */ } },
};
const WD = "日月火水木金土";
const md = (s) => { const d = new Date(s + "T00:00:00"); return `${d.getMonth() + 1}/${d.getDate()}(${WD[d.getDay()]})`; };
const ymd = (s) => { const d = new Date(s + "T00:00:00"); return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日(${WD[d.getDay()]})`; };

const TERMS = {
  "AI勝率": "過去のレース結果から学習したモデルが出した、1着になる確率。出走馬全員分を足すと100%。当日のオッズは使っていません。計算方法は「AIの仕組み」ページにあります。",
  "3着内率": "3着以内に入る確率、または入った割合。",
  "シミュ": "コースを再現した仮想レースを何千回も走らせて、1着になった割合。",
  "単勝": "1着の馬を当てる馬券。数字は100円が何倍になるか。",
  "複勝": "3着以内に入る馬を当てる馬券。",
  "馬連": "1着と2着の2頭を順不同で当てる馬券。",
  "ワイド": "3着以内の2頭を順不同で当てる馬券。",
  "馬単": "1着と2着を順番通りに当てる馬券。",
  "三連複": "1〜3着の3頭を順不同で当てる馬券。",
  "三連単": "1〜3着を順番通りに当てる馬券。",
  "人気": "単勝の売れている順位。",
  "斤量": "馬が背負う重さ（騎手・鞍など）。",
  "上がり": "ゴールまで最後の600mのタイム。小さいほど最後の脚が速い。カッコ内はそのレースで何番目に速かったか。",
  "通過": "各コーナーを何番手で通ったか。",
  "脚質": "位置取りの傾向。逃げ＝先頭、先行＝前の方、差し＝中団、追込＝後方。",
  "系統": "父の血筋のグループ。得意な距離や馬場が似やすい。",
  "期待値": "AI勝率×単勝オッズ。1を超えると、AIの見立てでは割のいい馬券。",
  "印": "自分の予想。◎本命 ○対抗 ▲単穴 △連下 ☆穴。押すたびに切り替わります。",
  "馬場": "良→稍重→重→不良の順に水分が多く、時計がかかります。",
  "回収率": "使った金額に対して戻ってきた金額の割合。",
  "着差": "勝ち馬とのタイム差（秒）。",
};
const MARKS = ["", "◎", "○", "▲", "△", "☆"];

const state = { index: null, race: null, tab: "card", open: null, sort: null, bet: store.get("bet", "ワイド") };

// ---------- small helpers ----------
const term = (w, label) => `<span class="term" data-term="${esc(w)}" tabindex="0">${esc(label ?? w)}</span>`;
const waku = (f, n) => `<span class="waku w${f || 0}">${n ?? ""}</span>`;
const gradeTag = (g) => (g ? `<span class="grade ${esc(g)}">${{ G1: "GⅠ", G2: "GⅡ", G3: "GⅢ" }[g] || esc(g)}</span>` : "");
const lineTag = (l) => `<span class="lg l-${esc(l)}">${esc(l)}</span>`;
const done = (r) => r.horses.some((h) => h.finish);
const marksOf = (id) => store.get("marks:" + id, {});
const pOf = (h) => h.p_ai ?? null;
function aiRank(r) {
  const order = r.horses.filter((h) => h.p_ai != null).sort((a, b) => b.p_ai - a.p_ai);
  return new Map(order.map((h, i) => [h.horse_id, i]));
}
const AIMARK = ["◎", "○", "▲", "△", "△"];
function rec(a) { return a.join("-"); }
const title = (r) => (r.grade ? String(r.name).replace(/\((?:G[IⅠ]+|J・G[IⅠ]+|L|OP)\)$/, "") : r.name);
const short = (n) => String(n ?? "").replace(/^第\d+回/, "");
function fmtTime(t) { return t == null ? "" : `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`; }

async function getJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`データを読み込めませんでした（${r.status}）`);
  return r.json();
}

// ---------- routing ----------
async function route() {
  hidePop();
  const h = location.hash.slice(1);
  if (!state.index) state.index = await getJSON("data/index.json");
  if (/^r\d+$/.test(h)) {
    const id = h.slice(1);
    if (state.race?.race_id !== id) {
      state.race = await getJSON(`data/race/${id}.json`);
      state.open = null;
      state.sort = state.race.horses.some((x) => x.number) ? { key: "num", dir: 1 } : { key: "ai", dir: -1 };
      if (!["card", "look", "pp", "ai", "data", "result", "bet"].includes(state.tab) || (state.tab === "ai" && !state.race.has_ai) || (state.tab === "result" && !done(state.race))) state.tab = "card";
    }
  } else state.race = null;
  if (h === "strategy" && !state.strat) state.strat = await getJSON("data/strategy.json");
  render();
  window.scrollTo(0, 0);
}

function render() {
  const h = location.hash.slice(1);
  let html;
  if (state.race) html = raceView(state.race);
  else if (h === "glossary") html = glossaryView();
  else if (h === "about") html = aboutView();
  else if (h === "strategy") html = strategyView();
  else html = homeView();
  $("#view").innerHTML = html;
  document.title = state.race ? `${state.race.name.replace(/\(G[IⅠ]+\)/, "")} | うまミル` : "うまミル";
}

// ---------- home ----------
function homeView() {
  const idx = state.index;
  const sel = Math.min(store.get("day", idx.days.length - 1), idx.days.length - 1);
  const day = idx.days[sel];
  const venues = [...new Set(day.races.map((r) => r.venue))];
  const maxR = Math.max(...day.races.map((r) => r.race_no));
  let rows = "";
  for (let n = 1; n <= maxR; n++) {
    rows += `<tr><td>${n}R</td>${venues.map((v) => {
      const r = day.races.find((x) => x.venue === v && x.race_no === n);
      if (!r) return "<td></td>";
      return `<td><a href="#r${r.race_id}"><div class="rn">${esc(title(r))}${gradeTag(r.grade)}</div>
        <div class="rm">${esc(r.start_time ?? "")} ${r.surface}${r.distance}m ${r.n_runners}頭</div></a></td>`;
    }).join("")}</tr>`;
  }
  const f = idx.featured[0];
  return `
    ${f ? `<a class="next" href="#r${f.race_id}"><span class="sub small">${md(f.date)} ${esc(f.venue)}${f.race_no}R</span>
      <b>${esc(title(f))}${gradeTag(f.grade)}</b>
      <span class="small">${f.surface}${f.distance}m　出走予定${f.n_runners}頭　AI予想あり</span></a>` : ""}
    <div>
      <div class="daytabs" role="tablist">${idx.days.map((d, i) => `<button type="button" role="tab" data-day="${i}" aria-selected="${i === sel}">${md(d.date)}</button>`).join("")}</div>
      <div class="tw" style="border-top:0"><table class="grid-races">
        <thead><tr><th></th>${venues.map((v) => `<th>${esc(v)}</th>`).join("")}</tr></thead>
        <tbody>${rows}</tbody></table></div>
    </div>
    <section style="display:grid;gap:6px">
      <h2 class="sec">過去の菊花賞</h2>
      <div class="history">${idx.history.slice().reverse().map((r) => `<a href="#r${r.race_id}">${r.date.slice(0, 4)}年（${esc(r.venue)}）</a>`).join("")}</div>
    </section>`;
}

// ---------- race ----------
function raceNav(r) {
  const day = state.index.days.find((d) => d.races.some((x) => x.race_id === r.race_id));
  if (!day) return `<div class="small"><a href="#">レース一覧</a></div>`;
  const venues = [...new Set(day.races.map((x) => x.venue))];
  const same = day.races.filter((x) => x.venue === r.venue).sort((a, b) => a.race_no - b.race_no);
  return `<div class="rnav">
    <div class="venues"><span class="sub small" style="align-self:center">${md(day.date)}</span>${venues.map((v) => {
      const first = day.races.find((x) => x.venue === v && x.race_no === r.race_no) || day.races.find((x) => x.venue === v);
      return `<a href="#r${first.race_id}" aria-current="${v === r.venue}">${esc(v)}</a>`;
    }).join("")}</div>
    <div class="rstrip">${same.map((x) => `<a href="#r${x.race_id}" aria-current="${x.race_id === r.race_id}">${x.race_no}R</a>`).join("")}</div>
  </div>`;
}

function raceHead(r) {
  return `<div class="rhead">
    <div class="rno">${r.race_no}R</div>
    <h1 class="rname">${esc(title(r))}${gradeTag(r.grade)}</h1>
    <div class="rcond"><span>${ymd(r.date)} ${esc(r.venue)}</span>${r.start_time ? `<span>${esc(r.start_time)}発走</span>` : ""}
      <b>${r.surface}${r.distance}m（${esc(r.direction ?? "")}${r.course_note ? "・" + esc(r.course_note) : ""}）</b>
      <span>${r.horses.length}頭</span>${r.weather ? `<span>天候:${esc(r.weather)}</span>` : ""}${r.going ? `<span>${term("馬場")}:${esc(r.going)}</span>` : r.baba?.turf ? `<span>${term("馬場")}:芝${esc(r.baba.turf)}（前日発表）</span>` : ""}</div>
    <div class="rclass">${esc(r.class_text ?? "")}</div>
  </div>`;
}

function raceView(r) {
  const tabs = [["card", "出馬表"], ["look", "見どころ"], ["pp", "馬柱"]];
  if (r.has_ai) tabs.push(["ai", "AI予想"]);
  tabs.push(["data", "データ"]);
  if (done(r)) tabs.push(["result", "結果"]);
  tabs.push(["bet", "買い目"]);
  const view = { card: cardView, look: lookView, pp: ppView, ai: aiView, data: dataView, result: resultView, bet: betView }[state.tab](r);
  return `${raceNav(r)}${raceHead(r)}
    ${r.note ? `<p class="notice" style="margin:0">※${esc(r.note)}</p>` : ""}
    <div class="tabs" role="tablist">${tabs.map(([k, l]) => `<button type="button" role="tab" data-tab="${k}" aria-selected="${state.tab === k}">${l}</button>`).join("")}</div>
    ${view}`;
}

// --- 出馬表
function sortVal(h, k, rank) {
  if (k === "num") return h.number ?? 99;
  if (k === "odds") return h.odds ?? 9999;
  if (k === "ai") return h.p_ai ?? -1;
  if (k === "fin") return h.finish ?? 99;
  return 0;
}
function sortHead(k, label, cls = "") {
  const s = state.sort;
  return `<th class="sortable ${cls}" data-sort="${k}" aria-sort="${s.key === k ? (s.dir > 0 ? "ascending" : "descending") : "none"}">${label}</th>`;
}

function cardView(r) {
  const marks = marksOf(r.race_id);
  const rank = aiRank(r);
  const fin = done(r);
  const s = state.sort;
  const hs = r.horses.slice().sort((a, b) => s.dir * (sortVal(a, s.key) - sortVal(b, s.key)) || (a.number ?? 0) - (b.number ?? 0));
  const hasNum = r.horses.some((h) => h.number), hasOdds = r.horses.some((h) => h.odds != null), hasBw = r.horses.some((h) => h.bw);
  const cols = 6 + (hasNum ? 2 : 0) + (hasOdds ? 1 : 0) + (hasBw ? 1 : 0) + (r.has_ai ? 1 : 0) + (fin ? 1 : 0);
  const rows = hs.map((h) => {
    const last = h.past[0];
    const ai = rank.has(h.horse_id) ? rank.get(h.horse_id) : null;
    const open = state.open === h.horse_id;
    const p = pOf(h);
    return `<tr class="h ${open ? "open" : ""}" data-horse="${esc(h.horse_id)}">
      <td class="c"><button type="button" class="mark" data-mark="${esc(h.horse_id)}" aria-label="${esc(h.name)}の印">${marks[h.horse_id] || ""}</button></td>
      ${hasNum ? `<td class="wk w${h.frame || 0}">${h.frame ?? ""}</td><td class="num">${h.number ?? ""}</td>` : ""}
      <td><div class="hn">${esc(h.name)}</div>
        <div class="hs">${esc(h.sex ?? "")}${h.age ?? ""} ${h.carried ?? ""}kg <span class="pc-inline">${esc(h.jockey ?? "騎手未定")}${last ? ` 前走${last.finish ?? esc(last.finish_raw ?? "")}着` : ""}</span></div></td>
      <td class="pc"><div>${esc(h.sire ?? "")}</div><div class="hs">母父 ${esc(h.damsire ?? "")}</div></td>
      <td class="pc nw">${esc(h.jockey ?? "未定")}<div class="hs">${esc(h.trainer ?? "")}${h.stable ? `(${esc(h.stable)})` : ""}</div></td>
      ${hasBw ? `<td class="pc r nw">${h.bw ?? ""}${h.bw_diff != null ? `<div class="hs">${h.bw_diff > 0 ? "+" : ""}${h.bw_diff}</div>` : ""}</td>` : ""}
      ${hasOdds ? `<td class="r nw">${h.odds != null ? `<b>${h.odds.toFixed(1)}</b><div class="hs">${h.pop}人気</div>` : ""}</td>` : ""}
      ${r.has_ai ? `<td class="r nw"><div class="pbar">${ai != null && ai < 5 ? `<span class="${ai === 0 ? "ai1" : ""}">${AIMARK[ai]}</span>` : ""}<span class="tr"><i style="width:${Math.min(100, (p ?? 0) * 200)}%"></i></span><b>${pct(p)}</b></div></td>` : ""}
      <td class="pc nw">${last ? `<span class="fin ${last.finish === 1 ? "f1" : ""}">${last.finish ?? esc(last.finish_raw ?? "")}着</span> <span class="hs">${esc(short(last.name))}</span>` : `<span class="sub">初出走</span>`}</td>
      ${fin ? `<td class="c fin ${h.finish === 1 ? "f1" : ""}">${h.finish ?? esc(h.finish_raw ?? "")}</td>` : ""}
    </tr>${open ? `<tr class="detail"><td colspan="${cols}">${detail(h, r)}</td></tr>` : ""}`;
  }).join("");
  return `<div class="tw"><table class="card">
    <thead><tr><th class="c">${term("印")}</th>${hasNum ? `<th class="c">枠</th>${sortHead("num", "馬番", "c")}` : ""}<th>馬名</th>
      <th class="pc">父 / 母父</th><th class="pc">騎手 / 厩舎</th>${hasBw ? `<th class="pc r">馬体重</th>` : ""}
      ${hasOdds ? sortHead("odds", "単勝", "r") : ""}
      ${r.has_ai ? sortHead("ai", "AI勝率", "r") : ""}
      <th class="pc">前走</th>${fin ? sortHead("fin", "着順", "c") : ""}</tr></thead>
    <tbody>${rows}</tbody></table></div>
    <p class="small sub" style="margin:0">馬の行を押すと、成績・血統・近走が開きます。${r.has_ai ? `${term("AI勝率")}は1着になる確率の見積もりで、◎○▲△はその上位5頭です（<a href="#about">計算方法</a>）。` : "AI勝率は、いまは菊花賞だけに出しています。"}</p>`;
}

// --- the checks a handicapper runs through, per horse
const top3 = (a) => (a ? a[0] + a[1] + a[2] : 0);
const MARKTXT = { "+": "＋", "-": "－", "": "" };
const markCls = (m) => (m === "+" ? "sp" : m === "-" ? "sm" : "sn");
// One row per point a handicapper checks: the horse's situation, and how every
// horse in the same situation has done (3着内率 against the average, 単勝回収率).
function checkTable(list) {
  if (!list?.length) return `<p class="sub small" style="margin:0">過去の出走がないため、比べられる項目がありません。</p>`;
  const rows = list.map((c) => {
    const ratio = c.base ? Math.min(2, c.top3 / c.base) : 1;
    return `<tr><td><div class="ck">${esc(c.k)}</div><div class="cv">${esc(c.v)}</div>${c.d ? `<div class="hs">${esc(c.d)}</div>` : ""}</td>
      <td class="r nw"><b class="${markCls(c.s)}">${pct(c.top3)}</b><div class="cmp" title="平均を縦線で表示"><i style="width:${ratio * 50}%"></i></div><div class="hs">平均${pct(c.base)}・${c.n.toLocaleString()}頭</div></td>
      <td class="r nw pc">${c.roi ?? "–"}%</td>
      <td class="c ${markCls(c.s)}">${MARKTXT[c.s]}</td></tr>`;
  }).join("");
  return `<div class="tw"><table class="chk"><thead><tr><th>項目とこの馬</th><th class="r">同じ条件の馬の${term("3着内率")}</th><th class="r pc">${term("回収率", "単勝回収率")}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
const CHECK_NOTE = "「同じ条件の馬」は、過去5年に同じ状況で走った全馬の成績です。3着内率が平均の1.2倍以上なら＋、0.8倍以下なら－をつけています（300頭以上の項目のみ。脚質・枠・血統は30頭以上、騎手は50回以上）。";

function detail(h, r) {
  const j = h.jockey_rec;
  const rs = h.past.slice(0, 5).map((x) => `<tr><td class="nw">${esc(x.date.slice(2).replaceAll("-", "/"))}</td><td class="nw">${esc(x.venue)}</td>
      <td class="nw">${esc(short(x.name))}</td><td class="nw">${x.surface}${x.distance} ${esc(x.going ?? "")}</td>
      <td class="r nw">${x.field ?? ""}頭${x.pop ?? "-"}人</td><td class="c fin ${x.finish === 1 ? "f1" : ""}">${x.finish ?? esc(x.finish_raw ?? "")}</td>
      <td class="r nw ${x.l3rank === 1 ? "ai1" : ""}">${x.l3 ?? ""}${x.l3rank ? `(${x.l3rank})` : ""}</td><td class="nw">${esc(x.passing ?? "")}</td><td class="nw">${esc(x.jockey ?? "")}</td></tr>`).join("");
  return `<div class="dgrid wide">
    <div><h4>チェック項目</h4>${checkTable(h.checks)}<p class="small sub" style="margin:4px 0 0">${CHECK_NOTE}</p></div>
    <div>
      ${h.p_ai != null ? `<h4>確率</h4><dl class="kv"><dt>${term("AI勝率")}</dt><dd>${pct(h.p_ai)}</dd>${h.p_sim != null ? `<dt>${term("シミュ", "シミュ勝率")}</dt><dd>${pct(h.p_sim)}</dd><dt>シミュ3着内率</dt><dd>${pct(h.p_sim_place)}</dd>` : ""}</dl>` : ""}
      <h4 style="margin-top:8px">成績（1着-2着-3着-着外）</h4><dl class="kv">
      <dt>全成績</dt><dd>${rec(h.records.all)}</dd>
      <dt>獲得賞金</dt><dd>${(h.prize ?? 0).toLocaleString()}万円</dd>
      <dt>父</dt><dd>${esc(h.sire ?? "?")} ${lineTag(h.line)}</dd>
      <dt>母父</dt><dd>${esc(h.damsire ?? "?")}</dd>
      <dt>厩舎</dt><dd>${esc(h.trainer ?? "")}${h.stable ? `（${esc(h.stable)}）` : ""}</dd></dl>
    </div>
  </div>
  ${rs ? `<div class="tw mini"><table><thead><tr><th>日付</th><th>場</th><th>レース</th><th>距離</th><th class="r">頭数/人気</th><th class="c">着</th><th class="r">${term("上がり")}</th><th>${term("通過")}</th><th>騎手</th></tr></thead><tbody>${rs}</tbody></table></div>` : ""}`;
}

// --- 見どころ
function trendFacts(r) {
  const t = r.trends;
  if (!t.runs) return [];
  const best = (rows, min = 8) => rows.filter((x) => x.n >= min).sort((a, b) => b.top3 - a.top3)[0];
  const bs = best(t.style);
  const avg = (xs) => xs.reduce((s, x) => s + x.top3 * x.n, 0) / Math.max(1, xs.reduce((s, x) => s + x.n, 0));
  const inner = avg(t.frame.filter((x) => x.key <= 4)), outer = avg(t.frame.filter((x) => x.key >= 5));
  const p1 = t.popularity.find((x) => x.key === "1");
  return [
    bs && `${term("脚質")}は${bs.key}の3着内率がいちばん高い（${pct(bs.top3, 0)}）。`,
    `内枠（1〜4枠）の3着内率は${pct(inner, 0)}、外枠（5〜8枠）は${pct(outer, 0)}。`,
    p1 && `1番人気は${p1.n}回で${Math.round(p1.win * p1.n)}勝、3着内率${pct(p1.top3, 0)}。`,
    t.winner_l3 && `勝ち馬の${term("上がり")}は平均${t.winner_l3}秒。`,
  ].filter(Boolean);
}

function lookView(r) {
  const rank = aiRank(r);
  const mk = (h) => (rank.has(h.horse_id) && rank.get(h.horse_id) < 5 ? `<span class="${rank.get(h.horse_id) === 0 ? "ai1" : ""}">${AIMARK[rank.get(h.horse_id)]}</span>` : "");
  const st = Object.fromEntries((r.trends.style || []).map((x) => [x.key, x]));
  const lineup = ["逃げ", "先行", "差し", "追込"].map((s) => {
    const hs = r.horses.filter((h) => h.style === s);
    return `<tr><th>${s}<div class="hs">${hs.length}頭</div></th><td>${hs.map((h) => `<span class="lu">${h.number ? `<span class="waku w${h.frame}">${h.number}</span> ` : ""}${esc(h.name)}${mk(h) ? " " + mk(h) : ""}</span>`).join("") || `<span class="sub">なし</span>`}</td>
      <td class="r nw">${st[s] ? `${pct(st[s].top3, 0)}<div class="hs">${st[s].n}頭</div>` : "–"}</td></tr>`;
  }).join("");
  const scored = r.horses.map((h) => ({ h, plus: (h.checks || []).filter((x) => x.s === "+"), minus: (h.checks || []).filter((x) => x.s === "-") }));
  const net = (x) => x.plus.length - x.minus.length;
  const pick = scored.filter((x) => net(x) >= 2).sort((a, b) => net(b) - net(a) || (a.h.pop ?? 99) - (b.h.pop ?? 99)).slice(0, 6);
  const shaky = scored.filter((x) => x.h.pop && x.h.pop <= 3 && x.minus.length >= 2);
  const item = (c) => `<div><span class="${markCls(c.s)}">${MARKTXT[c.s]}</span>${esc(c.k)}「${esc(c.v)}」 3着内率${pct(c.top3, 0)}（平均${pct(c.base, 0)}）</div>`;
  const row = (x) => `<tr><td class="nw">${x.h.number ? `<span class="waku w${x.h.frame}">${x.h.number}</span> ` : ""}<b>${esc(x.h.name)}</b> ${mk(x.h)}
      ${x.h.pop ? `<div class="hs">${x.h.pop}番人気</div>` : ""}${x.h.finish ? `<div class="hs">結果 ${x.h.finish}着</div>` : ""}</td>
    <td class="small">${x.plus.map(item).join("")}${x.minus.map(item).join("")}</td></tr>`;
  const facts = trendFacts(r);
  return `${babaBlock(r)}<section class="blk"><h3>脚質ごとの顔ぶれ</h3>
      <div class="tw"><table class="lineup"><thead><tr><th>${term("脚質")}</th><th>出走馬</th><th class="r">このコースの3着内率</th></tr></thead><tbody>${lineup}</tbody></table></div>
      <p class="small sub" style="margin:0">脚質は近5走で最初のコーナーを何番手で回ったかの最多。3着内率は過去5年のこのコースの値です。</p></section>
    ${facts.length ? `<section class="blk"><h3>このコースの傾向（過去5年）</h3><ul class="facts">${facts.map((x) => `<li>${x}</li>`).join("")}</ul></section>` : ""}
    <section class="blk"><h3>データ上の好材料が多い馬</h3>
      ${pick.length ? `<div class="tw"><table class="picks"><tbody>${pick.map(row).join("")}</tbody></table></div>` : `<p class="sub" style="margin:0">＋が－より2つ以上多い馬はいません。</p>`}</section>
    ${shaky.length ? `<section class="blk"><h3>人気でも－が2つ以上ある馬</h3><div class="tw"><table class="picks"><tbody>${shaky.map(row).join("")}</tbody></table></div></section>` : ""}
    <p class="small sub" style="margin:0">${CHECK_NOTE}各馬の全項目は、出馬表で馬の行を押すと見られます。</p>`;
}

// --- 馬柱
function ppView(r) {
  const hs = r.horses.slice().sort((a, b) => (a.number ?? 0) - (b.number ?? 0) || (b.p_ai ?? 0) - (a.p_ai ?? 0));
  const cell = (x) => {
    if (!x) return `<td></td>`;
    const t = x.finish && x.finish <= 3 ? "t" + x.finish : "";
    return `<td class="${t}"><div class="top"><span>${esc(x.date.slice(2).replaceAll("-", "."))} ${esc(x.venue)}</span><span class="rk">${x.finish ?? esc(x.finish_raw ?? "")}</span></div>
      <div class="rc" title="${esc(x.name)}">${esc(short(x.name))}</div>
      <div>${x.surface}${x.distance} ${esc(x.going ?? "")} ${x.field ?? ""}頭 ${x.pop ?? "-"}人</div>
      <div><span class="${x.l3rank === 1 ? "l3a" : ""}">上${x.l3 ?? "-"}(${x.l3rank ?? "-"})</span> ${esc(x.passing ?? "")}</div>
      <div>${esc(x.jockey ?? "")} ${x.carried ?? ""} ${x.behind != null && x.behind > 0 ? `差${x.behind}` : ""}</div></td>`;
  };
  const rows = hs.map((h) => `<tr><td class="wk w${h.frame || 0}">${h.number ?? ""}</td>
    <td class="hcol"><div class="hn">${esc(h.name)}</div><div class="hs">${esc(h.sex ?? "")}${h.age ?? ""} ${h.carried ?? ""} ${esc(h.jockey ?? "")}</div>
      <div class="hs">${esc(h.sire ?? "")} ${lineTag(h.line)}</div>${h.odds != null ? `<div class="hs">${h.odds}倍 ${h.pop}人気</div>` : ""}</td>
    ${[0, 1, 2, 3, 4].map((i) => cell(h.past[i])).join("")}</tr>`).join("");
  return `<div class="tw"><table class="pp"><thead><tr><th>番</th><th>馬名</th><th>前走</th><th>2走前</th><th>3走前</th><th>4走前</th><th>5走前</th></tr></thead>
    <tbody>${rows}</tbody></table></div>
    <p class="small sub" style="margin:0">着順の背景：1着は赤、2着は青、3着は緑。「上」は${term("上がり")}、赤字はメンバー最速。「差」は勝ち馬との${term("着差", "タイム差")}。</p>`;
}

// --- AI予想
function aiView(r) {
  const hs = r.horses.filter((h) => h.p_ai != null).sort((a, b) => b.p_ai - a.p_ai);
  const max = Math.max(...hs.map((h) => Math.max(h.p_ai, h.p_market ?? 0)), 0.01);
  const hasNum = hs.some((h) => h.number), hasOdds = hs.some((h) => h.odds);
  const ev = (h) => (h.odds ? h.p_ai * h.odds : null);
  const rows = hs.map((h, i) => {
    const e = ev(h);
    const pm = (h.checks || []).filter((c) => c.s === "+").length, mm = (h.checks || []).filter((c) => c.s === "-").length;
    return `<tr><td class="c ${i === 0 ? "ai1" : ""}">${i < 5 ? AIMARK[i] : ""}</td>
    ${hasNum ? `<td class="wk w${h.frame || 0}">${h.number ?? ""}</td>` : ""}
    <td><div class="hn">${esc(h.name)}</div><div class="hs">${esc(h.jockey ?? "")}</div></td>
    ${hasOdds ? `<td class="r nw">${h.odds ?? "–"}<div class="hs">${h.pop ?? "-"}番人気</div></td>` : ""}
    <td class="r nw"><div class="pbar"><span class="tr wide"><i style="width:${(h.p_ai / max) * 100}%"></i></span><b>${pct(h.p_ai)}</b></div>
      ${h.p_market != null ? `<div class="pbar mk"><span class="tr wide"><i style="width:${(h.p_market / max) * 100}%"></i></span><span class="hs">人気 ${pct(h.p_market)}</span></div>` : ""}</td>
    ${hasOdds ? `<td class="r nw ${e >= 1 ? "sp" : ""}">${e != null ? e.toFixed(2) : "–"}</td>` : ""}
    <td class="r pc">${pct(h.p_sim)}</td><td class="r">${pct(h.p_sim_place, 0)}</td>
    <td class="c pc nw"><span class="sp">${pm ? "＋" + pm : ""}</span> <span class="sm">${mm ? "－" + mm : ""}</span></td></tr>`;
  }).join("");
  const value = hasOdds ? hs.filter((h) => ev(h) >= 1.2 && h.p_ai >= 0.05) : [];
  return `${hasOdds ? `<p style="margin:0">${value.length ? `AI勝率が5%以上で、AI勝率×単勝オッズが1.2を超えるのは ${value.map((h) => `<b>${h.number ?? ""} ${esc(h.name)}</b>（${ev(h).toFixed(2)}）`).join("、")} です。` : "AI勝率が5%以上で、AI勝率×単勝オッズが1.2を超える馬はいません。"}${r.odds_time ? `<span class="small sub">　オッズは${esc(r.odds_time.slice(5, 16).replace("-", "/"))}時点</span>` : ""}</p>` : ""}
    <div class="tw"><table class="aitab"><thead><tr><th class="c">印</th>${hasNum ? `<th class="c">番</th>` : ""}<th>馬名</th>${hasOdds ? `<th class="r">単勝</th>` : ""}<th class="r">${term("AI勝率")}<div class="hs pc">下段は人気から見た勝率</div></th>${hasOdds ? `<th class="r">${term("期待値")}</th>` : ""}<th class="r pc">${term("シミュ", "シミュ勝率")}</th><th class="r">${term("3着内率")}</th><th class="c pc">データ</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="small sub" style="margin:0">今のAIは人気薄の馬を高めに見る傾向があり（テストでは本命の的中率も1番人気より低い）、期待値が1を超える馬が多めに出ます。「人気から見た勝率」は単勝オッズの逆数を合計100%に直した値です。AI勝率がこれより高い馬は、AIが人気より高く見ている馬です。3着内率はシミュレーションの値。データの＋－は出馬表のチェック項目の数です。<a href="#about">計算方法</a></p>`;
}

// If rain turns the track heavy: horses that gain or lose, from the wet-track study
function wetTable(r) {
  const hs = r.horses.filter((h) => h.wet && h.wet.grade !== "0");
  if (!hs.length) return "";
  const row = (h) => `<tr><td class="c ${h.wet.grade === "+" ? "sp" : "sm"}">${h.wet.grade === "+" ? "＋" : "－"}</td><td class="nw">${h.number ? waku(h.frame, h.number) + " " : ""}${esc(h.name)}</td><td class="small">${esc(h.wet.why)}</td></tr>`;
  const up = hs.filter((h) => h.wet.grade === "+"), down = hs.filter((h) => h.wet.grade === "-");
  return `<h4 style="margin:10px 0 4px">雨で重・不良になった場合</h4>
    <p class="small" style="margin:0 0 4px">稍重までなら良馬場とほぼ同じ結果です（京都芝3000mの2025年・稍重の勝ち時計は良の平均と同じ）。重・不良では時計が大きくかかり、京都の長距離では上がり最速の馬が勝つ割合が45%から61%に上がります。</p>
    <div class="tw"><table class="picks"><tbody>${[...up, ...down].map(row).join("")}</tbody></table></div>
    <p class="small sub" style="margin:0">＋は道悪の実績や血統から重以上で評価を上げられる馬、－は下げる馬です（過去の道悪成績と父・母父の産駒が重・不良で人気よりどれだけ走ったかから判定）。</p>`;
}

function babaBlock(r) {
  const b = r.baba;
  if (!b) return "";
  const wk = (b.week || []).slice(-4).map((x) => `<span class="lu">${esc(x.day)} ${esc(x.weather)}</span>`).join("");
  return `<section class="blk"><h3>馬場と天気</h3>
    <dl class="kv">
      <dt>馬場状態</dt><dd>芝 ${esc(b.turf ?? "?")}・ダート ${esc(b.dirt ?? "?")}<span class="small sub">（${esc(b.as_of ?? "")}現在、JRA発表）</span></dd>
      ${b.moisture ? `<dt>芝の含水率</dt><dd>ゴール前 ${b.moisture.turf[0]}%・4コーナー ${b.moisture.turf[1]}%</dd>` : ""}
      <dt>天気</dt><dd>${wk}</dd>
      ${b.course ? `<dt>使用コース</dt><dd>${esc(b.course)}</dd>` : ""}
      ${b.turf_note ? `<dt>芝の様子</dt><dd>${esc(b.turf_note)}</dd>` : ""}
    </dl>
    <p class="small sub" style="margin:0">天気は予報も含むJRAの週間情報です。</p>
    ${wetTable(r)}</section>`;
}

// --- コースデータ
function barRows(rows, label, best) {
  const max = Math.max(0.01, ...rows.map((x) => x.top3 ?? 0));
  return rows.map((x) => `<tr><td class="nw">${label(x)}</td>
    <td class="barcell"><div class="hb"><span class="tr"><i class="${x.key === best ? "hi" : ""}" style="width:${((x.top3 ?? 0) / max) * 100}%"></i></span></div></td>
    <td class="r nw">${pct(x.top3, 0)}</td><td class="r nw">${pct(x.win, 0)}</td><td class="r nw sub">${x.n}</td></tr>`).join("");
}
function dataTable(title, rows, label, best) {
  return `<section class="blk"><h3>${title}</h3><div class="tw"><table><thead><tr><th></th><th></th><th class="r">3着内</th><th class="r">勝率</th><th class="r">頭数</th></tr></thead>
    <tbody>${barRows(rows, label, best)}</tbody></table></div></section>`;
}
function dataView(r) {
  const t = r.trends;
  if (!t.runs) return `<p class="sub">同じコースの過去データがありません。</p>`;
  const best = (rows, min = 8) => rows.filter((x) => x.n >= min).sort((a, b) => b.top3 - a.top3)[0];
  const bs = best(t.style), bf = best(t.frame);
  const avg = (xs) => xs.reduce((s, x) => s + x.top3 * x.n, 0) / Math.max(1, xs.reduce((s, x) => s + x.n, 0));
  const inner = avg(t.frame.filter((x) => x.key <= 4)), outer = avg(t.frame.filter((x) => x.key >= 5));
  const p1 = t.popularity.find((x) => x.key === "1");
  const facts = [
    bs && `${term("脚質")}は${bs.key}の3着内率がいちばん高い（${pct(bs.top3, 0)}）。`,
    `内枠（1〜4枠）の3着内率は${pct(inner, 0)}、外枠（5〜8枠）は${pct(outer, 0)}。`,
    p1 && `1番人気は${p1.n}回で${Math.round(p1.win * p1.n)}勝、3着内率${pct(p1.top3, 0)}。`,
    t.winner_l3 && `勝ち馬の${term("上がり")}は平均${t.winner_l3}秒。`,
  ].filter(Boolean);
  const lines = t.line.filter((x) => x.n >= 5);
  return `<p class="small sub" style="margin:0">${esc(r.venue)}${r.surface}${r.distance}m${r.course_note ? "（" + esc(r.course_note) + "）" : ""}、過去5年の${t.races}レース・${t.runs}頭の集計。</p>
    <ul class="facts">${facts.map((x) => `<li>${x}</li>`).join("")}</ul>
    <div class="cols2">
      ${dataTable("枠番別", t.frame, (x) => waku(x.key, x.key), bf?.key)}
      ${dataTable(`${term("脚質")}別`, t.style.filter((x) => x.n), (x) => x.key, bs?.key)}
      ${dataTable(`${term("人気")}別`, t.popularity, (x) => x.key + "番人気", null)}
      ${dataTable(`父の${term("系統")}別`, lines, (x) => lineTag(x.key), best(lines, 10)?.key)}
      ${t.sire.length ? `<section class="blk"><h3>種牡馬別（8走以上）</h3><div class="tw"><table><thead><tr><th>父</th><th class="r">走</th><th class="r">勝率</th><th class="r">3着内</th><th class="r">単勝${term("回収率", "回収")}</th></tr></thead>
        <tbody>${t.sire.map((x) => `<tr><td>${esc(x.key)}</td><td class="r">${x.n}</td><td class="r">${pct(x.win, 0)}</td><td class="r">${pct(x.top3, 0)}</td><td class="r">${x.roi}%</td></tr>`).join("")}</tbody></table></div></section>` : ""}
    </div>`;
}

// --- 結果
function lapsSvg(laps) {
  const xs = laps.split("-").map((s) => parseFloat(s)).filter((x) => !isNaN(x));
  if (!xs.length) return "";
  const W = 600, H = 150, L = 6, bw = (W - L * 2) / xs.length;
  const lo = Math.floor(Math.min(...xs) - 0.6), hi = Math.ceil(Math.max(...xs) + 0.2);
  const y = (v) => 18 + ((v - lo) / (hi - lo)) * (H - 46);
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="200mごとのラップ">${xs.map((v, i) => {
    const top = y(v);
    const x = L + i * bw;
    return `<rect x="${x + 2}" y="${top}" width="${bw - 4}" height="${H - 24 - top}"></rect>
      <text x="${x + bw / 2}" y="${top - 4}" text-anchor="middle">${v.toFixed(1)}</text>
      <text x="${x + bw / 2}" y="${H - 8}" text-anchor="middle">${(i + 1) * 200}</text>`;
  }).join("")}</svg>`;
}
function resultView(r) {
  const hs = r.horses.slice().sort((a, b) => (a.finish ?? 99) - (b.finish ?? 99));
  const win = hs[0]?.time;
  const rows = hs.map((h) => `<tr><td class="c fin ${h.finish === 1 ? "f1" : ""}">${h.finish ?? esc(h.finish_raw ?? "")}</td>
    <td class="wk w${h.frame || 0}">${h.frame ?? ""}</td><td class="num">${h.number ?? ""}</td>
    <td><div class="hn">${esc(h.name)}</div><div class="hs">${esc(h.jockey ?? "")}</div></td>
    <td class="r nw">${fmtTime(h.time)}${h.time != null && win != null && h.time > win ? `<div class="hs">+${(h.time - win).toFixed(1)}</div>` : ""}</td>
    <td class="r">${h.l3 ?? ""}</td><td class="pc nw">${esc(h.passing ?? "")}</td><td class="r nw">${h.odds ?? ""}<div class="hs">${h.pop ? h.pop + "人気" : ""}</div></td></tr>`).join("");
  const order = ["単勝", "複勝", "枠連", "馬連", "ワイド", "馬単", "三連複", "三連単"];
  const pays = order.map((t) => {
    const ps = r.payouts.filter((p) => p.type === t);
    if (!ps.length) return "";
    return ps.map((p, i) => `<tr>${i === 0 ? `<th rowspan="${ps.length}" style="text-align:left">${TERMS[t] ? term(t) : esc(t)}</th>` : ""}<td>${esc(p.combo)}</td><td class="r">${p.payout.toLocaleString()}円</td><td class="r sub">${p.pop ?? ""}人気</td></tr>`).join("");
  }).join("");
  return `<div class="tw"><table><thead><tr><th class="c">着</th><th class="c">枠</th><th class="c">番</th><th>馬名</th><th class="r">タイム</th><th class="r">${term("上がり")}</th><th class="pc">${term("通過")}</th><th class="r">単勝</th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="cols2">
      <section class="blk"><h3>払戻（100円あたり）</h3><div class="tw"><table><tbody>${pays}</tbody></table></div></section>
      ${r.laps ? `<section class="blk laps"><h3>ラップ（200mごと・秒）</h3>${lapsSvg(r.laps)}<p class="small sub" style="margin:0">棒が高いほど速い区間。</p></section>` : ""}
    </div>`;
}

// --- 印・買い目
function combos(type, axis, others) {
  if (type === "単勝" || type === "複勝") return [axis, ...others].filter(Boolean).map((h) => [h]);
  if (!axis) return [];
  if (["馬連", "ワイド", "馬単"].includes(type)) return others.map((o) => [axis, o]);
  const out = [];
  if (type === "三連複") for (let i = 0; i < others.length; i++) for (let j = i + 1; j < others.length; j++) out.push([axis, others[i], others[j]]);
  if (type === "三連単") for (const a of others) for (const b of others) if (a !== b) out.push([axis, a, b]);
  return out;
}
function key(type, hs) {
  const ns = hs.map((h) => h.number);
  if (["馬連", "ワイド", "三連複"].includes(type)) ns.sort((a, b) => a - b);
  return ns.join("-");
}
function betView(r) {
  const marks = marksOf(r.race_id);
  const by = (m) => r.horses.filter((h) => marks[h.horse_id] === m);
  const axis = by("◎")[0];
  const others = ["○", "▲", "△", "☆"].flatMap(by);
  const type = state.bet;
  const list = combos(type, axis, others);
  const fin = done(r);
  let back = 0;
  const chips = list.map((c) => {
    const k = c[0].number ? key(type, c) : null;
    const hit = k && r.payouts.find((p) => p.type === type && p.combo === k);
    if (hit) back += hit.payout;
    return `<span class="${hit ? "hit" : ""}">${c.map((h) => h.number ?? esc(h.name)).join(type === "馬単" || type === "三連単" ? "→" : "-")}${hit ? ` ${hit.payout.toLocaleString()}円` : ""}</span>`;
  }).join("");
  const rows = r.horses.slice().sort((a, b) => (a.number ?? 0) - (b.number ?? 0) || (b.p_ai ?? 0) - (a.p_ai ?? 0)).map((h) => `<tr>
    <td class="c"><button type="button" class="mark" data-mark="${esc(h.horse_id)}" aria-label="${esc(h.name)}の印">${marks[h.horse_id] || ""}</button></td>
    <td class="wk w${h.frame || 0}">${h.frame ?? ""}</td><td class="num">${h.number ?? "–"}</td><td class="hn">${esc(h.name)}</td>
    <td class="r">${h.odds ?? "–"}</td>${r.has_ai ? `<td class="r">${pct(h.p_ai)}</td>` : ""}</tr>`).join("");
  const how = type === "単勝" || type === "複勝" ? "印をつけた馬を1点ずつ" : type === "三連単" ? "◎を1着に固定し、○▲△☆から2着・3着" : "◎から○▲△☆へ流し";
  const empty = !axis && !(type === "単勝" || type === "複勝") ? "◎をつけると買い目が出ます。" : "○▲△☆をつけると買い目が出ます。";
  return `<div class="cols2">
    <section class="blk"><h3>${term("印")}</h3>
      <div class="betform"><button type="button" class="btn" id="auto">${r.has_ai ? "AIの予想どおりにつける" : "人気順につける"}</button><button type="button" class="btn" id="clear">すべて消す</button></div>
      <div class="tw"><table><thead><tr><th class="c">印</th><th class="c">枠</th><th class="c">番</th><th>馬名</th><th class="r">単勝</th>${r.has_ai ? `<th class="r">AI</th>` : ""}</tr></thead><tbody>${rows}</tbody></table></div>
    </section>
    <section class="blk"><h3>買い目</h3>
      <div class="betform"><label for="bet-type">券種</label><select id="bet-type">${["単勝", "複勝", "馬連", "ワイド", "馬単", "三連複", "三連単"].map((t) => `<option value="${t}" ${t === type ? "selected" : ""}>${t}</option>`).join("")}</select>
        <span class="small sub">${esc(TERMS[type])}</span></div>
      <div class="small">${how}</div>
      <div class="tot"><b>${list.length}</b>点　${(list.length * 100).toLocaleString()}円（1点100円）</div>
      <div class="combos">${chips || `<span style="border:0;padding:0" class="sub">${empty}</span>`}</div>
      ${fin && list.length ? `<div class="tot">払戻 <b>${back.toLocaleString()}</b>円　${term("回収率")} ${Math.round((back / (list.length * 100)) * 100)}%</div>` : ""}
      ${r.seg?.surface === "芝" || r.seg?.surface === "ダ" ? `<p class="small" style="margin:8px 0 0">このレースと同じ条件（${esc([r.seg.surface, r.seg.field, r.seg.cls, r.seg.hande, r.seg.fav].filter(Boolean).join("・"))}）の過去レースで、どの買い方が当たりやすく戻りが多かったかを<a href="#strategy" id="to-strategy">買い方を比べる</a>で見られます。</p>` : ""}
    </section></div>`;
}

// --- 買い方を比べる
const SEG_LABEL = { surface: "芝・ダート", field: "頭数", cls: "クラス", hande: "ハンデ", fav: "1番人気のオッズ" };
function segKey(sel, keys) { return keys.map((k) => sel[k] || "").join("|"); }
function strategyRows(cur, all) {
  const base = Object.fromEntries(all.strategies.map((x) => [x.key, x]));
  return cur.strategies.map((x) => {
    const d = x.roi - base[x.key].roi;
    return `<tr><td>${esc(x.label)}<div class="hs">${x.tickets}点</div></td><td class="r">${pct(x.hit, 0)}</td>
      <td class="r"><b>${x.roi}%</b>${cur !== all ? `<div class="hs ${d >= 5 ? "sp" : d <= -5 ? "sm" : ""}">全体比 ${d >= 0 ? "+" : ""}${d}</div>` : ""}</td>
      <td class="r pc">${x.roi_a ?? "–"}%</td><td class="r pc">${x.roi_b ?? "–"}%</td><td class="r pc">${x.avg != null ? x.avg.toLocaleString() + "円" : "–"}</td></tr>`;
  }).join("");
}
function strategyView() {
  const S = state.strat;
  const sel = store.get("seg", {});
  const k = segKey(sel, S.keys);
  const cur = S.table[k], all = S.table[segKey({}, S.keys)];
  const selects = S.keys.map((d) => `<label class="seg"><span>${SEG_LABEL[d]}</span><select data-seg="${d}"><option value="">すべて</option>${S.dims[d].map((v) => `<option ${sel[d] === v ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>`).join("");
  const body = !cur ? `<p>この条件のレースは30未満なので出していません。条件をゆるめてください。</p>` : `
    <div class="facts-row">
      <div><b>${cur.races.toLocaleString()}</b><span>レース</span></div>
      <div><b>${pct(cur.fav_top3, 0)}</b><span>1番人気が3着内</span></div>
      <div><b>${pct(cur.calm, 0)}</b><span>1〜3着がすべて5番人気以内</span></div>
      <div><b>${(cur.trio_med ?? 0).toLocaleString()}円</b><span>3連複の配当（中央値）</span></div>
      <div><b>${pct(cur.big, 0)}</b><span>3連単が10万円以上</span></div>
    </div>
    <section class="blk"><h3>同じ買い方を全レースで続けた結果</h3>
      <div class="tw"><table><thead><tr><th>買い方</th><th class="r">的中率</th><th class="r">${term("回収率")}</th><th class="r pc">${S.split[0]}</th><th class="r pc">${S.split[1]}</th><th class="r pc">当たったときの払戻</th></tr></thead>
      <tbody>${strategyRows(cur, all)}</tbody></table></div>
      <p class="small sub" style="margin:0">100円ずつ買った場合。回収率100%で買った額がそのまま戻ります。JRAの控除があるため、全体ではどの買い方も100%を下回ります。期間の前半と後半で差が大きい買い方は、たまたまの結果の可能性があります。</p></section>
    <section class="blk"><h3>人気ごとの成績</h3>
      <div class="tw"><table><thead><tr><th>人気</th><th class="r">勝率</th><th class="r">3着内率</th><th class="r">単勝回収率</th><th class="r">複勝回収率</th></tr></thead>
      <tbody>${cur.pops.map((x) => `<tr><td>${x.key}番人気</td><td class="r">${pct(x.win)}</td><td class="r">${pct(x.top3)}</td><td class="r">${x.roi}%</td><td class="r">${x.proi}%</td></tr>`).join("")}</tbody></table></div></section>`;
  return `<h1 style="font-size:18px">買い方を比べる</h1>
    <p class="small sub" style="margin:0">${S.years}のJRA平地レースで、人気だけを基準に同じ買い方を続けたら、どれくらい当たってどれくらい戻ったかの集計です。条件を選ぶと、その条件のレースだけで数え直します。</p>
    <div class="segs">${selects}</div>${body}`;
}

// --- glossary / about
function glossaryView() {
  return `<h1 style="font-size:18px">用語</h1>
    <dl class="gl">${Object.entries(TERMS).map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>`;
}
function aboutView() {
  const rows = [
    ["芝 全4,642レース", "AI", "27.1%", "57.8%"], ["", "1番人気", "33.6%", "65.5%"],
    ["芝2400m以上 349レース", "シミュレーション", "28.4%", "64.5%"], ["", "AI", "30.9%", "65.9%"], ["", "1番人気", "39.5%", "70.2%"],
  ].map((x) => `<tr><td>${x[0]}</td><td>${x[1]}</td><td class="r">${x[2]}</td><td class="r">${x[3]}</td></tr>`).join("");
  return `<h1 style="font-size:18px">AI勝率の仕組み</h1>
    <div class="prose"><p>AI勝率は「このメンバーで何度も走ったら、その馬が何回に1回勝つか」の見積もりです。出走馬全員分を足すとちょうど100%になります。当日のオッズは使っていません。</p></div>
    <h2 class="sec">計算の手順</h2>
    <ol class="steps">
      <li><b>馬ごとの能力値を出す</b><p>過去の各レースで、その馬の平均速度が同じレースの真ん中の馬より何%速かったかを測ります。同じレースの中で比べるので、コースや馬場、ペースの違いは打ち消されます。一緒に走った相手を通じて全馬をつないで計算するので、G1で勝ち馬に迫った馬はG1級として評価されます。新しいレースほど重く数え、距離が延びたときに能力が上がるか下がるかも一緒に出します。</p></li>
      <li><b>21項目にまとめる</b><p>能力値と距離の向き不向き、前走と近5走の着順、近5走の人気（過去のレースのもの）、最初のコーナーでの位置、上がりの速さ、休養明けの日数、距離の延長・短縮、斤量と枠（出走馬の平均との差）、騎手の過去1年の3着内率、性別・年齢、出走数、獲得賞金、父と母父の産駒の長距離適性です。どれもそのレースより前のデータだけで計算しています。</p></li>
      <li><b>点数にして確率に直す</b><p>21項目それぞれに重みをかけて足し、馬ごとの点数を出します。点数の差を出走馬の中で比べて確率に直します（点数が1上がると勝つ見込みが約2.7倍になる計算です）。重みは2018〜2022年のレースで、実際に勝った馬に高い確率がつくように決め、2023年のレースで調整しました。</p></li>
      <li><b>シミュレーションで走らせる（菊花賞のみ）</b><p>長距離では展開やスタミナの影響が大きいので、点数から各馬の最高速度を、過去走から脚質・末脚・スタミナを決め、京都芝3000mのコースを数百回走らせます。勝った回数の割合が「シミュ勝率」、3着以内に入った割合が「3着内率」です。</p></li>
    </ol>
    <h2 class="sec">テストの成績</h2>
    <p class="small sub" style="margin:0">学習に使っていない2024年1月以降のレースで、AIがいちばん高い勝率をつけた馬（本命）の成績です（2026年10月14日時点）。</p>
    <div class="tw"><table><thead><tr><th>対象</th><th>予想</th><th class="r">本命が1着</th><th class="r">本命が3着内</th></tr></thead><tbody>${rows}</tbody></table></div>
    <h2 class="sec">わかっている弱点</h2>
    <div class="prose">
      <p>本命の的中率は、まだ1番人気に届いていません。オッズには大勢の予想が集まっているので、オッズを使わないモデルが人気より当てるのは簡単ではありません。このサイトでは、AI勝率をオッズと並べて、AIが人気より高く見ている馬（${term("期待値")}が1を超える馬）を探す使い方を想定しています。</p>
      <p>菊花賞は全馬が3000mを初めて走るので、距離適性は能力値の距離の向き不向きと血統からの推測です。</p>
      <p>調教、パドック、当日の馬体重はまだ入っていません。枠順が決まる前の予想なので、枠は仮の値で計算しています。</p>
    </div>`;
}

// ---------- popover ----------
function showPop(el) {
  const w = el.dataset.term, text = TERMS[w], pop = $("#pop");
  if (!text) return;
  pop.innerHTML = `<b>${esc(w)}</b>${esc(text)}`;
  pop.hidden = false;
  const r = el.getBoundingClientRect();
  const maxLeft = window.scrollX + document.documentElement.clientWidth - pop.offsetWidth - 12;
  pop.style.left = Math.max(12, Math.min(window.scrollX + r.left, maxLeft)) + "px";
  pop.style.top = window.scrollY + r.bottom + 4 + "px";
}
function hidePop() { $("#pop").hidden = true; }

// ---------- events ----------
document.addEventListener("click", (ev) => {
  const t = ev.target;
  const tm = t.closest("[data-term]");
  if (tm) { ev.preventDefault(); ev.stopPropagation(); showPop(tm); return; }
  hidePop();
  const day = t.closest("[data-day]");
  if (day) { store.set("day", Number(day.dataset.day)); return render(); }
  const tab = t.closest("[data-tab]");
  if (tab) { state.tab = tab.dataset.tab; state.open = null; return render(); }
  const sort = t.closest("th[data-sort]");
  if (sort) {
    const k = sort.dataset.sort;
    state.sort = state.sort.key === k ? { key: k, dir: -state.sort.dir } : { key: k, dir: k === "ai" ? -1 : 1 };
    return render();
  }
  const mk = t.closest("[data-mark]");
  if (mk) {
    const id = state.race.race_id, ms = marksOf(id);
    const next = MARKS[(MARKS.indexOf(ms[mk.dataset.mark] || "") + 1) % MARKS.length];
    if (next === "◎") for (const k in ms) if (ms[k] === "◎") delete ms[k];
    if (next) ms[mk.dataset.mark] = next; else delete ms[mk.dataset.mark];
    store.set("marks:" + id, ms);
    return render();
  }
  if (t.id === "auto") {
    const r = state.race;
    const hs = r.has_ai ? r.horses.filter((h) => h.p_ai != null).sort((a, b) => b.p_ai - a.p_ai) : r.horses.filter((h) => h.pop).sort((a, b) => a.pop - b.pop);
    const ms = {};
    hs.slice(0, 5).forEach((h, i) => { ms[h.horse_id] = MARKS[i + 1]; });
    store.set("marks:" + r.race_id, ms);
    return render();
  }
  if (t.id === "to-strategy") { const g = state.race.seg; store.set("seg", { surface: g.surface, field: g.field, cls: g.cls, hande: g.hande, fav: g.fav || undefined }); return; }
  if (t.id === "clear") { store.set("marks:" + state.race.race_id, {}); return render(); }
  if (t.closest("button, a, select, input")) return;
  const row = t.closest("tr.h[data-horse]");
  if (row) { state.open = state.open === row.dataset.horse ? null : row.dataset.horse; render(); }
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") hidePop();
  if (ev.key === "Enter" && ev.target.matches?.(".term")) showPop(ev.target);
});
document.addEventListener("change", (ev) => {
  if (ev.target.id === "bet-type") { state.bet = ev.target.value; store.set("bet", state.bet); render(); }
  const sg = ev.target.dataset?.seg;
  if (sg) { const sel = store.get("seg", {}); sel[sg] = ev.target.value || undefined; store.set("seg", sel); render(); }
});
window.addEventListener("hashchange", () => route().catch(fail));
function fail(e) { $("#view").innerHTML = `<p>${esc(e.message)}。再読み込みしてください。</p>`; }
route().catch(fail);
