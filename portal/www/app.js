// うまミル: race cards and predictions for beginners ("かんたん") and experts ("くわしく").
// Reads the JSON files written by portal/build.py. No framework; views are rebuilt on each change.

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x, d = 1) => (x == null ? "–" : (x * 100).toFixed(d) + "%");
const store = {
  get(k, d) { try { const v = localStorage.getItem("umamiru:" + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("umamiru:" + k, JSON.stringify(v)); } catch { /* storage unavailable */ } },
};

const GLOSSARY = {
  "勝率": "そのレースを100回走ったら何回勝つか、の見積もり。20%なら5回に1回勝つ計算です。",
  "AI勝率": "過去11年分のレースから学んだモデルが出した勝率。オッズ（人気）は使っていないので、人気との差を見るのに向いています。",
  "シミュ": "コースを再現した仮想レースで何千回も走らせ、勝った回数・3着以内に入った回数から出した確率。",
  "オッズ勝率": "単勝オッズから計算した、馬券を買った人たちの見立てでの勝率。オッズ2倍ならおよそ40%です。",
  "単勝": "1着になる馬を当てる馬券。いちばんシンプル。",
  "複勝": "3着以内に入る馬を当てる馬券（出走7頭以下は2着以内）。当たりやすいぶん配当は低め。",
  "馬連": "1着と2着の2頭を、順番を問わず当てる馬券。",
  "ワイド": "3着以内に入る2頭を当てる馬券。馬連より当たりやすい。",
  "馬単": "1着と2着を順番どおりに当てる馬券。",
  "三連複": "1〜3着の3頭を、順番を問わず当てる馬券。",
  "三連単": "1〜3着を順番どおりに当てる馬券。配当がいちばん大きい。",
  "枠": "スタート位置のグループ。1枠（白）が内側、8枠（ピンク）が外側。帽子の色と同じです。",
  "馬番": "馬ごとの番号。馬券はこの番号で買います。",
  "斤量": "馬が背負う重さ（騎手と鞍など）。重いほど不利とされます。",
  "上がり3F": "ゴールまで最後の600mにかかった時間。小さいほど最後の伸び（末脚）が鋭い。Fはハロン（約200m）。",
  "通過順": "コーナーごとの順位。「2-2-1-1」なら最初から前のほうにいたことがわかります。",
  "脚質": "レースでの位置取りの傾向。逃げ（先頭）、先行（前のほう）、差し（中団から）、追込（後方から）。",
  "系統": "父の血筋のグループ。同じ系統の馬は得意な距離や馬場が似やすいとされます。",
  "期待値": "AI勝率×単勝オッズ。1.0を超えると、AIの見立てでは長い目で見て得になる馬券です。",
  "人気": "馬券がどれだけ買われているかの順位。1番人気がいちばん買われている馬。",
  "馬場": "芝やダートの状態。良→稍重→重→不良の順に水分が多く、時計がかかります。",
  "回収率": "買った金額に対して戻ってきた金額の割合。100%を超えるとプラス。",
  "3着内率": "出走したうち3着以内に入った割合。",
  "印": "自分の予想のしるし。◎本命、○対抗、▲単穴、△連下、☆穴。タップで切り替わります。",
};
const MARKS = ["", "◎", "○", "▲", "△", "☆"];
const LINES = ["サンデー系", "ミスプロ系", "ノーザンダンサー系", "ロベルト系", "ナスルーラ系", "その他"];

const state = {
  mode: store.get("mode", "easy"),
  index: null,
  race: null,
  tab: null,
  day: 0,
  sort: { key: "p", dir: -1 },
  cols: store.get("cols", { past: true, ev: true, blood: true, body: true }),
  bet: store.get("bet", "ワイド"),
};

function term(word, label) {
  return `<span class="term" data-term="${esc(word)}" tabindex="0">${esc(label ?? word)}</span>`;
}
function q(word) {
  return `<button type="button" class="q" data-term="${esc(word)}" aria-label="${esc(word)}とは">?</button>`;
}
function waku(f, n) {
  return `<span class="waku w${f || 0}">${n ?? "–"}</span>`;
}
function grade(g) {
  return g ? `<span class="grade ${esc(g)}">${esc(g.replace("G1", "GⅠ").replace("G2", "GⅡ").replace("G3", "GⅢ"))}</span>` : "";
}
function lineChip(l) {
  return `<span class="line l-${esc(l)}">${esc(l)}</span>`;
}
function stars(p) {
  const n = p >= 0.25 ? 5 : p >= 0.15 ? 4 : p >= 0.08 ? 3 : p >= 0.04 ? 2 : 1;
  return `<span class="stars" aria-label="おすすめ度${n}">${"★".repeat(n)}${"☆".repeat(5 - n)}</span>`;
}
function jdate(s) {
  const d = new Date(s + "T00:00:00");
  return `${d.getMonth() + 1}月${d.getDate()}日（${"日月火水木金土"[d.getDay()]}）`;
}

async function getJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path} を読み込めませんでした（${r.status}）`);
  return r.json();
}

// ---------- probability helpers ----------
function marksFor(id) { return store.get("marks:" + id, {}); }
function oddsFor(id) { return store.get("odds:" + id, {}); }
function oddsOf(h) {
  const u = oddsFor(state.race.race_id)[h.horse_id];
  return u ? Number(u) : h.odds;
}
function mainP(h) { return h.p_ai ?? h.p_market ?? null; }
function mainLabel(r) { return r.has_ai ? "AI勝率" : "オッズ勝率"; }
function finished(r) { return r.horses.some((h) => h.finish); }

// ---------- views ----------
function setMode(m) {
  state.mode = m;
  store.set("mode", m);
  for (const b of document.querySelectorAll(".mode button")) b.setAttribute("aria-pressed", String(b.dataset.mode === m));
  if (state.race) state.tab = defaultTab(state.race);
  render();
}

function defaultTab(r) {
  return state.mode === "easy" ? "pick" : "card";
}

async function route() {
  hidePop();
  const h = location.hash.slice(1);
  if (!state.index) state.index = await getJSON("data/index.json");
  if (h.startsWith("r") && /^r\d+$/.test(h)) {
    const id = h.slice(1);
    if (!state.race || state.race.race_id !== id) {
      $("#view").innerHTML = `<p class="muted">読み込み中…</p>`;
      state.race = await getJSON(`data/race/${id}.json`);
      state.tab = defaultTab(state.race);
      state.sort = { key: "p", dir: -1 };
    }
  } else {
    state.race = null;
  }
  render();
  window.scrollTo(0, 0);
}

function render() {
  const h = location.hash.slice(1);
  const v = $("#view");
  if (state.race) v.innerHTML = raceView(state.race);
  else if (h === "glossary") v.innerHTML = glossaryView();
  else if (h === "about") v.innerHTML = aboutView();
  else v.innerHTML = homeView();
  document.title = state.race ? `${state.race.name} | うまミル` : "うまミル";
}

function homeView() {
  const idx = state.index;
  const easy = state.mode === "easy";
  const feat = idx.featured.map((r) => {
    const d = new Date(r.date + "T00:00:00");
    return `<a class="feature" href="#r${r.race_id}">
      <div class="date">${d.getMonth() + 1}月<b>${d.getDate()}</b>${"日月火水木金土"[d.getDay()]}曜</div>
      <div><h2>${esc(r.name.replace(/\(GI\)/, ""))}${grade(r.grade)}</h2>
        <p>${esc(r.venue)}${r.race_no}R　${r.surface}${r.distance}m（${r.direction}・${r.course_note}回り）　出走予定${r.n_runners}頭　AI予想あり</p></div>
      <div class="go">予想を見る →</div></a>`;
  }).join("");
  const day = idx.days[state.day] || idx.days[0];
  const tabs = idx.days.map((d, i) => `<button type="button" role="tab" data-day="${i}" aria-selected="${i === state.day}">${jdate(d.date)}</button>`).join("");
  const byVenue = {};
  for (const r of day.races) (byVenue[r.venue] ||= []).push(r);
  const venues = Object.entries(byVenue).map(([v, rs]) => `<div class="venue"><h3>${esc(v)}</h3>${rs.map((r) => `
      <a class="race-row" href="#r${r.race_id}"><span class="rno">${r.race_no}R</span>
        <span class="rname">${esc(r.name)}${grade(r.grade)}</span>
        <span class="rmeta">${r.surface}${r.distance}m・${r.n_runners}頭${r.going ? "・" + esc(r.going) : ""}</span></a>`).join("")}</div>`).join("");
  const hist = idx.history.slice().reverse().map((r) => `<a href="#r${r.race_id}">${r.date.slice(0, 4)}年 ${esc(r.venue)}</a>`).join("");
  return `
    <section class="intro">
      <h1>${easy ? "どの馬が来そう？を、わかる言葉で。" : "出馬表・指数・傾向をひとつの画面で。"}</h1>
      <p>${easy
        ? "勝つ確率と、その理由を短い文で出します。むずかしい言葉は点線の付いた文字をタップすると説明が出ます。慣れてきたら右上の「くわしく」へ。"
        : "近走・上がり順位・血統系統・騎手と種牡馬の成績・コース傾向・期待値を並べ替えながら比較できます。印と買い目、結果の答え合わせまでこの画面で完結します。"}</p>
    </section>
    ${feat}
    <section class="section-h"><h2>レース一覧</h2><span class="muted">結果が出ているレースは、予想と結果を見比べられます</span></section>
    <div class="tabs" role="tablist">${tabs}</div>
    <div class="venues">${venues}</div>
    <section class="section-h"><h2>過去の菊花賞</h2></section>
    <div class="history">${hist}</div>`;
}

function raceHeader(r) {
  const cond = [
    `<span><b>${r.surface}${r.distance}m</b>（${esc(r.direction || "")}${r.course_note ? "・" + esc(r.course_note) + "回り" : ""}）</span>`,
    r.start_time ? `<span>発走 <b class="num">${esc(r.start_time)}</b></span>` : "",
    `<span>${r.horses.length}頭</span>`,
    r.weather ? `<span>天候 ${esc(r.weather)}</span>` : "",
    r.going ? `<span>${term("馬場")} <b>${esc(r.going)}</b></span>` : "",
    r.class_text ? `<span class="muted">${esc(r.class_text)}</span>` : "",
  ].join("");
  return `<section class="race-h">
    <div class="crumb"><a href="#">トップ</a> ／ ${jdate(r.date)} ${esc(r.venue)}${r.race_no}R</div>
    <h1>${esc(r.name)}${grade(r.grade)}</h1>
    <div class="cond">${cond}</div>
  </section>${r.note ? `<div class="note">${esc(r.note)}</div>` : ""}`;
}

function raceView(r) {
  const tabs = [["pick", "予想"], ["card", "出馬表"], ["trend", "コース傾向"], ["bet", "印と買い目"]];
  if (finished(r)) tabs.push(["result", "結果"]);
  const body = { pick: pickView, card: cardView, trend: trendView, bet: betView, result: resultView }[state.tab](r);
  return `${raceHeader(r)}
    <div class="tabs" role="tablist">${tabs.map(([k, l]) => `<button type="button" role="tab" data-tab="${k}" aria-selected="${state.tab === k}">${l}</button>`).join("")}</div>
    ${body}`;
}

// --- 予想 (ranked cards with reasons)
function ranked(r) {
  return r.horses.slice().sort((a, b) => (mainP(b) ?? -1) - (mainP(a) ?? -1));
}

function pickView(r) {
  const hs = ranked(r);
  const done = finished(r);
  const label = mainLabel(r);
  const intro = r.has_ai
    ? `<div class="guide"><b>見方</b>　${term("AI勝率")}の高い順に並べています。緑のバーが勝つ確率、薄いバーが3着以内に入る確率（${term("シミュ", "シミュレーション")}）。○はプラス材料、△は気になる点です。</div>`
    : `<div class="guide"><b>見方</b>　このレースはAI予想の対象外のため、${term("オッズ勝率")}（みんなの見立て）の高い順に並べています。${done ? "右上のラベルが実際の着順です。" : ""}</div>`;
  const cards = hs.map((h, i) => {
    const p = mainP(h);
    const place = h.p_sim_place;
    const res = h.finish ? `<span class="result-chip ${h.finish <= 3 ? "hit" : ""}">${h.finish}着</span>` : (h.finish_raw && done ? `<span class="result-chip">${esc(h.finish_raw)}</span>` : "");
    return `<article class="pick" data-horse="${esc(h.horse_id)}">
      <div class="rank ${i === 0 ? "r1" : ""}">${i + 1}</div>
      <div class="pick-main">
        <div class="pick-head">${waku(h.frame, h.number)}<span class="name">${esc(h.name)}</span>${stars(p ?? 0)}${res}
          <span class="sub">${esc(h.sex ?? "")}${h.age ?? ""}・${esc(h.jockey ?? "騎手未定")}${h.pop ? `・${h.pop}番人気` : ""}</span></div>
        <div class="meters">
          <span>${state.mode === "easy" ? "勝つ確率" : label}</span><span class="meter"><i style="width:${Math.min(100, (p ?? 0) * 200)}%"></i></span><b class="num">${pct(p)}</b>
          ${place != null ? `<span>3着以内</span><span class="meter place"><i style="width:${place * 100}%"></i></span><b class="num">${pct(place)}</b>` : ""}
        </div>
        <ul class="points">${h.good.map((t) => `<li class="g">${esc(t)}</li>`).join("")}${h.warn.map((t) => `<li class="w">${esc(t)}</li>`).join("")}</ul>
      </div></article>`;
  }).join("");
  return `${intro}${easyBuy(r, hs)}<div class="picks">${cards}</div>`;
}

function easyBuy(r, hs) {
  const [a, b, c] = hs;
  if (!a || !b) return "";
  const name = (h) => `<b>${esc(h.name)}</b>${h.number ? `（${h.number}番）` : ""}`;
  let check = "";
  if (finished(r)) {
    const fuku = r.payouts.find((p) => p.type === "複勝" && Number(p.combo) === a.number);
    const wkey = [a.number, b.number].sort((x, y) => x - y).join("-");
    const wide = r.payouts.find((p) => p.type === "ワイド" && p.combo === wkey);
    check = `<p class="muted">答え合わせ：複勝は${fuku ? `<b>的中</b>（100円→${fuku.payout}円）` : "はずれ"}、ワイドは${wide ? `<b>的中</b>（100円→${wide.payout.toLocaleString()}円）` : "はずれ"}でした。</p>`;
  }
  return `<section class="easy-buy">
    <h3>迷ったら、この買い方</h3>
    <ol>
      <li>当たりやすさ重視：${name(a)}の${term("複勝")}（3着以内に入れば当たり）</li>
      <li>少し配当もほしい：${name(a)}と${name(b)}の${term("ワイド")}（2頭とも3着以内で当たり）</li>
      ${c ? `<li>大きく狙う：${name(a)}・${name(b)}・${name(c)}の${term("三連複")}（3頭が1〜3着を独占）</li>` : ""}
    </ol>
    ${check}
    <p class="muted" style="margin:0;font-size:13px">予想は確率の見積もりで、必ず当たるものではありません。馬券は余裕のある範囲で。</p>
  </section>`;
}

// --- 出馬表
function cardView(r) {
  return state.mode === "easy" ? easyCard(r) : proCard(r);
}

function easyCard(r) {
  const rows = r.horses.map((h) => {
    const last = h.past[0];
    return `<tr class="horse" data-horse="${esc(h.horse_id)}">
      <td>${waku(h.frame, h.number)}</td>
      <td><div class="hname">${esc(h.name)}</div><div class="hsub">${esc(h.sex ?? "")}${h.age ?? ""}　父 ${esc(h.sire ?? "?")}</div></td>
      <td>${esc(h.jockey ?? "未定")}</td>
      <td class="r num">${h.odds ? h.odds.toFixed(1) + "倍" : "–"}${h.pop ? `<div class="hsub">${h.pop}番人気</div>` : ""}</td>
      <td>${last ? `${last.finish_raw ?? "?"}着<div class="hsub">${esc(last.name)}</div>` : "初出走"}</td>
      <td>${lineChip(h.line)}</td>
    </tr>`;
  }).join("");
  return `<div class="guide"><b>見方</b>　馬名をタップすると、これまでの成績が見られます。${term("枠")}の色は騎手の帽子の色です。</div>
    <div class="scroll"><table>
      <thead><tr><th>${term("馬番")}</th><th>馬名</th><th>騎手</th><th class="r">オッズ</th><th>前走</th><th>${term("系統")}</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
}

