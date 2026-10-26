# Tramdispatch Gdańsk

Narzędzie doradcze dla dyspozytora tramwajowego w Gdańsku. Dyspozytor zaznacza awarię na mapie torów, program wskazuje dotknięte linie i składy, proponuje objazdy lub miejsca zawracania i generuje komunikaty z szablonów.

Działa wyłącznie na publicznych danych: OpenStreetMap i otwarte dane ZTM Gdańsk. Nie łączy się z żadnym systemem wewnętrznym ZTM. Nie używa modeli językowych.

**Program jest doradczy. Każdą propozycję zatwierdza dyspozytor.**

## Stan

Szkielet repozytorium. Plan i specyfikacja w [PLAN.md](PLAN.md). Implementacja wg sekcji 9 planu.

## Uruchomienie (docelowo)

```bash
./run.sh
```

Serwer startuje na http://127.0.0.1:8765. Wymaga Pythona 3.12+.

## Struktura

- `backend/` serwer FastAPI, graf torów, routing, analiza awarii, poller pozycji ZTM, szablony komunikatów
- `frontend/` jeden ekran z mapą Leaflet, bez bundlera
- `data/` dane OSM i GTFS (pobierane skryptami i commitowane), tabela taboru, ręczne poprawki grafu, szablony
- `scripts/` pobieranie danych i budowa grafu
- `tests/` testy jednostkowe i scenariusze realnych awarii
- `config.toml` adresy feedów ZTM i parametry algorytmów
