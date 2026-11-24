const PAGE = 50;
const state = { jobs: [], stats: null, page: 1, filtered: [] };

const $ = (id) => document.getElementById(id);

function money(job) {
  if (job.pay_min == null && job.pay_max == null) return "";
  const cur = job.pay_currency || "";
  const fmt = (value) =>
    new Intl.NumberFormat("en", { maximumFractionDigits: 0 }).format(value);
  const low = job.pay_min != null ? fmt(job.pay_min) : "";
  const high = job.pay_max != null ? fmt(job.pay_max) : "";
  const range = low && high && low !== high ? `${low}–${high}` : low || high;
  const period = job.pay_period ? `/${job.pay_period}` : "";
  return `${cur} ${range}${period}`.trim();
}

function placeOf(job) {
  const raw = job.location || [job.city, job.region].filter(Boolean).join(", ");
  if (!raw) return job.country || "";
  if (job.country && !raw.toLowerCase().includes(String(job.country).toLowerCase())) {
    return `${raw} · ${job.country}`;
  }
  return raw;
}

function workplaceLabel(job) {
  if (job.workplace === "remote") return "Remote";
  if (job.workplace === "hybrid") return "Hybrid";
  return "";
}

function readFilters() {
  const params = new URLSearchParams(location.search);
  for (const id of ["q", "company", "source", "workplace", "country", "sector", "posted"]) {
    if (params.get(id)) $(id).value = params.get(id);
  }
}

function writeFilters() {
  const params = new URLSearchParams();
  for (const id of ["q", "company", "source", "workplace", "country", "sector", "posted"]) {
    if ($(id).value) params.set(id, $(id).value);
  }
  const next = params.toString();
  history.replaceState(null, "", next ? `?${next}` : location.pathname);
}

function applyFilters() {
  const q = $("q").value.trim().toLowerCase();
  const company = $("company").value.trim().toLowerCase();
  const source = $("source").value;
  const workplace = $("workplace").value;
  const country = $("country").value;
  const sector = $("sector").value;
  const posted = $("posted").value;
  state.filtered = state.jobs.filter((job) => {
    if (company && !(job.company || "").toLowerCase().includes(company)) return false;
    if (source && !(job.sources || []).includes(source)) return false;
    if (workplace && job.workplace !== workplace) return false;
    if (country && job.country !== country) return false;
    if (sector && (job.sector || "other") !== sector) return false;
    if (posted && (!job.posted_at || job.posted_at < posted)) return false;
    if (q) {
      const blob = `${job.title || ""} ${job.company || ""} ${job.location || ""} ${job.city || ""} ${job.country || ""}`.toLowerCase();
      if (!blob.includes(q)) return false;
    }
    return true;
  });
  state.page = 1;
  writeFilters();
  renderRows();
}

function renderStats() {
  const stats = state.stats;
  const cards = [
    ["open_jobs", "Open jobs"],
    ["companies", "Companies"],
    ["countries", "Countries"],
    ["open_postings", "Open postings"],
  ];
  $("stats").innerHTML = cards
    .map(
      ([key, label]) =>
        `<article class="stat"><b>${(stats[key] || 0).toLocaleString()}</b><span>${label}</span></article>`
    )
    .join("");
  const sources = stats.postings_by_source || {};
  $("sources").innerHTML = Object.entries(sources)
    .map(([name, count]) => `<span class="chip"><strong>${count.toLocaleString()}</strong> ${name}</span>`)
    .join("");
  const when = stats.generated_at ? new Date(stats.generated_at).toUTCString() : "";
  const notable = stats.notable || {};
  $("generated").textContent = [
    when && `Updated ${when}`,
    notable.kalshi != null && `Kalshi ${notable.kalshi}`,
    notable.polymarket != null && `Polymarket ${notable.polymarket}`,
  ]
    .filter(Boolean)
    .join(" · ");

  const sourceSelect = $("source");
  for (const name of Object.keys(sources)) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    sourceSelect.appendChild(option);
  }
  const countries = new Set();
  const sectors = new Set();
  for (const job of state.jobs) {
    if (job.country) countries.add(job.country);
    sectors.add(job.sector || "other");
  }
  for (const name of [...countries].sort()) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    $("country").appendChild(option);
  }
  for (const name of [...sectors].sort()) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    $("sector").appendChild(option);
  }
}

function renderRows() {
  const start = (state.page - 1) * PAGE;
  const slice = state.filtered.slice(start, start + PAGE);
  $("match").textContent = `${state.filtered.length.toLocaleString()} matching jobs`;
  $("rows").innerHTML = slice
    .map((job) => {
      const place = placeOf(job);
      const tag = workplaceLabel(job);
      const sources = (job.sources || []).join(", ");
      return `<tr>
        <td class="company">${escapeHtml(job.company || "")}</td>
        <td>${escapeHtml(job.title || "")}${tag ? `<span class="tag">${tag}</span>` : ""}</td>
        <td class="muted">${escapeHtml(place)}</td>
        <td class="pay">${escapeHtml(money(job))}</td>
        <td class="when">${escapeHtml(job.posted_at || "")}</td>
        <td class="src">${escapeHtml(sources)}</td>
        <td><a class="apply" href="${escapeAttr(job.apply_url || "#")}" target="_blank" rel="noopener">Apply</a></td>
      </tr>`;
    })
    .join("");
  const pages = Math.max(1, Math.ceil(state.filtered.length / PAGE));
  $("pager").innerHTML = `
    <button type="button" id="prev" ${state.page <= 1 ? "disabled" : ""}>Previous</button>
    <span>Page ${state.page} of ${pages}</span>
    <button type="button" id="next" ${state.page >= pages ? "disabled" : ""}>Next</button>`;
  $("prev").onclick = () => {
    state.page -= 1;
    renderRows();
  };
  $("next").onclick = () => {
    state.page += 1;
    renderRows();
  };
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
function escapeAttr(value) {
  return escapeHtml(value).replaceAll("'", "&#39;");
}

async function main() {
  const [statsRes, jobsRes] = await Promise.all([fetch("data/stats.json"), fetch("data/jobs.json")]);
  if (!statsRes.ok || !jobsRes.ok) {
    $("generated").textContent = "Dashboard data is not built yet. Run python3 -m jobdir run.";
    return;
  }
  state.stats = await statsRes.json();
  const payload = await jobsRes.json();
  state.jobs = payload.jobs || [];
  renderStats();
  readFilters();
  applyFilters();
  let timer = 0;
  for (const id of ["q", "company"]) {
    $(id).addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(applyFilters, 120);
    });
  }
  for (const id of ["source", "workplace", "country", "sector", "posted"]) {
    $(id).addEventListener("change", applyFilters);
  }
  $("clear").onclick = () => {
    for (const id of ["q", "company", "source", "workplace", "country", "sector", "posted"]) $(id).value = "";
    applyFilters();
  };
}

main();
