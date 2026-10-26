# Tramdispatch Gdańsk — plan MVP

Narzędzie doradcze dla dyspozytora tramwajowego w Gdańsku. Dyspozytor zaznacza awarię na mapie torów, program wskazuje dotknięte linie i składy, proponuje objazdy lub miejsca zawracania, i generuje komunikaty z szablonów. Działa wyłącznie na publicznych danych (OSM + otwarte dane ZTM Gdańsk). Nie integruje się z żadnym systemem wewnętrznym ZTM. Nie używa modeli językowych.

Data planu: 2026-10-26. Autor planu: Claude Fable 5.1. Implementacja: Claude Opus na podstawie tego pliku.

---

## 1. Ustalenia z badania danych (zweryfikowane 2026-10-26)

### 1.1 Otwarte dane ZTM Gdańsk (zbiór "tristar" na ckan.multimediagdansk.pl)

| Zasób | URL | Uwagi |
|---|---|---|
| Pozycje GPS wszystkich pojazdów | `https://ckan2.multimediagdansk.pl/gpsPositions?v=2` | JSON, ~157 pojazdów, ~43 tramwaje wieczorem. **Brak nagłówka Access-Control-Allow-Origin** — przeglądarka nie pobierze bezpośrednio, konieczny backend-proxy. |
| Komunikaty na tablicach przystankowych | `https://ckan2.multimediagdansk.pl/displayMessages` | JSON, brak CORS. Wzorzec stylu komunikatów ZTM. |
| Estymowane odjazdy | `https://ckan2.multimediagdansk.pl/departures?stopId=` | poza MVP |
| Bieżące utrudnienia | `https://files.cloudgdansk.pl/d/otwarte-dane/ztm/bsk.json` | zwraca 301, sprawdzić docelowy adres; wzorzec treści komunikatów |
| Zmiany na trasach | `https://files.cloudgdansk.pl/d/otwarte-dane/ztm/znt.json?v=1` | j.w. |
| GTFS statyczny | `https://ckan.multimediagdansk.pl/dataset/c24aa637-3619-4dc2-a171-a23eec8f2172/resource/30e783e4-2bec-4a7d-bb22-ee3e3b26ca96/download/gtfsgoogle.zip` | ZIP ~30 MB, ma CORS. Przystanki, linie, trasy, kształty. |
| Linki GTFS-RT | `.../resource/976e1fd1-73d9-4237-b6ba-3c06004d1105/download/linki.json` | opcjonalnie, zamiast gpsPositions |

Struktura rekordu pojazdu w `gpsPositions`:

```json
{"generated":"2026-10-26T20:46:12Z","routeShortName":"12","tripId":312,"routeId":12,
 "headsign":"Ujeścisko","vehicleCode":"1037","vehicleService":"012-01","vehicleId":441,
 "speed":0,"direction":90,"delay":0,"scheduledTripStartTime":"2026-10-26T19:19:00Z",
 "lat":54.33108901977539,"lon":18.573579788208006,"gpsQuality":3}
```

- `delay` w sekundach, bywa ujemny i bywa absurdalnie duży (odrzucać |delay| > 3600 jako brak danych).
- Rekordy z `lat`/`lon` = 0 lub `gpsQuality` = 0 odrzucać.
- `generated` starsze niż 120 s od `lastUpdate` oznacza pojazd niekomunikujący się; pokazać wyszarzony.
- Tramwaje = `routeShortName` liczbowe 2..12 (w feedzie są też autobusy i linie nocne N, metropolitalne M, tymczasowe T).
- Odpytywać co 15 s.

### 1.2 OpenStreetMap — Gdańsk, zapytanie Overpass

Zapytanie (area admin_level=8 name=Gdańsk):

```
[out:json][timeout:90];
area["name"="Gdańsk"]["admin_level"="8"]->.a;
(
  way["railway"="tram"](area.a);
  node["railway"="switch"](area.a);
  node["railway"="railway_crossing"](area.a);
  node["railway"="tram_stop"](area.a);
  relation["route"="tram"](area.a);
);
out geom;
```

Wynik 2026-10-26: 605 odcinków torów (512 `oneway=yes`, 2 `oneway=no`, 91 bez tagu), 989 zwrotnic, 86 skrzyżowań torów, 248 przystanków, 48 relacji `route=tram` (linie 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12 z wariantami tras, np. skróty do Strzyża PKM, Nowy Port Zajezdnia, Władysława IV, Chełm Witosa, Siedlce).

