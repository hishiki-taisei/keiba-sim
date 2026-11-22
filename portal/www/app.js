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
  "展開": "各馬の脚質・末脚・スタミナでコース上のレースを再現したもの。何千回も走らせて3着内率を出しています。",
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

const state = { index: null, race: null, tab: "card", open: null, sort: null, bet: store.get("bet", "ワイド"), how: store.get("how", "流し") };

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

// ---------- live odds ----------
// Races still to run read data/odds/<date>.json each time they are opened
// (refreshed through the day by portal/fetch_odds.py). Odds, popularity and
// the market's win rates are replaced; the AI win rate keeps the model's
// correction to the market (AI = market × exp(correction), so the ratio of AI
// to market stays as the model set it) and moves with the new odds.
async function liveOdds(r) {
  const day = state.index.days.find((d) => d.upcoming && d.date === r.date);
  if (!day || done(r)) return;
  let live;
  try { live = await getJSON(`data/odds/${r.date}.json?t=${Date.now()}`); } catch { return; }
  const g = live.going?.[r.race_id];
  if (r.baba) {
    const venue = Object.entries(live.going || {}).filter(([k]) => k.slice(0, 10) === r.race_id.slice(0, 10)).map(([, x]) => x);
    if (venue.length) r.baba.same_day = venue.sort((a, b) => a.r - b.r);
    const turf = r.baba.same_day.filter((x) => x.surface === "芝").pop();
    if (r.replay && turf) r.replay = r.replay.replace(/going=[^&]*/, `going=${encodeURIComponent(GOING[turf.going] ?? turf.going)}`);
    if (live.jra?.moisture) Object.assign(r.baba, { moisture: live.jra.moisture, as_of: live.jra.as_of });
  } else if (g) {
    r.going = GOING[g.going] ?? g.going; r.weather = g.weather;
  }
  r.going_time = live.fetched?.slice(11);
  const o = live.races?.[r.race_id];
  r.bets = live.bets?.[r.race_id] || [];
  if (!o?.win) return;
  const hs = r.horses.filter((h) => h.number && o.win[String(h.number).padStart(2, "0")]);
  if (!hs.length) return;
  const corr = new Map(hs.map((h) => [h, h.p_ai != null && h.p_market ? Math.log(h.p_ai / h.p_market) : null]));
  for (const h of hs) {
    const k = String(h.number).padStart(2, "0");
    h.odds = o.win[k][0]; h.pop = o.win[k][2];
    if (o.place?.[k]) h.place_odds = [o.place[k][0], o.place[k][1]];
  }
  const inv = hs.reduce((a, h) => a + 1 / h.odds, 0);
  for (const h of hs) h.p_market = 1 / h.odds / inv;
  if (hs.every((h) => corr.get(h) != null)) {
    const raw = hs.map((h) => h.p_market * Math.exp(corr.get(h))), sum = raw.reduce((a, x) => a + x, 0);
    hs.forEach((h, i) => { h.p_ai = raw[i] / sum; });
  }
  r.pairs = { umaren: o.umaren || {}, wide: o.wide || {} };
  try { r.combo = await getJSON(`data/odds/${r.date}/${r.race_id}.json?t=${Date.now()}`); } catch { r.combo = null; }
  r.odds_time = o.time;
  r.note = `${r.race_id === state.index.featured[0]?.race_id ? "枠順確定。" : ""}オッズは${o.time.slice(5, 16).replace("-", "/")}時点です（ページを開くたびに最新を読み込みます。発走までに変わります）。${r.going && !r.baba ? `馬場は${esc(r.going_time ?? "")}時点の発表で${esc(r.going)}です。` : ""}`;
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
      await liveOdds(state.race);
      state.open = null;
      state.sort = state.race.horses.some((x) => x.number) ? { key: "num", dir: 1 } : { key: "ai", dir: -1 };
      if (!["card", "look", "pp", "ai", "race", "data", "result", "bet"].includes(state.tab) || (state.tab === "ai" && !state.race.has_ai) || (state.tab === "race" && !state.race.theater && !state.race.replay) || (state.tab === "result" && !done(state.race))) state.tab = "card";
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
  fitReplay();
  $(".daytabs [aria-selected=true]")?.scrollIntoView({ block: "nearest", inline: "end" });
  document.title = state.race ? `${state.race.name.replace(/\(G[IⅠ]+\)/, "")} | うまミル` : "うまミル";
}

// ---------- home ----------
function homeView() {
  const idx = state.index;
  // a day with races still to run opens first; the chosen tab is remembered per build
  const up = idx.days.findIndex((d) => d.upcoming);
  const sel = Math.min(store.get("day:" + idx.built, up >= 0 ? up : idx.days.length - 1), idx.days.length - 1);
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
      <span class="small">${f.surface}${f.distance}m　${f.n_runners}頭　AI予想・レース再現あり</span></a>` : ""}
    <div>
      <div class="daytabs" role="tablist">${idx.days.map((d, i) => `<button type="button" role="tab" data-day="${i}" aria-selected="${i === sel}">${md(d.date)}</button>`).join("")}</div>
      <div class="tw" style="border-top:0"><table class="grid-races">
        <thead><tr><th></th>${venues.map((v) => `<th>${esc(v)}</th>`).join("")}</tr></thead>
        <tbody>${rows}</tbody></table></div>
    </div>
    <section style="display:grid;gap:6px">
      <h2 class="sec">過去のマイルチャンピオンシップ</h2>
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
      <span>${r.horses.length}頭</span>${r.weather ? `<span>天候:${esc(r.weather)}</span>` : ""}${r.going ? `<span>${term("馬場")}:${esc(r.going)}</span>` : r.baba?.turf ? `<span>${term("馬場")}:${(() => { const t = (r.baba.day_before || []).filter((x) => x.surface === "芝").pop(); const d = (r.baba.same_day || []).filter((x) => x.surface === "芝").pop(); return d ? `芝${esc(GOING[d.going] ?? d.going)}（当日発表）` : t ? `前日は芝${esc(GOING[t.going] ?? t.going)}・当日の予報は${esc(r.baba.week?.[r.baba.week.length - 1]?.weather ?? "未発表")}` : `芝${esc(r.baba.turf)}（前日発表）`; })()}</span>` : ""}</div>
    <div class="rclass">${esc(r.class_text ?? "")}</div>
  </div>`;
}