function sortVal(h, key) {
  switch (key) {
    case "num": return h.number ?? 99;
    case "p": return mainP(h) ?? -1;
    case "sim": return h.p_sim ?? -1;
    case "mkt": return h.p_market ?? -1;
    case "odds": return oddsOf(h) ?? 9999;
    case "ev": return ev(h) ?? -1;
    case "jockey": return h.jockey_rec?.top3 ?? -1;
    case "sire": return h.sire_rec?.top3 ?? -1;
    case "l3": { const v = h.past.slice(0, 3).map((x) => x.l3rank).filter(Boolean); return v.length ? -Math.min(...v) : -99; }
    case "carried": return h.carried ?? 0;
    default: return 0;
  }
}
function ev(h) {
  const o = oddsOf(h);
  return h.p_ai != null && o ? h.p_ai * o : null;
}

function pastCell(x) {
  if (!x) return `<td class="muted">–</td>`;
  const f = x.finish;
  return `<td><div class="pr" title="${esc(x.date)} ${esc(x.name)}">
    <span class="f ${f && f <= 3 ? "f" + f : ""}">${f ?? esc(x.finish_raw ?? "?")}</span>
    <span>${esc(x.venue)}${x.surface}${x.distance} ${esc(x.going ?? "")}</span>
    <span>${x.pop ?? "-"}人 <span class="${x.l3rank === 1 ? "l3top" : ""}">上${x.l3 ?? "-"}(${x.l3rank ?? "-"})</span> ${x.behind != null && x.behind > 0 ? "+" + x.behind : ""}</span>
  </div></td>`;
}