Uwagi:
- Overpass bez nagłówka `User-Agent` zwraca 406. Ustawiać własny UA.
- Serwer `overpass-api.de` bywa wolny; dane pobierać raz skryptem i commitować do repo jako `data/osm_tram.json`. Użytkownik nie potrzebuje Overpass do uruchomienia.
- Relacje `route=tram` zawierają listę odcinków torów i przystanków w kolejności, to najlepsze źródło przypisania linia → tory. GTFS daje tylko `shapes.txt` (punkty), które trzeba by dopasowywać do torów. Używać OSM jako głównego źródła tras, GTFS jako źródła nazw i identyfikatorów przystanków oraz rozkładu.

### 1.3 Tabor GAiT (do potwierdzenia u dyspozytora)

Numery taborowe widoczne w feedzie 2026-10-26: 1007–1043, 1051–1083, 1111–1176.

| Zakres numerów | Typ | Kierunkowość | Zawracanie |
|---|---|---|---|
| 1001–1035 (ok.) | Pesa Swing 120NaG / Bombardier NGT6 | jednokierunkowy | tylko pętle i trójkąty |
| 1036–1043 (ok.) | Pesa Swing (2. seria) | jednokierunkowy | tylko pętle i trójkąty |
| 1051–1085 (ok.) | Pesa Jazz Duo 128NG | **dwukierunkowy** | pętle, trójkąty, przejazdy międzytorowe |
| 1101–1186 (ok.) | Düwag N8C / N8C-NF | **dwukierunkowy** | pętle, trójkąty, przejazdy międzytorowe |

Tabela typów w pliku `data/fleet.json` edytowalnym ręcznie. Zakresy powyżej są przybliżone i wymagają korekty przez dyspozytora.

### 1.4 Odpowiedzi na pytania projektowe

- **Bez AI**: tak, w całości. Objazdy = algorytmy grafowe, komunikaty = szablony Jinja2. Zero zewnętrznych API poza ZTM.
- **GitHub**: kod publiczny w repo, `git clone` + jedna komenda uruchamia lokalnie. GitHub Pages nie wystarczy, bo feed ZTM nie ma CORS i bo historia pozycji wymaga procesu, który działa w tle.
- **Live pozycje**: w MVP, z 4 funkcjami: składy na mapie, składy dotknięte awarią, opóźnienia kolorem, historia ostatnich 60 minut.
- **Komunikaty**: pasażerskie PL, pasażerskie EN, służbowe dla motorniczych, komunikat o przywróceniu ruchu.

---

## 2. Architektura

```
repo/
  README.md
  PLAN.md                     (ten plik)
  pyproject.toml              (uv / pip; Python 3.12)
  run.sh / run.ps1            (uruchamia backend i otwiera przeglądarkę)
  data/
    osm_tram.json             (surowe dane Overpass, commitowane)
    gtfs/                     (rozpakowane: stops.txt, routes.txt, trips.txt, stop_times.txt, shapes.txt)
    fleet.json                (numer taborowy → typ, kierunkowość)
    overrides.json            (ręczne poprawki grafu: dodane/usunięte krawędzie, oznaczenia pętli)
    templates/                (szablony komunikatów .txt.j2)
  scripts/
    fetch_osm.py              (Overpass → data/osm_tram.json)
    fetch_gtfs.py             (ZIP → data/gtfs/)
    build_graph.py            (OSM + overrides → data/graph.json, walidacja, raport)
  backend/
    app.py                    (FastAPI)
    graph.py                  (ładowanie grafu, routing, zawracanie)
    lines.py                  (linie, warianty, przystanki na krawędziach)
    incidents.py              (model awarii, analiza wpływu)
    live.py                   (poller ZTM, bufor historii, filtr tramwajów)
    messages.py               (renderowanie szablonów)
    store.py                  (SQLite: incidents, positions_history, decisions)
  frontend/
    index.html                (jeden plik + vendor/leaflet)
    app.js
    style.css
    vendor/leaflet/
  tests/
    test_graph.py
    test_routing.py
    test_incidents.py
    test_messages.py
    fixtures/scenarios.json   (5 prawdziwych awarii od dyspozytora)
```

