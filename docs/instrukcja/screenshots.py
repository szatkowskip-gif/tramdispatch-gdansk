"""Zrzuty ekranu do instrukcji obsługi (Playwright, headless). Wymaga działającego serwera.

    .venv/bin/python docs/instrukcja/screenshots.py http://127.0.0.1:8790
"""
import sys, time, json, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8790"
OUT = Path(__file__).parent / "img"
OUT.mkdir(exist_ok=True)
EDGE = "1488892824:0"  # al. Grunwaldzka przy Galerii Bałtyckiej

def api(path, method="GET", body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req))

# zamknij ewentualne aktywne awarie, żeby zrzuty były czyste
for inc in api("/api/incidents?status=active")["incidents"]:
    api(f"/api/incidents/{inc['id']}", "PATCH", {"status": "resolved", "note": "zamknięte przed zrzutami"})

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1400, "height": 880}, device_scale_factor=2, locale="pl-PL")
    page.goto(BASE)
    page.wait_for_function("window.TD && TD.state.data && document.querySelectorAll('.tram-icon').length > 5", timeout=60000)
    time.sleep(2)
    page.screenshot(path=str(OUT / "01_glowny.png"))

    # klik w tramwaj z listy -> popup
    page.locator("#tram-list div").first.click()
    time.sleep(1.5)
    page.screenshot(path=str(OUT / "02_tramwaj.png"))

    # filtr linii: 6 i 8
    page.locator("#line-buttons button", has_text="6").first.click()
    page.locator("#line-buttons button", has_text="8").first.click()
    time.sleep(1)
    page.screenshot(path=str(OUT / "03_filtr_linii.png"))
    page.locator("#line-buttons button", has_text="wszystkie").click()

    # zgłoszenie awarii
    page.click("#inc-start")
    page.evaluate(f"TD.map.setView([54.3785, 18.6045], 15)")
    time.sleep(1.5)
    page.evaluate(f"TD.state.edgeById.get('{EDGE}').layer.fire('click')")
    page.fill("#inc-location", "al. Grunwaldzka przy Galerii Bałtyckiej")
    page.select_option("#inc-cause", "awaria sieci trakcyjnej")
    page.fill("#inc-until", "ok. 60 min")
    time.sleep(0.8)
    page.screenshot(path=str(OUT / "04_zglaszanie.png"))
    page.locator("#inc-form").screenshot(path=str(OUT / "04b_formularz.png"))

    page.click("#inc-analyze")
    page.wait_for_selector("#inc-result .card", timeout=30000)
    page.evaluate("TD.map.setView([54.372, 18.612], 13)")
    time.sleep(2)
    page.screenshot(path=str(OUT / "05_analiza_mapa.png"))
    page.locator("#inc-result").screenshot(path=str(OUT / "05b_analiza_panel.png"))
    page.locator("#inc-result .card").first.screenshot(path=str(OUT / "06_karta_linii.png"))
    page.locator("#inc-result .card").last.screenshot(path=str(OUT / "07_sklady.png"))

    page.click("#inc-save")
    page.wait_for_selector("#inc-active:not([hidden])", timeout=30000)
    time.sleep(1)
    page.locator("#inc-active").screenshot(path=str(OUT / "08_aktywna.png"))

    page.click("#inc-messages")
    page.wait_for_selector("#msg-fields textarea", timeout=30000)
    time.sleep(0.8)
    page.locator("#msg-box").screenshot(path=str(OUT / "09_komunikaty.png"))

    page.locator("#inc-log").scroll_into_view_if_needed()
    page.locator("#inc-log").screenshot(path=str(OUT / "10_dziennik.png"))

    # zakończenie awarii (z komunikatem o przywróceniu)
    page.on("dialog", lambda d: d.accept())
    page.click("#inc-resolve")
    time.sleep(2)
    page.locator("#incident-section").screenshot(path=str(OUT / "11_zakonczenie.png"))
    b.close()
print("ok", sorted(x.name for x in OUT.iterdir()))
