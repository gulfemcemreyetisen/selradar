/* ============ PentEarth · Uygulama ============
 * Ekip dosyalarını data/ klasöründen okur ve siteyi kurar.
 * Dosya gelmemişse site çökmez; "Veri durumu" kartında eksik görünür.
 * Bir dosyada "Örnek" kelimesi veya "is_sample": true varsa "örnek veri" diye işaretlenir.
 * Örnek dosyalara "is_sample": true eklerseniz durum kartı doğru gösterir; gerçek dosyada bu alan olmaz.
 */
(function () {
  "use strict";

  // Hangi dosya kimden geliyor (planla aynı)
  const FILES = {
    event:        { path: "data/event.json",               owner: "Kişi 1", label: "Olay bilgisi" },
    observations: { path: "data/observations.json",        owner: "Kişi 1", label: "Radar gözlemleri" },
    rainfall:     { path: "data/rainfall.json",            owner: "Kişi 2", label: "GPM yağış" },
    flood:        { path: "data/flood_extent.geojson",     owner: "Kişi 3", label: "Sel alanı" },
    validation:   { path: "data/validation_results.json",  owner: "Kişi 3", label: "Doğrulama" },
    critical:     { path: "data/critical_places.geojson",  owner: "Kişi 5", label: "Kritik altyapı" },
    impact:       { path: "data/impact_results.json",      owner: "Kişi 5", label: "Etki analizi" }
  };

  const status = {}; // key -> "ok" | "sample" | "missing"
  const $ = id => document.getElementById(id);
  const fmt = n => (n == null || isNaN(n)) ? "—" : Number(n).toLocaleString("tr-TR");
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  async function load(key) {
    const f = FILES[key];
    try {
      const res = await fetch(f.path, { cache: "no-cache" });
      if (!res.ok) throw new Error(res.status);
      const text = await res.text();
      const json = JSON.parse(text);
      status[key] = (/Örnek|is_sample"\s*:\s*true/i.test(text)) ? "sample" : "ok";
      return json;
    } catch (e) {
      status[key] = "missing";
      return null;
    }
  }

  /* ---- Alan hesabı (area_km2 yoksa poligondan yaklaşık) ---- */
  function ringAreaKm2(ring) {
    const R = 6371.0088, rad = Math.PI / 180;
    let s = 0;
    for (let i = 0; i < ring.length - 1; i++) {
      const [x1, y1] = ring[i], [x2, y2] = ring[i + 1];
      s += (x2 - x1) * rad * (2 + Math.sin(y1 * rad) + Math.sin(y2 * rad));
    }
    return Math.abs(s * R * R / 2);
  }
  function polygonArea(coords) {
    return coords.reduce((a, ring, i) => a + (i === 0 ? 1 : -1) * ringAreaKm2(ring), 0);
  }
  function floodAreaKm2(gj) {
    let total = 0;
    (gj.features || []).forEach(f => {
      const p = f.properties || {}, g = f.geometry || {};
      if (p.area_km2 != null) total += Number(p.area_km2);
      else if (g.type === "Polygon") total += polygonArea(g.coordinates);
      else if (g.type === "MultiPolygon") g.coordinates.forEach(c => (total += polygonArea(c)));
    });
    return total;
  }

  /* ---- Yağış verisi: iki biçimi de kabul et ----
   * a) { unit, daily: [{date, mm}], pre_flood_5day_total_mm }
   * b) Kişi 2 biçimi: [{ tarih, yagis_mm }, ...]                       */
  function normRain(r) {
    if (Array.isArray(r)) {
      return {
        unit: "mm",
        source: "NASA GPM IMERG",
        daily: r.map(x => ({ date: x.tarih || x.date, mm: Number(x.yagis_mm ?? x.mm ?? x.value ?? 0) }))
      };
    }
    return r;
  }
  function rain5(rain, floodDate) {
    if (!rain) return null;
    if (rain.pre_flood_5day_total_mm != null) return rain.pre_flood_5day_total_mm;
    if (!Array.isArray(rain.daily) || !floodDate) return null;
    const f = new Date(floodDate + "T00:00:00");
    let toplam = 0, n = 0;
    rain.daily.forEach(d => {
      const gun = (f - new Date(d.date + "T00:00:00")) / 86400000;
      if (gun >= 1 && gun <= 5) { toplam += Number(d.mm) || 0; n++; }
    });
    return n ? Math.round(toplam * 10) / 10 : null;
  }

  /* ---- Bölümler ---- */
  function renderEvent(ev) {
    if (!ev) { $("event-name").textContent = "Olay bilgisi bekleniyor"; return; }
    $("event-name").textContent = ev.event_name || "Sel olayı";
    const parts = [ev.region, ev.country].filter(Boolean).join(", ");
    const date = ev.flood_date ? new Date(ev.flood_date + "T00:00:00").toLocaleDateString("tr-TR", { day: "numeric", month: "long", year: "numeric" }) : "";
    $("event-meta").textContent = [parts, date].filter(Boolean).join(" · ");
    document.title = `PentEarth · ${ev.event_name || "Sel izleme"}`;
  }

  function renderTimeline(obs) {
    const slider = $("time-slider"), ticks = $("time-ticks");
    if (!obs || !obs.length) {
      $("timeline").style.display = "none";
      return;
    }
    obs.sort((a, b) => String(a.date).localeCompare(String(b.date)));
    slider.max = obs.length - 1;
    slider.disabled = obs.length < 2;
    ticks.innerHTML = obs.map((o, i) => `<span data-i="${i}">${esc(o.date)}</span>`).join("");

    const show = i => {
      const o = obs[i];
      $("obs-stage").textContent = `${o.stage || ""} · ${o.sensor || ""}`;
      $("obs-desc").textContent = o.description || "";
      ticks.querySelectorAll("span").forEach((s, k) => s.classList.toggle("active", k === i));
      PEMap.showObservation(i);
    };
    slider.addEventListener("input", () => show(Number(slider.value)));
    ticks.addEventListener("click", e => {
      const i = e.target.dataset.i;
      if (i != null) { slider.value = i; show(Number(i)); }
    });
    if (obs.length < 2) {
      $("obs-desc").textContent = "Uyarı: tek radar gözlemi var; önce–sonra değişimi gösterilemez.";
    }
    show(0);
  }

  function renderStats(flood, impact, rain, ev) {
    $("stat-area").textContent = flood ? floodAreaKm2(flood).toLocaleString("tr-TR", { maximumFractionDigits: 1 }) : "—";
    $("stat-pop").textContent = impact ? fmt(impact.estimated_affected_population) : "—";
    const r5 = rain5(rain, ev && ev.flood_date);
    $("stat-rain").textContent = r5 != null ? fmt(r5) : "—";
    $("stat-roads").textContent = impact ? fmt(impact.closed_roads_count) : "—";
  }

  function renderRain(rain, ev) {
    if (!rain || !Array.isArray(rain.daily) || !rain.daily.length) {
      PECharts.empty("Yağış verisi bekleniyor (Kişi 2 · rainfall.json)");
      return;
    }
    PECharts.rain(rain, ev && ev.flood_date);
    $("soil-note").textContent = [rain.smap_soil_saturation_note, rain.source ? `Kaynak: ${rain.source}` : ""].filter(Boolean).join(" · ");
  }

  function renderPriorities(impact) {
    const ol = $("priority-list");
    const list = impact && Array.isArray(impact.priority_actions) ? impact.priority_actions : [];
    if (!list.length) {
      ol.innerHTML = `<li class="muted" style="display:block">Etki analizi bekleniyor (Kişi 5 · impact_results.json)</li>`;
      return;
    }
    ol.innerHTML = list
      .sort((a, b) => (a.rank || 99) - (b.rank || 99))
      .map(a => `<li><span class="rank">${esc(a.rank)}</span><div><strong>${esc(a.target)}</strong><span class="reason">${esc(a.reason)}</span></div></li>`)
      .join("");
    if (impact.population_source) {
      ol.insertAdjacentHTML("afterend", `<p class="note">Nüfus kaynağı: ${esc(impact.population_source)}</p>`);
    }
  }

  function renderValidation(v) {
    const box = $("validation");
    if (!v) {
      box.innerHTML = `<p class="muted">Bağımsız referansla doğrulama sonucu henüz yok (Kişi 3 · validation_results.json). Doğrulanmamış sonuçlar ön bulgu olarak değerlendirilmelidir.</p>`;
      return;
    }
    const pct = x => x == null ? "—" : (x <= 1 ? (x * 100).toFixed(0) : Number(x).toFixed(0)) + "%";
    box.innerHTML = `
      <div class="metrics">
        <div class="metric"><b>${pct(v.precision)}</b><small>Precision</small></div>
        <div class="metric"><b>${pct(v.recall)}</b><small>Recall</small></div>
        <div class="metric"><b>${pct(v.iou)}</b><small>IoU</small></div>
      </div>
      ${v.reference ? `<p class="note">Referans: ${esc(v.reference)}</p>` : ""}`;
  }

  function renderStatus(ev) {
    const label = { ok: "yüklendi", sample: "örnek veri", missing: "bekleniyor" };
    $("data-status").innerHTML = Object.entries(FILES).map(([k, f]) =>
      `<li><span>${f.label} <span class="muted">· ${f.owner}</span></span><span class="badge ${status[k]}">${label[status[k]]}</span></li>`
    ).join("");

    const sources = (ev && ev.sources) || [];
    const defaults = [
      { name: "NASA ASF Vertex (NISAR)", url: "https://search.asf.alaska.edu/" },
      { name: "NASA GPM IMERG", url: "https://gpm.nasa.gov/data/imerg" },
      { name: "OpenStreetMap", url: "https://www.openstreetmap.org/" },
      { name: "WorldPop", url: "https://www.worldpop.org/" }
    ];
    const seen = new Set();
    $("sources").innerHTML = [...sources, ...defaults]
      .filter(s => s && s.url && !seen.has(s.url) && seen.add(s.url))
      .map(s => `<li>↗ <a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.name || s.url)}</a></li>`)
      .join("");
  }

  /* ---- Mobil panel düğmesi ---- */
  function setupToggle() {
    const btn = $("panel-toggle"), side = $("sidebar");
    btn.addEventListener("click", () => {
      const collapsed = side.classList.toggle("collapsed");
      btn.setAttribute("aria-expanded", String(!collapsed));
      setTimeout(PEMap.invalidate, 50);
    });
  }

  /* ---- Başlat ---- */
  async function start() {
    setupToggle();

    if (location.protocol === "file:") {
      document.body.insertAdjacentHTML("afterbegin",
        `<div style="background:#ffb547;color:#1a1200;padding:8px 16px;font-size:13px">
          Dosyayı çift tıklayarak açtınız; tarayıcı data/ dosyalarını okumaz. VS Code'da <b>Live Server</b> ile açın
          (veya klasörde <code>python3 -m http.server</code>).</div>`);
    }

    const keys = Object.keys(FILES);
    const results = await Promise.all(keys.map(load));
    const d = Object.fromEntries(keys.map((k, i) => [k, results[i]]));

    renderEvent(d.event);
    PEMap.init(d.event);

    if (d.observations) PEMap.setObservations(d.observations, d.event && d.event.bounds);
    if (d.flood) PEMap.setFlood(d.flood);
    if (d.critical) PEMap.setCritical(d.critical);
    if (d.flood && !d.event) PEMap.fit();

    d.rainfall = normRain(d.rainfall);
    renderTimeline(d.observations);
    renderStats(d.flood, d.impact, d.rainfall, d.event);
    renderRain(d.rainfall, d.event);
    renderPriorities(d.impact);
    renderValidation(d.validation);
    renderStatus(d.event);

    const sampleCount = Object.values(status).filter(s => s === "sample").length;
    if (sampleCount) PEMap.showMessage(`${sampleCount} dosya hâlâ örnek veri. Gerçek NASA verisi geldikçe otomatik güncellenecek.`, 7000);
  }

  document.addEventListener("DOMContentLoaded", start);
})();