Stos: Python 3.12, FastAPI + uvicorn, NetworkX, Jinja2, SQLite (stdlib), httpx. Front: czysty JS + Leaflet 1.9 (vendored, bez CDN, żeby działało offline po starcie). Brak frameworka frontowego, brak bundlera. Brak zewnętrznych usług poza ZTM i kafelkami mapy (OSM tiles; opcjonalnie cache kafelków w `data/tiles/` na później).

Uruchomienie: `uv run tramdispatch` lub `python -m backend.app` → serwer na `http://127.0.0.1:8765`, otwiera przeglądarkę.

---

## 3. Model danych

### 3.1 Graf torów (`graph.py`)

- **Węzeł** = punkt OSM będący zwrotnicą, końcem odcinka, przystankiem lub miejscem łączenia odcinków. Atrybuty: `osm_id`, `lat`, `lon`, `kind` ∈ {switch, stop, end, plain, crossing}, `stop_name`, `gtfs_stop_ids[]`.
- **Krawędź skierowana** = fragment odcinka toru między dwoma węzłami. Atrybuty: `osm_way_id`, `length_m`, `line_refs[]` (które linie tędy jeżdżą wg relacji OSM), `name` (nazwa ulicy z OSM), `geometry` (lista współrzędnych).
- Odcinki `oneway=yes` dają jedną krawędź, `oneway=no` i bez tagu dają dwie (ostrzeżenie w raporcie budowy grafu dla tych 91 bez tagu, do ręcznej weryfikacji).
- **Punkty zawracania** (wyliczane + overrides):
  - `loop`: pętla — cykl w grafie, którym tramwaj jednokierunkowy zmienia kierunek. Wykrywanie: cykle o długości < 600 m zawierające przystanek końcowy z GTFS (nazwy pętli: Jelitkowo, Łostowice Świętokrzyska, Lawendowe Wzgórze, Nowy Port Zajezdnia, Nowy Port Oliwska, Brzeźno Dom Zdrojowy, Strzyża PKM, Brętowo PKM, Oliwa, Zaspa, Ujeścisko, Głęboka, Chełm Witosa, Siedlce, Władysława IV, Wilka-Krzyżanowskiego).
  - `triangle`: trójkąt torowy, zestaw 3 zwrotnic pozwalający zawrócić z cofaniem. Tylko z overrides (ręcznie).
  - `crossover`: przejazd międzytorowy, para zwrotnic łącząca tor A→B z B→A. Wykrywanie: krawędź między węzłem `switch` na torze w jednym kierunku a `switch` na równoległym torze w przeciwnym, długość < 80 m. Dostępny tylko dla taboru dwukierunkowego.
- `overrides.json` ma format: `{"add_edges":[...], "remove_edges":[...], "turnbacks":[{"node":id,"kind":"triangle","name":"..."}], "notes":[...]}`. Nakładany po wczytaniu OSM. Każdy override ma pole `reason` (tekst od dyspozytora).

`scripts/build_graph.py` wypisuje raport: liczba komponentów spójności (powinien być 1 lub 2 z zajezdniami), węzły stopnia 1 niebędące pętlami (prawdopodobnie błędy danych), odcinki bez `oneway`, wykryte pętle i przejazdy. Ten raport to pierwsza rzecz do pokazania dyspozytorowi.

### 3.2 Linie (`lines.py`)

Z relacji `route=tram` OSM: `{"ref":"6","variant_id":osm_rel_id,"name":"Tram 6: Jelitkowo => Łostowice Świętokrzyska","from":"Jelitkowo","to":"Łostowice Świętokrzyska","edges":[...],"stops":[...]}`. Warianty tej samej linii (48 relacji dla 11 linii) grupowane po `ref`. Wariant "podstawowy" = najdłuższy w każdym kierunku; warianty skrócone (do Strzyża PKM itp.) zachowane jako gotowe propozycje skrócenia trasy przy awarii.

Z GTFS: mapowanie `stop_name` → `stop_id`, `stop_code`, oraz częstotliwość kursów na linii w danej godzinie (z `stop_times.txt`, do szacowania wpływu — liczba kursów/h, nie pasażerów, bo napełnień nie mamy).

### 3.3 Awaria (`incidents.py`)

