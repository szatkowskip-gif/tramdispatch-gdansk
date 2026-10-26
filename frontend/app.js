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
    edges: L.layerGroup().addTo(map),
    switches: L.layerGroup().addTo(map),
    stops: L.layerGroup().addTo(map),
    turnbacks: L.layerGroup().addTo(map),
  };
  const LABEL_ZOOM = 14;
  const state = { data: null, selectedLine: null, colorByLine: false, edgeLayers: [], tbMarkers: [] };
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
    const lines = p.lines || [];
    const onSelected = state.selectedLine && lines.includes(state.selectedLine);
    if (state.selectedLine) {
      return { color: onSelected ? LINE_COLORS[state.selectedLine] || "#c8102e" : "#bbb", weight: onSelected ? 5 : 2, opacity: onSelected ? 1 : 0.6 };
    }
    if (state.colorByLine && lines.length) {
      return { color: LINE_COLORS[lines[0]] || "#444", weight: 3, opacity: 0.9 };
    }
    if (p.service === "yard" || p.service === "siding" || p.service === "spur") return { color: "#999", weight: 2, dashArray: "4 4", opacity: 0.8 };
    if (!lines.length) return { color: "#d08770", weight: 3, opacity: 0.9 }; // tor poza trasami linii (łącznik, przejazd)
    return { color: "#333", weight: 3, opacity: 0.9 };
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
        layer.on("click", () => show({ typ: "tor", id: p.id, dlugosc_m: p.length_m, linie: p.lines.join(", ") || "brak", service: p.service || "-", osm_way: p.way }));
        state.edgeLayers.push({ layer, props: p });
        (p.lines || []).forEach((l) => lineSet.add(l));
      } else if (p.kind === "switch") {
        const m = L.circleMarker([f.geometry.coordinates[1], f.geometry.coordinates[0]], { radius: 3, color: "#fff", weight: 1, fillColor: p.in_loop ? "#1a7f37" : "#c8102e", fillOpacity: 1 }).addTo(layers.switches);
        m.on("click", () => show({ typ: "zwrotnica", osm_node: p.id, ref: p.ref || "-", w_petli: p.in_loop ? "tak" : "nie" }));
      } else if (p.kind === "tram_stop") {
        const m = L.circleMarker([f.geometry.coordinates[1], f.geometry.coordinates[0]], { radius: 4, color: "#1d1d1b", weight: 1.5, fillColor: "#fff", fillOpacity: 1 }).addTo(layers.stops);
        m.bindTooltip(p.name || "(bez nazwy)", { direction: "top", offset: [0, -4] });
        m.on("click", () => show({ typ: "przystanek", nazwa: p.name, osm_node: p.id }));
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
    all.onclick = () => { state.selectedLine = null; setActive(all); restyleEdges(); };
    box.appendChild(all);
    sorted.forEach((l) => {
      const b = document.createElement("button"); b.textContent = l;
      b.style.borderColor = LINE_COLORS[l] || "#444";
      b.onclick = () => { state.selectedLine = l; setActive(b); restyleEdges(); };
      box.appendChild(b);
    });
    function setActive(btn) { [...box.children].forEach((c) => c.classList.toggle("active", c === btn)); }
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
  [["l-edges", "edges"], ["l-switches", "switches"], ["l-stops", "stops"], ["l-turnbacks", "turnbacks"]].forEach(([id, key]) => {
    $(id).addEventListener("change", (e) => (e.target.checked ? layers[key].addTo(map) : map.removeLayer(layers[key])));
  });
  $("l-lines").addEventListener("change", (e) => { state.colorByLine = e.target.checked; restyleEdges(); });

  fetch("/api/network").then((r) => r.json()).then(render).catch((err) => { $("report").textContent = "Błąd ładowania sieci: " + err; });
})();
