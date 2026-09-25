const state = { league: "nfl", tab: "picks", board: null, picks: null, week: null };
const $ = (sel) => document.querySelector(sel);

const pct = (x, d = 1) => (x == null ? "–" : `${(x * 100).toFixed(d)}%`);
const signed = (x) => (x == null ? "" : x > 0 ? `+${x}` : `${x}`);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (x) => (x == null ? "–" : `${x < 0 ? "-" : ""}$${Math.abs(x).toFixed(2)}`);
const cls = (x) => (x > 0 ? "pos" : x < 0 ? "neg" : "");

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || res.statusText);
  return body;
}

function easternOffset(s) {
  // Rough US DST window (mid-March to early November) is plenty for kickoff display.
  const m = Number(s.slice(5, 7)), day = Number(s.slice(8, 10));
  const dst = (m > 3 && m < 11) || (m === 3 && day >= 10) || (m === 11 && day < 3);
  return dst ? "-04:00" : "-05:00";
}

function kickoff(s) {
  if (!s) return "";
  const bare = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(s);  // nflverse: Eastern time, no offset
  const d = new Date(bare ? `${s}:00${easternOffset(s)}` : s);
  return isNaN(d) ? s : d.toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function lineText(o) {
  if (o.line == null) return "ML";
  return o.market === "spread" ? signed(o.line) : o.line;
}

// ---- status -----------------------------------------------------------------------------------
async function loadStatus() {
  const s = await api("/api/status");
  const lg = s.leagues[state.league];
  const parts = [`${lg.games} games`];
  if (lg.refreshed_at) parts.push(`data ${new Date(lg.refreshed_at).toLocaleDateString()}`);
  if (!s.keys.odds_api) parts.push("no odds key");
  if (state.league === "cfb" && !s.keys.cfbd) parts.push("no CFBD key");
  $("#status").textContent = parts.join(" · ");
  return s;
}

// ---- board ------------------------------------------------------------------------------------
async function loadBoard(force = false) {
  const minEv = Number($("#min-ev").value) / 100;
  const kelly = $("#kelly").value;
  $("#board-alert").innerHTML = "";
  $("#value-bets").innerHTML = `<p class="muted">Loading…</p>`;
  $("#games").innerHTML = "";
  try {
    const b = await api(`/api/board/${state.league}?min_ev=${minEv}&kelly=${kelly}&force=${force}`);
    state.board = b;
    renderBoard(b);
  } catch (e) {
    $("#value-bets").innerHTML = "";
    $("#board-alert").innerHTML = `<div class="alert">${esc(e.message)}</div>`;
  }
}

function renderBoard(b) {
  const bankroll = Number($("#bankroll").value) || 0;
  const meta = [];
  if (b.odds_fetched_at) meta.push(`odds ${new Date(b.odds_fetched_at).toLocaleTimeString()}`);
  if (b.odds_remaining) meta.push(`${b.odds_remaining} API credits left`);
  $("#board-meta").textContent = meta.join(" · ");

  const alerts = [];
  if (b.odds_error) alerts.push(b.odds_error);
  if (b.unmatched.length) alerts.push(`Couldn't match ${b.unmatched.length} game(s) to team ratings: ${b.unmatched.slice(0, 5).join(", ")}${b.unmatched.length > 5 ? "…" : ""}`);
  $("#board-alert").innerHTML = alerts.map((a) => `<div class="alert">${esc(a)}</div>`).join("");

  if (!b.value_bets.length) {
    $("#value-bets").innerHTML = `<p class="muted">${b.odds_error ? "Add an Odds API key to compare against sportsbook prices." : "No bets clear your EV threshold right now. That's normal, because most lines are efficient."}</p>`;
  } else {
    $("#value-bets").innerHTML = `<div class="table-wrap"><table>
      <thead><tr><th>Game</th><th>Bet</th><th class="num">Price</th><th>Book</th>
        <th class="num">Model</th><th class="num">Market</th><th class="num">EV</th><th class="num">Stake</th><th></th></tr></thead>
      <tbody>${b.value_bets.map((o, i) => `<tr>
        <td>${esc(o.game)}<br><span class="muted">${kickoff(o.kickoff)}</span></td>
        <td>${esc(o.selection)} ${lineText(o)} ${o.caution ? '<span class="pill" title="Model disagrees with the market by 10%+. Check injuries and news before betting.">check news</span>' : ""}</td>
        <td class="num">${signed(o.price)}</td><td>${esc(o.book)}</td>
        <td class="num">${pct(o.model_prob)}</td><td class="num">${pct(o.market_prob)}</td>
        <td class="num pos">${pct(o.ev)}</td>
        <td class="num">${money(o.kelly * bankroll)}</td>
        <td><button class="secondary" data-track="${i}">Track</button></td>
      </tr>`).join("")}</tbody></table></div>`;
  }

  $("#games").innerHTML = b.games.map(renderGame).join("") || `<p class="muted">No upcoming games found.</p>`;
}

function renderGame(g) {
  const p = g.prediction;
  const offers = g.offers.length ? `<table>
      <thead><tr><th>Bet</th><th class="num">Best</th><th class="num">Model</th><th class="num">Mkt</th><th class="num">EV</th></tr></thead>
      <tbody>${g.offers.map((o) => `<tr class="${o.value ? "value-row" : ""}">
        <td>${esc(o.side === "home" ? g.home : o.side === "away" ? g.away : o.selection)} ${lineText(o)}</td>
        <td class="num" title="${esc(o.book)}">${signed(o.price)}</td>
        <td class="num">${pct(o.model_prob, 0)}</td><td class="num">${pct(o.market_prob, 0)}</td>
        <td class="num ${cls(o.ev)}">${pct(o.ev)}</td></tr>`).join("")}</tbody></table>`
    : `<div class="muted">Fair lines: ${esc(g.home)} ${signed(p.fair_home_spread)} · ML ${signed(p.fair_home_ml)} / ${signed(p.fair_away_ml)} · total ${p.total}</div>`;
  return `<div class="game">
    <div class="matchup"><span>${esc(g.away_name)} @ ${esc(g.home_name)}</span><span class="muted">${kickoff(g.kickoff)}</span></div>
    <div class="proj">Projected ${esc(g.away)} ${p.away_score.toFixed(0)} – ${esc(g.home)} ${p.home_score.toFixed(0)}${g.neutral ? " · neutral site" : ""}
      · ${esc(g.home)} wins ${pct(p.home_win_prob)}</div>
    <div class="bar"><div style="width:${(p.home_win_prob * 100).toFixed(1)}%"></div></div>
    ${offers}
  </div>`;
}

// ---- tracking bets ----------------------------------------------------------------------------
let pendingBet = null;
$("#value-bets").addEventListener("click", (e) => {
  const i = e.target.dataset.track;
  if (i == null) return;
  const o = state.board.value_bets[i];
  openTrack(o, o.kelly * (Number($("#bankroll").value) || 0));
});

function openTrack(bet, stake) {
  pendingBet = bet;
  $("#bet-desc").textContent = `${bet.game}: ${bet.selection} ${lineText(bet)}${bet.book ? ` (${bet.book})` : ""}`;
  const f = $("#bet-form");
  f.price.value = bet.price;
  f.stake.value = stake.toFixed(2);
  f.notes.value = "";
  $("#bet-dialog").showModal();
}

$("#bet-dialog").addEventListener("close", async () => {
  if ($("#bet-dialog").returnValue !== "save" || !pendingBet) return;
  const f = $("#bet-form");
  const o = pendingBet;
  await api("/api/bets", {
    method: "POST",
    body: JSON.stringify({
      league: state.league, game: o.game, market: o.market, selection: o.selection,
      line: o.line, price: Number(f.price.value), stake: Number(f.stake.value),
      model_prob: o.model_prob, book: o.book, notes: f.notes.value || null,
    }),
  });
  pendingBet = null;
});

async function loadBets() {
  const { bets, summary: s } = await api("/api/bets");
  $("#bets-summary").innerHTML = [
    ["Bets", s.count], ["Record (W-L-P)", s.record], ["Staked", money(s.staked)],
    ["Profit", `<span class="${cls(s.profit)}">${money(s.profit)}</span>`], ["ROI", pct(s.roi)],
    ["Expected profit", money(s.expected_profit)],
  ].map(([k, v]) => `<div class="card"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");

  const settled = bets.filter((b) => b.result !== "pending").sort((a, b) => a.id - b.id);
  const chart = $("#bets-chart");
  chart.hidden = settled.length < 2;
  if (settled.length >= 2) {
    let run = 0;
    const pts = settled.map((b) => ({ label: `${b.created_at.slice(0, 10)} · ${b.selection}`, y: (run += b.profit) }));
    lineChart(chart, pts, { title: "Cumulative profit", fmt: money, baseline: 0 });
  }

  $("#bets").innerHTML = bets.length ? `<div class="table-wrap"><table>
    <thead><tr><th>Date</th><th>Game</th><th>Bet</th><th class="num">Price</th><th class="num">Stake</th>
      <th class="num">Model EV</th><th>Result</th><th class="num">P/L</th><th></th></tr></thead>
    <tbody>${bets.map((b) => `<tr>
      <td>${esc(b.created_at.slice(0, 10))}</td><td>${esc(b.league.toUpperCase())} · ${esc(b.game)}</td>
      <td>${esc(b.selection)} ${b.line == null ? "ML" : b.market === "spread" ? signed(b.line) : b.line}</td>
      <td class="num">${signed(b.price)}</td><td class="num">${money(b.stake)}</td>
      <td class="num">${pct(b.ev)}</td>
      <td><select data-settle="${b.id}">${["pending", "win", "loss", "push"].map((r) => `<option ${r === b.result ? "selected" : ""}>${r}</option>`).join("")}</select></td>
      <td class="num ${cls(b.profit)}">${money(b.profit)}</td>
      <td><button class="secondary" data-delete="${b.id}">✕</button></td>
    </tr>`).join("")}</tbody></table></div>`
    : `<p class="muted">No tracked bets yet. Click "Track" on a value bet to log it. Tracking every bet is how you find out whether the model really has an edge.</p>`;
}

$("#bets").addEventListener("change", async (e) => {
  const id = e.target.dataset.settle;
  if (!id) return;
  await api(`/api/bets/${id}`, { method: "PATCH", body: JSON.stringify({ result: e.target.value }) });
  loadBets();
});
$("#bets").addEventListener("click", async (e) => {
  const id = e.target.dataset.delete;
  if (!id || !confirm("Delete this bet?")) return;
  await api(`/api/bets/${id}`, { method: "DELETE" });
  loadBets();
});

// ---- ratings & team detail ---------------------------------------------------------------------
async function loadRatings() {
  $("#ratings").innerHTML = `<p class="muted">Loading…</p>`;
  try {
    const rows = await api(`/api/ratings/${state.league}`);
    state.teams = rows.map((r) => r.team);
    $("#ratings").innerHTML = `<div class="table-wrap"><table>
      <thead><tr><th>#</th><th>Team</th><th class="num">Elo</th><th class="num">Pts vs avg</th>
        <th class="num">Off</th><th class="num">Def</th>${state.league === "nfl" ? "<th>QB</th>" : ""}</tr></thead>
      <tbody>${rows.map((r, i) => `<tr class="clickable" data-team="${esc(r.team)}"><td>${i + 1}</td><td>${chip(r.team)}</td>
        <td class="num">${r.elo}</td><td class="num">${signed(r.pts_vs_avg)}</td>
        <td class="num">${signed(r.off)}</td><td class="num">${signed(r.def)}</td>
        ${state.league === "nfl" ? `<td>${esc(r.qb || "")}</td>` : ""}</tr>`).join("")}</tbody></table></div>`;
  } catch (e) {
    $("#ratings").innerHTML = `<div class="alert">${esc(e.message)}</div>`;
  }
}

$("#ratings").addEventListener("click", (e) => {
  const row = e.target.closest("tr[data-team]");
  if (!row) return;
  document.querySelectorAll("#ratings tr.selected").forEach((r) => r.classList.remove("selected"));
  row.classList.add("selected");
  loadTeam(row.dataset.team);
});

function atsResult(p, team) {
  if (!p.completed || p.market_home_spread == null) return "";
  const isHome = p.home === team;
  const margin = (p.home_score - p.away_score) * (isHome ? 1 : -1);
  const cover = margin + (isHome ? p.market_home_spread : -p.market_home_spread);
  return cover === 0 ? "push" : cover > 0 ? "win" : "loss";
}

async function loadTeam(team) {
  const el = $("#team-detail");
  el.innerHTML = `<p class="muted">Loading ${esc(team)}…</p>`;
  const t = await api(`/api/team/${state.league}/${encodeURIComponent(team)}`);
  el.innerHTML = `<div class="chart-title">${esc(t.team)} · Elo ${t.rating.elo} (${signed(t.rating.pts_vs_avg)} pts vs average)</div>
    <div id="team-chart"></div>
    <h2>Recent &amp; upcoming games</h2>
    <div class="table-wrap"><table>
      <thead><tr><th>Date</th><th>Opponent</th><th>Score</th><th class="num">Line</th><th>ATS</th><th>Model pick</th></tr></thead>
      <tbody>${t.games.slice().reverse().map((p) => {
        const home = p.home === team, opp = home ? p.away : p.home;
        const line = p.market_home_spread == null ? "" : signed(home ? p.market_home_spread : -p.market_home_spread);
        const us = home ? p.home_score : p.away_score, them = home ? p.away_score : p.home_score;
        const score = p.completed ? `${us > them ? "W" : us < them ? "L" : "T"} ${us}-${them}` : `proj ${home ? p.proj_home : p.proj_away}-${home ? p.proj_away : p.proj_home}`;
        const ats = atsResult(p, team);
        const sp = p.spread;
        return `<tr><td>${esc(kickoff(p.kickoff).split(",").slice(0, 2).join(","))}</td><td>${home ? "vs" : "@"} ${esc(opp)}</td>
          <td>${score}</td><td class="num">${line}</td><td>${ats ? `<span class="res res-${ats}">${ats.toUpperCase()}</span>` : ""}</td>
          <td>${sp ? `${esc(sp.team)} ${signed(sp.line)} ${sp.result ? `<span class="res res-${sp.result}">${sp.result === "win" ? "✓" : sp.result === "loss" ? "✗" : "P"}</span>` : ""}` : ""}</td></tr>`;
      }).join("")}</tbody></table></div>`;
  lineChart($("#team-chart"), t.history.map((h) => ({ label: h.date, y: h.elo })),
    { fmt: (v) => Math.round(v), baseline: 1500, seasonTicks: true });
}

// ---- backtest ---------------------------------------------------------------------------------
async function runBacktest() {
  const btn = $("#run-backtest");
  btn.disabled = true;
  $("#backtest").innerHTML = `<p class="muted">Replaying history…</p>`;
  try {
    const start = $("#bt-start").value;
    const ev = Number($("#bt-ev").value) / 100;
    const r = await api(`/api/backtest/${state.league}?min_ev=${ev}${start ? `&start=${start}` : ""}`);
    const a = r.accuracy;
    const row = (name, s) => `<tr><td>${name}</td><td class="num">${s.bets}</td><td class="num">${s.wins}-${s.losses}-${s.pushes}</td>
      <td class="num">${pct(s.win_pct)}</td><td class="num ${cls(s.units)}">${signed(s.units)}</td><td class="num ${cls(s.roi)}">${pct(s.roi)}</td></tr>`;
    const head = `<thead><tr><th>Market</th><th class="num">Bets</th><th class="num">W-L-P</th><th class="num">Win %</th><th class="num">Units</th><th class="num">ROI</th></tr></thead>`;
    $("#backtest").innerHTML = `
      <h2>Results: seasons ${r.start_season}+ (${r.games_evaluated} games)</h2>
      <div class="table-wrap"><table>${head}<tbody>${Object.entries(r.markets).map(([m, s]) => row(m, s)).join("")}</tbody></table></div>

      <h2>Model vs. market accuracy</h2>
      <p class="muted">If the market's error is lower than the model's, the model is not yet sharper than the books. That's the main thing to improve.</p>
      <div class="table-wrap"><table>
        <thead><tr><th>Measure</th><th class="num">Model</th><th class="num">Market</th></tr></thead>
        <tbody>
          <tr><td>Margin mean abs. error (pts)</td><td class="num">${a.model_margin_mae}</td><td class="num">${a.market_margin_mae ?? "–"}</td></tr>
          <tr><td>Total mean abs. error (pts)</td><td class="num">${a.model_total_mae}</td><td class="num">${a.market_total_mae ?? "–"}</td></tr>
          <tr><td>Moneyline Brier score</td><td class="num">${a.model_brier}</td><td class="num">${a.market_brier ?? "–"}</td></tr>
          <tr><td>Margin std dev (observed / assumed)</td><td class="num">${a.observed_margin_sd}</td><td class="num">${a.assumed_margin_sd}</td></tr>
          <tr><td>Total std dev (observed / assumed)</td><td class="num">${a.observed_total_sd}</td><td class="num">${a.assumed_total_sd}</td></tr>
        </tbody></table></div>

      <h2>Win-probability calibration</h2>
      <div class="table-wrap"><table>
        <thead><tr><th>Predicted</th><th class="num">Games</th><th class="num">Avg predicted</th><th class="num">Actual</th></tr></thead>
        <tbody>${r.calibration.map((c) => `<tr><td>${c.bucket}</td><td class="num">${c.games}</td><td class="num">${pct(c.predicted)}</td><td class="num">${pct(c.actual)}</td></tr>`).join("")}</tbody></table></div>

      <h2>By season</h2>
      <div class="table-wrap"><table>
        <thead><tr><th>Season</th><th>Market</th><th class="num">Bets</th><th class="num">W-L-P</th><th class="num">Win %</th><th class="num">Units</th><th class="num">ROI</th></tr></thead>
        <tbody>${Object.entries(r.by_season).flatMap(([season, ms]) => Object.entries(ms).map(([m, s]) =>
          `<tr><td>${season}</td>${row(m, s).slice(4)}`)).join("")}</tbody></table></div>`;
  } catch (e) {
    $("#backtest").innerHTML = `<div class="alert">${esc(e.message)}</div>`;
  } finally {
    btn.disabled = false;
  }
}

// ---- team colors ------------------------------------------------------------------------------
const NFL_COLORS = {
  ARI: "#97233F", ATL: "#A71930", BAL: "#241773", BUF: "#00338D", CAR: "#0085CA", CHI: "#0B162A",
  CIN: "#FB4F14", CLE: "#311D00", DAL: "#041E42", DEN: "#FB4F14", DET: "#0076B6", GB: "#203731",
  HOU: "#03202F", IND: "#002C5F", JAX: "#006778", KC: "#E31837", LV: "#000000", LAC: "#0080C6",
  LA: "#003594", MIA: "#008E97", MIN: "#4F2683", NE: "#002244", NO: "#D3BC8D", NYG: "#0B2265",
  NYJ: "#125740", PHI: "#004C54", PIT: "#FFB612", SF: "#AA0000", SEA: "#002244", TB: "#D50A0A",
  TEN: "#0C2340", WAS: "#5A1414",
};

function teamColor(team) {
  if (state.league === "nfl" && NFL_COLORS[team]) return NFL_COLORS[team];
  // College: a stable color per school name
  let h = 0;
  for (const ch of team) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return `hsl(${h % 360} 55% 36%)`;
}

function inkFor(bg) {
  if (!bg.startsWith("#")) return "#fff";
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(bg.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.4 ? "#111" : "#fff";
}

const chip = (team) => {
  const c = teamColor(team);
  return `<span class="chip" style="--c:${c};--t:${inkFor(c)}">${esc(team)}</span>`;
};
const teamsLine = (away, home, neutral) => `${chip(away)}<span class="at">${neutral ? "vs" : "@"}</span>${chip(home)}`;

function winBar(away, home, pHome) {
  return `<div class="wp" role="img" aria-label="${esc(home)} ${pct(pHome, 0)} to win">
      <div style="width:${((1 - pHome) * 100).toFixed(1)}%;background:${teamColor(away)}"></div>
      <div style="width:${(pHome * 100).toFixed(1)}%;background:${teamColor(home)}"></div></div>
    <div class="wp-labels"><span>${esc(away)} ${pct(1 - pHome, 0)}</span><span>${esc(home)} ${pct(pHome, 0)}</span></div>`;
}

// ---- weekly picks ------------------------------------------------------------------------------
const TIER_LABEL = { best: "★ Best", lean: "Lean", caution: "⚠ Check news", pass: "Pass" };
const TIER_TIPS = {
  best: "Model differs from the line by 3-6 pts, the range where it has historically done best",
  lean: "Small disagreement with the line; historically close to a coin flip",
  caution: "Model disagrees with the market by 6+ pts. The market usually knows something (injury, QB news). Check before betting.",
  pass: "Model agrees with the line; no bet",
};
const tierBadge = (t) => `<span class="tier tier-${t}" title="${esc(TIER_TIPS[t])}">${TIER_LABEL[t]}</span>`;
const resBadge = (r) => (r ? `<span class="res res-${r}">${r.toUpperCase()}</span>` : "");
const rec = (b) => (b ? `${b.wins}-${b.losses}${b.pushes ? `-${b.pushes}` : ""}` : "–");
const BREAK_EVEN = 0.524;
const unitSize = () => (Number($("#bankroll").value) || 0) * 0.01;

async function loadPicks(week = state.week) {
  $("#picks-alert").innerHTML = "";
  $("#picks").innerHTML = `<p class="muted">Loading picks…</p>`;
  try {
    const r = await api(`/api/picks/${state.league}${week ? `?week=${encodeURIComponent(week)}` : ""}`);
    state.picks = r;
    state.week = r.week.id;
    renderPicks(r);
  } catch (e) {
    $("#picks").innerHTML = "";
    $("#picks-hero").innerHTML = "";
    $("#best-bets").innerHTML = "";
    $("#picks-alert").innerHTML = `<div class="alert">${esc(e.message)}</div>`;
  }
}

function meter(p, { breakEven = true } = {}) {
  if (p == null) return "";
  const lo = 0.4, hi = breakEven ? 0.6 : 0.8;
  const pos = (x) => `${(Math.max(0, Math.min(1, (x - lo) / (hi - lo))) * 100).toFixed(1)}%`;
  const cls = !breakEven ? "info" : p >= BREAK_EVEN ? "above" : "";
  return `<div class="meter"><div class="fill ${cls}" style="width:${pos(p)}"></div>
      ${breakEven ? `<div class="be" style="left:${pos(BREAK_EVEN)}" title="Break-even 52.4%"></div>` : ""}</div>
    <div class="meter-scale"><span>${pct(lo, 0)}</span>${breakEven ? "<span>break-even 52.4%</span>" : ""}<span>${pct(hi, 0)}</span></div>`;
}

function trackCard(title, all, recent, opts = {}) {
  return `<div class="card ${opts.accent ? "accent" : ""}"><div class="k">${title}</div>
    <div class="v">${pct(all?.win_pct)}</div>
    ${meter(all?.win_pct, opts)}
    <div class="sub">${all ? `${rec(all)} all-time` : "no history"}${recent ? ` · ${pct(recent.win_pct)} last 5 seasons` : ""}
      ${opts.units && all ? `<br>${signed(all.units)} units all-time` : ""}</div></div>`;
}

function dateRange(r) {
  const days = r.picks.map((p) => p.kickoff).filter(Boolean).sort();
  if (!days.length) return "";
  const f = (s) => kickoff(s).split(",").slice(0, 2).join(",");
  const a = f(days[0]), b = f(days[days.length - 1]);
  return a === b ? a : `${a} – ${b}`;
}

function renderHero(r) {
  const n = r.picks.length, done = r.picks.filter((p) => p.completed).length;
  const caution = r.picks.filter((p) => p.spread?.tier === "caution").length;
  const bbw = r.best_bets_week;
  $("#picks-hero").innerHTML = `<div class="hero">
    <div><div class="hero-k">${r.league.toUpperCase()} · ${r.week.season} season</div>
      <div class="hero-t">${esc(r.week.label)}</div>
      <div class="hero-sub">${esc(dateRange(r))} · ${n} games</div></div>
    <div class="hero-stats">
      <div class="hero-stat"><b>${r.best_bets.length}</b><span>Best bets</span></div>
      <div class="hero-stat"><b>${caution}</b><span>Check news</span></div>
      <div class="hero-stat"><b>${done}/${n}</b><span>Final</span></div>
      ${bbw.wins + bbw.losses ? `<div class="hero-stat"><b>${rec(bbw)}</b><span>Best bets this week</span></div>` : ""}
    </div></div>`;
}

function renderBestBets(r) {
  const hist = r.history.all_time.best_bets, recent = r.history.recent.best_bets, season = r.best_bets_season;
  const unit = unitSize();
  const items = r.best_bets.map((b, i) => {
    const finalLine = b.completed ? ` · Final ${esc(b.away)} ${b.away_score}–${b.home_score} ${esc(b.home)}` : ` · ${kickoff(b.kickoff)}`;
    return `<div class="bb">
      <div class="bb-rank">${i + 1}</div>
      <div>
        <div class="bb-pick">${chip(b.team)} ${esc(b.team)} ${signed(b.line)} <span class="price">${signed(b.price)}</span></div>
        <div class="bb-meta">${esc(b.away)} @ ${esc(b.home)}${finalLine}</div>
        <div class="bb-meta">Model is ${b.edge_pts} pts off the line · model: covers ${pct(b.prob, 0)}</div>
      </div>
      <div class="bb-side">
        ${b.completed ? resBadge(b.result) : `<span class="bb-stake">1 unit${unit ? ` = ${money(unit)}` : ""}</span>
          <button class="small" data-bb="${i}">Track bet</button>`}
      </div></div>`;
  }).join("");
  $("#best-bets").innerHTML = `<section class="bestbets">
    <div class="bb-head"><h2>🔥 This week's best bets</h2>
      <div class="bb-record">Best-bets record: <b>${pct(hist.win_pct)}</b> all-time (${rec(hist)}, ${signed(hist.units)}u) ·
        <b>${pct(recent.win_pct)}</b> last 5 seasons · this season <b>${rec(season)}</b></div></div>
    <div class="bb-list">${items || `<div class="bb-empty">No best bets this week. The model doesn't see a big enough edge anywhere, and sitting a week out is a legitimate choice.</div>`}</div>
    <p class="bb-note">The top ${5} spread picks where the model is 3–6 points off the line. Suggested stake: 1 unit = 1% of your bankroll (set it on the Live odds tab), same size every bet.
      Historically these have been only slightly above the 52.4% break-even line, so keep stakes small.</p>
  </section>`;
}

function renderPicks(r) {
  // selectors
  $("#season-select").innerHTML = r.seasons.map((s) => `<option value="${s.first_week}" ${s.season === r.week.season ? "selected" : ""}>${s.season}</option>`).join("");
  $("#week-select").innerHTML = r.weeks.map((w) => `<option value="${w.id}" ${w.id === r.week.id ? "selected" : ""}>${esc(w.label)}</option>`).join("");
  const idx = r.weeks.findIndex((w) => w.id === r.week.id);
  $("#week-prev").disabled = idx <= 0;
  $("#week-next").disabled = idx >= r.weeks.length - 1;
  $("#picks-csv").href = `/api/picks/${state.league}/csv?week=${encodeURIComponent(r.week.id)}`;

  renderHero(r);
  renderBestBets(r);

  // track record (honesty first)
  const all = r.history.all_time.record, recent = r.history.recent.record;
  $("#picks-track").innerHTML = [
    trackCard("Best bets (top 5 / week)", r.history.all_time.best_bets, r.history.recent.best_bets, { accent: true, units: true }),
    trackCard("All ★ Best spread picks", all["spread:best"], recent["spread:best"]),
    trackCard("Lean spread picks", all["spread:lean"], recent["spread:lean"]),
    trackCard("Total picks (lean)", all["total:lean"], recent["total:lean"]),
    trackCard("Winner picks (straight up)", all.winner, recent.winner, { breakEven: false }),
  ].join("");
  $("#picks-track-note").textContent = `Graded against closing lines, ${r.history.all_time.from}–${r.history.all_time.to}. `
    + "The black tick marks the 52.4% break-even at -110; green bars are above it. Winner picks are for information, not bets: favorites pay less than even money.";

  // week summary
  const wr = r.week_record, sr = r.season_record;
  const done = r.picks.filter((p) => p.completed).length;
  const line = (lbl, rr) => `${lbl}: winners ${rec(rr.winner)} · best ATS ${rec(rr["spread:best"])} · lean ATS ${rec(rr["spread:lean"])} · totals ${rec(rr["total:lean"])}`;
  $("#picks-week-summary").innerHTML = `<p class="muted small">${done ? line(`${r.week.label} results`, wr) + "<br>" : ""}${line(`${r.week.season} season to date`, sr)}</p>`;

  const filter = $("#picks-filter").value;
  const picks = r.picks.filter((p) => filter === "all" || ["best", "lean"].includes(p.best_tier));
  $("#picks").innerHTML = picks.map(renderPick).join("") || `<p class="muted">No picks for this week${filter === "picks" ? " at best/lean confidence" : ""}.</p>`;
}

function renderPick(p) {
  const i = state.picks.picks.indexOf(p);
  const w = p.winner, sp = p.spread, tp = p.total, ml = p.moneyline;
  const final = p.completed ? `<div class="final">Final: ${esc(p.away)} ${p.away_score} – ${esc(p.home)} ${p.home_score}</div>` : "";
  const trackBtn = (m) => (!p.completed ? `<button class="secondary small" data-pick="${i}" data-market="${m}">Track</button>` : "");
  const topTier = sp?.tier === "caution" ? "caution" : p.best_tier;
  return `<div class="game tier-card-${topTier}">
    <div class="matchup"><span class="teams">${teamsLine(p.away, p.home, p.neutral)}</span><span class="muted small">${kickoff(p.kickoff)}</span></div>
    <div class="proj">Projected ${esc(p.away)} ${p.proj_away.toFixed(0)} – ${esc(p.home)} ${p.proj_home.toFixed(0)}
      ${p.away_qb && p.home_qb ? `· QBs ${esc(p.away_qb)} / ${esc(p.home_qb)}` : ""}</div>
    ${winBar(p.away, p.home, p.home_win_prob)}
    ${final}
    <div class="pick-line"><div><div class="what">Winner: ${esc(w.team)}</div><div class="meta">${pct(w.prob, 0)} to win</div></div>
      <div>${resBadge(w.result)}</div></div>
    ${sp ? `<div class="pick-line"><div><div class="what">${esc(sp.team)} ${signed(sp.line)} <span class="meta">(${signed(sp.price)})</span></div>
      <div class="meta">Spread · model is ${sp.edge_pts} pts off the line · model: covers ${pct(sp.prob, 0)}</div></div>
      <div>${tierBadge(sp.tier)} ${resBadge(sp.result)} ${["best", "lean"].includes(sp.tier) ? trackBtn("spread") : ""}</div></div>` : ""}
    ${tp ? `<div class="pick-line"><div><div class="what">${tp.side} ${tp.line} <span class="meta">(${signed(tp.price)})</span></div>
      <div class="meta">Total · projected ${(p.proj_home + p.proj_away).toFixed(1)} · model: hits ${pct(tp.prob, 0)}</div></div>
      <div>${tierBadge(tp.tier)} ${resBadge(tp.result)} ${tp.tier === "lean" ? trackBtn("total") : ""}</div></div>` : ""}
    ${ml ? `<div class="pick-line"><div><div class="what">${esc(ml.team)} ML ${signed(ml.price)}</div>
      <div class="meta">Moneyline value · model ${pct(ml.prob, 0)} · EV ${pct(ml.ev)}</div></div><div>${resBadge(ml.result)}</div></div>` : ""}
    ${p.notes.length ? `<div class="notes">${p.notes.map(esc).join("<br>")}</div>` : ""}
  </div>`;
}

$("#picks").addEventListener("click", (e) => {
  const i = e.target.dataset.pick;
  if (i == null) return;
  const p = state.picks.picks[i];
  const m = e.target.dataset.market;
  const x = p[m];
  openTrack({
    game: `${p.away} @ ${p.home}`, market: m,
    selection: m === "spread" ? x.team : x.side, line: x.line, price: x.price,
    model_prob: x.prob, book: null,
  }, unitSize());
});

$("#best-bets").addEventListener("click", (e) => {
  const i = e.target.dataset.bb;
  if (i == null) return;
  const b = state.picks.best_bets[i];
  openTrack({
    game: `${b.away} @ ${b.home}`, market: "spread", selection: b.team, line: b.line,
    price: b.price, model_prob: b.prob, book: null,
  }, unitSize());
});

$("#week-select").addEventListener("change", (e) => loadPicks(e.target.value));
$("#season-select").addEventListener("change", (e) => loadPicks(e.target.value));
$("#picks-filter").addEventListener("change", () => state.picks && renderPicks(state.picks));
for (const [id, step] of [["#week-prev", -1], ["#week-next", 1]]) {
  $(id).addEventListener("click", () => {
    const weeks = state.picks.weeks;
    const idx = weeks.findIndex((w) => w.id === state.week) + step;
    if (weeks[idx]) loadPicks(weeks[idx].id);
  });
}

// ---- matchup calculator -----------------------------------------------------------------------
async function loadMatchupTeams() {
  if (!state.teams) state.teams = (await api(`/api/ratings/${state.league}`)).map((r) => r.team);
  const sorted = [...state.teams].sort();
  const opts = (sel) => sorted.map((t) => `<option ${t === sel ? "selected" : ""}>${esc(t)}</option>`).join("");
  const cur = { away: $("#mu-away").value, home: $("#mu-home").value };
  $("#mu-away").innerHTML = opts(sorted.includes(cur.away) ? cur.away : state.teams[1]);
  $("#mu-home").innerHTML = opts(sorted.includes(cur.home) ? cur.home : state.teams[0]);
}

async function runMatchup() {
  const home = $("#mu-home").value, away = $("#mu-away").value;
  if (home === away) {
    $("#matchup").innerHTML = `<div class="alert">Pick two different teams.</div>`;
    return;
  }
  try {
    const m = await api(`/api/matchup/${state.league}?home=${encodeURIComponent(home)}&away=${encodeURIComponent(away)}&neutral=${$("#mu-neutral").checked}`);
    const p = m.prediction;
    $("#matchup").innerHTML = `
      <div class="panel" style="margin-bottom:12px">
        <div class="matchup" style="display:flex;justify-content:space-between;align-items:center;font-weight:700">
          <span>${teamsLine(away, home, $("#mu-neutral").checked)}</span><span class="muted small">${$("#mu-neutral").checked ? "Neutral site" : `at ${esc(home)}`}</span></div>
        ${winBar(away, home, p.home_win_prob)}
      </div>
      <div class="cards">
        <div class="card accent"><div class="k">Projected score</div><div class="v">${p.away_score.toFixed(0)}–${p.home_score.toFixed(0)}</div><div class="sub">${esc(away)} – ${esc(home)}</div></div>
        <div class="card"><div class="k">${esc(home)} win chance</div><div class="v">${pct(p.home_win_prob)}</div><div class="sub">fair ML ${signed(p.fair_home_ml)} / ${signed(p.fair_away_ml)}</div></div>
        <div class="card"><div class="k">Fair spread</div><div class="v">${esc(home)} ${signed(p.fair_home_spread) || "PK"}</div><div class="sub">projected margin ${signed(p.home_margin)}</div></div>
        <div class="card"><div class="k">Fair total</div><div class="v">${p.total}</div><div class="sub">combined points</div></div>
      </div>
      <p class="muted small">Compare any sportsbook line to these tables: if the book's price is better than the fair price, the model sees value.</p>
      <div class="two-col">
        <div class="table-wrap"><table><thead><tr><th>${esc(home)} spread</th><th class="num">${esc(home)} covers</th><th class="num">Fair price</th></tr></thead>
          <tbody>${m.alt_spreads.map((s) => `<tr><td>${signed(s.home_spread) || "PK"}</td><td class="num">${pct(s.home_cover)}</td><td class="num">${signed(s.fair_price)}</td></tr>`).join("")}</tbody></table></div>
        <div class="table-wrap"><table><thead><tr><th>Total</th><th class="num">Over hits</th><th class="num">Fair over price</th></tr></thead>
          <tbody>${m.alt_totals.map((t) => `<tr><td>${t.line}</td><td class="num">${pct(t.over)}</td><td class="num">${signed(t.fair_price)}</td></tr>`).join("")}</tbody></table></div>
      </div>`;
  } catch (e) {
    $("#matchup").innerHTML = `<div class="alert">${esc(e.message)}</div>`;
  }
}
$("#mu-run").addEventListener("click", runMatchup);

// ---- odds calculator (client-side) ------------------------------------------------------------
const toDecimal = (o) => (o > 0 ? 1 + o / 100 : 1 + 100 / Math.abs(o));
const implied = (o) => (o > 0 ? 100 / (o + 100) : -o / (-o + 100));
function updateCalc() {
  const price = Number($("#calc-price").value), p = Number($("#calc-prob").value) / 100;
  if (price && Math.abs(price) >= 100 && p > 0 && p < 1) {
    const b = toDecimal(price) - 1, ev = p * b - (1 - p), kelly = Math.max(0, (b * p - (1 - p)) / b);
    $("#calc-out").innerHTML = `Break-even ${pct(implied(price))} · EV <span class="${cls(ev)}">${ev >= 0 ? "+" : ""}${money(ev * 100)}</span> per $100 · quarter-Kelly stake ${pct(kelly / 4)} of bankroll`;
  } else $("#calc-out").textContent = "Enter American odds (e.g. -110 or +150) and a probability.";
  const a = Number($("#calc-a").value), bb = Number($("#calc-b").value);
  if (Math.abs(a) >= 100 && Math.abs(bb) >= 100) {
    const ia = implied(a), ib = implied(bb), hold = ia + ib - 1;
    $("#devig-out").textContent = `No-vig: A ${pct(ia / (ia + ib))} · B ${pct(ib / (ia + ib))} · book's margin ${pct(hold)}`;
  }
}
["#calc-price", "#calc-prob", "#calc-a", "#calc-b"].forEach((id) => $(id).addEventListener("input", updateCalc));
updateCalc();

// ---- line chart (single series, hover crosshair) ----------------------------------------------
function lineChart(el, pts, { title = "", fmt = (v) => v, baseline = null, seasonTicks = false } = {}) {
  if (!pts.length) { el.innerHTML = `<p class="muted">No history yet.</p>`; return; }
  const W = 600, H = 220, L = 48, R = 12, T = 10, B = 24;
  const ys = pts.map((p) => p.y).concat(baseline == null ? [] : [baseline]);
  let lo = Math.min(...ys), hi = Math.max(...ys);
  const pad = (hi - lo || 1) * 0.08; lo -= pad; hi += pad;
  const x = (i) => L + (pts.length === 1 ? 0 : (i * (W - L - R)) / (pts.length - 1));
  const y = (v) => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
  const ticks = [0, 1, 2, 3].map((k) => lo + ((hi - lo) * k) / 3);
  const xticks = seasonTicks
    ? pts.map((p, i) => [i, p.label.slice(0, 4)]).filter(([i, yr]) => i === 0 || pts[i - 1].label.slice(0, 4) !== yr)
    : [[0, "first"], [pts.length - 1, "latest"]];
  const d = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.y).toFixed(1)}`).join("");
  el.innerHTML = `${title ? `<div class="chart-title">${esc(title)}</div>` : ""}<div class="chart">
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(title || "rating history")}">
      ${ticks.map((t) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}"/><text class="axis" x="${L - 6}" y="${y(t) + 4}" text-anchor="end">${fmt(t)}</text>`).join("")}
      ${baseline != null ? `<line class="baseline" x1="${L}" x2="${W - R}" y1="${y(baseline)}" y2="${y(baseline)}"/>` : ""}
      ${xticks.map(([i, lbl]) => `<text class="axis" x="${x(i)}" y="${H - 6}" text-anchor="${i === pts.length - 1 && !seasonTicks ? "end" : "start"}">${esc(lbl)}</text>`).join("")}
      <path class="line" d="${d}"/>
      <line class="cross" y1="${T}" y2="${H - B}" visibility="hidden"/>
      <circle class="dot" r="4" visibility="hidden"/>
      <rect x="${L}" y="0" width="${W - L - R}" height="${H}" fill="transparent"/>
    </svg></div>`;
  const svg = el.querySelector("svg"), cross = svg.querySelector(".cross"), dot = svg.querySelector(".dot"), tip = $("#chart-tip");
  svg.addEventListener("mousemove", (e) => {
    const r = svg.getBoundingClientRect();
    const vx = ((e.clientX - r.left) / r.width) * W;
    const i = Math.max(0, Math.min(pts.length - 1, Math.round(((vx - L) / (W - L - R)) * (pts.length - 1))));
    cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
    dot.setAttribute("cx", x(i)); dot.setAttribute("cy", y(pts[i].y)); dot.setAttribute("visibility", "visible");
    tip.hidden = false;
    tip.textContent = `${pts[i].label}: ${fmt(pts[i].y)}`;
    tip.style.left = `${Math.min(e.clientX + 12, window.innerWidth - tip.offsetWidth - 8)}px`;
    tip.style.top = `${e.clientY - 32}px`;
  });
  svg.addEventListener("mouseleave", () => {
    cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); tip.hidden = true;
  });
}

// ---- navigation -------------------------------------------------------------------------------
function show(tab) {
  state.tab = tab;
  document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("active", s.id === `tab-${tab}`));
  if (tab === "picks") loadPicks();
  if (tab === "board") loadBoard();
  if (tab === "ratings") loadRatings();
  if (tab === "matchup") loadMatchupTeams().then(runMatchup);
  if (tab === "bets") loadBets();
}

document.querySelectorAll("nav button").forEach((b) => b.addEventListener("click", () => show(b.dataset.tab)));
document.querySelectorAll(".league-toggle button").forEach((b) => b.addEventListener("click", () => {
  state.league = b.dataset.league;
  state.week = null;
  state.teams = null;
  $("#team-detail").innerHTML = `<p class="muted">Click a team to see its rating history and recent games.</p>`;
  document.querySelectorAll(".league-toggle button").forEach((x) => x.classList.toggle("active", x === b));
  $("#backtest").innerHTML = "";
  loadStatus();
  show(state.tab);
}));

$("#reload-odds").addEventListener("click", () => loadBoard(true));
$("#min-ev").addEventListener("change", () => loadBoard());
$("#kelly").addEventListener("change", () => loadBoard());
$("#bankroll").addEventListener("change", () => state.board && renderBoard(state.board));
$("#run-backtest").addEventListener("click", runBacktest);
$("#refresh-data").addEventListener("click", async (e) => {
  e.target.disabled = true;
  e.target.textContent = "Refreshing…";
  try {
    const r = await api(`/api/refresh/${state.league}`, { method: "POST" });
    $("#board-alert").innerHTML = `<div class="alert">${esc(r.skipped || `Updated ${r.games_upserted} games.`)}</div>`;
    await loadStatus();
    await loadBoard();
  } catch (err) {
    $("#board-alert").innerHTML = `<div class="alert">${esc(err.message)}</div>`;
  } finally {
    e.target.disabled = false;
    e.target.textContent = "Refresh data";
  }
});

loadStatus();
show("picks");