```json
{
  "id": "2026-10-26T21:03:00+01:00-001",
  "status": "active | planned | resolved",
  "blocked_edges": [edge_id, ...],
  "location_text": "Al. Grunwaldzka przy Galerii Bałtyckiej, tor w kier. Oliwy",
  "cause": "awaria sieci trakcyjnej | kolizja | awaria składu | zdarzenie z pieszym | inne",
  "both_directions": true,
  "started_at": "...", "expected_until": "... | null", "resolved_at": null,
  "analysis": { ... wynik 3.4 ... },
  "decision": { ... co dyspozytor zatwierdził, wolny tekst + wybrane propozycje ... },
  "messages": { "passenger_pl": "...", "passenger_en": "...", "drivers": "...", "restored_pl": "...", "restored_en": "..." }
}
```

Zapis w SQLite. Historia awarii = dziennik zdarzeń.

### 3.4 Analiza wpływu (wynik algorytmu, sekcja 4)

```json
{
  "affected_lines": [
    {
      "ref": "6", "variant": "Jelitkowo => Łostowice Świętokrzyska",
      "crosses_block": true,
      "detour": {"found": true, "edges":[...], "extra_length_m": 1250, "skipped_stops":[...], "added_stops":[...]} | {"found": false},
      "turnbacks": {
        "side_a": {"from_terminus":"Jelitkowo", "nearest": [{"name":"Strzyża PKM","kind":"loop","distance_to_block_m":900,"for":"all"}, {"name":"przejazd Grunwaldzka/Hallera","kind":"crossover","distance_to_block_m":300,"for":"bidirectional"}]},
        "side_b": {...}
      },
      "unserved_stops": ["Galeria Bałtycka", "Politechnika", ...],
      "existing_short_variant": "Tram 6: Jelitkowo => Strzyża PKM" | null,
      "trips_per_hour_now": 6
    }
  ],
  "affected_vehicles": [
    {"vehicleCode":"1062","line":"6","headsign":"Łostowice","type":"Jazz Duo","bidirectional":true,
     "situation":"approaching | trapped_between | beyond | unaffected", "distance_to_block_m": 1400,
     "nearest_turnback": {...}}
  ],
  "unserved_stops_all": [...],
  "summary_pl": "Linie 6, 8, 12. Brak objazdu dla 6 i 8. Zawracanie: Strzyża PKM / Zaspa."
}
```

---

## 4. Algorytmy

### 4.1 Routing objazdu

1. Graf G bez `blocked_edges` (dla `both_directions=false` blokujemy tylko krawędzie w podanym kierunku).
2. Dla każdego wariantu linii, którego `edges` przecinają blokadę: znajdź ostatni węzeł przed blokadą `u` i pierwszy po blokadzie `v` na trasie. Dijkstra `u → v` po G ważony `length_m`. Jeśli ścieżka istnieje i `extra_length_m < 4000` (parametr), to `detour.found = true`. Nowa trasa = prefix + ścieżka + sufiks. `skipped_stops` = przystanki oryginalnej trasy nie na nowej; `added_stops` = przystanki na ścieżce objazdu (tramwaj może na nich stawać).
3. Zasada praktyczna: objazd w Gdańsku rzadko istnieje (sieć w dużej mierze drzewiasta z kilkoma pierścieniami w centrum: Hucisko–Brama Wyżynna–Dworzec Główny, Wrzeszcz, Siedlce). Program ma to uczciwie powiedzieć ("brak objazdu") i przejść do zawracania.

### 4.2 Zawracanie

Dla każdej strony blokady (A: od terminusa początkowego, B: od końcowego): idąc trasą linii wstecz od blokady, zbierz punkty zawracania w promieniu 5 km (parametr), z typem i odległością. Dla taboru jednokierunkowego tylko `loop` i `triangle`. Posortuj po odległości. Pierwszy wynik = propozycja domyślna. Jeśli istnieje wariant skrócony z OSM/GTFS kończący się w tym punkcie, podaj go nazwą (dyspozytor zna te nazwy).

Specjalny przypadek: zablokowany odcinek tuż przy pętli → linia skrócona do poprzedniej pętli, pętla końcowa nieobsługiwana.

### 4.3 Składy dotknięte awarią (live)

Dla każdego tramwaju z feedu: rzutuj pozycję na najbliższą krawędź jego linii (po `routeShortName` i `headsign` dobierz wariant; rzutowanie = najbliższa krawędź wariantu w promieniu 60 m, inaczej `unmatched`). Pozycja na trasie = indeks krawędzi + offset. Porównaj z pozycją blokady na tym wariancie:

