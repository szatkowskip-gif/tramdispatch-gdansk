/* Tramdispatch Gdańsk, etap 1: mapa grafu torów. Czysty JS + Leaflet. */
(function () {
  const map = L.map("map", { zoomControl: true }).setView([54.37, 18.62], 12);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);

  const LINE_COLORS = {
    "2": "#e6194b", "3": "#3cb44b", "4": "#ffe119", "5": "#4363d8", "6": "#f58231", "7": "#911eb4",
    "8": "#46f0f0", "9": "#f032e6", "10": "#bcf60c", "11": "#fabebe", "12": "#008080",
  };
  const TB_COLORS = { loop: "#1a7f37", ring: "#b58900", stub: "#6f42c1", crossover: "#0969da", triangle: "#b58900" };

  const layers = {
    trams: L.layerGroup().addTo(map),
    trail: L.layerGroup().addTo(map),
    edges: L.layerGroup().addTo(map),
    switches: L.layerGroup().addTo(map),
    stops: L.layerGroup().addTo(map),
    turnbacks: L.layerGroup().addTo(map),
  };
  const LABEL_ZOOM = 14;
  const state = { data: null, selectedLines: new Set(), colorByLine: false, edgeLayers: [], edgeById: new Map(), tbMarkers: [], stopById: new Map() };
  map.on("zoomend", () => {
    const permanent = map.getZoom() >= LABEL_ZOOM;
    state.tbMarkers.forEach(({ marker, name }) => {
      marker.unbindTooltip();
      marker.bindTooltip(name, { permanent, direction: "right", offset: [8, 0], className: "tb-label" });
    });
  });
  const $ = (id) => document.getElementById(id);

  function show(obj) {
    $("selected").textContent = JSON.stringify(obj, null, 1).replace(/[{}"]/g, "");
  }

  function edgeStyle(p) {
    if (window.TD && TD.edgeOverride) { const o = TD.edgeOverride(p.id); if (o) return o; }
    const lines = p.lines || [];
    if (state.selectedLines.size) {
      const hit = lines.find((l) => state.selectedLines.has(l));
      return { color: hit ? LINE_COLORS[hit] || "#c8102e" : "#bbb", weight: hit ? 5 : 2, opacity: hit ? 1 : 0.6 };
    }
    if (state.colorByLine && lines.length) {
      return { color: LINE_COLORS[lines[0]] || "#444", weight: 3, opacity: 0.9 };
    }
    if (p.service === "yard" || p.service === "siding" || p.service === "spur") return { color: "#999", weight: 2, dashArray: "4 4", opacity: 0.8 };
    if (!lines.length) return { color: "#d08770", weight: 3, opacity: 0.9 }; // tor poza trasami linii (łącznik, przejazd)
    return { color: "#333", weight: 3, opacity: 0.9 };
  }

  function onLineFilterChange() {
    restyleEdges();
    if (typeof renderTrams === "function" && live.lastSnapshot) renderTrams(live.lastSnapshot);
  }

  function restyleEdges() {
    state.edgeLayers.forEach(({ layer, props }) => layer.setStyle(edgeStyle(props)));
  }

  function render(data) {
    state.data = data;
    const lineSet = new Set();
    data.features.forEach((f) => {
      const p = f.properties;
      if (p.kind === "edge") {
        const latlngs = f.geometry.coordinates.map(([lon, lat]) => [lat, lon]);
        const layer = L.polyline(latlngs, edgeStyle(p)).addTo(layers.edges);
        layer.on("click", (ev) => {
          if (window.TD && TD.onEdgeClick && TD.onEdgeClick(p, ev)) return;
          show({ typ: "tor", id: p.id, dlugosc_m: p.length_m, linie: p.lines.join(", ") || "brak", service: p.service || "-", osm_way: p.way });
        });
        state.edgeLayers.push({ layer, props: p });
        state.edgeById.set(p.id, { layer, props: p });
        (p.lines || []).forEach((l) => lineSet.add(l));
      } else if (p.kind === "switch") {
        const m = L.circleMarker([f.geometry.coordinates[1], f.geometry.coordinates[0]], { radius: 3, color: "#fff", weight: 1, fillColor: p.in_loop ? "#1a7f37" : "#c8102e", fillOpacity: 1 }).addTo(layers.switches);
        m.on("click", () => show({ typ: "zwrotnica", osm_node: p.id, ref: p.ref || "-", w_petli: p.in_loop ? "tak" : "nie" }));
      } else if (p.kind === "tram_stop") {
        const m = L.circleMarker([f.geometry.coordinates[1], f.geometry.coordinates[0]], { radius: 4, color: "#1d1d1b", weight: 1.5, fillColor: "#fff", fillOpacity: 1 }).addTo(layers.stops);
        m.bindTooltip(p.name || "(bez nazwy)", { direction: "top", offset: [0, -4] });
        m.on("click", () => show({ typ: "przystanek", nazwa: p.name, osm_node: p.id }));
        state.stopById.set(p.id, { marker: m, props: p });
      } else if (p.kind === "turnback") {
        const cls = tbClass(p);
        const color = TB_COLORS[cls] || "#444";
        const m = L.circleMarker([f.geometry.coordinates[1], f.geometry.coordinates[0]], { radius: 8, color: "#fff", weight: 2, fillColor: color, fillOpacity: 1 }).addTo(layers.turnbacks);
        m.bindTooltip(p.name, { permanent: map.getZoom() >= LABEL_ZOOM, direction: "right", offset: [8, 0], className: "tb-label" });
        state.tbMarkers.push({ marker: m, name: p.name });
        m.on("click", () => show({ typ: "punkt zawracania", rodzaj: tbLabel(cls), nazwa: p.name, tylko_dwukierunkowe: p.for_bidirectional_only ? "tak" : "nie", zrodlo: p.source, wezly: (p.nodes || []).length }));
      }
    });
    // przyciski linii
    const sorted = [...lineSet].sort((a, b) => Number(a) - Number(b));
    const box = $("line-buttons");
    box.innerHTML = "";
    const all = document.createElement("button"); all.textContent = "wszystkie"; all.className = "active";
    all.onclick = () => { state.selectedLines.clear(); refreshButtons(); onLineFilterChange(); };
    box.appendChild(all);
    sorted.forEach((l) => {
      const b = document.createElement("button"); b.textContent = l; b.dataset.line = l;
      b.style.borderColor = LINE_COLORS[l] || "#444";
      b.onclick = () => {
        if (state.selectedLines.has(l)) state.selectedLines.delete(l); else state.selectedLines.add(l);
        refreshButtons(); onLineFilterChange();
      };
      box.appendChild(b);
    });
    function refreshButtons() {
      [...box.children].forEach((c) => {
        const l = c.dataset.line;
        c.classList.toggle("active", l ? state.selectedLines.has(l) : state.selectedLines.size === 0);
      });
    }
    // raport
    $("report").textContent = reportText(data.report);
    layers.switches.eachLayer((l) => l.bringToFront && l.bringToFront());
  }

  function tbClass(p) {
    if (p.tb_kind === "loop") return p.terminus ? "loop" : "ring";
    return p.tb_kind;
  }
  function tbLabel(cls) {
    return { loop: "pętla końcowa", ring: "pierścień/trójkąt (do weryfikacji)", stub: "końcówka bez pętli", crossover: "przejazd międzytorowy", triangle: "trójkąt" }[cls] || cls;
  }

  function reportText(r) {
    if (!r) return "brak";
    return [
      `Odcinki OSM: ${r.ways}, węzły: ${r.nodes}, krawędzie: ${r.edges}`,
      `Komponenty: ${r.components} ${JSON.stringify(r.component_sizes)}`,
      `Bez tagu oneway: ${r.ways_without_oneway.length}`,
      `Relacje linii z przerwami: ${r.broken_relations.length}`,
      `Pętle końcowe (${r.loops.length}): ${r.loops.join(", ")}`,
      `Pierścienie do weryfikacji (${r.rings.length}): ${r.rings.join(", ")}`,
      `Końcówki bez pętli (${r.stubs.length}): ${r.stubs.join(", ")}`,
      `Przejazdy międzytorowe: ${r.crossovers}`,
      `Izolowane odcinki: ${r.isolated_ways.length ? r.isolated_ways.join(", ") : "brak"}`,
    ].join("\n");
  }

  // przełączniki warstw
  map.removeLayer(layers.turnbacks);
  [["l-edges", "edges"], ["l-switches", "switches"], ["l-stops", "stops"], ["l-turnbacks", "turnbacks"], ["l-trams", "trams"]].forEach(([id, key]) => {
    $(id).addEventListener("change", (e) => (e.target.checked ? layers[key].addTo(map) : map.removeLayer(layers[key])));
  });
  $("l-lines").addEventListener("change", (e) => { state.colorByLine = e.target.checked; restyleEdges(); });

  fetch("/api/network").then((r) => r.json()).then(render).catch((err) => { $("report").textContent = "Błąd ładowania sieci: " + err; });

  // ------------------------------------------------------------ tramwaje na żywo
  const live = { markers: new Map(), selected: null, historyMinutes: 0, timer: null, lastSnapshot: null };

  function delayColor(t) {
    if (t.age_s > 120) return "#9ca3af";
    const d = t.delay;
    if (d === null || d === undefined) return "#9ca3af";
    if (d < -60) return "#2563eb";
    if (d <= 60) return "#16a34a";
    if (d <= 180) return "#ca8a04";
    if (d <= 600) return "#ea580c";
    return "#dc2626";
  }
  function fmtDelay(d) {
    if (d === null || d === undefined) return "–";
    const m = Math.round(d / 60);
    return (m > 0 ? "+" : "") + m + " min";
  }
  function fmtAge(s) { return s < 60 ? s + " s" : Math.round(s / 60) + " min"; }

  function tramIcon(t) {
    const stale = t.age_s > 120;
    const dir = typeof t.direction === "number" ? t.direction : 0;
    const sit = (window.TD && TD.vehicleSituation) ? TD.vehicleSituation(t.vehicle_code) : "";
    const html = `<div class="tram-icon${stale ? " stale" : ""}${live.selected === t.vehicle_code ? " selected" : ""}${sit ? " sit-" + sit : ""}" style="background:${delayColor(t)}">${t.line}<span class="arrow" style="transform:rotate(${dir}deg)"></span></div>`;
    return L.divIcon({ html, className: "", iconSize: [24, 24], iconAnchor: [12, 12] });
  }

  function popupHtml(t) {
    return `<b>Linia ${t.line}</b> → ${t.headsign || "?"}<br>` +
      `Nr taborowy <b>${t.vehicle_code}</b> · ${t.type || "typ nieznany"}` +
      (t.bidirectional === true ? " · dwukierunkowy" : t.bidirectional === false ? " · jednokierunkowy" : "") + `<br>` +
      `Opóźnienie: <b>${fmtDelay(t.delay)}</b> · prędkość ${t.speed ?? "?"} km/h<br>` +
      `Pozycja sprzed ${fmtAge(t.age_s)}` + (t.service ? ` · brygada ${t.service}` : "");
  }

  function renderTrams(snapshot) {
    live.lastSnapshot = snapshot;
    const visible = state.selectedLines.size ? snapshot.trams.filter((t) => state.selectedLines.has(t.line)) : snapshot.trams;
    const seen = new Set();
    visible.forEach((t) => {
      seen.add(t.vehicle_code);
      let m = live.markers.get(t.vehicle_code);
      if (!m) {
        m = L.marker([t.lat, t.lon], { icon: tramIcon(t), zIndexOffset: 1000 }).addTo(layers.trams);
        m.bindPopup("", { offset: [0, -8] });
        m.on("click", () => selectTram(t.vehicle_code));
        live.markers.set(t.vehicle_code, m);
      } else {
        m.setLatLng([t.lat, t.lon]);
        m.setIcon(tramIcon(t));
      }
      m.setPopupContent(popupHtml(t));
      m._tram = t;
    });
    [...live.markers.keys()].forEach((code) => {
      if (!seen.has(code)) { layers.trams.removeLayer(live.markers.get(code)); live.markers.delete(code); }
    });
    // lista w panelu
    const list = $("tram-list");
    list.innerHTML = "";
    [...visible].sort((a, b) => Number(a.line) - Number(b.line) || a.vehicle_code.localeCompare(b.vehicle_code)).forEach((t) => {
      const row = document.createElement("div");
      row.innerHTML = `<b style="background:${delayColor(t)}">${t.line}</b><span>${t.vehicle_code}</span><span class="dir">→ ${t.headsign || "?"}</span><span class="delay">${fmtDelay(t.delay)}</span>`;
      row.onclick = () => { selectTram(t.vehicle_code); map.panTo([t.lat, t.lon]); live.markers.get(t.vehicle_code)?.openPopup(); };
      list.appendChild(row);
    });
    $("tram-count").textContent = state.selectedLines.size ? `${visible.length} z ${snapshot.trams.length} (linie ${[...state.selectedLines].sort((a, b) => a - b).join(", ")})` : `${snapshot.trams.length}`;
  }

  function selectTram(code) {
    live.selected = code;
    live.markers.forEach((m) => m.setIcon(tramIcon(m._tram)));
    layers.trail.clearLayers();
    fetch(`/api/history?vehicle=${encodeURIComponent(code)}&minutes=60`).then((r) => r.json()).then((h) => {
      if (live.selected !== code || !h.trail.length) return;
      const pts = h.trail.map((p) => [p.lat, p.lon]);
      L.polyline(pts, { color: "#1d1d1b", weight: 3, opacity: 0.7, dashArray: "2 6" }).addTo(layers.trail);
      L.circleMarker(pts[0], { radius: 4, color: "#1d1d1b", fillColor: "#fff", fillOpacity: 1 }).bindTooltip("start śladu, " + new Date(h.trail[0].ts * 1000).toLocaleTimeString("pl-PL")).addTo(layers.trail);
    });
  }

  function setStatus(health) {
    const el = $("status");
    const lv = health.live || {};
    if (lv.feed_age_s === null || lv.feed_age_s === undefined) {
      el.className = "status bad"; el.textContent = "Feed ZTM: brak danych" + (lv.last_error ? " (" + lv.last_error + ")" : "");
    } else if (lv.feed_age_s > 90) {
      el.className = "status bad"; el.textContent = `Feed ZTM: ostatnie dane ${fmtAge(lv.feed_age_s)} temu`;
    } else {
      el.className = "status ok"; el.textContent = `Feed ZTM OK · ${lv.trams} tramwajów · odświeżono ${fmtAge(lv.feed_age_s)} temu`;
    }
  }

  function tick() {
    if (live.historyMinutes > 0) return;
    fetch("/api/live").then((r) => r.json()).then(renderTrams).catch(() => {});
    fetch("/api/health").then((r) => r.json()).then(setStatus).catch(() => {});
  }
  tick();
  live.timer = setInterval(tick, 5000);

  // ------------------------------------------------------------ historia
  const slider = $("history");
  let sliderDebounce = null;
  slider.addEventListener("input", () => {
    const min = Number(slider.value);
    live.historyMinutes = min;
    $("history-label").textContent = min === 0 ? "teraz" : `−${min} min`;
    clearTimeout(sliderDebounce);
    sliderDebounce = setTimeout(() => {
      if (min === 0) { tick(); return; }
      const at = Math.floor(Date.now() / 1000) - min * 60;
      fetch(`/api/history?at=${at}`).then((r) => r.json()).then((snap) => {
        snap.trams.forEach((t) => { t.age_s = 0; });
        renderTrams(snap);
        $("status").className = "status";
        $("status").textContent = `Historia: ${new Date(at * 1000).toLocaleTimeString("pl-PL")} · ${snap.trams.length} tramwajów`;
      });
    }, 150);
  });

  window.TD = Object.assign(window.TD || {}, { map, layers, state, live, $, restyleEdges, renderTrams, LINE_COLORS, fmtDelay });
})();
