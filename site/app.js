(() => {
  // Set by the publish step (app.js?v=...). Used to reload open pages when the code changes.
  const MY_VERSION = new URL(document.currentScript.src).searchParams.get("v");
  const ICON = { green: "✓", amber: "!", red: "✕", unknown: "?" };
  const WORD = { green: "GO", amber: "CAUTION", red: "NO GO", unknown: "NO DATA" };
  const LABEL = { green: "Go", amber: "Caution", red: "No go", unknown: "No data" };
  const REFRESH_MS = 10 * 60 * 1000;

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const light = (level, size = "") =>
    `<span class="light ${size} ${level}" role="img" aria-label="${LABEL[level]}">${ICON[level]}</span>`;

  let data = null;
  let selected = 0;

  async function load() {
    try {
      const res = await fetch(`data/latest.json?t=${Date.now()}`, { cache: "no-store" });
      data = await res.json();
      if (MY_VERSION && data.site_version && data.site_version !== MY_VERSION) {
        location.reload();
        return;
      }
      render();
    } catch (e) {
      $("updated").textContent = "Could not load data.";
      $("stale").hidden = false;
      $("stale").textContent = "No data – check BOM and Melbourne Water directly.";
    }
  }

  function render() {
    const generated = new Date(data.generated_at);
    const ageHrs = (Date.now() - generated) / 3.6e6;
    const stale = ageHrs > data.stale_after_hours;
    $("location").textContent = data.location;
    $("updated").textContent = `Updated ${generated.toLocaleString("en-AU", {
      weekday: "short", hour: "numeric", minute: "2-digit", timeZone: "Australia/Melbourne",
    })}`;
    $("stale").hidden = !stale;
    if (stale) $("stale").textContent =
      `Data is ${Math.floor(ageHrs)} hours old – lights greyed out. Check conditions yourself.`;

    renderWarnings();
    renderGrid(stale);
    renderDetail(stale);
    renderNow();
    renderSources();
  }

  function renderWarnings() {
    const w = data.now.warnings || [];
    $("warnings").hidden = !w.length;
    $("warnings").innerHTML = w.length
      ? `<strong>BOM warnings</strong><ul>${w.map((x) =>
          `<li>${x.link ? `<a href="${esc(x.link)}" target="_blank" rel="noopener">${esc(x.title)}</a>` : esc(x.title)}</li>`).join("")}</ul>`
      : "";
  }

  function renderGrid(stale) {
    const cols = data.columns;
    const lv = (l) => (stale ? "unknown" : l);
    const colClass = (i) => (i === 0 || cols[i].date !== cols[i - 1].date ? "col-start" : "");
    const sel = (i) => (i === selected ? " selected" : "");

    let html = "<thead><tr><th class=\"rowhead\" scope=\"col\"><span class=\"visually-hidden\">Factor</span></th>";
    cols.forEach((c, i) => {
      html += `<th scope="col" class="${colClass(i)}${sel(i)}" data-col="${i}">
        <span class="day">${esc(c.day_label)}</span>
        <span class="sess">${esc(c.session_label)}</span>
        <span class="time">${esc(c.time_label)}</span></th>`;
    });
    html += "</tr></thead><tbody>";

    html += `<tr class="overall"><th class="rowhead" scope="row">Overall</th>`;
    cols.forEach((c, i) => {
      const l = lv(c.overall);
      const why = stale ? "" : (c.drivers || []).join(", ");
      html += `<td class="cell ${colClass(i)}${sel(i)}" data-col="${i}">${light(l, "light-lg")}<span class="word">${WORD[l]}</span>${
        why ? `<span class="drivers">${esc(why)}</span>` : ""}</td>`;
    });
    html += "</tr>";

    data.factors.forEach((f) => {
      const link = f.links?.[0];
      html += `<tr><th class="rowhead" scope="row">${link
        ? `<a href="${esc(link.url)}" target="_blank" rel="noopener" title="Check: ${esc(link.label)}">${esc(f.label)}<span class="ext" aria-hidden="true">↗</span></a>`
        : esc(f.label)}</th>`;
      cols.forEach((c, i) => {
        const x = c.factors[f.id];
        const l = lv(x.level);
        html += `<td class="cell ${colClass(i)}${sel(i)}" data-col="${i}" title="${esc(x.reasons.join(" • "))}">
          ${light(l)}<span class="val">${esc(x.value)}</span>${x.combo ? `<span class="combo-tag">${esc(x.combo)}</span>` : ""}</td>`;
      });
      html += "</tr>";
    });
    $("grid").innerHTML = html + "</tbody>";
    $("grid").querySelectorAll("[data-col]").forEach((el) =>
      el.addEventListener("click", () => {
        selected = +el.dataset.col;
        render();
        $("detail").scrollIntoView({ behavior: "smooth", block: "nearest" });
      }));
  }

  function renderDetail(stale) {
    const c = data.columns[selected];
    if (!c) { $("detail").hidden = true; return; }
    const l = stale ? "unknown" : c.overall;
    let html = `<h2>${light(l)} ${esc(c.date_label)} · ${esc(c.session_label)} ${esc(c.time_label)} – ${WORD[l]}</h2>`;
    if (c.combinations?.length) html += `<p><strong>No-go combination:</strong> ${c.combinations.map(esc).join(", ")}</p>`;
    if (c.bom_text) html += `<p class="bom">BOM: “${esc(c.bom_text)}”</p>`;
    html += `<ul class="factor-list">`;
    data.factors.forEach((f) => {
      const x = c.factors[f.id];
      html += `<li>${light(stale ? "unknown" : x.level, "light-sm")}<span class="name">${esc(f.label)}</span>
        <span class="why">${x.reasons.map((r) => `<div>${esc(r)}</div>`).join("")}${(f.links || []).length
          ? `<div class="check">Check: ${f.links.map((l) => `<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)}</a>`).join(" · ")}</div>` : ""}</span></li>`;
    });
    $("detail").innerHTML = html + "</ul>";
    $("detail").hidden = false;
  }

  function fmtTime(iso) {
    return new Date(iso).toLocaleString("en-AU", { weekday: "short", hour: "numeric", minute: "2-digit", timeZone: "Australia/Melbourne" });
  }

  function renderNow() {
    const o = data.now.observations;
    $("obs").innerHTML = o
      ? `<h3>Weather – ${esc(o.station)}</h3><dl class="kv">
          <dt>Temperature</dt><dd>${o.temp ?? "–"}°C</dd>
          <dt>Wind</dt><dd>${esc(o.wind_dir || "")} ${o.wind_kn ?? "–"} kn</dd>
          <dt>Gusts</dt><dd>${o.gust_kn ?? "–"} kn</dd>
          <dt>Rain since 9am</dt><dd>${o.rain_since_9am ?? "–"} mm</dd>
          <dt>Visibility</dt><dd>${o.visibility_km ?? "–"} km</dd></dl>
         <p class="note">Observed ${esc(o.time.slice(8, 10))}:${esc(o.time.slice(10, 12))}</p>`
      : `<h3>Weather</h3><p>No data.</p>`;

    const g = data.now.gauges || [];
    $("river").innerHTML = `<h3>River gauges</h3>` + (g.length
      ? `<table class="gauges"><thead><tr><th>Gauge</th><th>Level</th><th>Change /hr</th></tr></thead><tbody>${g.map((x) => {
          const r = x.rise_m_per_hr;
          const trend = r == null ? "–" : r > 0.01 ? `<span class="up">▲ ${r.toFixed(2)}</span>` : r < -0.01 ? `▼ ${Math.abs(r).toFixed(2)}` : "steady";
          return `<tr><td>${esc(x.name)}</td><td>${x.level_m.toFixed(2)} m</td><td>${trend}</td></tr>`;
        }).join("")}</tbody></table><p class="note">The Flood light uses Keilor (same reading as BOM).</p>`
      : "<p>No data.</p>") + riverForecastHtml(data.now.river_forecast);

    const t = data.now.tides || [];
    const ct = data.now.course_tide;
    let tideHtml = `<h3>Tide at the course</h3>`;
    if (ct) {
      const r = ct.rate_m_per_hr;
      tideHtml += `<dl class="kv">
          <dt>Now</dt><dd><strong>${esc(ct.state || "–")}</strong>${r != null ? ` · ${r < 0 ? "falling" : "rising"} ${Math.abs(r).toFixed(2)} m/hr` : ""}</dd>
          <dt>Level</dt><dd>${ct.level_m.toFixed(2)} m <span class="note-inline">at ${esc(ct.time.slice(11, 16))}</span></dd></dl>
        ${lineChart("tide", "Water level at the course: measured last 24 hours and predicted next 30 hours", [
          { name: "Measured", cls: "tc-obs", pts: toPts(ct.observed), measured: true },
          { name: "Forecast", cls: "tc-pred", pts: toPts(ct.predicted) },
        ])}`;
    }
    tideHtml += t.length
      ? `<dl class="kv">${t.map((x) => `<dt>${esc(x.type)}</dt><dd>${fmtTime(x.time)}</dd>`).join("")}</dl>
         <p class="note">Measured: Melbourne Water gauge near Poyntons. Times: BOM Williamstown (in step with the course).</p>`
      : "<p>No data.</p>";
    $("tides").innerHTML = tideHtml;
    wireCharts();
  }

  // ---- line chart: measured (solid) vs predicted (dashed), sessions shaded, hover readout.
  // series: [{name, cls, pts:[[ms, m], ...], measured?}], lines: [{v, cls, label}]
  const charts = {};
  function lineChart(id, label, series, lines = []) {
    const W = 320, H = 130, P = { l: 30, r: 8, t: 8, b: 18 };
    series = series.filter((s) => s.pts.length);
    const all = series.flatMap((s) => s.pts);
    if (all.length < 2) return "";
    const x0 = Math.min(...all.map((p) => p[0])), x1 = Math.max(...all.map((p) => p[0]));
    const ys = all.map((p) => p[1]).concat(lines.map((l) => l.v));
    let y0 = Math.min(...ys), y1 = Math.max(...ys);
    const pad = (y1 - y0) * 0.1 || 0.1; y0 -= pad; y1 += pad;
    const X = (v) => P.l + ((v - x0) / (x1 - x0)) * (W - P.l - P.r);
    const Y = (v) => P.t + (1 - (v - y0) / (y1 - y0)) * (H - P.t - P.b);
    const path = (pts) => pts.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
    const now = Date.parse(data.generated_at);

    let shade = "";
    for (const c of data.columns) {
      const s0 = Date.parse(c.start), s1 = Date.parse(c.end);
      if (s1 < x0 || s0 > x1) continue;
      shade += `<rect class="tc-sess" x="${X(Math.max(s0, x0))}" y="${P.t}" width="${X(Math.min(s1, x1)) - X(Math.max(s0, x0))}" height="${H - P.t - P.b}"/>`;
    }
    let grid = "";
    const span = y1 - y0, step = span > 3 ? 1 : span > 1 ? 0.5 : 0.25;
    for (let v = Math.ceil(y0 / step) * step; v <= y1; v += step) {
      if (Y(v) < P.t + 4) continue;
      grid += `<line class="tc-grid" x1="${P.l}" x2="${W - P.r}" y1="${Y(v)}" y2="${Y(v)}"/><text class="tc-ax" x="${P.l - 4}" y="${Y(v) + 3}" text-anchor="end">${v.toFixed(2)}</text>`;
    }
    const hl = lines.map((l) => `<line class="tc-line ${l.cls}" x1="${P.l}" x2="${W - P.r}" y1="${Y(l.v)}" y2="${Y(l.v)}"/>
      <text class="tc-ax tc-line-label" x="${W - P.r - 2}" y="${Y(l.v) - 3}" text-anchor="end">${esc(l.label)}</text>`).join("");
    // x ticks: every 6 h for short charts, otherwise one per day at local midnight
    let ticks = "";
    const days = (x1 - x0) > 1.5 * 864e5;
    const localHour = (ms) => +new Intl.DateTimeFormat("en-AU", { hour: "numeric", hourCycle: "h23", timeZone: "Australia/Melbourne" }).format(ms);
    const fmtTick = (ms) => new Date(ms).toLocaleString("en-AU", days
      ? { weekday: "short", timeZone: "Australia/Melbourne" }
      : { hour: "numeric", timeZone: "Australia/Melbourne" });
    // Walk hour by hour so ticks land on real local midnights / 6-hourly marks, even across daylight-saving changes.
    for (let v = Math.ceil(x0 / 36e5) * 36e5; v <= x1; v += 36e5) {
      const h = localHour(v);
      if (days && h === 0) {
        ticks += `<line class="tc-grid" x1="${X(v)}" x2="${X(v)}" y1="${P.t}" y2="${H - P.b}"/><text class="tc-ax" x="${X(v) + 3}" y="${H - 4}">${fmtTick(v)}</text>`;
      } else if (!days && h % 6 === 0) {
        ticks += `<text class="tc-ax" x="${X(v)}" y="${H - 4}" text-anchor="middle">${fmtTick(v)}</text>`;
      }
    }

    charts[id] = { series, X, Y, x0, x1, P, W };
    const keys = series.map((s) => `<span class="key ${s.cls}"></span>${esc(s.name)}`).join(" ");
    return `<figure class="line-chart" data-chart="${id}">
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}">
        ${shade}${grid}${hl}${ticks}
        ${series.slice().reverse().map((s) => `<path class="${s.cls}" d="${path(s.pts)}"/>`).join("")}
        <line class="tc-now" x1="${X(now)}" x2="${X(now)}" y1="${P.t}" y2="${H - P.b}"/>
        <text class="tc-ax" x="${X(now) + 3}" y="${P.t + 8}">now</text>
        <g class="tc-hover" hidden><line class="tc-cross" y1="${P.t}" y2="${H - P.b}"/><circle r="3.5"/></g>
        <rect class="tc-hit" x="${P.l}" y="0" width="${W - P.l - P.r}" height="${H}"/>
      </svg>
      <figcaption>${keys} <span class="key key-sess"></span>Sessions
        <span class="tc-readout" aria-live="polite"></span></figcaption>
    </figure>`;
  }

  function wireCharts() {
    document.querySelectorAll(".line-chart").forEach((fig) => {
      const st = charts[fig.dataset.chart];
      if (!st) return;
      const svg = fig.querySelector("svg"), g = fig.querySelector(".tc-hover"), out = fig.querySelector(".tc-readout");
      const { series, X, Y, x0, x1, P, W } = st;
      const measured = series.find((s) => s.measured);
      const move = (ev) => {
        const r = svg.getBoundingClientRect();
        const ms = x0 + ((((ev.clientX - r.left) / r.width) * W - P.l) / (W - P.l - P.r)) * (x1 - x0);
        const nearest = (pts) => pts.reduce((b, p) => (Math.abs(p[0] - ms) < Math.abs(b[0] - ms) ? p : b), pts[0]);
        const useMeasured = measured && ms <= measured.pts[measured.pts.length - 1][0];
        const shown = useMeasured ? [measured] : series.filter((s) => !s.measured);
        const pts = shown.map((s) => nearest(s.pts));
        if (!pts.length) return;
        g.hidden = false;
        g.querySelector("line").setAttribute("x1", X(pts[0][0])); g.querySelector("line").setAttribute("x2", X(pts[0][0]));
        g.querySelector("circle").setAttribute("cx", X(pts[0][0])); g.querySelector("circle").setAttribute("cy", Y(pts[0][1]));
        out.textContent = `${fmtTime(new Date(pts[0][0]).toISOString())}: ` +
          shown.map((s, i) => `${pts[i][1].toFixed(2)} m ${s.name.toLowerCase()}`).join(" · ");
      };
      const hit = svg.querySelector(".tc-hit");
      hit.addEventListener("pointermove", move);
      hit.addEventListener("pointerdown", move);
      hit.addEventListener("pointerleave", () => { g.hidden = true; out.textContent = ""; });
    });
  }

  const toPts = (rows) => (rows || []).map((p) => [Date.parse(p.time), p.level_m]);

  function riverForecastHtml(fc) {
    if (!fc) return "";
    const errHigh = fc.typical_error_high_river_m?.["+24h"];
    return `<h3 class="sub-h">Keilor forecast <span class="badge">trial</span></h3>
      ${lineChart("river", "Keilor river height: measured and forecast", [
        { name: "Measured", cls: "tc-obs", pts: toPts(fc.observed), measured: true },
        { name: "Forecast", cls: "tc-pred", pts: toPts(fc.with_rain) },
      ], [
        { v: fc.thresholds.red, cls: "tc-red", label: `red ${fc.thresholds.red} m` },
        { v: fc.thresholds.yellow, cls: "tc-amber", label: `yellow ${fc.thresholds.yellow} m` },
      ])}
      <p class="note">Our forecast from Keilor's level and catchment rain (${fc.rain_past_72h_mm} mm last 3 days, ${fc.rain_next_72h_mm != null
          ? `${fc.rain_next_72h_mm} mm forecast next 3` : "<strong>rain forecast unavailable</strong>"}).${
        errHigh != null ? ` Usually within ${Math.round(errHigh * 100)} cm a day ahead when the river is high, but can miss sudden rises.` : ""}
        ${fc.use_for_lights ? "Sets the Flood light for sessions 3+ hours away." : ""}</p>`;
  }

  function renderSources() {
    $("sources").innerHTML = Object.entries(data.sources).map(([k, v]) =>
      `<li class="${v === "ok" ? "" : "src-bad"}">${esc(k)}: ${esc(v)}</li>`).join("");
  }

  function usage() {
    const code = (window.DASHBOARD_CONFIG || {}).goatcounter;
    if (!code) return;
    const s = document.createElement("script");
    s.async = true;
    s.src = "https://gc.zgo.at/count.js";
    s.dataset.goatcounter = `https://${code}.goatcounter.com/count`;
    document.body.appendChild(s);
    const base = `https://${code}.goatcounter.com/counter/TOTAL.json`;
    const weekAgo = new Date(Date.now() - 7 * 864e5).toISOString().slice(0, 10);
    // Without a start date GoatCounter's total comes back as 0, so count from launch.
    Promise.all([
      fetch(`${base}?start=2026-10-01`).then((r) => r.json()),
      fetch(`${base}?start=${weekAgo}`).then((r) => r.json()).catch(() => null),
    ]).then(([all, week]) => {
      $("usage").textContent = `${all.count} visits` + (week ? ` · ${week.count} this week` : "");
      $("usage").hidden = false;
    }).catch(() => {});
  }

  load();
  usage();
  setInterval(load, REFRESH_MS);
})();
