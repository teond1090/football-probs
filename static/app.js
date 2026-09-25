const state = { league: "nfl", tab: "board", board: null };
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

function kickoff(s) {
  if (!s) return "";
  const d = new Date(s);
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
  const bankroll = Number($("#bankroll").value) || 0;
  pendingBet = o;
  $("#bet-desc").textContent = `${o.game}: ${o.selection} ${lineText(o)} (${o.book})`;
  const f = $("#bet-form");
  f.price.value = o.price;
  f.stake.value = (o.kelly * bankroll).toFixed(2);
  f.notes.value = "";
  $("#bet-dialog").showModal();
});

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

// ---- ratings ----------------------------------------------------------------------------------
async function loadRatings() {
  $("#ratings").innerHTML = `<p class="muted">Loading…</p>`;
  try {
    const rows = await api(`/api/ratings/${state.league}`);
    $("#ratings").innerHTML = `<div class="table-wrap"><table>
      <thead><tr><th>#</th><th>Team</th><th class="num">Elo</th><th class="num">Pts vs avg team</th>
        <th class="num">Offense</th><th class="num">Defense</th></tr></thead>
      <tbody>${rows.map((r, i) => `<tr><td>${i + 1}</td><td>${esc(r.team)}</td><td class="num">${r.elo}</td>
        <td class="num ${cls(r.pts_vs_avg)}">${signed(r.pts_vs_avg)}</td>
        <td class="num">${signed(r.off)}</td><td class="num">${signed(r.def)}</td></tr>`).join("")}</tbody></table></div>`;
  } catch (e) {
    $("#ratings").innerHTML = `<div class="alert">${esc(e.message)}</div>`;
  }
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

// ---- navigation -------------------------------------------------------------------------------
function show(tab) {
  state.tab = tab;
  document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("active", s.id === `tab-${tab}`));
  if (tab === "board") loadBoard();
  if (tab === "ratings") loadRatings();
  if (tab === "bets") loadBets();
}

document.querySelectorAll("nav button").forEach((b) => b.addEventListener("click", () => show(b.dataset.tab)));
document.querySelectorAll(".league-toggle button").forEach((b) => b.addEventListener("click", () => {
  state.league = b.dataset.league;
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
    $("#board-alert").innerHTML = `<div class="alert">Updated ${r.games_upserted} games.</div>`;
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
loadBoard();