function raceView(r) {
  const tabs = [["card", "出馬表"], ["look", "見どころ"], ["pp", "馬柱"]];
  if (r.has_ai) tabs.push(["ai", "AI予想"]);
  tabs.push(["data", "データ"]);
  if (done(r)) tabs.push(["result", "結果"]);
  tabs.push(["bet", "買い目"]);
  const view = { card: cardView, look: lookView, pp: ppView, ai: aiView, race: theaterView, data: dataView, result: resultView, bet: betView }[state.tab](r);
  return `${raceNav(r)}${raceHead(r)}
    ${r.note ? `<p class="notice" style="margin:0">※${esc(r.note)}</p>` : ""}
    ${r.replay || r.theater ? `<div class="racebtn"><button type="button" class="btn${state.tab === "race" ? " on" : ""}" data-tab="race">▶ ${r.replay ? "レース再現" : "展開"}を見る</button><span class="small sub">脚質と枠からレースを走らせます</span></div>` : ""}
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
    <p class="small sub" style="margin:0">馬の行を押すと、成績・血統・近走が開きます。左の${term("印")}を押すと◎○▲△☆を付けられます。${r.has_ai ? `${term("AI勝率")}は1着になる確率の見積もりで、◎○▲△はその上位5頭です（<a href="#about">計算方法</a>）。` : "AI勝率は、いまは今日のレースだけに出しています。"}</p>
    ${builderView(r)}`;
}