- `approaching`: przed blokadą, jedzie w jej stronę. Podaj dystans i najbliższy punkt zawracania przed blokadą (wg 4.2 i typu taboru).
- `beyond`: za blokadą, oddala się. Nieaktywnie dotknięty, ale w drodze powrotnej będzie `approaching`.
- `trapped_between`: na odcinku między blokadą a końcem trasy, który nie ma pętli ani przejazdu dostępnego dla tego typu taboru. To są składy, które trzeba holować lub które muszą czekać. Najważniejsza informacja na ekranie.
- `unaffected`: wariant nie przechodzi przez blokadę.

### 4.4 Historia pozycji

`live.py` co 15 s zapisuje do SQLite tabeli `positions(ts, vehicleCode, line, lat, lon, delay, speed, headsign)` tylko tramwaje, z retencją 24 h (czyszczenie co godzinę). Endpoint `/api/history?vehicle=1062&minutes=60` zwraca ślad. Front rysuje polyline po kliknięciu składu i ma suwak "cofnij o N minut" pokazujący pozycje wszystkich składów w wybranej chwili (snapshot = ostatni rekord każdego pojazdu przed ts).

### 4.5 Opóźnienia

Kolor kropki: `delay ≤ 60` zielony, `≤ 180` żółty, `≤ 600` pomarańczowy, `> 600` czerwony, brak danych szary. Ujemne = przed czasem, niebieski.

---

## 5. API backendu (FastAPI)

| Metoda | Ścieżka | Opis |
|---|---|---|
| GET | `/api/network` | GeoJSON: krawędzie (z `line_refs`), węzły zwrotnic, przystanki, punkty zawracania. Cache w pamięci. |
| GET | `/api/lines` | lista linii z wariantami i przystankami |
| GET | `/api/live` | ostatni snapshot tramwajów (przefiltrowany, znormalizowany, z `age_s`, `type`, `bidirectional`) |
| GET | `/api/history?vehicle=&minutes=` / `?at=ts` | ślad jednego pojazdu / snapshot z przeszłości |
| POST | `/api/incidents` | utworzenie awarii, zwraca awarię z `analysis` |
| GET | `/api/incidents` `?status=` | lista |
| GET | `/api/incidents/{id}` | szczegóły z aktualną analizą (analiza składów liczona na bieżąco z live) |
| PATCH | `/api/incidents/{id}` | edycja (status, decision, expected_until, blocked_edges) → przelicza analizę |
| POST | `/api/incidents/{id}/messages` | render komunikatów z szablonów; body = parametry nadpisujące (np. ręcznie wybrane punkty zawracania) |
| GET | `/api/health` | wiek ostatniego snapshotu ZTM, stan grafu |

Backend serwuje `frontend/` jako statyczne pliki pod `/`.

---

## 6. Frontend (jeden ekran)

Układ: mapa na 70% szerokości, panel boczny 30%.

**Mapa**
- Warstwa torów: szare linie; po wybraniu linii w panelu jej trasa podświetlona kolorem.
- Zwrotnice jako małe punkty widoczne od zoomu 15. Punkty zawracania ikonami (pętla, trójkąt, przejazd).
- Przystanki z nazwą po najechaniu.
- Tramwaje: kółko z numerem linii, kolor wg opóźnienia, obrót strzałki wg `direction`. Kliknięcie: numer taborowy, typ, kierunek, opóźnienie, wiek pozycji, ślad 60 min.
- Tryb "zgłoś awarię": kliknięcie na tor zaznacza krawędź (czerwona). Można zaznaczyć kilka. Przełącznik "oba kierunki".
- Po analizie: blokada czerwona, objazd zielony przerywany, punkty zawracania duże ikony z etykietą, przystanki nieobsługiwane przekreślone, składy `approaching` pomarańczowa obwódka, `trapped_between` czerwona pulsująca.

