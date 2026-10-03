(() => {
  const ICON = { green: "✓", amber: "!", red: "✕", unknown: "?" };
  const WORD = { green: "GO", amber: "CAUTION", red: "NO GO", unknown: "CHECK" };
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
      render();
    } catch (e) {
      $("updated").textContent = "Could not load conditions data.";
      $("stale").hidden = false;
      $("stale").textContent = "Data unavailable – check BOM and Melbourne Water directly.";
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
      `Data is ${Math.floor(ageHrs)} hours old – lights shown in grey. Check conditions manually.`;

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
      ? `<strong>Active BOM warnings</strong><ul>${w.map((x) =>
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
      html += `<td class="cell ${colClass(i)}${sel(i)}" data-col="${i}">${light(l, "light-lg")}<span class="word">${WORD[l]}</span></td>`;
    });
    html += "</tr>";

    data.factors.forEach((f) => {
      html += `<tr><th class="rowhead" scope="row">${esc(f.label)}</th>`;
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
    if (c.combinations?.length) html += `<p><strong>Dangerous combination:</strong> ${c.combinations.map(esc).join(", ")}</p>`;
    if (c.bom_text) html += `<p class="bom">BOM: “${esc(c.bom_text)}”</p>`;
    html += `<ul class="factor-list">`;
    data.factors.forEach((f) => {
      const x = c.factors[f.id];
      html += `<li>${light(stale ? "unknown" : x.level, "light-sm")}<span class="name">${esc(f.label)}</span>
        <span class="why">${x.reasons.map((r) => `<div>${esc(r)}</div>`).join("")}</span></li>`;
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
      : `<h3>Weather</h3><p>Observations unavailable.</p>`;

    const g = data.now.gauges || [];
    $("river").innerHTML = `<h3>River gauges (Melbourne Water)</h3>` + (g.length
      ? `<table class="gauges"><thead><tr><th>Gauge</th><th>Level</th><th>Change /hr</th></tr></thead><tbody>${g.map((x) => {
          const r = x.rise_m_per_hr;
          const trend = r == null ? "–" : r > 0.01 ? `<span class="up">▲ ${r.toFixed(2)}</span>` : r < -0.01 ? `▼ ${Math.abs(r).toFixed(2)}` : "steady";
          return `<tr><td>${esc(x.name)}</td><td>${x.level_m.toFixed(2)} m</td><td>${trend}</td></tr>`;
        }).join("")}</tbody></table>${(g.find((x) => x.flow_m3s != null) || null)
          ? `<p class="note">Keilor flow: ${g.find((x) => x.flow_m3s != null).flow_m3s.toFixed(1)} m³/s. Upstream gauges give early warning of rises reaching the course.</p>` : ""}`
      : "<p>River data unavailable.</p>");

    const t = data.now.tides || [];
    const ct = data.now.course_tide;
    let tideHtml = `<h3>Tide at the course</h3>`;
    if (ct) {
      const r = ct.rate_m_per_hr;
      tideHtml += `<dl class="kv">
          <dt>Now</dt><dd><strong>${esc(ct.state || "–")}</strong>${r != null ? ` · ${r < 0 ? "falling" : "rising"} ${Math.abs(r).toFixed(2)} m/hr` : ""}</dd>
          <dt>Level</dt><dd>${ct.level_m.toFixed(2)} m <span class="note-inline">(${esc(ct.gauge)} gauge, ${esc(ct.time.slice(11, 16))})</span></dd></dl>
        ${tideChart(ct)}`;
    }
    tideHtml += t.length
      ? `<dl class="kv">${t.map((x) => `<dt>${esc(x.type)}</dt><dd>${fmtTime(x.time)}</dd>`).join("")}</dl>
         <p class="note">Measured level from Melbourne Water's Maribyrnong gauge, about 700 m from Poyntons. High/low times from BOM ${esc(data.now.tide_station)} predictions, which match the course to within a few minutes.</p>`
      : "<p>Tide predictions unavailable.</p>";
    $("tides").innerHTML = tideHtml;
    wireTideChart();
  }

  // ---- tide chart: measured (solid) vs predicted (dashed), sessions shaded, hover readout
  let chartState = null;
  function tideChart(ct) {
    const W = 320, H = 130, P = { l: 30, r: 8, t: 8, b: 18 };
    const obs = ct.observed.map((p) => [Date.parse(p.time), p.level_m]);
    const pred = ct.predicted.map((p) => [Date.parse(p.time), p.level_m]);
    const all = obs.concat(pred);
    if (all.length < 2) return "";
    const x0 = Math.min(...all.map((p) => p[0])), x1 = Math.max(...all.map((p) => p[0]));
    let y0 = Math.min(...all.map((p) => p[1])), y1 = Math.max(...all.map((p) => p[1]));
    const pad = (y1 - y0) * 0.1 || 0.1; y0 -= pad; y1 += pad;
    const X = (v) => P.l + ((v - x0) / (x1 - x0)) * (W - P.l - P.r);
    const Y = (v) => P.t + (1 - (v - y0) / (y1 - y0)) * (H - P.t - P.b);
    const path = (pts) => pts.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
    const now = Date.parse(data.generated_at);

    // shade session windows that fall inside the chart
    let shade = "";
    for (const c of data.columns) {
      const s0 = Date.parse(c.start), s1 = Date.parse(c.end);
      if (s1 < x0 || s0 > x1) continue;
      shade += `<rect class="tc-sess" x="${X(Math.max(s0, x0))}" y="${P.t}" width="${X(Math.min(s1, x1)) - X(Math.max(s0, x0))}" height="${H - P.t - P.b}"/>`;
    }
    // y gridlines
    let grid = "";
    const step = (y1 - y0) > 1 ? 0.5 : 0.25;
    for (let v = Math.ceil(y0 / step) * step; v <= y1; v += step) {
      if (Y(v) < P.t + 4) continue;
      grid += `<line class="tc-grid" x1="${P.l}" x2="${W - P.r}" y1="${Y(v)}" y2="${Y(v)}"/><text class="tc-ax" x="${P.l - 4}" y="${Y(v) + 3}" text-anchor="end">${v.toFixed(2)}</text>`;
    }
    // x ticks every 6 h
    let ticks = "";
    const fmtH = (ms) => new Date(ms).toLocaleTimeString("en-AU", { hour: "numeric", timeZone: "Australia/Melbourne" });
    for (let v = Math.ceil(x0 / 216e5) * 216e5; v <= x1; v += 216e5) ticks += `<text class="tc-ax" x="${X(v)}" y="${H - 4}" text-anchor="middle">${fmtH(v)}</text>`;

    chartState = { obs, pred, X, Y, x0, x1, P, W, H };
    return `<figure class="tide-chart">
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Water level at the course: measured last 24 hours and predicted next 30 hours">
        ${shade}${grid}${ticks}
        <path class="tc-pred" d="${path(pred)}"/>
        <path class="tc-obs" d="${path(obs)}"/>
        <line class="tc-now" x1="${X(now)}" x2="${X(now)}" y1="${P.t}" y2="${H - P.b}"/>
        <text class="tc-ax" x="${X(now) + 3}" y="${P.t + 8}">now</text>
        <g class="tc-hover" hidden><line class="tc-cross" y1="${P.t}" y2="${H - P.b}"/><circle r="3.5"/></g>
        <rect class="tc-hit" x="${P.l}" y="0" width="${W - P.l - P.r}" height="${H}"/>
      </svg>
      <figcaption><span class="key key-obs"></span>Measured <span class="key key-pred"></span>Predicted <span class="key key-sess"></span>Sessions
        <span class="tc-readout" aria-live="polite"></span></figcaption>
    </figure>`;
  }

  function wireTideChart() {
    const fig = document.querySelector(".tide-chart");
    if (!fig || !chartState) return;
    const svg = fig.querySelector("svg"), g = fig.querySelector(".tc-hover"), out = fig.querySelector(".tc-readout");
    const { obs, pred, X, Y, x0, x1, P, W } = chartState;
    const move = (ev) => {
      const r = svg.getBoundingClientRect();
      const px = ((ev.clientX - r.left) / r.width) * W;
      const ms = x0 + ((px - P.l) / (W - P.l - P.r)) * (x1 - x0);
      const nearest = (pts) => pts.reduce((b, p) => (Math.abs(p[0] - ms) < Math.abs(b[0] - ms) ? p : b), pts[0]);
      const useObs = obs.length && ms <= obs[obs.length - 1][0];
      const p = nearest(useObs ? obs : pred);
      g.hidden = false;
      g.querySelector("line").setAttribute("x1", X(p[0])); g.querySelector("line").setAttribute("x2", X(p[0]));
      g.querySelector("circle").setAttribute("cx", X(p[0])); g.querySelector("circle").setAttribute("cy", Y(p[1]));
      out.textContent = `${fmtTime(new Date(p[0]).toISOString())}: ${p[1].toFixed(2)} m ${useObs ? "measured" : "predicted"}`;
    };
    const hit = svg.querySelector(".tc-hit");
    hit.addEventListener("pointermove", move);
    hit.addEventListener("pointerdown", move);
    hit.addEventListener("pointerleave", () => { g.hidden = true; out.textContent = ""; });
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
    Promise.all([
      fetch(base).then((r) => r.json()),
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