// --- 印から買い目を作る（出馬表の下）
const BET_TYPES = ["単勝", "複勝", "馬連", "ワイド", "馬単", "三連複", "三連単"];
const BET_HOW = { "流し": "◎を軸に、○▲△☆へ流す", "ボックス": "印をつけた馬すべての組み合わせ", "フォーメーション": "1列目 ◎○・2列目 ◎○▲・3列目 印すべて" };
const ORDERED = (t) => t === "馬単" || t === "三連単";
const SIZE = (t) => (t === "単勝" || t === "複勝" ? 1 : t.startsWith("三連") ? 3 : 2);
function tickets(type, how, marks, horses) {
  const by = (ms) => horses.filter((h) => ms.includes(marks[h.horse_id]));
  const all = by(["◎", "○", "▲", "△", "☆"]), axis = by(["◎"]);
  const n = SIZE(type);
  if (n === 1) return all.map((h) => [h]);
  let cols;
  if (how === "ボックス") cols = Array(n).fill(all);
  else if (how === "フォーメーション") cols = n === 2 ? [by(["◎", "○"]), all] : [by(["◎", "○"]), by(["◎", "○", "▲"]), all];
  else cols = [axis, ...Array(n - 1).fill(all)];
  const out = [], seen = new Set();
  const walk = (i, cur) => {
    if (i === n) {
      const k = ORDERED(type) ? cur.map((h) => h.horse_id).join(">") : cur.map((h) => h.horse_id).sort().join("|");
      if (!seen.has(k)) { seen.add(k); out.push(ORDERED(type) ? cur : cur.slice().sort((a, b) => (a.number ?? 99) - (b.number ?? 99))); }
      return;
    }
    for (const h of cols[i]) if (!cur.includes(h)) walk(i + 1, [...cur, h]);
  };
  walk(0, []);
  return out;
}
const COMBO_KEY = { "単勝": "win", "複勝": "place", "馬連": "umaren", "ワイド": "wide", "馬単": "umatan", "三連複": "trio", "三連単": "trifecta" };
function ticketOdds(r, type, c) {
  if (c.some((h) => !h.number)) return null;
  const k = c.map((h) => String(h.number).padStart(2, "0")).join("");
  if (type === "単勝") return c[0].odds != null ? [c[0].odds] : null;
  if (type === "複勝") return c[0].place_odds?.[0] != null ? c[0].place_odds : null;
  const o = r.combo?.[COMBO_KEY[type]]?.[k];
  return o == null ? null : Array.isArray(o) ? o : [o];
}
function builderView(r) {
  const marks = marksOf(r.race_id);
  const type = BET_TYPES.includes(state.bet) ? state.bet : "ワイド";
  const how = BET_HOW[state.how] ? state.how : "流し";
  const list = tickets(type, how, marks, r.horses);
  const fin = done(r);
  let back = 0;
  const odds = list.map((c) => ticketOdds(r, type, c));
  const rows = list.map((c, i) => {
    const k = c[0].number ? key(type, c) : null;
    const hit = fin && k && r.payouts.find((p) => p.type === type && p.combo === k);
    if (hit) back += hit.payout;
    const o = odds[i];
    return `<tr class="${hit ? "hit" : ""}"><td class="nw">${c.map((h) => waku(h.frame, h.number ?? "?")).join(`<span class="sep">${ORDERED(type) ? "→" : "-"}</span>`)}</td>
      <td class="small">${c.map((h) => `${marks[h.horse_id] ?? ""}${esc(h.name)}`).join(" / ")}</td>
      <td class="r nw">${o ? `<b>${o[0].toFixed(1)}</b>${o[1] ? `〜${o[1].toFixed(1)}` : ""}倍` : "<span class='sub'>–</span>"}</td>
      ${fin ? `<td class="r nw">${hit ? `<b class="sm">${hit.payout.toLocaleString()}円</b>` : ""}</td>` : ""}</tr>`;
  }).join("");
  const known = odds.filter(Boolean).map((o) => o[0]);
  const marked = r.horses.filter((h) => marks[h.horse_id]).length;
  const empty = !marked ? "印をつけると買い目が出ます。" : SIZE(type) > 1 && how === "流し" && !r.horses.some((h) => marks[h.horse_id] === "◎") ? "流しは◎が必要です。" : "この買い方では組み合わせができません。印を増やしてください。";
  return `<section class="blk builder"><h3>印から買い目を作る</h3>
    <div class="betform">
      <button type="button" class="btn" id="auto">${r.has_ai ? "AIの予想どおりに印をつける" : "人気順に印をつける"}</button><button type="button" class="btn" id="clear">印をすべて消す</button>
    </div>
    <div class="chips"><span class="lab">券種</span>${BET_TYPES.map((t) => `<button type="button" class="chip" data-bet="${t}" aria-pressed="${t === type}">${t}</button>`).join("")}</div>
    ${SIZE(type) > 1 ? `<div class="chips"><span class="lab">買い方</span>${Object.keys(BET_HOW).map((h) => `<button type="button" class="chip" data-how="${h}" aria-pressed="${h === how}">${h}</button>`).join("")}<span class="small sub">　${esc(type === "三連単" && how === "流し" ? "◎を1着に固定し、○▲△☆から2・3着" : type === "馬単" && how === "流し" ? "◎を1着に固定し、○▲△☆へ" : BET_HOW[how])}</span></div>` : `<p class="small sub" style="margin:0">印をつけた馬を1点ずつ買います。</p>`}
    <div class="tot"><b>${list.length}</b>点　${(list.length * 100).toLocaleString()}円（1点100円）${known.length ? `<span class="small sub">　オッズ ${Math.min(...known).toFixed(1)}〜${Math.max(...known).toFixed(1)}倍${r.combo?.time || r.odds_time ? `（${esc((r.combo?.time || r.odds_time).slice(11, 16))}時点）` : ""}</span>` : ""}</div>
    ${list.length ? `<div class="tw"><table class="tix"><thead><tr><th>組み合わせ</th><th>馬</th><th class="r">オッズ</th>${fin ? `<th class="r">払戻</th>` : ""}</tr></thead><tbody>${rows}</tbody></table></div>` : `<p class="sub" style="margin:0">${empty}</p>`}
    ${fin && list.length ? `<div class="tot">払戻 <b>${back.toLocaleString()}</b>円　${term("回収率")} ${Math.round((back / (list.length * 100)) * 100)}%</div>` : ""}
    ${!fin && list.length && !r.combo && SIZE(type) > 1 ? `<p class="small sub" style="margin:0">この券種のオッズはまだ取得していません。</p>` : ""}
  </section>`;
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
      ${h.p_ai != null ? `<h4>確率</h4><dl class="kv"><dt>${term("AI勝率")}</dt><dd>${pct(h.p_ai)}</dd>${h.p_place != null ? `<dt>${term("3着内率")}</dt><dd>${pct(h.p_place)}</dd>` : ""}</dl>` : ""}
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

// --- 展開 (the race replay, the same component as theater/)
let theaterLoaded = false;
function theaterView(r) {
  if (r.replay) {
    return `<p class="small sub" style="margin:0">各馬の巡航速度・スタミナ・最高速度・脚質と枠順でコースを走らせます。勝率はどこにも入力しておらず、「1000回走らせる」の勝率は走らせた結果を数えたものです（AI予想タブの「展開シミュ」と同じしくみ）。馬場は今日の発表に合わせてあり、再現の中で切り替えられます。</p>
    <iframe class="replay" src="${esc(r.replay)}" title="レース再現" loading="lazy"></iframe>`;
  }
  if (!theaterLoaded) {
    theaterLoaded = true;
    const s = document.createElement("script");
    s.type = "module"; s.src = "theater/player.js";
    document.head.appendChild(s);
  }
  return `<p class="small sub" style="margin:0">各馬の${term("脚質")}・末脚・スタミナでコースを走らせます。「もう一回」で毎回違うレースになり、何千回も走らせるとAI勝率どおりの割合で勝つように合わせてあります。ペースや馬場を変えると、得意不得意で勝率が動きます。</p>
    <div class="theater"><race-theater src="${esc(r.theater)}"></race-theater></div>`;
}

// The replay is its own page in a frame; grow the frame to the page's height.
function fitReplay() {
  const f = document.querySelector("iframe.replay");
  if (!f) return;
  const fit = () => { try { f.style.height = f.contentDocument.documentElement.scrollHeight + "px"; } catch { /* keep the CSS height */ } };
  f.addEventListener("load", () => {
    fit();
    try { new ResizeObserver(fit).observe(f.contentDocument.body); } catch { /* not same-origin */ }
  });
}

// --- AI予想
function aiView(r) {
  const hs = r.horses.filter((h) => h.p_ai != null).sort((a, b) => b.p_ai - a.p_ai);
  const max = Math.max(...hs.map((h) => Math.max(h.p_ai, h.p_market ?? 0)), 0.01);
  const hasNum = hs.some((h) => h.number), hasOdds = hs.some((h) => h.odds);
  const hasAb = hs.some((h) => h.p_ability != null), hasSim = hs.some((h) => h.sim);
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
    ${hasSim ? `<td class="r nw">${h.sim ? `<b>${pct(h.sim.win)}</b><div class="hs">稍重${pct(h.sim.win_soft, 0)}・重${pct(h.sim.win_heavy, 0)}</div>` : "–"}</td>` : ""}
    ${hasAb ? `<td class="r pc">${pct(h.p_ability)}</td>` : ""}
    ${hasOdds ? `<td class="r nw ${e >= 1.1 ? "sp" : ""}">${e != null ? e.toFixed(2) : "–"}</td>` : ""}
    <td class="r">${pct(h.sim?.place ?? h.p_place ?? h.p_sim_place, 0)}</td>
    <td class="c pc nw"><span class="sp">${pm ? "＋" + pm : ""}</span> <span class="sm">${mm ? "－" + mm : ""}</span></td></tr>`;
  }).join("");
  const value = hasOdds ? hs.filter((h) => ev(h) >= 1.1 && h.p_ai >= 0.03) : [];
  const gap = hasAb && hasOdds ? hs.filter((h) => h.p_market >= 0.03 || h.p_ability >= 0.05).sort((a, b) => Math.abs(b.p_ability - b.p_market) - Math.abs(a.p_ability - a.p_market)).slice(0, 2) : [];
  return `${hasOdds ? `<p style="margin:0">${value.length ? `AI勝率×単勝オッズが1.1を超えるのは ${value.map((h) => `<b>${h.number ?? ""} ${esc(h.name)}</b>（${ev(h).toFixed(2)}）`).join("、")} です。` : "AI勝率×単勝オッズが1.1を超える馬はいません。"}
    ${gap.length ? `過去の走りだけで見たAIと人気の差が大きいのは ${gap.map((h) => `<b>${esc(h.name)}</b>（走りだけ${pct(h.p_ability, 0)}・人気${pct(h.p_market, 0)}）`).join("、")}。` : ""}
    ${r.odds_time ? `<span class="small sub">オッズは${esc(r.odds_time.slice(5, 16).replace("-", "/"))}時点</span>` : ""}
    ${done(r) ? "" : `<button type="button" class="linkbtn" data-tab="bet">買い目タブ</button>に、オッズとAI勝率から見た券種ごとの買い方があります。`}</p>` : ""}
    <div class="tw"><table class="aitab"><thead><tr><th class="c">印</th>${hasNum ? `<th class="c">番</th>` : ""}<th>馬名</th>${hasOdds ? `<th class="r">単勝</th>` : ""}<th class="r">${term("AI勝率")}<div class="hs pc">下段は人気から見た勝率</div></th>${hasSim ? `<th class="r">展開シミュ<div class="hs">枠順・道悪込み</div></th>` : ""}${hasAb ? `<th class="r pc">走りだけ<div class="hs">オッズなしのAI</div></th>` : ""}${hasOdds ? `<th class="r">${term("期待値")}</th>` : ""}<th class="r">${term("3着内率")}</th><th class="c pc">データ</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="small sub" style="margin:0">${r.pipeline ? `AI勝率は、オッズを使わない新しい予想パイプラインの値です。過去の走りから出した基礎能力に、距離・コース・馬場・騎手などの条件適性と調教評価を足し、枠と脚質からの位置取り、ペース、前日までの馬場傾向を入れて、このレースを重馬場で10万回走らせて数えました。下段の「人気から見た勝率」は単勝オッズの逆数を合計100%に直した値です。「展開シミュ」の下段は、同じ計算を稍重と重でそれぞれ10万回やり直した勝率です（上段と3着内率は重）。${r.theater ? `<button type="button" class="linkbtn" data-tab="race">展開タブ</button>のレース再生は、このAI勝率どおりに勝つよう強さを合わせた別のシミュレーターです。` : ""}` : `AI勝率は、オッズを出発点に、過去の走りやペースの有利不利からオッズのずれを直した値です。「走りだけ」はオッズを使わず過去の走りだけで出した勝率で、人気とどれだけ違う見方をしているかの参考です（こちらは本命の的中率が1番人気より低い）。「人気から見た勝率」は単勝オッズの逆数を合計100%に直した値です。${hasSim ? `「展開シミュ」は勝率を入力に使わず、馬ごとのスタミナ・末脚・脚質と枠順、道悪の得意不得意からレースを稍重と重で各6000回走らせて数えた勝率です（過去350レースの検証で強気すぎた分をならした値）。` : ""}${hasSim ? "3着内率もこのシミュレーションの値です。" : ""}${r.replay ? `<button type="button" class="linkbtn" data-tab="race">レース再現タブ</button>で、このシミュレーションのレースを1回ずつ見られます。` : r.theater ? `<button type="button" class="linkbtn" data-tab="race">展開タブ</button>のレース再生は、AI勝率どおりに勝つよう強さを合わせた別のシミュレーターです${hasSim ? "" : "（3着内率はその結果）"}。` : ""}`}データの＋－は出馬表のチェック項目の数です。<a href="#about">計算方法</a></p>`;
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

const GOING = { "稍": "稍重", "不": "不良" };
function babaBlock(r) {
  const b = r.baba, f = r.forecast;
  if (!b && !f) return "";
  const prev = (b?.day_before || []);
  const turf = prev.filter((x) => x.surface === "芝"), last = prev[prev.length - 1];
  const now = turf.length ? turf[turf.length - 1] : null;
  const day = (b?.same_day || []), dturf = day.filter((x) => x.surface === "芝"), dnow = dturf[dturf.length - 1];
  return `<section class="blk"><h3>馬場と天気</h3>
    <dl class="kv">
      ${dnow ? `<dt>当日（日）の京都</dt><dd><b>芝 ${esc(GOING[dnow.going] ?? dnow.going)}</b>・天候 ${esc(day[day.length - 1].weather)}<span class="small sub">（${dnow.reported ? `${esc(dnow.reported)}。` : ""}${r.going_time ? `${esc(r.going_time)}に取得した` : ""}netkeibaの各レースの発表。${dturf.map((x) => `${x.r}R ${GOING[x.going] ?? x.going}`).join("・")}）</span></dd>` : ""}
      ${now ? `<dt>前日（土）の京都</dt><dd><b>芝 ${esc(GOING[now.going] ?? now.going)}</b>・天候 ${esc(last.weather)}<span class="small sub">（${last.r}Rの発表。${turf.map((x) => `${x.r}R ${GOING[x.going] ?? x.going}`).join("・")}）</span></dd>` : ""}
      ${f ? `<dt>当日（日）の予報</dt><dd><b>${esc(f.text)}</b><span class="small sub">（${esc(f.as_of)}時点、${f.sources.map((x) => `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.name)}</a>`).join("・")}）</span></dd>` : ""}
      ${b?.moisture ? `<dt>芝の含水率</dt><dd>ゴール前 ${b.moisture.turf[0]}%・4コーナー ${b.moisture.turf[1]}%<span class="small sub">（JRA発表の最新値${b.as_of ? `、${esc(b.as_of)}` : ""}）</span></dd>` : ""}
      ${b?.course ? `<dt>使用コース</dt><dd>${esc(b.course)}</dd>` : ""}
      ${b?.turf_note ? `<dt>芝の様子</dt><dd>${esc(b.turf_note)}</dd>` : ""}
    </dl>
    ${dnow ? `<p style="margin:0">今日の京都芝は<b>${esc(GOING[dnow.going] ?? dnow.going)}</b>の発表です（${dnow.r}Rの時点）。${["重", "不"].includes(dnow.going) ? (r.pipeline ? "AI予想タブのAI勝率は重馬場で計算した値なので、そのまま見てください。" : `下の「雨で重・不良になった場合」の表がそのまま当てはまります。${r.horses.some((h) => h.sim) ? "AI予想タブの「展開シミュ」は稍重と重の平均なので、重の列（下段）を重く見てください。" : ""}`) : dnow.going === "良" ? `${r.pipeline ? "AI予想タブのAI勝率は雨で重になる前提で計算しています。良馬場のままなら少し割り引いて見てください。" : (dturf.some((x) => x.going !== "良") ? "朝の道悪から良まで回復しました。" : "良馬場です。")}${!r.pipeline && r.horses.some((h) => h.sim) ? "AI予想タブの「展開シミュ」は稍重と重で計算したもので、良馬場では計算していません。シミュの数字は参考程度に見てください。" : ""}` : dnow.going === "稍" ? `${dturf.some((x) => x.going === "重") ? "朝の重から回復してきています。" : ""}${r.pipeline ? "雨が続く予報なので、AI予想タブのAI勝率は重馬場で計算しています。稍重で計算した勝率も「展開シミュ」の下段にあり、順位はほぼ変わりません。" : r.horses.some((h) => h.sim) ? "AI予想タブの「展開シミュ」は稍重と重の平均なので、稍重の列（上段）を重く見てください。" : ""}` : ""}</p>` : now ? `<p style="margin:0">前日（土）の京都芝は<b>${esc(GOING[now.going] ?? now.going)}</b>でした。${b?.turf ? `JRAの発表（${esc(b.as_of || "")}）も芝${esc(b.turf)}です。` : ""}当日の芝のレースが終わると、ここに当日の発表が出ます。</p>` : ""}
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
  if (!t.runs) return `<p class="sub">同じコースの過去データがありません。</p>${similarView(r)}`;
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
    </div>
    ${similarView(r)}`;
}

// --- 似た条件の直近レース（3着まで）と、その馬たちの共通点
function simTable(title, rows, label) {
  const ok = rows.filter((x) => x.n);
  if (!ok.length) return "";
  const max = Math.max(0.01, ...ok.map((x) => x.top3 ?? 0));
  const best = ok.filter((x) => x.n >= 8).sort((a, b) => b.top3 - a.top3)[0]?.key;
  return `<section class="blk"><h3>${title}</h3><div class="tw"><table><thead><tr><th></th><th></th><th class="r">3着内</th><th class="r">3着内率</th><th class="r">出走</th></tr></thead><tbody>
    ${ok.map((x) => `<tr><td class="nw">${label(x)}</td><td class="barcell"><div class="hb"><span class="tr"><i class="${x.key === best ? "hi" : ""}" style="width:${((x.top3 ?? 0) / max) * 100}%"></i></span></div></td>
      <td class="r nw"><b>${x.top3n}</b>頭</td><td class="r nw">${pct(x.top3, 0)}</td><td class="r nw sub">${x.n}</td></tr>`).join("")}</tbody></table></div></section>`;
}
function similarView(r) {
  const f1 = (x) => (x == null ? "–" : Number(x).toFixed(1));
  const S = r.similar;
  if (!S || !S.races?.length) return "";
  const m = S.summary;
  const dates = S.races.map((x) => x.date).sort();
  const sireSet = new Map(m.sires.map((x) => [x.key, x.n])), dsSet = new Map(m.damsires.map((x) => [x.key, x.n]));
  const topLine = (rows) => rows.filter((x) => x.n >= 8).sort((a, b) => b.top3 - a.top3)[0];
  const st = topLine(m.style), l3 = m.l3.find((x) => x.key === "1位"), l3b = m.l3.find((x) => x.key === "2〜3位");
  const ln = topLine(m.line), dl = topLine(m.dline), p1 = m.pop.find((x) => x.key === "1番人気");
  const facts = [
    st && `${term("脚質")}は<b>${st.key}</b>の3着内率がいちばん高い（${pct(st.top3, 0)}、平均${pct(m.base, 0)}）。`,
    l3 && l3b && `${term("上がり")}1位の馬は${l3.n}頭中${l3.top3n}頭、2〜3位は${l3b.n}頭中${l3b.top3n}頭が3着内。3着内の馬の上がりは平均${f1(m.top_l3)}秒${m.back3f ? `（レースの後半3Fは平均${f1(m.back3f)}秒${m.front3f ? `、前半3Fは${f1(m.front3f)}秒` : ""}）` : ""}。`,
    ln && `父の${term("系統")}は<b>${esc(ln.key)}</b>が3着内率${pct(ln.top3, 0)}（${ln.n}頭中${ln.top3n}頭）。`,
    dl && `母父の系統は<b>${esc(dl.key)}</b>が3着内率${pct(dl.top3, 0)}（${dl.n}頭中${dl.top3n}頭）。`,
    p1 && `1番人気は${p1.n}レースで3着内${p1.top3n}回。3着内${S.races.length * 3}頭のうち7番人気以下は${m.pop.find((x) => x.key === "7番人気以下")?.top3n ?? 0}頭。`,
  ].filter(Boolean);
  const hit = (h) => (sireSet.has(h.sire) ? 1 : 0) + (dsSet.has(h.damsire) ? 1 : 0);
  const rate = (rows, k) => rows.find((x) => x.key === k);
  const cell = (row) => (row && row.n >= 5 ? `<span class="${row.top3 >= m.base * 1.2 ? "sp" : row.top3 <= m.base * 0.8 ? "sm" : "sn"}">${pct(row.top3, 0)}</span>` : `<span class="sn">–</span>`);
  const all = r.horses.filter((h) => h.number || !r.horses.some((x) => x.number));
  if (!state.simf || state.simf.id !== r.race_id) state.simf = { id: r.race_id, style: [], line: [], dline: [], hit: false };
  const F = state.simf;
  const keep = (h) => (!F.style.length || F.style.includes(h.style ?? "–")) && (!F.line.length || F.line.includes(h.line ?? "–"))
    && (!F.dline.length || F.dline.includes(h.dline ?? "–")) && (!F.hit || sireSet.has(h.sire) || dsSet.has(h.damsire));
  const runners = all.filter(keep);
  const chipRow = (label, kind, rows, order) => {
    const keys = [...new Set(all.map((h) => h[kind] ?? "–"))].sort((a, b) => (order ? order.indexOf(a) - order.indexOf(b) : (rate(rows, b)?.top3 ?? 0) - (rate(rows, a)?.top3 ?? 0)));
    return `<div class="chips"><span class="lab">${label}</span>${keys.map((k) => {
      const row = rate(rows, k), n = all.filter((h) => (h[kind] ?? "–") === k).length;
      return `<button type="button" class="chip" data-simf="${kind}" data-key="${esc(k)}" aria-pressed="${F[kind].includes(k)}">${esc(k)}<small>${n}頭</small> ${row && row.n >= 5 ? cell(row) : ""}</button>`;
    }).join("")}</div>`;
  };
  const filters = `<div style="display:grid;gap:4px;margin:6px 0">
      ${chipRow(term("脚質"), "style", m.style, ["逃げ", "先行", "差し", "追込", "–"])}
      ${chipRow(`父の${term("系統")}`, "line", m.line)}
      ${chipRow("母父の系統", "dline", m.dline)}
      <div class="chips"><span class="lab">血統</span><button type="button" class="chip" data-simf="hit" aria-pressed="${F.hit}">似たレースの3着内にいる父・母父を持つ馬だけ</button>
        ${F.style.length || F.line.length || F.dline.length || F.hit ? `<button type="button" class="chip" data-simf="clear">絞り込みを解除</button>` : ""}
        <span class="sub">　${all.length}頭中<b>${runners.length}</b>頭を表示</span></div>
    </div>`;
  const match = `<div class="tw"><table class="mini" style="margin-top:0"><thead><tr><th>馬</th><th>父（系統）</th><th>母父（系統）</th><th>${term("脚質")}</th><th class="r">父系統の3着内率</th><th class="r">母父系統</th><th class="r">脚質</th></tr></thead><tbody>
    ${runners.map((h) => `<tr><td class="nw">${h.number ? waku(h.frame, h.number) + " " : ""}<b>${esc(h.name)}</b></td>
      <td class="nw">${sireSet.has(h.sire) ? "<b>" : ""}${esc(h.sire ?? "–")}${sireSet.has(h.sire) ? `</b><span class="sp">（3着内${sireSet.get(h.sire)}頭）</span>` : ""} ${h.line ? lineTag(h.line) : ""}</td>
      <td class="nw">${dsSet.has(h.damsire) ? "<b>" : ""}${esc(h.damsire ?? "–")}${dsSet.has(h.damsire) ? `</b><span class="sp">（3着内${dsSet.get(h.damsire)}頭）</span>` : ""} ${h.dline ? lineTag(h.dline) : ""}</td>
      <td class="nw">${esc(h.style ?? "–")}</td>
      <td class="r">${cell(rate(m.line, h.line))}</td><td class="r">${cell(rate(m.dline, h.dline))}</td><td class="r">${cell(rate(m.style, h.style))}</td></tr>`).join("")}
    </tbody></table></div>`;
  const list = S.races.map((x) => `<tr class="h"><td colspan="8" style="background:var(--head)"><b>${x.date.slice(0, 4)}/${md(x.date)} ${esc(short(title(x)))}</b>${gradeTag(x.grade)}
      <span class="small sub">　${esc(x.cls)}・${esc(x.going)}・${x.n}頭${x.front3f || x.back3f ? `・前半3F ${f1(x.front3f)} / 後半3F ${f1(x.back3f)}` : ""}</span></td></tr>
    ${x.top.map((t) => `<tr><td class="c fin f${t.finish}">${t.finish}</td><td class="nw">${t.number ? waku(t.frame, t.number) + " " : ""}${esc(t.name)}</td>
      <td class="r nw">${t.pop ?? "–"}人気<div class="hs">${t.odds ?? ""}倍</div></td>
      <td class="nw">${esc(t.style ?? "–")}<div class="hs">${esc(t.passing ?? "")}</div></td>
      <td class="r nw">${t.l3 != null ? t.l3.toFixed(1) : "–"}<div class="hs">${t.l3rank ? `${t.l3rank}位` : ""}</div></td>
      <td class="nw">${esc(t.sire ?? "–")}<div class="hs">${t.line ? lineTag(t.line) : ""}</div></td>
      <td class="nw">${esc(t.damsire ?? "–")}<div class="hs">${t.dline ? lineTag(t.dline) : ""}</div></td>
      <td class="nw small sub">${esc(t.jockey ?? "")}</td></tr>`).join("")}`).join("");
  return `<h2 class="sec" style="margin-top:18px">似た条件の直近${S.races.length}レース</h2>
    <p class="small sub" style="margin:0">${esc(r.venue)}${r.surface}${r.distance}m${r.course_note ? "（" + esc(r.course_note) + "）" : ""}で、クラスが近い（${esc(S.cls)}${m.class_gap ? "とその前後" : ""}）レースを、${esc(S.going)}馬場を優先して新しい順に選びました（${dates[0].replace(/-/g, "/")}〜${dates[dates.length - 1].replace(/-/g, "/")}）。各レースの3着までと、その馬たちの共通点です。</p>
    <ul class="facts">${facts.map((x) => `<li>${x}</li>`).join("")}</ul>
    <section class="blk"><h3>今回の出走馬と照らし合わせ</h3>
      <p class="small sub" style="margin:0">ボタンで脚質・系統を選ぶと、当てはまる馬だけに絞り込めます（同じ行の中は「または」、行どうしは「かつ」）。ボタンと右の3列の数字は、似たレースでその系統・脚質の馬が3着以内に入った割合（緑は平均${pct(m.base, 0)}の1.2倍以上、赤は0.8倍以下、5頭未満は–）。太字の父・母父は、似たレースの3着内に2頭以上いた種牡馬です。</p>
      ${filters}${runners.length ? match : `<p class="sub">条件に合う馬がいません。</p>`}</section>
    <div class="cols2">
      ${simTable(`父の${term("系統")}`, m.line, (x) => lineTag(x.key))}
      ${simTable("母父の系統", m.dline, (x) => lineTag(x.key))}
      ${simTable(term("脚質"), m.style, (x) => x.key)}
      ${simTable(`${term("上がり")}の順位`, m.l3, (x) => x.key)}
      ${simTable(term("人気"), m.pop, (x) => x.key)}
      ${simTable("枠", m.frame, (x) => x.key)}
      ${m.sires.length || m.damsires.length ? `<section class="blk"><h3>3着内に多い父・母父</h3><div class="tw"><table><thead><tr><th>父</th><th class="r">頭</th><th>母父</th><th class="r">頭</th></tr></thead><tbody>
        ${Array.from({ length: Math.max(m.sires.length, m.damsires.length) }, (_, i) => `<tr><td>${esc(m.sires[i]?.key ?? "")}</td><td class="r">${m.sires[i]?.n ?? ""}</td><td>${esc(m.damsires[i]?.key ?? "")}</td><td class="r">${m.damsires[i]?.n ?? ""}</td></tr>`).join("")}
        </tbody></table></div></section>` : ""}
    </div>
    <section class="blk"><h3>レースごとの3着まで</h3><div class="tw"><table class="simlist"><thead><tr><th>着</th><th>馬</th><th class="r">人気</th><th>脚質<div class="hs">通過順</div></th><th class="r">上がり<div class="hs">順位</div></th><th>父<div class="hs">系統</div></th><th>母父<div class="hs">系統</div></th><th>騎手</th></tr></thead>
      <tbody>${list}</tbody></table></div></section>`;
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
  const g = done(r) ? "" : guideView(r);
  return `${g || `<p class="sub" style="margin:0">このレースはAI勝率がないので、オッズから見た買い方は出していません。</p>`}
    <p class="small" style="margin:0">印と買い目づくりは<button type="button" class="linkbtn" data-tab="card">出馬表タブ</button>に移しました。</p>
    ${r.seg?.surface === "芝" || r.seg?.surface === "ダ" ? `<p class="small" style="margin:0">このレースと同じ条件（${esc([r.seg.surface, r.seg.field, r.seg.cls, r.seg.hande, r.seg.fav].filter(Boolean).join("・"))}）の過去レースで、どの買い方が当たりやすく戻りが多かったかを<a href="#strategy" id="to-strategy">買い方を比べる</a>で見られます。</p>` : ""}`;
}

// --- オッズとAI勝率から見た買い方
// Win probabilities -> top-2 and top-3 probabilities by the Harville formula
// (the chance of finishing 2nd is the win chance among the horses left).
function harville(p) {
  const n = p.length, top3 = new Array(n).fill(0), pair2 = {}, pair3 = {};
  const k = (a, b) => (a < b ? `${a}|${b}` : `${b}|${a}`);
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
    if (j === i) continue;
    const pij = p[i] * p[j] / (1 - p[i]);
    pair2[k(i, j)] = (pair2[k(i, j)] || 0) + pij;
    for (let l = 0; l < n; l++) {
      if (l === i || l === j) continue;
      const pijl = pij * p[l] / (1 - p[i] - p[j]);
      top3[i] += pijl; top3[j] += pijl; top3[l] += pijl;
      for (const [a, b] of [[i, j], [i, l], [j, l]]) pair3[k(a, b)] = (pair3[k(a, b)] || 0) + pijl;
    }
  }
  return { top3, pair2, pair3 };
}

const STRAT = {
  fav_win: "オッズ準拠モデルの本命・単勝", fav_place: "オッズ準拠モデルの本命・複勝", value_win: "期待値1.2以上の単勝",
  indep_win: "独自モデルの本命・単勝", indep_place: "独自モデルの本命・複勝",
  claude_gap_win: "独自モデルが市場の3倍評価（単勝）", claude_dirt_place: "ダート1番人気＋好材料2つ（複勝）", claude_dirt_win: "ダート1番人気＋好材料3つ（単勝）",
};

function guideView(r) {
  const hs = r.horses.filter((h) => h.number && h.p_ai != null && h.odds);
  if (!r.has_ai || hs.length < 3) return "";
  const sum = hs.reduce((a, h) => a + h.p_ai, 0), p = hs.map((h) => h.p_ai / sum);
  const hv = harville(p);
  const place = hs.map((h, i) => h.sim?.place ?? h.p_place ?? hv.top3[i]);
  const name = (h) => `${waku(h.frame, h.number)} ${esc(h.name)}`;
  const ev = (x) => `<b class="${x >= 1.1 ? "sp" : ""}">${x.toFixed(2)}</b>`;
  const fav = hs.reduce((a, h) => (h.p_ai > a.p_ai ? h : a));
  const win = hs.map((h, i) => ({ h, p: p[i], o: h.odds, e: p[i] * h.odds })).filter((x) => x.p >= 0.03).sort((a, b) => b.e - a.e).slice(0, 4);
  const plc = hs.map((h, i) => ({ h, p: place[i], o: h.place_odds?.[0], e: h.place_odds ? place[i] * h.place_odds[0] : null }))
    .filter((x) => x.e != null && x.p >= 0.15).sort((a, b) => b.e - a.e).slice(0, 4);
  const pairs = (kind, prob) => {
    const odds = r.pairs?.[kind] || {}, out = [];
    for (let i = 0; i < hs.length; i++) for (let j = i + 1; j < hs.length; j++) {
      const [a, b] = hs[i].number < hs[j].number ? [hs[i], hs[j]] : [hs[j], hs[i]];
      const o = odds[`${String(a.number).padStart(2, "0")}${String(b.number).padStart(2, "0")}`];
      const q = prob[i < j ? `${i}|${j}` : `${j}|${i}`];
      if (o && q >= 0.04) out.push({ a, b, p: q, o: o[0], e: q * o[0] });
    }
    return out.sort((x, y) => y.e - x.e).slice(0, 4);
  };
  const umaren = pairs("umaren", hv.pair2), wide = pairs("wide", hv.pair3);
  const row1 = (x) => `<tr><td class="nw">${name(x.h)}</td><td class="r">${pct(x.p)}</td><td class="r">${x.o ?? "–"}</td><td class="r">${x.e != null ? ev(x.e) : "–"}</td></tr>`;
  const row2 = (x) => `<tr><td class="nw">${waku(x.a.frame, x.a.number)}-${waku(x.b.frame, x.b.number)} <span class="small pc">${esc(short(x.a.name))}・${esc(short(x.b.name))}</span></td><td class="r">${pct(x.p)}</td><td class="r">${x.o}</td><td class="r">${ev(x.e)}</td></tr>`;
  const table = (title, rows, f, note) => rows.length ? `<h4 style="margin:10px 0 4px">${title}</h4><div class="tw"><table class="mini" style="margin:0"><thead><tr><th>買い目</th><th class="r">当たる確率</th><th class="r">オッズ</th><th class="r">期待値</th></tr></thead><tbody>${rows.map(f).join("")}</tbody></table></div>${note ? `<p class="small sub" style="margin:2px 0 0">${note}</p>` : ""}` : "";
  const mine = (r.bets || []).map((b) => `<li>${esc(STRAT[b.strategy] || b.strategy)}：${b.number}番 ${esc(b.name)}（${b.type}、買った時点の単勝${b.odds ?? "–"}倍）</li>`).join("");
  const anyValue = [...win, ...plc, ...umaren, ...wide].some((x) => x.e >= 1.1);
  return `<section class="blk"><h3>オッズとAI勝率から見た買い方</h3>
    <p style="margin:0">期待値は「当たる確率×オッズ」で、100円がAIの見立てで平均いくら戻るかです。JRAの取り分（単勝・複勝20%、馬連・ワイド22.5%）があるので、ふつうの馬券は0.8前後になります。${anyValue ? "<b>1.1を超える買い目（緑）</b>が、AIが人気より高く見ている所です。" : "今のオッズでは1.1を超える買い目はありません。期待値で選ぶなら、このレースは見送りか少額が妥当です。"}</p>
    <dl class="kv" style="margin-top:6px"><dt>基本の一点</dt><dd>${name(fav)}の複勝${fav.place_odds ? `（${fav.place_odds[0]}〜${fav.place_odds[1]}倍）` : ""}。${r.pipeline ? "先週末（11/7〜8）の69レースでは、AI本命の複勝は的中39回・回収率78%でした。" : "仮想ベット（10/18〜11/21の240レース）では、AI本命の複勝は的中率60%・回収率82%、単勝は的中率34%・回収率83%でした。"}</dd></dl>
    ${table("単勝", win, row1, "当たる確率はAI勝率。")}
    ${table("複勝", plc, row1, `当たる確率は3着内率${r.horses.some((h) => h.sim) ? "（展開シミュ）" : "（AI勝率から計算）"}、オッズは下限で計算。`)}
    ${table("馬連（期待値の高い組み合わせ）", umaren, row2, "")}
    ${table("ワイド（期待値の高い組み合わせ）", wide, row2, "馬連とワイドの確率は、AI勝率から「1着の馬を除いた残りで2着を決める」計算で出した近似です（人気馬どうしの組み合わせを少し高めに出す傾向があります）。ワイドのオッズは下限で計算。")}
    ${mine ? `<h4 style="margin:10px 0 4px">このレースで仮想ベットしている買い方</h4><ul class="facts small">${mine}</ul>` : ""}
    <p class="small sub" style="margin:6px 0 0">${r.pipeline ? "このAI勝率はオッズを使っていないので、確率の正確さは単勝オッズに届きません（2024年以降の芝4,743レースで対数損失2.078、確定オッズ1.906。本命の勝率は28.0%、1番人気は33.1%）。" : "AI勝率はオッズに近い精度で、オッズを大きく上回るほどではありません（仮想ベットの期待値買い（勝率×オッズ≧1.2）は20点で回収率57%）。"}期待値が1を超えても、モデルの誤差を考えると勝てる保証はありません。買い方ごとの過去の成績は<a href="#strategy">買い方を比べる</a>にあります。</p>
  </section>`;
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
    ["芝 全4,642レース", "AI（オッズなし）", "27.6%", "58.3%"], ["", "AI（オッズ補正）", "33.2%", "65.2%"], ["", "1番人気", "33.6%", "65.5%"],
    ["芝2200m以上 549レース", "AI（オッズなし）", "34.4%", "65.2%"], ["", "AI（オッズ補正）", "37.0%", "69.8%"], ["", "1番人気", "37.3%", "69.0%"],
  ].map((x) => `<tr><td>${x[0]}</td><td>${x[1]}</td><td class="r">${x[2]}</td><td class="r">${x[3]}</td></tr>`).join("");
  return `<h1 style="font-size:18px">AI勝率の仕組み</h1>
    <div class="prose"><p>AI勝率は「このメンバーで何度も走ったら、その馬が何回に1回勝つか」の見積もりです。出走馬全員分を足すとちょうど100%になります。オッズが出る前は過去の走りだけから出し、オッズが出たあとは、オッズを出発点にAIがずれを直した値に切り替えます。</p></div>
    <h2 class="sec">計算の手順</h2>
    <ol class="steps">
      <li><b>馬ごとの能力値を出す</b><p>過去の各レースで、その馬の平均速度が同じレースの真ん中の馬より何%速かったかを測ります。同じレースの中で比べるので、コースや馬場、ペースの違いは打ち消されます。一緒に走った相手を通じて全馬をつないで計算するので、G1で勝ち馬に迫った馬はG1級として評価されます。新しいレースほど重く数え、距離が延びたときに能力が上がるか下がるかも一緒に出します。</p></li>
      <li><b>項目にまとめる</b><p>能力値と距離の向き不向き、近5走の着順・人気・位置取り・上がり、休養明けの日数、距離の延長・短縮、斤量と枠、騎手の過去1年の成績、性別・年齢、出走数、獲得賞金、血統の長距離適性、重い馬場の得意不得意、それぞれ出走馬の平均との差などです。どれもそのレースより前のデータだけで計算しています。</p></li>
      <li><b>確率に直す</b><p>決定木をたくさん足し合わせるモデル（勾配ブースティング）で、どの組み合わせの馬が勝ちやすいかを学び、出走馬の中で比べて確率に直します。2018〜2022年のレースで学び、2023年のレースで学習の止めどころを決めました。</p></li>
      <li><b>オッズ補正（オッズが出たあと）</b><p>オッズには大勢の予想が集まっているので、オッズの確率を出発点にして、AIは過去の走りやペースの有利不利から「オッズのずれ」だけを直します。</p></li>
      <li><b>${term("展開")}で3着内率を出す</b><p>脚質・末脚・スタミナ・長距離・道悪の得意不得意を過去走から決め、AI勝率どおりの割合で勝つように強さを合わせたうえで、コースを何千回も走らせます。3着以内に入った割合が「3着内率」です。展開タブで同じレースを見られます。</p></li>
    </ol>
    <h2 class="sec">テストの成績</h2>
    <p class="small sub" style="margin:0">学習に使っていない2024年1月以降のレースで、AIがいちばん高い勝率をつけた馬（本命）の成績です（2026年10月14日時点）。オッズ補正は確定オッズで計算しています。</p>
    <div class="tw"><table><thead><tr><th>対象</th><th>予想</th><th class="r">本命が1着</th><th class="r">本命が3着内</th></tr></thead><tbody>${rows}</tbody></table></div>
    <h2 class="sec">わかっている弱点</h2>
    <div class="prose">
      <p>オッズを使わないAIの本命は、1番人気ほど当たりません。オッズ補正後の確率は、オッズそのものより少しだけ正確です（確率の当たり具合を測る対数損失が4,642レースで1.9093→1.9074）。本命が当たる割合はほぼ同じなので、このサイトでは「人気より当てる」ではなく、AIが人気より高く見ている馬（${term("期待値")}が1を超える馬）と、レース展開を見るための道具として使うことを想定しています。</p>
      <p>マイルチャンピオンシップ（2026年11月22日）と今日のレースのAI勝率は、仮想ベットと同じオッズ補正モデル（offset_pace2）の朝の予想です。マイルCSは、モデルの補正分（AIと人気のずれ）はそのままにして、人気の部分だけ10:58のオッズで計算し直しました。ページを開くたびに最新オッズで同じように動きます。「走りだけ」はオッズを使わない独自モデルです。芝マイルのG1（2015年以降81レース）では、人気馬はオッズどおりに勝っていて、上積みは見られません。</p>
      <p>調教とパドックはまだ入っていません。枠順が決まる前の予想では、枠を毎回くじ引きにして平均しています。</p>
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
  const bt = t.closest("[data-bet]");
  if (bt) { state.bet = bt.dataset.bet; store.set("bet", state.bet); const y = window.scrollY; render(); window.scrollTo(0, y); return; }
  const hw = t.closest("[data-how]");
  if (hw) { state.how = hw.dataset.how; store.set("how", state.how); const y = window.scrollY; render(); window.scrollTo(0, y); return; }
  const sf = t.closest("[data-simf]");
  if (sf && state.simf) {
    const k = sf.dataset.simf, F = state.simf;
    if (k === "hit") F.hit = !F.hit;
    else if (k === "clear") Object.assign(F, { style: [], line: [], dline: [], hit: false });
    else F[k] = F[k].includes(sf.dataset.key) ? F[k].filter((x) => x !== sf.dataset.key) : [...F[k], sf.dataset.key];
    const y = window.scrollY; render(); window.scrollTo(0, y); return;
  }
  const day = t.closest("[data-day]");
  if (day) { store.set("day:" + state.index.built, Number(day.dataset.day)); return render(); }
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
    const y = window.scrollY; render(); window.scrollTo(0, y); return;
  }
  if (t.id === "auto") {
    const r = state.race;
    const hs = r.has_ai ? r.horses.filter((h) => h.p_ai != null).sort((a, b) => b.p_ai - a.p_ai) : r.horses.filter((h) => h.pop).sort((a, b) => a.pop - b.pop);
    const ms = {};
    hs.slice(0, 5).forEach((h, i) => { ms[h.horse_id] = MARKS[i + 1]; });
    store.set("marks:" + r.race_id, ms);
    const y = window.scrollY; render(); window.scrollTo(0, y); return;
  }
  if (t.id === "to-strategy") { const g = state.race.seg; store.set("seg", { surface: g.surface, field: g.field, cls: g.cls, hande: g.hande, fav: g.fav || undefined }); return; }
  if (t.id === "clear") { store.set("marks:" + state.race.race_id, {}); const y = window.scrollY; render(); window.scrollTo(0, y); return; }
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
