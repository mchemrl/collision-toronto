
const API_BASE = "http://127.0.0.1:8000";

// Read theme colors straight from CSS so JS and CSS never drift apart.
const css = getComputedStyle(document.documentElement);
const COLOR = (name) => css.getPropertyValue(name).trim();
const THEME = {
  text: COLOR("--color-text"),
  muted: COLOR("--color-text-muted"),
  line: COLOR("--color-line"),
  accent: COLOR("--color-accent"),
  fatal: COLOR("--color-fatal"),
  injury: COLOR("--color-injury"),
  ftr: COLOR("--color-ftr"),
  pd: COLOR("--color-pd"),
  pedestrian: COLOR("--color-pedestrian"),
  bicycle: COLOR("--color-bicycle"),
  automobile: COLOR("--color-automobile"),
  motorcycle: COLOR("--color-motorcycle"),
  passenger: COLOR("--color-passenger"),
  surface: COLOR("--color-surface"),
};

Chart.defaults.color = THEME.muted;
Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
Chart.defaults.borderColor = THEME.line;

const SEVERITY_COLOR = {
  "Fatal": THEME.fatal,
  "Injury": THEME.injury,
  "Fail to remain": THEME.ftr,
  "Property damage": THEME.pd,
};
const ROAD_USER_COLOR = {
  Automobile: THEME.automobile,
  Motorcycle: THEME.motorcycle,
  Passenger: THEME.passenger,
  Bicycle: THEME.bicycle,
  Pedestrian: THEME.pedestrian,
};

let YEAR_FROM = null;
let YEAR_TO = null;

async function api(path, params = {}) {
  const url = new URL(API_BASE + path);
  const merged = { ...params };
  if (YEAR_FROM) merged.year_from = YEAR_FROM;
  if (YEAR_TO) merged.year_to = YEAR_TO;
  Object.entries(merged).forEach(([k, v]) => {
    if (v !== null && v !== undefined && v !== "") url.searchParams.set(k, v);
  });
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`);
  return res.json();
}

function fmt(n) {
  return Number(n).toLocaleString();
}

function showError(container, err) {
  container.innerHTML = `<p class="error-msg">Couldn't load this chart (${err.message}). Is the backend running at ${API_BASE}?</p>`;
}

// ============================================================
// Dot navigation + scroll-driven activation
// ============================================================
function initNav() {
  const sections = [...document.querySelectorAll(".section")];
  const nav = document.getElementById("dot-nav");
  const loaded = new Set();

  sections.forEach((sec) => {
    const btn = document.createElement("button");
    btn.setAttribute("aria-label", sec.dataset.label || sec.id);
    btn.innerHTML = `<span class="dot-label">${sec.dataset.label || ""}</span>`;
    btn.addEventListener("click", () => sec.scrollIntoView({ behavior: "smooth" }));
    btn.dataset.target = sec.id;
    nav.appendChild(btn);
  });

  const dots = [...nav.querySelectorAll("button")];

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        const idx = sections.indexOf(entry.target);
        if (entry.isIntersecting) {
          dots.forEach((d) => d.classList.remove("active"));
          dots[idx].classList.add("active");
          if (!loaded.has(entry.target.id)) {
            loaded.add(entry.target.id);
            renderSection(entry.target.id);
          }
        }
      });
    },
    { root: document.getElementById("scroller"), threshold: 0.5 }
  );

  sections.forEach((s) => observer.observe(s));
}

function renderSection(id) {
  const map = {
    hero: renderHero,
    "page-trend": renderTrend,
    "page-fatal": renderFatal,
    "page-matrix": renderMatrix,
    "page-factors": renderFactors,
    "page-cumulative": renderCumulative,
    "page-map": renderMap,
    "page-solutions": renderSolutions,
    conclusion: renderConclusion,
  };
  if (map[id]) map[id]().catch((e) => console.error(id, e));
}

// ============================================================
// Global year filter
// ============================================================
async function initGlobalFilters() {
  const meta = await api("/api/meta");
  const from = document.getElementById("year-from");
  const to = document.getElementById("year-to");
  for (let y = meta.year_min; y <= meta.year_max; y++) {
    from.add(new Option(y, y));
    to.add(new Option(y, y));
  }
  from.value = meta.year_min;
  to.value = meta.year_max;
  YEAR_FROM = meta.year_min;
  YEAR_TO = meta.year_max;

  const onChange = () => {
    YEAR_FROM = Number(from.value);
    YEAR_TO = Number(to.value);
    // re-render every already-loaded chart with the new range
    ["hero", "page-trend", "page-fatal", "page-matrix", "page-factors", "page-cumulative", "page-map", "page-solutions", "conclusion"]
      .forEach(renderSection);
  };
  from.addEventListener("change", onChange);
  to.addEventListener("change", onChange);
}