function proCard(r) {
  const hs = r.horses.slice().sort((a, b) => state.sort.dir * (sortVal(a, state.sort.key) - sortVal(b, state.sort.key)) || (a.number ?? 0) - (b.number ?? 0));
  const marks = marksFor(r.race_id);
  const upcoming = !finished(r);
  const c = state.cols;
  const th = (key, label, cls = "") => `<th class="sort ${cls}" data-sort="${key}" aria-sort="${state.sort.key === key ? (state.sort.dir < 0 ? "descending" : "ascending") : "none"}">${label}</th>`;
  const rows = hs.map((h) => {
    const j = h.jockey_rec, s = h.sire_rec, e = ev(h);
    return `<tr class="horse" data-horse="${esc(h.horse_id)}">
      <td><button type="button" class="mark" data-mark="${esc(h.horse_id)}" aria-label="印">${marks[h.horse_id] || ""}</button></td>
      <td>${waku(h.frame, h.number)}</td>
      <td><div class="hname">${esc(h.name)}</div><div class="hsub">${esc(h.sex ?? "")}${h.age ?? ""} ${h.carried ?? ""}kg ${esc(h.style ?? "")}</div></td>
      ${c.blood ? `<td>${lineChip(h.line)}<div class="hsub">${esc(h.sire ?? "?")} / 母父 ${esc(h.damsire ?? "?")}</div></td>
        <td class="r num">${s ? pct(s.top3, 0) : "–"}<div class="hsub">${s ? s.n + "走 回収" + s.roi + "%" : ""}</div></td>` : ""}
      <td>${esc(h.jockey ?? "未定")}<div class="hsub num">${j ? `1年 ${pct(j.top3, 0)}（${j.n}騎乗）` : ""}</div></td>
      ${c.body ? `<td class="r num">${h.bw ?? "–"}<div class="hsub">${h.bw_diff != null ? (h.bw_diff > 0 ? "+" : "") + h.bw_diff : ""}</div></td>` : ""}
      <td class="r num">${upcoming && !h.odds
        ? `<input class="odds-in" id="odds-${esc(h.horse_id)}" data-odds="${esc(h.horse_id)}" inputmode="decimal" placeholder="オッズ" value="${esc(oddsFor(r.race_id)[h.horse_id] ?? "")}">`
        : `${h.odds ?? "–"}<div class="hsub">${h.pop ? h.pop + "人気" : ""}</div>`}</td>
      <td class="r num">${pct(h.p_market)}</td>
      ${r.has_ai ? `<td class="r num"><b>${pct(h.p_ai)}</b></td><td class="r num">${pct(h.p_sim)}</td>` : ""}
      ${c.ev && r.has_ai ? `<td class="r num ${e != null && e >= 1 ? "ev-hi" : ""}">${e != null ? e.toFixed(2) : "–"}</td>` : ""}
      ${c.past ? [0, 1, 2, 3, 4].map((i) => pastCell(h.past[i])).join("") : ""}
      ${!upcoming ? `<td class="r num"><b>${h.finish ?? esc(h.finish_raw ?? "")}</b></td>` : ""}
    </tr>`;
  }).join("");
  const toggles = [["past", "近5走"], ["blood", "血統"], ["ev", "期待値"], ["body", "馬体重"]]
    .filter(([k]) => k !== "ev" || r.has_ai)
    .map(([k, l]) => `<button type="button" class="chip" data-col="${k}" aria-pressed="${!!c[k]}">${l}</button>`).join("");
  return `<div class="cols"><span class="muted">表示する列</span>${toggles}
      <span class="muted" style="margin-left:auto">見出しをクリックで並べ替え　${q("印")}</span></div>
    ${upcoming && r.has_ai ? `<div class="guide"><b>期待値</b>　オッズが出たら入力すると、AI勝率×オッズで${term("期待値")}を計算します（入力はこの端末にだけ保存）。</div>` : ""}
    <div class="scroll"><table>
      <thead><tr><th>${term("印")}</th>${th("num", "番")}<th>馬名</th>
        ${c.blood ? `<th>${term("系統")}・父/母父</th>${th("sire", "父産駒<br>3着内", "r")}` : ""}
        ${th("jockey", "騎手（3着内率）")}
        ${c.body ? `<th class="r">馬体重</th>` : ""}
        ${th("odds", "単勝", "r")}${th("mkt", term("オッズ勝率", "市場"), "r")}
        ${r.has_ai ? th("p", term("AI勝率", "AI"), "r") + th("sim", term("シミュ"), "r") : ""}
        ${c.ev && r.has_ai ? th("ev", term("期待値"), "r") : ""}
        ${c.past ? `<th>前走</th><th>2走前</th><th>3走前</th><th>4走前</th><th>5走前</th>` : ""}
        ${!upcoming ? `<th class="r">着順</th>` : ""}</tr></thead>
      <tbody>${rows}</tbody></table></div>
    <p class="muted" style="font-size:12px;margin:0">近走の見方：大きな数字が着順、「上」は${term("上がり3F")}（カッコ内はレース内順位、1位は赤）、「+」は勝ち馬とのタイム差（秒）。父産駒3着内は同じ芝ダ・距離帯での過去5年。</p>`;
}

