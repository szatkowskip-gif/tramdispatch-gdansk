/* Tramdispatch Gdańsk, etap 3: zgłaszanie awarii, objazdy, zawracanie, składy dotknięte. */
(function () {
  const TD = window.TD;
  const { map, layers, state, live, $ } = TD;
  const inc = {
    reporting: false,
    selected: new Set(),   // krawędzie zaznaczone ręcznie
    blocked: new Set(),    // krawędzie zablokowane wg analizy (z równoległymi)
    detour: new Set(),
    shuttle: new Set(),
    strategies: {},       // ref -> detour | shorten | shuttle | suspended
    analysis: null,
    active: null,          // zapisana awaria (obiekt z API)
    vehicleSit: new Map(),
  };
  layers.incident = L.layerGroup().addTo(map);

  const SIT_LABEL = { trapped_between: "bez możliwości zawrócenia", approaching: "jedzie na blokadę", beyond: "za blokadą", on_block: "na blokadzie", unaffected: "nie dotyczy" };
  const KIND_LABEL = { loop: "pętla", stub: "końcówka", crossover: "przejazd", triangle: "trójkąt" };
  const kindOf = (c) => (c.kind === "loop" && c.verified === false) ? "pierścień, do weryfikacji" : KIND_LABEL[c.kind] || c.kind;

  // ------------------------------------------------------------ hooki do app.js
  TD.onEdgeClick = (p) => {
    if (!inc.reporting) return false;
    if (inc.selected.has(p.id)) inc.selected.delete(p.id); else inc.selected.add(p.id);
    inc.blocked = new Set(inc.selected);
    inc.detour.clear();
    $("inc-count").textContent = `Zaznaczono ${inc.selected.size} odcinków. Klikaj tory na mapie (ponowny klik odznacza).`;
    $("inc-save").disabled = true;
    TD.restyleEdges();
    return true;
  };
  TD.edgeOverride = (id) => {
    if (inc.blocked.has(id)) return { color: "#dc2626", weight: 8, opacity: 0.95 };
    if (inc.detour.has(id)) return { color: "#16a34a", weight: 6, opacity: 0.9, dashArray: "8 6" };
    if (inc.shuttle.has(id)) return { color: "#2563eb", weight: 6, opacity: 0.9, dashArray: "4 6" };
    return null;
  };
  TD.vehicleSituation = (code) => inc.vehicleSit.get(code) || "";

  // ------------------------------------------------------------ tryb zgłaszania
  function startReporting() {
    inc.reporting = true;
    document.body.classList.add("reporting");
    $("inc-idle").hidden = true; $("inc-form").hidden = false; $("inc-active").hidden = true;
    $("inc-count").textContent = "Zaznaczono 0 odcinków. Klikaj tory na mapie.";
    if (!map.hasLayer(layers.edges)) { layers.edges.addTo(map); $("l-edges").checked = true; }
  }
  function stopReporting() {
    inc.reporting = false;
    document.body.classList.remove("reporting");
    $("inc-form").hidden = true; $("inc-idle").hidden = false;
  }
  function clearAll() {
    inc.selected.clear(); inc.blocked.clear(); inc.detour.clear(); inc.shuttle.clear(); inc.strategies = {}; inc.analysis = null; inc.active = null; inc.vehicleSit.clear();
    $("msg-box").hidden = true; $("msg-fields").innerHTML = ""; $("inc-messages").textContent = "Komunikaty";
    layers.incident.clearLayers();
    $("inc-result").hidden = true; $("inc-result").innerHTML = "";
    $("inc-active").hidden = true;
    TD.restyleEdges();
    if (live.lastSnapshot) TD.renderTrams(live.lastSnapshot);
  }

  $("inc-start").onclick = () => { clearAll(); startReporting(); };
  $("inc-cancel").onclick = () => { stopReporting(); clearAll(); };
  $("inc-analyze").onclick = () => {
    if (!inc.selected.size) { alert("Zaznacz najpierw odcinek toru na mapie."); return; }
    postJSON("/api/incidents/preview", formBody()).then((res) => { showAnalysis(res); $("inc-save").disabled = false; });
  };
  $("inc-save").onclick = () => {
    postJSON("/api/incidents", formBody()).then((saved) => {
      stopReporting();
      setActive(saved);
      loadLog();
    });
  };
  $("inc-resolve").onclick = () => {
    if (!inc.active) return;
    if (!confirm("Zakończyć awarię " + inc.active.id + "?")) return;
    fetch(`/api/incidents/${inc.active.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: "resolved" }) })
      .then((r) => r.json()).then((full) => {
        const restored = (full.messages && full.messages.restored_pl) ? full.messages : null;
        clearAll(); loadLog();
        if (restored) {
          inc.active = full; $("inc-active").hidden = false;
          $("inc-active-title").textContent = `Zakończona ${full.id}`; $("inc-active-meta").textContent = "Komunikat o przywróceniu ruchu do skopiowania:";
          showMessages({ restored_pl: restored.restored_pl, restored_en: restored.restored_en });
        }
      });
  };
  $("inc-close").onclick = () => clearAll();

  function formBody() {
    const mode = document.querySelector('input[name="inc-mode"]:checked').value;
    return { blocked_edges: [...inc.selected], both_directions: mode === "both", location_text: $("inc-location").value.trim(),
             cause: $("inc-cause").value, expected_until: $("inc-until").value.trim() || null };
  }
  function postJSON(url, body) {
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then((r) => {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    }).catch((e) => { alert("Błąd: " + e.message); throw e; });
  }

  function setActive(saved) {
    inc.active = saved;
    inc.selected = new Set(saved.blocked_edges);
    inc.strategies = (saved.decision && saved.decision.lines) || {};
    $("inc-active").hidden = false;
    $("inc-active-title").textContent = `Awaria ${saved.id}: ${saved.location_text || saved.analysis.blocked_names.join(", ")}`;
    $("inc-active-meta").textContent = `${saved.cause} · od ${new Date(saved.created_at * 1000).toLocaleTimeString("pl-PL")}` + (saved.expected_until ? ` · ${saved.expected_until}` : "");
    showAnalysis(saved.analysis);
  }

  // ------------------------------------------------------------ wizualizacja
  function showAnalysis(res) {
    inc.analysis = res;
    inc.blocked = new Set(res.blocked_edges);
    inc.detour = new Set(); inc.shuttle = new Set();
    res.affected_lines.forEach((l) => {
      const st = strategyOf(l);
      if (st === "detour" && l.detour.found) l.detour.edges.forEach((e) => inc.detour.add(e));
      if (st === "shuttle" && l.shuttle && l.shuttle.possible) l.shuttle.path_edges.forEach((e) => inc.shuttle.add(e.replace(/:shuttle$/, "")));
    });
    inc.vehicleSit = new Map(res.affected_vehicles.filter((v) => v.situation !== "unaffected").map((v) => [v.vehicle_code, v.situation]));
    TD.restyleEdges();
    if (live.lastSnapshot) TD.renderTrams(live.lastSnapshot);

    layers.incident.clearLayers();
    // punkty zawracania (domyślne) i przystanki bez obsługi
    const shownTb = new Set();
    res.affected_lines.forEach((l) => {
      ["side_a", "side_b"].forEach((sk) => {
        const s = l[sk];
        [["default_unidirectional", false], ["default_bidirectional", true]].forEach(([k, bi]) => {
          const c = s[k];
          if (!c || shownTb.has(c.id)) return;
          shownTb.add(c.id);
          L.marker([c.lat, c.lon], { icon: L.divIcon({ html: `<div class="tb-big${c.for === "bidirectional" ? " bi" : ""}">↩ ${c.name}</div>`, className: "", iconAnchor: [0, 10] }), zIndexOffset: 500 })
            .bindTooltip(`${kindOf(c)}${c.for === "bidirectional" ? ", tylko tabor dwukierunkowy" : ""}, ${c.distance_to_block_m} m od blokady`).addTo(layers.incident);
        });
      });
    });
    // przystanki bez obsługi: po nazwie ze state.data
    const unserved = new Set(res.unserved_stops_all);
    state.data.features.forEach((f) => {
      const p = f.properties;
      if (p.kind === "tram_stop" && p.name && unserved.has(stripNo(p.name))) {
        L.marker([f.geometry.coordinates[1], f.geometry.coordinates[0]], { icon: L.divIcon({ html: '<div class="stop-x">✕</div>', className: "", iconSize: [16, 16], iconAnchor: [8, 8] }), interactive: false }).addTo(layers.incident);
      }
    });

    // panel
    const box = $("inc-result");
    box.hidden = false;
    let html = `<div class="summary"><b>Blokada:</b> ${res.blocked_names.join(", ")} (${res.blocked_edges.length} odc.)<br>${res.summary_pl}</div>`;
    res.affected_lines.forEach((l) => {
      const col = TD.LINE_COLORS[l.ref] || "#444";
      html += `<div class="card"><h3><span class="pill" style="background:${col}">${l.ref}</span> ${l.from} → ${l.to}</h3>`;
      const st = strategyOf(l);
      html += `<div class="strategy" data-ref="${l.ref}">` +
        opt(l.ref, "detour", "objazd", st, l.detour.found) + opt(l.ref, "shuttle", "wahadło", st, !!(l.shuttle && l.shuttle.possible)) +
        opt(l.ref, "shorten", "skrócenie", st, true) + opt(l.ref, "suspended", "zawieszenie", st, true) + `</div>`;
      if (l.detour.found) {
        html += `<div class="ok">Objazd: +${l.detour.extra_length_m} m` + (l.detour.via_names.length ? ` przez ${l.detour.via_names.join(", ")}` : "") + `</div>`;
        if (l.detour.skipped_stops.length) html += `<div>Pominięte: ${l.detour.skipped_stops.join(", ")}</div>`;
      } else {
        html += `<div class="no">Brak objazdu po innych torach.</div>`;
      }
      const sh = l.shuttle || {};
      if (sh.possible) {
        html += `<div class="shuttle"><b>Wahadło po jednym torze:</b> między ${sh.crossover_before.name} a ${sh.crossover_after.name}, ${sh.single_track_m} m jednotorowo, przejazd ok. ${Math.round(sh.pass_time_s / 60)} min. ` +
          `Przepustowość ok. ${sh.capacity_per_h_per_dir}/h/kier. przy zapotrzebowaniu ok. ${sh.demand_per_h_per_dir}/h ` + (sh.sufficient ? `<span class="ok">(wystarczy)</span>` : `<span class="no">(za mało, część linii skrócić)</span>`) +
          (sh.stops_opposite_platform.length ? `<br>Przystanki z peronu przeciwnego: ${sh.stops_opposite_platform.join(", ")}` : "") + `<br><span class="muted">${sh.note}</span></div>`;
      } else if (sh.reason && !res.both_directions) {
        html += `<div class="shuttle no">Wahadło: ${sh.reason}.</div>`;
      }
      html += sideHtml("Od " + l.side_a.terminus, l.side_a) + sideHtml("Od " + l.side_b.terminus, l.side_b);
      if (l.unserved_stops.length) html += `<div class="muted">Bez obsługi przy skróceniu: ${l.unserved_stops.join(", ")}</div>`;
      html += `</div>`;
    });
    const veh = res.affected_vehicles.filter((v) => v.situation !== "unaffected");
    html += `<div class="card"><h3>Składy (${veh.length})</h3>`;
    if (!veh.length) html += `<div class="muted">Żaden tramwaj z feedu nie jest w tej chwili dotknięty.</div>`;
    veh.forEach((v) => {
      html += `<div class="veh"><span class="pill" style="background:${TD.LINE_COLORS[v.line] || "#444"}">${v.line}</span><span>${v.vehicle_code}</span>` +
        `<span>${v.bidirectional === true ? "dwukier." : v.bidirectional === false ? "jednokier." : "?"}, ${v.distance_to_block_m ?? "?"} m` +
        (v.nearest_turnback ? `, zawrót: ${v.nearest_turnback.name}` : v.situation === "approaching" ? ", <b>brak zawrotu przed blokadą</b>" : "") + `</span>` +
        `<span class="sit sit-${v.situation}">${SIT_LABEL[v.situation]}</span></div>`;
    });
    html += `</div>`;
    box.innerHTML = html;
    box.querySelectorAll(".strategy label:not(.dis)").forEach((lab) => {
      lab.onclick = () => {
        const ref = lab.parentElement.dataset.ref;
        inc.strategies[ref] = lab.dataset.value;
        if (inc.active) {
          fetch(`/api/incidents/${inc.active.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision: { ...(inc.active.decision || {}), lines: inc.strategies } }) })
            .then((r) => r.json()).then((full) => { inc.active = full; showAnalysis(full.analysis); });
        } else {
          showAnalysis(inc.analysis);
        }
      };
    });
  }

  function strategyOf(l) {
    const chosen = inc.strategies[l.ref];
    if (chosen) return chosen;
    if (l.detour.found) return "detour";
    if (l.shuttle && l.shuttle.possible) return "shuttle";
    return "shorten";
  }
  function opt(ref, value, label, current, enabled) {
    return `<label class="${current === value ? "on" : ""}${enabled ? "" : " dis"}" data-value="${value}">${label}</label>`;
  }

  // ------------------------------------------------------------ komunikaty
  const MSG_LABEL = { passenger_pl: "Pasażerowie (PL)", passenger_en: "Pasażerowie (EN)", drivers: "Motorniczowie (służbowy)", restored_pl: "Przywrócenie ruchu (PL)", restored_en: "Przywrócenie ruchu (EN)" };
  function showMessages(messages) {
    const box = $("msg-fields");
    box.innerHTML = "";
    Object.keys(MSG_LABEL).forEach((k) => {
      const lab = document.createElement("label");
      lab.innerHTML = `${MSG_LABEL[k]} <button class="copy" data-key="${k}">Kopiuj</button>`;
      const ta = document.createElement("textarea"); ta.dataset.key = k; ta.value = messages[k] || "";
      box.appendChild(lab); box.appendChild(ta);
    });
    box.querySelectorAll(".copy").forEach((b) => {
      b.onclick = (e) => { e.preventDefault(); const ta = box.querySelector(`textarea[data-key="${b.dataset.key}"]`); navigator.clipboard.writeText(ta.value).then(() => { b.textContent = "Skopiowano"; b.classList.add("copied"); setTimeout(() => { b.textContent = "Kopiuj"; b.classList.remove("copied"); }, 1500); }); };
    });
    $("msg-box").hidden = false;
  }
  let generating = false;
  function generateMessages() {
    if (!inc.active || generating) return;
    generating = true;
    $("msg-regen").disabled = true;
    fetch(`/api/incidents/${inc.active.id}/messages`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })
      .then((r) => r.json()).then((d) => { inc.active.messages = d.messages; inc.active.messages_edited = false; showMessages(d.messages); })
      .finally(() => { generating = false; $("msg-regen").disabled = false; });
  }
  $("inc-messages").onclick = () => {
    if (!inc.active) return;
    const box = $("msg-box");
    if (!box.hidden) { box.hidden = true; $("inc-messages").textContent = "Komunikaty"; return; }
    $("inc-messages").textContent = "Ukryj komunikaty";
    if (inc.active.messages && inc.active.messages.passenger_pl) showMessages(inc.active.messages); else generateMessages();
  };
  $("msg-regen").onclick = generateMessages;
  $("msg-save").onclick = () => {
    const messages = {};
    $("msg-fields").querySelectorAll("textarea").forEach((ta) => { messages[ta.dataset.key] = ta.value; });
    fetch(`/api/incidents/${inc.active.id}/messages`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ messages }) })
      .then((r) => r.json()).then((d) => { inc.active.messages = d.messages; inc.active.messages_edited = true; $("msg-save").textContent = "Zapisano"; setTimeout(() => { $("msg-save").textContent = "Zapisz teksty"; }, 1500); });
  };

  function sideHtml(title, s) {
    const u = s.default_unidirectional, b = s.default_bidirectional;
    let t = `<div><b>${title}:</b> `;
    if (!u && !b) return t + `<span class="no">brak miejsca zawracania</span></div>`;
    t += u ? `jednokier. ↩ ${u.name} (${kindOf(u)}, ${u.distance_to_block_m} m)` : `<span class="no">jednokier.: brak</span>`;
    if (b && (!u || b.id !== u.id)) t += `; dwukier. ↩ ${b.name} (${kindOf(b)}, ${b.distance_to_block_m} m)`;
    if (u && u.existing_variant) t += ` <span class="muted">– istnieje wariant „${u.existing_variant.replace(/^Tram \\d+: /, "")}”</span>`;
    return t + `</div>`;
  }

  function stripNo(name) { const p = name.trim().split(/\s+/); if (p.length > 1 && /^\d+$/.test(p[p.length - 1])) p.pop(); return p.join(" "); }

  // ------------------------------------------------------------ dziennik
  function loadLog() {
    fetch("/api/incidents").then((r) => r.json()).then(({ incidents }) => {
      const box = $("inc-log");
      if (!incidents.length) { box.textContent = "brak"; return; }
      box.innerHTML = "";
      incidents.forEach((i) => {
        const d = document.createElement("div");
        const t = new Date(i.created_at * 1000);
        d.innerHTML = `<span class="st ${i.status}">${i.status === "active" ? "AKTYWNA" : "zakończona"}</span>${t.toLocaleDateString("pl-PL")} ${t.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" })} · ${i.location_text || i.analysis.blocked_names.join(", ")} · linie ${i.analysis.lines_hit.join(", ") || "–"}`;
        d.onclick = () => fetch(`/api/incidents/${i.id}`).then((r) => r.json()).then((full) => { clearAll(); setActive(full); });
        box.appendChild(d);
      });
      // aktywna awaria po odświeżeniu strony
      const act = incidents.find((i) => i.status === "active");
      if (act && !inc.active && !inc.reporting) fetch(`/api/incidents/${act.id}`).then((r) => r.json()).then(setActive);
    });
  }
  loadLog();

  // odświeżanie sytuacji składów przy aktywnej awarii (co 15 s)
  setInterval(() => {
    if (!inc.active || inc.reporting || live.historyMinutes > 0) return;
    fetch(`/api/incidents/${inc.active.id}`).then((r) => r.json()).then((full) => {
      if (!inc.active || full.id !== inc.active.id) return;
      full.messages = full.messages || inc.active.messages;
      inc.active = full;
      showAnalysis(full.analysis);
    });
  }, 15000);
})();