// ============================================================
// 1. Hero
// ============================================================
async function renderHero() {
  const el = document.getElementById("hero-stat");
  try {
    const s = await api("/api/summary");
    el.innerHTML = `${fmt(s.total_collisions)} <small>collisions on record · ${fmt(s.total_fatalities)} fatal</small>`;
  } catch (e) {
    showError(el, e);
  }
}

// ============================================================
// 2. Yearly trend — stacked bar
// ============================================================
let trendChart;
async function renderTrend() {
  const panel = document.querySelector("#page-trend .chart-panel");
  try {
    const d = await api("/api/yearly");
    const ctx = document.getElementById("chart-trend");
    if (trendChart) trendChart.destroy();
    trendChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels: d.years,
        datasets: [
          { label: "Injury", data: d.injury, backgroundColor: THEME.injury },
          { label: "Property damage", data: d.property_damage, backgroundColor: THEME.pd },
        ],
      },
      options: {
        responsive: true,
        scales: {
          x: { stacked: true, grid: { display: false } },
          y: { stacked: true, grid: { color: THEME.line } },
        },
        plugins: { legend: { display: false } },
      },
    });
    document.getElementById("trend-legend").innerHTML = legendHTML({
      Injury: THEME.injury, "Property damage": THEME.pd,
    });
  } catch (e) {
    showError(panel, e);
  }
}

function legendHTML(map) {
  return Object.entries(map)
    .map(([label, color]) => `<span><span class="swatch" style="background:${color}"></span>${label}</span>`)
    .join("");
}

// ============================================================
// 2. Fatal collisions — dedicated fatality-rate-by-road-user chart
// ============================================================
let fatalChart;
async function renderFatal() {
  const panel = document.querySelector("#page-fatal .chart-panel");
  try {
    const d = await api("/api/fatal-by-road-user");
    const ctx = document.getElementById("chart-fatal");
    if (fatalChart) fatalChart.destroy();
    fatalChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels: d.rows.map((r) => r.road_user),
        datasets: [{
          label: "Fatality rate",
          data: d.rows.map((r) => r.fatality_rate_pct),
          backgroundColor: d.rows.map((r) =>
            r.road_user === "Pedestrian" ? THEME.pedestrian
            : r.road_user === "Bicycle" ? THEME.bicycle
            : THEME.fatal
          ),
        }],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        scales: {
          x: {
            grid: { color: THEME.line },
            ticks: { callback: (v) => v + "%" },
            title: { display: true, text: "% of that road user's collisions that were fatal", color: THEME.muted },
          },
          y: { grid: { display: false } },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const r = d.rows[ctx.dataIndex];
                return `${r.fatality_rate_pct}% (${fmt(r.fatal_collisions)} of ${fmt(r.total_collisions)} collisions)`;
              },
            },
          },
        },
      },
    });

    const top = d.rows[0];
    const bottom = d.rows[d.rows.length - 1];
    const multiple = bottom.fatality_rate_pct ? (top.fatality_rate_pct / bottom.fatality_rate_pct).toFixed(1) : "—";
    document.getElementById("fatal-callout").innerHTML =
      `${multiple}&times; <small>${top.road_user.toLowerCase()} collisions are ${multiple}&times; more likely to be fatal than ${bottom.road_user.toLowerCase()} collisions</small>`;
  } catch (e) {
    showError(panel, e);
  }
}

// ============================================================
// 3. Matrix — custom heatmap table
// ============================================================
let matrixMode = "count";
async function renderMatrix() {
  const table = document.getElementById("matrix-table");
  try {
    const d = await api("/api/matrix");
    const severities = d.severities;
    let maxVal = 0;
    d.rows.forEach((r) => severities.forEach((s) => {
      const v = matrixMode === "pct" ? (r.total ? (r.counts[s] / r.total) * 100 : 0) : r.counts[s];
      if (v > maxVal) maxVal = v;
    }));

    let html = "<thead><tr><th>Road user</th>" + severities.map((s) => `<th>${s}</th>`).join("") + "<th>Total</th></tr></thead><tbody>";
    d.rows.forEach((r) => {
      html += `<tr><th>${r.road_user}</th>`;
      severities.forEach((s) => {
        const raw = r.counts[s];
        const val = matrixMode === "pct" ? (r.total ? (raw / r.total) * 100 : 0) : raw;
        const alpha = maxVal ? Math.min(val / maxVal, 1) : 0;
        const bg = mixColor(THEME.surface, SEVERITY_COLOR[s], alpha * 0.85);
        const textColor = alpha > 0.45 ? "#14171a" : THEME.text;
        const display = matrixMode === "pct" ? `${val.toFixed(1)}%` : fmt(raw);
        html += `<td class="matrix-cell" style="background:${bg};color:${textColor}">${display}</td>`;
      });
      html += `<td>${fmt(r.total)}</td></tr>`;
    });
    html += "</tbody>";
    table.innerHTML = html;
  } catch (e) {
    showError(table.parentElement, e);
  }
}