// --- コース傾向
function bars(rows, keyLabel, best) {
  const max = Math.max(0.01, ...rows.map((r) => r.top3 ?? 0));
  return `<div class="bars">${rows.map((r) => `
    <span>${keyLabel(r)}</span>
    <span class="meter ${r.key === best ? "best" : ""}"><i style="width:${((r.top3 ?? 0) / max) * 100}%"></i></span>
    <span class="num">${pct(r.top3, 0)} <span class="muted">(${r.n})</span></span>`).join("")}</div>`;
}

function trendView(r) {
  const t = r.trends;
  if (!t.runs) return `<p class="muted">同じコースの過去データがありません。</p>`;
  const bestOf = (rows, min = 8) => rows.filter((x) => x.n >= min).sort((a, b) => b.top3 - a.top3)[0];
  const bs = bestOf(t.style), bf = bestOf(t.frame);
  const inner = t.frame.filter((x) => x.key <= 4), outer = t.frame.filter((x) => x.key >= 5);
  const avg = (xs) => xs.reduce((s, x) => s + x.top3 * x.n, 0) / Math.max(1, xs.reduce((s, x) => s + x.n, 0));
  const p1 = t.popularity.find((x) => x.key === "1");
  const take = [
    bs ? `位置取りは<b>${bs.key}</b>の馬がいちばん3着以内に入っています（${pct(bs.top3, 0)}）。` : "",
    `内枠（1〜4枠）の3着内率は${pct(avg(inner), 0)}、外枠（5〜8枠）は${pct(avg(outer), 0)}です。`,
    p1 ? `1番人気は${p1.n}回中${Math.round(p1.win * p1.n)}勝、3着以内は${pct(p1.top3, 0)}。` : "",
    t.winner_l3 ? `勝ち馬の${term("上がり3F")}は平均${t.winner_l3}秒でした。` : "",
  ].filter(Boolean);
  const lineRows = t.line.filter((x) => x.n >= 5);
  return `<div class="guide"><b>集計の範囲</b>　${esc(r.venue)} ${r.surface}${r.distance}m${r.course_note ? "（" + esc(r.course_note) + "回り）" : ""}の過去5年、${t.races}レース・${t.runs}頭。少ないレース数の数字はぶれやすいので、カッコ内の頭数も見てください。</div>
    <section class="panel"><h3>${state.mode === "easy" ? "このコースのポイント" : "まとめ"}</h3><ul class="takeaways">${take.map((x) => `<li>${x}</li>`).join("")}</ul></section>
    <div class="trend-grid">
      <section class="panel"><h3>${term("枠")}別 3着内率</h3>${bars(t.frame, (x) => waku(x.key, x.key), bf?.key)}</section>
      <section class="panel"><h3>${term("脚質")}別 3着内率</h3>${bars(t.style.filter((x) => x.n), (x) => x.key, bs?.key)}</section>
      <section class="panel"><h3>${term("人気")}別 3着内率</h3>${bars(t.popularity, (x) => x.key + "番人気", null)}</section>
      <section class="panel"><h3>父の${term("系統")}別 3着内率</h3>${bars(lineRows, (x) => lineChip(x.key), bestOf(lineRows, 10)?.key)}</section>
    </div>
    ${state.mode === "pro" && t.sire.length ? `<section class="panel"><h3>種牡馬別（8走以上、3着内率順）</h3><div class="scroll" style="border:0"><table>
      <thead><tr><th>父</th><th class="r">出走</th><th class="r">勝率</th><th class="r">3着内率</th><th class="r">単勝${term("回収率")}</th></tr></thead>
      <tbody>${t.sire.map((s) => `<tr><td>${esc(s.key)}</td><td class="r num">${s.n}</td><td class="r num">${pct(s.win, 0)}</td><td class="r num">${pct(s.top3, 0)}</td><td class="r num">${s.roi}%</td></tr>`).join("")}</tbody></table></div></section>` : ""}`;
}

