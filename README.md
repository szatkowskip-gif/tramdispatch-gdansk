# Tramdispatch Gdańsk

Narzędzie doradcze dla dyspozytora tramwajowego w Gdańsku. Dyspozytor zaznacza awarię na mapie torów, program wskazuje dotknięte linie i składy, proponuje objazdy lub miejsca zawracania i generuje komunikaty z szablonów.

Działa wyłącznie na publicznych danych: OpenStreetMap i otwarte dane ZTM Gdańsk. Nie łączy się z żadnym systemem wewnętrznym ZTM. Nie używa modeli językowych.

**Program jest doradczy. Każdą propozycję zatwierdza dyspozytor.**

## Stan

Etapy 1, 2 i 3 z [PLAN.md](PLAN.md) gotowe:

- graf torów ze zwrotnicami i punktami zawracania, mapa do weryfikacji przez dyspozytora, raport jakości w [data/graph_report.md](data/graph_report.md);
- linie i ich warianty tras z relacji OSM, tabela taboru (`data/fleet.json`);
- tramwaje na żywo z otwartego feedu ZTM (co 15 s), kolor wg opóźnienia, popup z numerem taborowym i typem składu, ślad z ostatniej godziny po kliknięciu, suwak cofający mapę do 60 minut wstecz, filtr po liniach. Historia pozycji w lokalnej bazie SQLite (`data/tramdispatch.db`, 24 h retencji);
- zgłaszanie awarii: zaznaczenie odcinków toru na mapie (z automatycznym dodaniem toru równoległego), analiza: dotknięte linie i warianty, objazd po pozostałych torach jeśli istnieje, punkty zawracania po obu stronach blokady osobno dla taboru jedno- i dwukierunkowego, przystanki bez obsługi, sytuacja każdego tramwaju z feedu (jedzie na blokadę / na blokadzie / za blokadą / bez możliwości zawrócenia). Dziennik awarii z zamykaniem.

Następny etap: komunikaty z szablonów i eksport dziennika (sekcja 9 planu, etap 4).

## Jak zgłosić awarię

1. „Zgłoś awarię”, potem klikaj odcinki torów na mapie (czerwone). „Oba kierunki” dokłada tor równoległy.
2. Wpisz miejsce, przyczynę i przewidywany czas. „Analizuj” pokazuje wynik bez zapisu.
3. „Zapisz awarię” zapisuje ją w dzienniku; sytuacja składów odświeża się co 15 s. „Zakończ awarię” zamyka wpis.

Program proponuje, dyspozytor decyduje. Punkty zawracania oznaczone „do weryfikacji” pochodzą z heurystyki i wymagają potwierdzenia w `data/overrides.json`.

## Uruchomienie

```bash
./run.sh
```

Serwer startuje na http://127.0.0.1:8766 i otwiera przeglądarkę. Wymaga Pythona 3.12+. Internet jest potrzebny do kafelków mapy i do feedu pozycji ZTM; bez niego działa sama mapa torów.

Dane: © OpenStreetMap contributors (ODbL), otwarte dane ZTM Gdańsk (ckan.multimediagdansk.pl).

Odświeżenie danych (rzadko, dane są w repo):

```bash
.venv/bin/python scripts/fetch_osm.py
.venv/bin/python scripts/fetch_gtfs.py
.venv/bin/python scripts/build_graph.py
```

Testy: `.venv/bin/python -m pytest`.

## Weryfikacja z dyspozytorem (po etapie 1)

Mapa pokazuje to, co program "wie" o torach. Do sprawdzenia:

1. Zielone punkty: pętle końcowe wykryte automatycznie. Czy wszystkie istnieją i czy czegoś brakuje.
2. Fioletowe: przystanki końcowe, przy których program nie znalazł pętli (zakłada zawracanie tylko składów dwukierunkowych). Jeśli pętla jest, trzeba ją dopisać w `data/overrides.json`.
3. Niebieskie: przejazdy międzytorowe wykryte heurystycznie. Które są używane do zawracania w praktyce.
4. Żółte: krótkie pierścienie i trójkąty w centrum. Czy służą do zawracania.
5. Pomarańczowe tory: odcinki poza trasami linii (łączniki). Czy są przejezdne.
6. Zakresy numerów taborowych w `data/fleet.json`.

## Struktura

- `backend/` serwer FastAPI, graf torów, routing, analiza awarii, poller pozycji ZTM, szablony komunikatów
- `frontend/` jeden ekran z mapą Leaflet, bez bundlera
- `data/` dane OSM i GTFS (pobierane skryptami i commitowane), tabela taboru, ręczne poprawki grafu, szablony
- `scripts/` pobieranie danych i budowa grafu
- `tests/` testy jednostkowe i scenariusze realnych awarii
- `config.toml` adresy feedów ZTM i parametry algorytmów