function mixColor(hexA, hexB, t) {
  const a = hexToRgb(hexA), b = hexToRgb(hexB);
  const r = Math.round(a.r + (b.r - a.r) * t);
  const g = Math.round(a.g + (b.g - a.g) * t);
  const bl = Math.round(a.b + (b.b - a.b) * t);
  return `rgb(${r},${g},${bl})`;
}
function hexToRgb(hex) {
  hex = hex.replace("#", "");
  if (hex.length === 3) hex = hex.split("").map((c) => c + c).join("");
  const num = parseInt(hex, 16);
  return { r: (num >> 16) & 255, g: (num >> 8) & 255, b: num & 255 };
}

document.querySelectorAll("#page-matrix .controls button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#page-matrix .controls button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    matrixMode = btn.dataset.mode;
    renderMatrix();
  });
});

// ============================================================
// 5. Factors by division — horizontal stacked bar
// ============================================================
let factorsChart;
async function renderFactors() {
  const panel = document.querySelector("#page-factors .chart-panel");
  try {
    const d = await api("/api/factors", { top_n: 10 });
    const ctx = document.getElementById("chart-factors");
    const labels = d.rows.map((r) => r.division);
    if (factorsChart) factorsChart.destroy();
    factorsChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: d.severities.map((sev) => ({
          label: sev,
          data: d.rows.map((r) => r.counts[sev]),
          backgroundColor: SEVERITY_COLOR[sev],
        })),
      },
      options: {
        indexAxis: "y",
        responsive: true,
        scales: {
          x: { stacked: true, grid: { color: THEME.line } },
          y: { stacked: true, grid: { display: false } },
        },
        plugins: { legend: { position: "bottom", labels: { boxWidth: 10 } } },
      },
    });
  } catch (e) {
    showError(panel, e);
  }
}

// ============================================================
// 5. Pedestrian hourly profile — average collisions per hour
// ============================================================
let cumulativeChart;
async function renderCumulative() {
  const panel = document.querySelector("#page-cumulative .chart-panel");
  try {
    const d = await api("/api/pedestrian-hourly-profile");
    const ctx = document.getElementById("chart-cumulative");
    if (cumulativeChart) cumulativeChart.destroy();

    cumulativeChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: d.hours.map((h) => `${h}:00`),
        datasets: [{
          label: "Average pedestrian collisions per day, by hour",
          data: d.average_per_day,
          borderColor: THEME.pedestrian,
          backgroundColor: THEME.pedestrian + "33",
          fill: true,
          tension: 0.3,
          pointRadius: 0,
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        scales: {
          x: { grid: { display: false } },
          y: {
            grid: { color: THEME.line },
            title: { display: true, text: "Avg. pedestrian collisions / day", color: THEME.muted },
          },
        },
        plugins: { legend: { display: false } },
      },
    });

    if (d.peak_hour !== null) {
      const peakVal = d.total[d.peak_hour];
      document.getElementById("cumulative-callout").innerHTML =
        `${d.peak_hour}:00 <small>is the peak hour — ${fmt(peakVal)} pedestrian collisions recorded at that hour across the full ${fmt(d.days_covered)}-day range in view</small>`;
    }
  } catch (e) {
    showError(panel, e);
  }
}

// ============================================================
// 7. Map — Leaflet, aggregated by neighbourhood
// ============================================================
// Tile source: plain OpenStreetMap tiles, which need no API key or signup.
// (CARTO's free dark-mode raster tiles, used here previously, started
// requiring a paid/free-tier API key from carto.com/basemaps/apikey as of
// August 2026 — see README for how to switch back to them if you'd rather
// sign up for a key and get CARTO's native dark styling. For now we get a
// similar dark look for free with a CSS filter on the tile layer instead,
// see .leaflet-tile-pane in styles.css.)
const OSM_TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const OSM_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