// --- 印と買い目
function combos(type, axis, others) {
  const out = [];
  if (type === "単勝" || type === "複勝") return [axis, ...others].filter(Boolean).map((h) => [h]);
  if (!axis) return out;
  if (type === "馬連" || type === "ワイド" || type === "馬単") return others.map((o) => [axis, o]);
  if (type === "三連複") {
    for (let i = 0; i < others.length; i++) for (let j = i + 1; j < others.length; j++) out.push([axis, others[i], others[j]]);
  }
  if (type === "三連単") {
    for (const a of others) for (const b of others) if (a !== b) out.push([axis, a, b]);
  }
  return out;
}
function comboKey(type, hs) {
  const ns = hs.map((h) => h.number);
  if (["馬連", "ワイド", "三連複"].includes(type)) ns.sort((a, b) => a - b);
  return ns.join("-");
}

function betView(r) {
  const marks = marksFor(r.race_id);
  const byMark = (m) => r.horses.filter((h) => marks[h.horse_id] === m);
  const axis = byMark("◎")[0];
  const others = ["○", "▲", "△", "☆"].flatMap(byMark);
  const type = state.bet;
  const list = combos(type, axis, others);
  const done = finished(r);
  let hitTotal = 0;
  const chips = list.map((c) => {
    const key = c[0].number ? comboKey(type, c) : null;
    const pay = key && r.payouts.find((p) => p.type === type && p.combo === key);
    if (pay) hitTotal += pay.payout;
    return `<span class="${pay ? "hit" : ""}">${c.map((h) => h.number ?? esc(h.name)).join(type === "馬単" || type === "三連単" ? "→" : "-")}${pay ? ` ${pay.payout.toLocaleString()}円` : ""}</span>`;
  }).join("");
  const cost = list.length * 100;
  const markRows = r.horses.slice().sort((a, b) => (a.number ?? 0) - (b.number ?? 0)).map((h) => `
    <tr><td><button type="button" class="mark" data-mark="${esc(h.horse_id)}" aria-label="印">${marks[h.horse_id] || ""}</button></td>
      <td>${waku(h.frame, h.number)}</td><td class="hname">${esc(h.name)}</td><td class="r num">${pct(mainP(h))}</td></tr>`).join("");
  const opts = ["単勝", "複勝", "馬連", "ワイド", "馬単", "三連複", "三連単"].map((t) => `<option ${t === type ? "selected" : ""}>${t}</option>`).join("");
  return `<div class="guide"><b>使い方</b>　${term("印")}をつけると買い目ができます。◎が軸（中心の馬）、○▲△☆が相手です。${done ? "結果が出ているレースは、当たった買い目が赤く表示されます。" : ""}</div>
    <div class="trend-grid">
      <section class="panel"><h3>印をつける</h3>
        <div class="cols"><button type="button" class="chip" id="auto-mark">予想の上位5頭に自動でつける</button><button type="button" class="chip" id="clear-mark">全部消す</button></div>
        <div class="scroll" style="border:0"><table><thead><tr><th>印</th><th>番</th><th>馬名</th><th class="r">${mainLabel(r)}</th></tr></thead><tbody>${markRows}</tbody></table></div>
      </section>
      <section class="panel"><h3>買い目</h3>
        <div class="bet-form"><label for="bet-type">券種</label><select id="bet-type">${opts}</select>${q(type)}</div>
        <p class="muted" style="margin:0">${type === "単勝" || type === "複勝" ? "印をつけた馬を1頭ずつ" : type === "三連単" ? "◎を1着に固定し、相手から2着・3着" : "◎から相手へ流し"}</p>
        <div><span class="big num">${list.length}</span> 点　<span class="num">${cost.toLocaleString()}円</span>（各100円）</div>
        <div class="combos">${chips || `<span class="muted" style="border:0">${axis || type === "単勝" || type === "複勝" ? "相手に印をつけてください" : "◎をつけてください"}</span>`}</div>
        ${done && list.length ? `<div>払戻 <b class="num">${hitTotal.toLocaleString()}円</b>（${term("回収率")} ${Math.round((hitTotal / cost) * 100)}%）</div>` : ""}
      </section>
    </div>`;
}