**Panel**
1. Nagłówek: zegar, wiek feedu ZTM (zielony/czerwony), liczba tramwajów na mapie.
2. Zakładka **Awaria**: formularz (lokalizacja tekstowo — autouzupełnianie z nazw ulic/przystanków, przyczyna, kierunki, przewidywany czas), przycisk "Analizuj". Wynik: lista linii z kartami (objazd / zawracanie z radio do wyboru propozycji / przystanki wypadające / kursy na godzinę), lista składów dotkniętych posortowana: trapped → approaching → beyond.
3. Zakładka **Komunikaty**: 5 pól tekstowych (pasażerski PL, pasażerski EN, motorniczowie, przywrócenie PL, przywrócenie EN), każde z "Kopiuj". Edytowalne; po edycji ręcznej nie nadpisywać przy ponownym renderze bez potwierdzenia.
4. Zakładka **Dziennik**: aktywne i zakończone awarie, przycisk "Zakończ" (ustawia `resolved_at`, podsuwa komunikat o przywróceniu), eksport dziennika do CSV.
5. Zakładka **Historia**: suwak czasu 0–60 min wstecz, mapa pokazuje snapshot.

Język UI: polski. Brak logowania.

---

## 7. Komunikaty — szablony

Styl wzorowany na realnych komunikatach ZTM (displayMessages używa WIELKICH LITER i dwóch krótkich linii; strona ZTM używa formy "Utrudnienia w ruchu tramwajów. Linie X, Y kursują..."). Zebrać 5–10 prawdziwych komunikatów z bsk.json / strony ztm.gda.pl do `data/templates/examples.md` przed pisaniem szablonów.

`passenger_pl.txt.j2` (szkic):
```
UTRUDNIENIA W RUCHU TRAMWAJÓW
{{ location_text }}{% if cause %} — {{ cause_label }}{% endif %}.
{% for l in lines %}
Linia {{ l.ref }}{% if l.detour.found %} kursuje objazdem przez {{ l.detour.via_names|join(", ") }}{% else %} kursuje na skróconej trasie {{ l.side_a.terminus }} – {{ l.side_a.turnback.name }} oraz {{ l.side_b.turnback.name }} – {{ l.side_b.terminus }}{% endif %}.
{% endfor %}
Przystanki nieobsługiwane: {{ unserved_stops|join(", ") }}.
{% if replacement_bus %}Uruchomiono autobusową komunikację zastępczą {{ replacement_bus }}.{% endif %}
Przewidywany czas: {{ expected_until_text }}.
```

`passenger_en.txt.j2`: ten sam szablon po angielsku, z nazwami przystanków bez tłumaczenia. Tłumaczenie etykiet (przyczyna, "skrócona trasa", "objazd") ze słownika w `messages.py`, nie z modelu.

`drivers.txt.j2`:
```
KOMUNIKAT SŁUŻBOWY {{ now_text }}
Blokada: {{ location_text }} ({{ cause_label }}), kier.: {{ directions_text }}.
{% for l in lines %}L{{ l.ref }}: {% if l.detour.found %}objazd {{ l.detour.via_names|join(" – ") }}{% else %}zawracanie {{ l.side_a.turnback.name }} ({{ l.side_a.turnback.kind_label }}) / {{ l.side_b.turnback.name }} ({{ l.side_b.turnback.kind_label }}){% endif %}. Nieobsł.: {{ l.unserved_stops|join(", ") }}.
{% endfor %}
Składy jednokierunkowe zawracają wyłącznie na pętlach. Do odwołania.
```

`restored_pl.txt.j2` / `restored_en.txt.j2`:
```
PRZYWRÓCONO RUCH TRAMWAJÓW
{{ location_text }}. Linie {{ line_refs|join(", ") }} wracają na stałe trasy. Mogą występować opóźnienia.
```

Zmienne wejściowe renderu: wynik analizy + wybór dyspozytora (które punkty zawracania zatwierdził) + pola formularza. `cause_label` i `kind_label` ze słowników PL/EN.

---

## 8. Testy

- `tests/fixtures/scenarios.json`: 5 realnych awarii spisanych z dyspozytorem: miejsce (nazwa ulicy/przystanku → zamienić na edge_id przy pierwszym uruchomieniu), oczekiwane dotknięte linie, oczekiwane punkty zawracania. Testy sprawdzają, że program zwraca te same linie i że zatwierdzone przez dyspozytora punkty zawracania są na liście propozycji (niekoniecznie pierwsze).
- `test_graph.py`: graf spójny, każda relacja linii z OSM tworzy ciągłą ścieżkę w grafie (to wykrywa brakujące zwrotnice i złe `oneway`), każda pętla z listy w 3.1 wykryta.
- `test_routing.py`: syntetyczny graf (pierścień + odnogi) z blokadami w różnych miejscach; objazd istnieje tylko na pierścieniu; jednokierunkowy nie dostaje przejazdu jako punktu zawracania.
- `test_messages.py`: snapshot renderu dla jednego scenariusza; brak pustych nawiasów i "None" w tekście.
- `live.py`: test na zapisanej próbce JSON z feedu (`tests/fixtures/gpsPositions_sample.json`), sprawdza filtr tramwajów i odrzucanie rekordów zerowych.