let leafletMap, markerLayer;
let currentSeverity = "";
async function renderMap() {
  const panel = document.querySelector("#page-map .chart-panel");
  try {
    if (!leafletMap) {
      leafletMap = L.map("map-canvas", { scrollWheelZoom: false }).setView([43.7, -79.4], 10.3);
      L.tileLayer(OSM_TILE_URL, { attribution: OSM_ATTRIBUTION, maxZoom: 19 }).addTo(leafletMap);
      markerLayer = L.layerGroup().addTo(leafletMap);
    }
    const d = await api("/api/map", { severity: currentSeverity });
    markerLayer.clearLayers();
    const maxTotal = Math.max(1, ...d.points.map((p) => p.total));
    d.points.forEach((p) => {
      const severeShare = p.total ? (p.fatal + p.injury) / p.total : 0;
      const color = mixColor(THEME.pd, THEME.fatal, Math.min(severeShare * 2, 1));
      const radius = 3 + (p.total / maxTotal) * 18;
      L.circleMarker([p.lat, p.lon], {
        radius,
        color,
        weight: 1,
        fillColor: color,
        fillOpacity: 0.55,
      })
        .bindPopup(`<strong>${p.neighbourhood}</strong><br>${fmt(p.total)} collisions<br>${fmt(p.fatal)} fatal · ${fmt(p.injury)} injury`)
        .addTo(markerLayer);
    });
  } catch (e) {
    showError(panel, e);
  }
}

document.getElementById("map-controls").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-severity]");
  if (!btn) return;
  document.querySelectorAll("#map-controls button").forEach((b) => b.classList.remove("active"));
  btn.classList.add("active");
  currentSeverity = btn.dataset.severity;
  renderMap();
});

// ============================================================
// 6. Solutions map — click a fix, see where the data suggests it first
// ============================================================
let solutionsMap, solutionsLayer;
let currentSolution = "rumble_strips";
const SOLUTION_COLOR = {
  rumble_strips: THEME.accent,
  intersection: THEME.pedestrian,
  lighting: THEME.ftr,
  stop_signs: THEME.fatal,
};

async function renderSolutions() {
  const panel = document.querySelector("#page-solutions .chart-panel");
  try {
    if (!solutionsMap) {
      solutionsMap = L.map("solutions-map-canvas", { scrollWheelZoom: false }).setView([43.7, -79.4], 10.3);
      L.tileLayer(OSM_TILE_URL, { attribution: OSM_ATTRIBUTION, maxZoom: 19 }).addTo(solutionsMap);
      solutionsLayer = L.layerGroup().addTo(solutionsMap);
    }
    const d = await api("/api/solutions", { type: currentSolution });
    solutionsLayer.clearLayers();
    const color = SOLUTION_COLOR[currentSolution];
    const maxTotal = Math.max(1, ...d.points.map((p) => p.total));
    d.points.forEach((p) => {
      L.circleMarker([p.lat, p.lon], {
        radius: 4 + (p.total / maxTotal) * 16,
        color,
        weight: 1,
        fillColor: color,
        fillOpacity: 0.5,
      })
        .bindPopup(`<strong>${p.neighbourhood}</strong><br>${fmt(p.total)} related collisions`)
        .addTo(solutionsLayer);
    });
  } catch (e) {
    showError(panel, e);
  }
}

document.getElementById("solution-list").addEventListener("click", (e) => {
  const item = e.target.closest(".solution-item[data-solution]");
  if (!item) return;
  document.querySelectorAll(".solution-item").forEach((el) => el.classList.remove("active"));
  item.classList.add("active");
  currentSolution = item.dataset.solution;
  renderSolutions();
});

// ============================================================
// 7. Conclusion scorecard
// ============================================================
async function renderConclusion() {
  const wrap = document.getElementById("scorecard");
  try {
    const [s, fatal] = await Promise.all([
      api("/api/summary"),
      api("/api/fatal-by-road-user"),
    ]);
    const riskiest = fatal.rows[0];
    const cells = [
      { num: fmt(s.total_collisions), label: "total collisions on record" },
      { num: fmt(s.total_fatalities), label: "fatal collisions" },
      { num: `${riskiest.fatality_rate_pct}%`, label: `fatality rate for ${riskiest.road_user.toLowerCase()} collisions — the highest of any group` },
      { num: s.top_division || "—", label: "division with most collisions" },
    ];
    wrap.innerHTML = cells.map((c) => `<div class="cell"><div class="num">${c.num}</div><div class="label">${c.label}</div></div>`).join("");
  } catch (e) {
    showError(wrap, e);
  }
}

// ============================================================
// Boot
// ============================================================
(async function init() {
  try {
    await initGlobalFilters();
  } catch (e) {
    console.error("Failed to load filter metadata", e);
  }
  initNav();
  renderSection("hero"); // hero is visible immediately; observer covers the rest
})();
