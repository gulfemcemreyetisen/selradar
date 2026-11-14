/* ============ PentEarth · Harita (Leaflet) ============ */
(function () {
  "use strict";

  let map, layerControl;
  let floodLayer = null;
  let criticalLayer = null;
  let radarLayer = null;
  let observations = [];
  let defaultBounds = null;
  const radarOpacity = 0.75;

  // Kategori -> renk ve Türkçe ad (Kişi 5'in "category" alanı)
  const CATEGORY = {
    hospital:         { color: "#ff5d6c", label: "Hastane" },
    clinic:           { color: "#ff5d6c", label: "Sağlık ocağı" },
    school:           { color: "#b18cff", label: "Okul" },
    power_substation: { color: "#ffb547", label: "Trafo / enerji" },
    power:            { color: "#ffb547", label: "Enerji tesisi" },
    bridge:           { color: "#9aa7bd", label: "Köprü" },
    road:             { color: "#9aa7bd", label: "Yol" },
    fire_station:     { color: "#ff8a3d", label: "İtfaiye" },
    police:           { color: "#4da3ff", label: "Emniyet" }
  };
  const STATUS = {
    flooded:              "Su baskını alanı içinde",
    field_check_required: "Saha kontrolü gerekli",
    risk_under_watch:     "Risk altında, izleniyor",
    safe:                 "Şu an güvenli görünüyor"
  };

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function showMessage(text, ms = 6000) {
    const wrap = document.querySelector(".map-wrap");
    let box = wrap.querySelector(".map-msg");
    if (!box) {
      box = document.createElement("div");
      box.className = "map-msg";
      wrap.appendChild(box);
    }
    box.textContent = text;
    box.style.opacity = 1;
    clearTimeout(box._t);
    if (ms) box._t = setTimeout(() => (box.style.opacity = 0), ms);
  }

  function init(event) {
    const center = (event && event.coordinates) || [39.0, 35.0]; // [lat, lon]
    const zoom = (event && event.zoom) || 6;

    map = L.map("map", { zoomControl: true, preferCanvas: true }).setView(center, zoom);

    const dark = L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
      maxZoom: 19, subdomains: "abcd",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>'
    });
    const osm = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    });
    const sat = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: 19, attribution: "Tiles &copy; Esri"
    });

    dark.addTo(map);
    layerControl = L.control.layers(
      { "Koyu harita": dark, "OpenStreetMap": osm, "Uydu (optik)": sat },
      {},
      { collapsed: window.innerWidth < 900, position: "topright" }
    ).addTo(map);

    L.control.scale({ imperial: false }).addTo(map);

    if (event && event.bounds) {
      defaultBounds = L.latLngBounds(event.bounds);
      map.fitBounds(defaultBounds, { padding: [20, 20] });
    }
  }

  function setFlood(geojson) {
    if (floodLayer) { map.removeLayer(floodLayer); layerControl.removeLayer(floodLayer); }
    floodLayer = L.geoJSON(geojson, {
      style: { color: "#2f8cff", weight: 2, fillColor: "#2f8cff", fillOpacity: 0.35 },
      onEachFeature: (f, layer) => {
        const p = f.properties || {};
        layer.bindPopup(
          `<h3>Olası su baskını ${esc(p.zone_id || "")}</h3>` +
          (p.area_km2 != null ? `<p>Alan: <b>${esc(p.area_km2)} km²</b></p>` : "") +
          (p.confidence ? `<p>Güven: ${esc(p.confidence)}</p>` : "") +
          (p.land_cover ? `<p>Arazi: ${esc(p.land_cover)}</p>` : "")
        );
      }
    }).addTo(map);
    layerControl.addOverlay(floodLayer, "Olası su baskını (radar)");
    floodLayer.bringToFront();
    return floodLayer;
  }

  function setCritical(geojson) {
    if (criticalLayer) { map.removeLayer(criticalLayer); layerControl.removeLayer(criticalLayer); }
    criticalLayer = L.geoJSON(geojson, {
      pointToLayer: (f, latlng) => {
        const cat = CATEGORY[(f.properties || {}).category] || { color: "#35d0ba" };
        const pr = (f.properties || {}).priority;
        return L.circleMarker(latlng, {
          radius: pr === 1 ? 9 : 7,
          color: "#0b1220", weight: 2,
          fillColor: cat.color, fillOpacity: 0.95
        });
      },
      style: f => {           // yol/köprü çizgileri gelirse
        const cat = CATEGORY[(f.properties || {}).category] || { color: "#9aa7bd" };
        return { color: cat.color, weight: 4, opacity: 0.9 };
      },
      onEachFeature: (f, layer) => {
        const p = f.properties || {};
        const cat = CATEGORY[p.category];
        layer.bindPopup(
          `<h3>${esc(p.name || "Kritik yapı")}</h3>` +
          `<p>${esc(cat ? cat.label : p.category || "")}${p.priority ? " · Öncelik " + esc(p.priority) : ""}</p>` +
          (p.status ? `<p><b>${esc(STATUS[p.status] || p.status)}</b></p>` : "") +
          (p.note ? `<p>${esc(p.note)}</p>` : "")
        );
      }
    }).addTo(map);
    layerControl.addOverlay(criticalLayer, "Kritik altyapı");
    return criticalLayer;
  }

  /* Radar katmanları: her gözlem { image_url, bounds? } ya da { tile_url } */
  function setObservations(list, fallbackBounds) {
    observations = Array.isArray(list) ? list : [];
    if (fallbackBounds) defaultBounds = L.latLngBounds(fallbackBounds);
  }

  function showObservation(i) {
    const obs = observations[i];
    if (radarLayer) { map.removeLayer(radarLayer); layerControl.removeLayer(radarLayer); radarLayer = null; }
    if (!obs) return;

    if (obs.tile_url) {
      radarLayer = L.tileLayer(obs.tile_url, { opacity: radarOpacity, maxZoom: 19 });
    } else if (obs.image_url) {
      const b = obs.bounds ? L.latLngBounds(obs.bounds) : defaultBounds;
      if (!b) { showMessage("Radar katmanı için koordinat sınırı (bounds) eksik."); return; }
      radarLayer = L.imageOverlay(obs.image_url, b, { opacity: radarOpacity, interactive: false });
      radarLayer.on("error", () => {
        showMessage(`Radar görüntüsü henüz yok: ${obs.image_url} (Kişi 1 yükleyince görünecek)`);
        if (radarLayer) { map.removeLayer(radarLayer); layerControl.removeLayer(radarLayer); radarLayer = null; }
      });
    } else {
      showMessage("Bu gözlem için radar katmanı tanımlı değil.");
      return;
    }

    radarLayer.addTo(map);
    layerControl.addOverlay(radarLayer, `Radar: ${obs.date || ""}`);
    if (floodLayer) floodLayer.bringToFront();
  }

  function fit() {
    if (floodLayer && floodLayer.getLayers().length) {
      map.fitBounds(floodLayer.getBounds(), { padding: [40, 40], maxZoom: 14 });
    }
  }

  function invalidate() { if (map) map.invalidateSize(); }

  window.PEMap = { init, setFlood, setCritical, setObservations, showObservation, showMessage, fit, invalidate };
})();