// --- 結果
function lapsSvg(laps) {
  const xs = laps.split("-").map((s) => parseFloat(s)).filter((x) => !isNaN(x));
  if (!xs.length) return "";
  const W = 640, H = 170, pad = 28, bw = (W - pad * 2) / xs.length;
  const lo = Math.floor(Math.min(...xs) - 0.5), hi = Math.ceil(Math.max(...xs));
  const y = (v) => H - 24 - ((hi - v) / (hi - lo)) * (H - 50);
  const bar = xs.map((v, i) => {
    const top = y(v);
    return `<rect x="${pad + i * bw + 2}" y="${top}" width="${bw - 4}" height="${H - 24 - top}" rx="2"></rect>
      <text x="${pad + i * bw + bw / 2}" y="${top - 4}" text-anchor="middle">${v.toFixed(1)}</text>
      <text x="${pad + i * bw + bw / 2}" y="${H - 8}" text-anchor="middle">${(i + 1) * 200}</text>`;
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="200mごとのラップタイム">${bar}</svg>`;
}

function resultView(r) {
  const hs = r.horses.slice().sort((a, b) => (a.finish ?? 99) - (b.finish ?? 99));
  const rows = hs.map((h) => `<tr class="horse" data-horse="${esc(h.horse_id)}">
    <td class="num"><b>${h.finish ?? esc(h.finish_raw ?? "")}</b></td><td>${waku(h.frame, h.number)}</td><td class="hname">${esc(h.name)}</td>
    <td>${esc(h.jockey ?? "")}</td><td class="r num">${h.time != null ? Math.floor(h.time / 60) + ":" + (h.time % 60).toFixed(1).padStart(4, "0") : "–"}</td>
    <td class="r num">${h.l3 ?? "–"}</td><td class="num">${esc(h.passing ?? "")}</td><td class="r num">${h.odds ?? "–"}</td><td class="r num">${h.pop ?? "–"}</td>
    <td class="r num">${pct(mainP(h))}</td></tr>`).join("");
  const pays = r.payouts.map((p) => `<tr><td>${term(p.type)}</td><td class="num">${esc(p.combo)}</td><td class="r num">${p.payout.toLocaleString()}円</td><td class="r num">${p.pop ?? ""}</td></tr>`).join("");
  return `<div class="scroll"><table><thead><tr><th>着</th><th>番</th><th>馬名</th><th>騎手</th><th class="r">タイム</th><th class="r">${term("上がり3F", "上がり")}</th><th>${term("通過順")}</th><th class="r">単勝</th><th class="r">人気</th><th class="r">${mainLabel(r)}</th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="trend-grid">
      ${r.laps ? `<section class="panel laps"><h3>ラップ（200mごと、秒）</h3>${lapsSvg(r.laps)}<p class="muted" style="margin:0;font-size:12px">棒が高いほど速い区間です。</p></section>` : ""}
      <section class="panel"><h3>払戻（100円あたり）</h3><div class="scroll" style="border:0"><table><thead><tr><th>券種</th><th>組み合わせ</th><th class="r">払戻</th><th class="r">人気</th></tr></thead><tbody>${pays}</tbody></table></div></section>
    </div>`;
}

// --- horse drawer
function horseDrawer(h) {
  const r = state.race;
  const rec = (a) => `<b>${a.join("-")}</b>`;
  const rows = h.past.map((x) => `<tr><td class="num">${esc(x.date)}</td><td>${esc(x.venue)}</td><td>${esc(x.name)}${grade(x.grade)}</td>
    <td>${x.surface}${x.distance}</td><td>${esc(x.going ?? "")}</td><td class="r num">${x.field ?? ""}</td><td class="r num">${x.pop ?? ""}</td>
    <td class="r num"><b>${x.finish ?? esc(x.finish_raw ?? "")}</b></td><td>${esc(x.jockey ?? "")}</td><td class="num">${esc(x.passing ?? "")}</td>
    <td class="r num ${x.l3rank === 1 ? "ev-hi" : ""}">${x.l3 ?? ""}</td><td class="r num">${x.behind ?? ""}</td><td class="r num">${x.bw ?? ""}</td></tr>`).join("");
  return `<h2 id="dr-title">${esc(h.name)}</h2>
    <div class="cond" style="display:flex;flex-wrap:wrap;gap:6px 14px;font-size:14px">
      <span>${esc(h.sex ?? "")}${h.age ?? ""}</span><span>騎手 ${esc(h.jockey ?? "未定")}</span><span>${esc(h.trainer ?? "")}${h.stable ? "（" + esc(h.stable) + "）" : ""}</span>
      <span>獲得賞金 <span class="num">${(h.prize ?? 0).toLocaleString()}</span>万円</span></div>
    <div>${lineChip(h.line)}　父 <b>${esc(h.sire ?? "?")}</b>　母父 <b>${esc(h.damsire ?? "?")}</b></div>
    <div class="recs">
      <div>全成績 ${rec(h.records.all)}</div>
      <div>${r.surface}・同距離帯 ${rec(h.records.band)}</div>
      <div>${esc(r.venue)}${r.surface} ${rec(h.records.course)}</div>
      <div>${r.surface}・稍重〜不良 ${rec(h.records.heavy)}</div>
    </div>
    <p class="muted" style="margin:0;font-size:12px">成績は「1着-2着-3着-4着以下」の回数。</p>
    ${h.good.length || h.warn.length ? `<ul class="points">${h.good.map((t) => `<li class="g">${esc(t)}</li>`).join("")}${h.warn.map((t) => `<li class="w">${esc(t)}</li>`).join("")}</ul>` : ""}
    <h3 style="margin:0">近走（最大10走）</h3>
    <div class="scroll"><table><thead><tr><th>日付</th><th>場</th><th>レース</th><th>距離</th><th>馬場</th><th class="r">頭</th><th class="r">人</th><th class="r">着</th><th>騎手</th><th>通過</th><th class="r">上がり</th><th class="r">差</th><th class="r">体重</th></tr></thead><tbody>${rows || `<tr><td colspan="13" class="muted">記録なし</td></tr>`}</tbody></table></div>`;
}
function openDrawer(id) {
  const h = state.race?.horses.find((x) => x.horse_id === id);
  if (!h) return;
  $("#drawer-body").innerHTML = horseDrawer(h);
  $("#drawer").hidden = false;
  $(".drawer-x").focus();
}
function closeDrawer() { $("#drawer").hidden = true; }

// --- glossary & about
function glossaryView() {
  return `<section class="intro"><h1>用語集</h1><p>サイト内の点線付きの言葉は、タップするとここと同じ説明が出ます。</p></section>
    <dl class="gloss">${Object.entries(GLOSSARY).map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>`;
}
function aboutView() {
  const rows = [
    ["芝 全4,642レース", "AI（勝率モデル）", "27.1%", "57.8%"],
    ["", "1番人気", "33.6%", "65.5%"],
    ["芝2400m以上 349レース", "シミュレーション", "28.4%", "64.5%"],
    ["", "AI（勝率モデル）", "30.9%", "65.9%"],
    ["", "1番人気", "39.5%", "70.2%"],
  ].map((r) => `<tr><td>${r[0]}</td><td>${r[1]}</td><td class="r num">${r[2]}</td><td class="r num">${r[3]}</td></tr>`).join("");
  return `<section class="intro"><h1>AIの成績</h1><p>予想サイトの多くは当たった話しか載せません。うまミルは、学習に使っていない期間でのテスト結果をそのまま出します。</p></section>
    <div class="scroll"><table><thead><tr><th>対象（2024年1月〜のテスト）</th><th>予想</th><th class="r">本命が1着</th><th class="r">本命が3着以内</th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="prose">
      <p>いまのAIは、本命の的中率ではまだ1番人気に届いていません。オッズにはたくさんの人の情報が集まっているためで、世界的にも「オッズを入れずに人気より当てる」モデルはまれです。</p>
      <p>そこでうまミルでは、AI勝率とオッズを並べて見せ、AIが人気よりも高く見ている馬（${term("期待値")}が1を超える馬）を探せるようにしています。モデルは「過去レースのデータ収集」「予想モデルの土台づくり」で改良を続けています。</p>
      <p class="muted">数字の出典：プロジェクトのデータ整理ノート（2026年10月14日時点）。</p>
    </div>`;
}

// ---------- popover ----------
function showPop(el) {
  const w = el.dataset.term, pop = $("#pop");
  const text = GLOSSARY[w];
  if (!text) return;
  pop.innerHTML = `<b>${esc(w)}</b>${esc(text)}`;
  pop.hidden = false;
  const r = el.getBoundingClientRect();
  const left = Math.min(window.scrollX + r.left, window.scrollX + document.documentElement.clientWidth - pop.offsetWidth - 16);
  pop.style.left = Math.max(16, left) + "px";
  pop.style.top = window.scrollY + r.bottom + 6 + "px";
}
function hidePop() { $("#pop").hidden = true; }

// ---------- events ----------
document.addEventListener("click", (ev) => {
  const t = ev.target;
  const termEl = t.closest("[data-term]");
  if (termEl) { ev.stopPropagation(); ev.preventDefault(); showPop(termEl); return; }
  hidePop();
  const m = t.closest(".mode button");
  if (m) return setMode(m.dataset.mode);
  const day = t.closest("[data-day]");
  if (day) { state.day = Number(day.dataset.day); return render(); }
  const tab = t.closest("[data-tab]");
  if (tab) { state.tab = tab.dataset.tab; return render(); }
  const mark = t.closest("[data-mark]");
  if (mark) {
    const id = state.race.race_id, ms = marksFor(id), cur = MARKS.indexOf(ms[mark.dataset.mark] || "");
    const next = MARKS[(cur + 1) % MARKS.length];
    if (next === "◎") for (const k in ms) if (ms[k] === "◎") delete ms[k];
    if (next) ms[mark.dataset.mark] = next; else delete ms[mark.dataset.mark];
    store.set("marks:" + id, ms);
    return render();
  }
  if (t.id === "auto-mark") {
    const ms = {};
    ranked(state.race).slice(0, 5).forEach((h, i) => { ms[h.horse_id] = MARKS[i + 1]; });
    store.set("marks:" + state.race.race_id, ms);
    return render();
  }
  if (t.id === "clear-mark") { store.set("marks:" + state.race.race_id, {}); return render(); }
  const col = t.closest("[data-col]");
  if (col) { state.cols[col.dataset.col] = !state.cols[col.dataset.col]; store.set("cols", state.cols); return render(); }
  const s = t.closest("th[data-sort]");
  if (s) {
    const k = s.dataset.sort;
    state.sort = state.sort.key === k ? { key: k, dir: -state.sort.dir } : { key: k, dir: k === "num" || k === "odds" ? 1 : -1 };
    return render();
  }
  if (t.closest("[data-close]")) return closeDrawer();
  if (t.closest("input, select, button")) return;
  const row = t.closest("[data-horse]");
  if (row) openDrawer(row.dataset.horse);
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") { hidePop(); closeDrawer(); }
  if (ev.key === "Enter" && ev.target.matches?.(".term")) showPop(ev.target);
});
document.addEventListener("change", (ev) => {
  const t = ev.target;
  if (t.id === "bet-type") { state.bet = t.value; store.set("bet", t.value); render(); }
  if (t.dataset?.odds) {
    const id = state.race.race_id, os = oddsFor(id);
    const v = parseFloat(t.value);
    if (v > 1) os[t.dataset.odds] = v; else delete os[t.dataset.odds];
    store.set("odds:" + id, os);
    render();
  }
});
window.addEventListener("hashchange", () => route().catch(showError));

function showError(e) {
  $("#view").innerHTML = `<p class="note">${esc(e.message)}。ページを再読み込みしてください。</p>`;
}

for (const b of document.querySelectorAll(".mode button")) b.setAttribute("aria-pressed", String(b.dataset.mode === state.mode));
route().catch(showError);