---

## 9. Kolejność implementacji (dla Opusa)

Każdy etap kończy się działającym programem i commitem.

**Etap 1 — Dane i graf (bez UI)**
1. `scripts/fetch_osm.py`, `scripts/fetch_gtfs.py`, commit `data/`.
2. `graph.py` + `build_graph.py` z raportem jakości. `test_graph.py`.
3. Prosta mapa `index.html` pokazująca tylko graf, zwrotnice, pętle i przejazdy. **Pokazać dyspozytorowi, zebrać overrides.**

**Etap 2 — Linie i live**
4. `lines.py` z wariantami z OSM + nazwy z GTFS.
5. `live.py` poller + SQLite + `/api/live`, `/api/history`. Tramwaje na mapie z kolorem opóźnienia, klik → ślad.
6. Zakładka Historia z suwakiem.

**Etap 3 — Awaria**
7. `incidents.py`: blokada, routing objazdu, zawracanie wg typu taboru, składy dotknięte. `test_routing.py`, scenariusze.
8. UI zgłaszania awarii i wizualizacja analizy. **Druga runda z dyspozytorem na realnych scenariuszach.**

**Etap 4 — Komunikaty i dziennik**
9. Szablony + zakładka Komunikaty + kopiowanie.
10. Dziennik, zamykanie awarii, komunikat o przywróceniu, eksport CSV.
11. README z instrukcją instalacji na Windows i macOS, `run.sh`/`run.ps1`.

Poza MVP (nie robić teraz): komunikacja zastępcza autobusowa (routing po ulicach), awarie planowane z wyprzedzeniem, powiadomienia (SMS/Teams), szacowanie liczby pasażerów, wielu użytkowników, hosting, LLM do wygładzania komunikatów.

---

## 10. Pytania do dyspozytora przed etapem 1

1. Pięć realnych awarii z ostatnich miesięcy: gdzie, które linie, gdzie zawracano, jaki komunikat poszedł, ile trwało.
2. Które numery taborowe są dwukierunkowe (potwierdzić tabelę 1.3). Czy Jazz Duo i N8C faktycznie zawracają na przejazdach międzytorowych w praktyce, czy tylko teoretycznie.
3. Lista trójkątów torowych i przejazdów międzytorowych, których ZTM używa do zawracania (OSM może ich nie mieć lub mieć za dużo).
4. Czy zajezdnie (Wrzeszcz, Nowy Port) mają być w grafie jako miejsca, gdzie skład może zjechać.
5. Które pętle są "niepełne" (np. Władysława IV, Siedlce) i jakie mają ograniczenia pojemności.
6. Jak dziś wygląda komunikat dla motorniczych: radio, SMS, tablet? Jaki format tekstu jest praktyczny.
7. System operacyjny jego komputera w dyspozytorni (Windows?), czy może instalować Pythona, czy potrzebny jest pojedynczy plik .exe (PyInstaller) — wpływa na etap 4.

---

## 11. Ryzyka

- **Jakość zwrotnic w OSM**: 989 zwrotnic to dużo, ale jedna brakująca zmienia wynik. Overrides i raport jakości grafu są obowiązkowe, nie opcjonalne.
- **Zmiana adresów feedu ZTM**: adresy w `config.toml`, nie w kodzie. Healthcheck w UI pokazuje, kiedy feed padł.
- **Dopasowanie headsign → wariant**: feed daje `headsign` tekstowo ("Ujeścisko"), OSM daje nazwy w relacjach, GTFS daje `trip_headsign`. Normalizować (lowercase, bez polskich znaków, bez "PKM"/"Zajezdnia") i mapować ręcznie w `data/headsigns.json` tam, gdzie automat nie trafi.
- **Odpowiedzialność**: program jest doradczy. README i ekran startowy mówią to wprost. Dyspozytor zatwierdza każdą propozycję kliknięciem przed renderem komunikatów.
