# Tramdispatch Gdańsk

Narzędzie doradcze dla dyspozytora tramwajowego w Gdańsku. Dyspozytor zaznacza awarię na mapie torów, program wskazuje dotknięte linie i składy, proponuje objazdy lub miejsca zawracania i generuje komunikaty z szablonów.

Działa wyłącznie na publicznych danych: OpenStreetMap i otwarte dane ZTM Gdańsk. Nie łączy się z żadnym systemem wewnętrznym ZTM. Nie używa modeli językowych.

**Program jest doradczy. Każdą propozycję zatwierdza dyspozytor.**

## Stan

Etap 1 z [PLAN.md](PLAN.md) gotowy: dane OSM i GTFS pobrane, graf torów ze zwrotnicami i punktami zawracania, mapa do weryfikacji przez dyspozytora. Raport jakości grafu w [data/graph_report.md](data/graph_report.md).

## Uruchomienie

```bash
./run.sh
```

Serwer startuje na http://127.0.0.1:8766 i otwiera przeglądarkę. Wymaga Pythona 3.12+ i dostępu do internetu tylko dla kafelków mapy.

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
