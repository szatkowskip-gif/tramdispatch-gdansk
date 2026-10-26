"""Składa instrukcję obsługi do PDF z tekstu poniżej i zrzutów z docs/instrukcja/img/.

    .venv/bin/python docs/instrukcja/build_pdf.py
"""
from pathlib import Path

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image as RLImage, KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HERE = Path(__file__).parent
IMG = HERE / "img"
OUT = HERE.parent / "Instrukcja_Dyspozytor.pdf"

pdfmetrics.registerFont(TTFont("Arial", "/System/Library/Fonts/Supplemental/Arial.ttf"))
pdfmetrics.registerFont(TTFont("Arial-Bold", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"))
pdfmetrics.registerFontFamily("Arial", normal="Arial", bold="Arial-Bold", italic="Arial", boldItalic="Arial-Bold")

W, H = A4
MARGIN = 18 * mm
CONTENT_W = W - 2 * MARGIN

base = ParagraphStyle("base", fontName="Arial", fontSize=10.5, leading=14.5, alignment=TA_LEFT)
h1 = ParagraphStyle("h1", parent=base, fontName="Arial-Bold", fontSize=22, leading=27, spaceAfter=4)
h2 = ParagraphStyle("h2", parent=base, fontName="Arial-Bold", fontSize=14.5, leading=18, spaceBefore=14, spaceAfter=6, textColor=colors.HexColor("#1d1d1b"))
sub = ParagraphStyle("sub", parent=base, fontSize=11, textColor=colors.HexColor("#555"), spaceAfter=10)
cap = ParagraphStyle("cap", parent=base, fontSize=9, leading=11.5, textColor=colors.HexColor("#555"), spaceBefore=3, spaceAfter=10)
note = ParagraphStyle("note", parent=base, backColor=colors.HexColor("#fff7e6"), borderColor=colors.HexColor("#f3d9a4"), borderWidth=0.7, borderPadding=6, spaceBefore=6, spaceAfter=10)


JPG = HERE / "_jpg"
JPG.mkdir(exist_ok=True)


def _jpeg(name: str, max_w: int = 1600) -> Path:
    """Zrzuty są w 2x PNG (duże); do PDF idzie zmniejszony JPEG, żeby plik był lekki."""
    src = IMG / name
    dst = JPG / (Path(name).stem + ".jpg")
    if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
        im = Image.open(src).convert("RGB")
        if im.width > max_w:
            im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
        im.save(dst, "JPEG", quality=82, optimize=True)
    return dst


def img(name: str, width: float = CONTENT_W, caption: str | None = None, max_h: float = 150 * mm):
    p = _jpeg(name)
    w, h = Image.open(p).size
    scale = width / w
    if h * scale > max_h:
        scale = max_h / h
    fl = [RLImage(str(p), width=w * scale, height=h * scale)]
    if caption:
        fl.append(Paragraph(caption, cap))
    return KeepTogether(fl)


def bullets(items: list[str]):
    return ListFlowable([ListItem(Paragraph(i, base), leftIndent=12) for i in items], bulletType="bullet", bulletFontName="Arial", leftIndent=14, bulletOffsetY=-1)


def steps(items: list[str]):
    return ListFlowable([ListItem(Paragraph(i, base), leftIndent=14) for i in items], bulletType="1", bulletFontName="Arial", leftIndent=16)


def legend_table(rows, col_widths):
    t = Table(rows, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Arial"), ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("FONTNAME", (0, 0), (-1, 0), "Arial-Bold"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.7, colors.HexColor("#999")),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor("#ddd")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def color_cell(hexcolor):
    t = Table([[""]], colWidths=[6 * mm], rowHeights=[4 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), colors.HexColor(hexcolor))]))
    return t


story = []
story += [
    Paragraph("Dyspozytor tramwajowy Gdańsk", h1),
    Paragraph("Instrukcja obsługi programu, wersja 1.0", sub),
    Paragraph("Program pokazuje sieć tramwajową Gdańska i tramwaje na żywo, a po zgłoszeniu awarii podpowiada, co zrobić z każdą linią: "
              "objazd, wahadło, skrócenie do najbliższej pętli albo zawieszenie. Generuje też gotowe komunikaty do skopiowania. "
              "<b>Program tylko doradza. Decyzję zawsze podejmuje dyspozytor.</b>", base),
    Spacer(1, 6),
    Paragraph("Dane pochodzą z publicznych źródeł: mapa torów z OpenStreetMap, pozycje tramwajów i rozkłady z otwartych danych ZTM Gdańsk. "
              "Program nie łączy się z żadnym systemem wewnętrznym ZTM i niczego nie wysyła.", base),

    Paragraph("1. Logowanie", h2),
    steps([
        "Otwórz w przeglądarce adres <b>https://dyspo.piotrszatkowski.com</b> (komputer, tablet albo telefon).",
        "Wpisz swój adres e-mail i kliknij przycisk wysłania kodu.",
        "Na e-mail przyjdzie sześciocyfrowy kod. Wpisz go na stronie.",
        "Logowanie ważne jest 24 godziny, potem procedura się powtarza. Hasła nie ma.",
    ]),
    Paragraph("Dostęp mają tylko adresy wpisane na listę. Jeśli strona odrzuca Twój adres, napisz do Piotra.", note),

    Paragraph("2. Ekran główny", h2),
    Paragraph("Po lewej mapa, po prawej panel. Na mapie są tory (czarne linie), przystanki (białe kółka), zwrotnice (czerwone kropki) i tramwaje (kolorowe kółka z numerem linii).", base),
    img("01_glowny.png", caption="Rys. 1. Ekran główny: mapa z tramwajami na żywo i panel z listą składów."),
    Paragraph("Kolor tramwaju to jego opóźnienie względem rozkładu:", base),
]
story.append(legend_table(
    [["Kolor", "Znaczenie"],
     [color_cell("#2563eb"), "przed czasem"], [color_cell("#16a34a"), "na czas, do 1 minuty opóźnienia"], [color_cell("#ca8a04"), "do 3 minut"],
     [color_cell("#ea580c"), "do 10 minut"], [color_cell("#dc2626"), "ponad 10 minut"], [color_cell("#9ca3af"), "brak danych albo pozycja starsza niż 2 minuty"]],
    [20 * mm, CONTENT_W - 20 * mm]))
story += [
    Spacer(1, 8),
    bullets([
        "<b>Pasek u góry panelu</b> mówi, czy dane z ZTM płyną. Zielony: wszystko w porządku. Czerwony: feed nie odpowiada, tramwaje na mapie są nieaktualne.",
        "<b>Lista tramwajów</b> pokazuje wszystkie składy. Kliknięcie w wiersz centruje mapę na tramwaju i otwiera jego opis.",
        "<b>Kliknięcie w tramwaj</b> na mapie pokazuje numer taborowy, typ składu (jedno- czy dwukierunkowy), opóźnienie i brygadę, a na mapie rysuje jego trasę z ostatniej godziny.",
        "<b>Linie</b>: kliknięcie numeru linii w sekcji „Linie” zostawia na mapie tylko jej tramwaje i podświetla trasę. Można wybrać kilka linii naraz. „Wszystkie” przywraca komplet.",
        "<b>Historia</b>: suwak cofa mapę o 1 do 60 minut wstecz, żeby zobaczyć, gdzie tramwaje były przed awarią.",
    ]),
    img("02_tramwaj.png", caption="Rys. 2. Opis tramwaju po kliknięciu: numer taborowy, typ składu, opóźnienie."),
    img("03_filtr_linii.png", caption="Rys. 3. Filtr linii: wybrane linie 6 i 8, pozostałe tramwaje ukryte."),

    PageBreak(),
    Paragraph("3. Zgłoszenie awarii", h2),
    steps([
        "Kliknij czerwony przycisk <b>Zgłoś awarię</b> w sekcji „Awaria”.",
        "Przybliż mapę i <b>kliknij odcinek toru</b>, na którym jest awaria. Odcinek robi się czerwony. Można zaznaczyć kilka odcinków; ponowne kliknięcie odznacza.",
        "Wybierz, czy zablokowane są <b>oba tory</b> (program sam dołoży tor równoległy), czy <b>tylko zaznaczony tor</b>, a drugi jest przejezdny. W drugim przypadku program sprawdzi, czy da się puścić ruch wahadłowy.",
        "Wpisz miejsce (np. „al. Grunwaldzka przy Galerii Bałtyckiej”), wybierz przyczynę i wpisz przewidywany czas.",
        "Kliknij <b>Analizuj</b>. Wynik pojawia się bez zapisu, można poprawić zaznaczenie i analizować ponownie.",
    ]),
    img("04_zglaszanie.png", caption="Rys. 4. Zaznaczony odcinek (czerwony) i wypełniony formularz awarii."),

    Paragraph("4. Co pokazuje analiza", h2),
    Paragraph("Po kliknięciu „Analizuj” mapa i panel pokazują skutki blokady.", base),
    img("05_analiza_mapa.png", caption="Rys. 5. Mapa po analizie: blokada, punkty zawracania, przekreślone przystanki bez obsługi, tramwaje z kolorową obwódką."),
    bullets([
        "<b>Czerwony gruby odcinek</b> to blokada. <b>Zielona przerywana linia</b> to objazd, jeśli istnieje. <b>Niebieska przerywana</b> to trasa wahadła.",
        "<b>Etykiety ze strzałką ↩</b> to proponowane miejsca zawracania: zielona ramka dla wszystkich składów (pętla), niebieska tylko dla składów dwukierunkowych (końcówka bez pętli, przejazd międzytorowy).",
        "<b>Przekreślone przystanki</b> nie będą obsługiwane przy skróceniu tras.",
        "<b>Obwódka wokół tramwaju</b>: pomarańczowa – jedzie w stronę blokady, fioletowa – stoi na blokadzie, czerwona pulsująca – nie ma gdzie zawrócić.",
    ]),
    Paragraph("Na początku panelu jest żółte podsumowanie, a pod nim karta dla każdej linii i kierunku:", base),
    img("06_karta_linii.png", width=110 * mm, caption="Rys. 6. Karta linii: wybór strategii, miejsca zawracania osobno dla składów jedno- i dwukierunkowych, przystanki bez obsługi."),
    bullets([
        "<b>Przyciski strategii</b> (objazd, wahadło, skrócenie, zawieszenie). Program zaznacza domyślną, niedostępne są wyszarzone. Twój wybór zmienia komunikaty.",
        "<b>Od [pętla]</b>: najbliższe miejsce zawracania z każdej strony blokady, z odległością. Dopisek „jednokier.” dotyczy składów jednokierunkowych (tylko pętle), „dwukier.” dwukierunkowych (także końcówki i przejazdy).",
        "<b>„Do weryfikacji”</b> oznacza miejsce wykryte automatycznie z mapy, którego program nie jest pewien. Traktuj je jako podpowiedź.",
        "<b>Wahadło</b> pojawia się tylko przy blokadzie jednego toru i tylko tam, gdzie program zna przejazdy międzytorowe przed i za blokadą. Podaje długość odcinka jednotorowego, czas przejazdu i przepustowość.",
    ]),
    img("07_sklady.png", width=110 * mm, caption="Rys. 7. Składy w rejonie blokady, posortowane od najpilniejszych: bez możliwości zawrócenia, jadące na blokadę, za blokadą."),

    PageBreak(),
    Paragraph("5. Zapis awarii i komunikaty", h2),
    steps([
        "Kliknij <b>Zapisz awarię</b>. Awaria trafia do dziennika i staje się aktywna; sytuacja składów odświeża się co 15 sekund.",
        "W czerwonym polu aktywnej awarii kliknij <b>Komunikaty</b>.",
        "Pojawia się pięć tekstów: dla pasażerów po polsku i po angielsku, komunikat służbowy dla motorniczych oraz komunikaty o przywróceniu ruchu po polsku i angielsku.",
        "Przycisk <b>Kopiuj</b> przy każdym tekście kopiuje go do schowka, żeby wkleić na tablice, stronę, do radia.",
        "Teksty można poprawić ręcznie i kliknąć <b>Zapisz teksty</b>. <b>Generuj ponownie</b> tworzy je od nowa z aktualnej analizy i nadpisuje poprawki.",
    ]),
    img("08_aktywna.png", width=110 * mm, caption="Rys. 8. Aktywna awaria: przyciski Komunikaty, Zakończ awarię, Ukryj."),
    img("09_komunikaty.png", width=100 * mm, max_h=200 * mm, caption="Rys. 9. Panel komunikatów z przyciskami Kopiuj."),

    PageBreak(),
    Paragraph("6. Zakończenie awarii i dziennik", h2),
    bullets([
        "<b>Zakończ awarię</b> zamyka wpis i od razu podsuwa komunikat o przywróceniu ruchu do skopiowania.",
        "<b>Dziennik awarii</b> na dole sekcji pokazuje wszystkie awarie. Kliknięcie wpisu otwiera jego analizę i komunikaty.",
        "<b>Eksport CSV</b> zapisuje dziennik do pliku, który otwiera się w Excelu.",
        "<b>Ukryj</b> chowa aktywną awarię z ekranu, ale jej nie kończy. Po odświeżeniu strony wraca.",
    ]),
    img("11_zakonczenie.png", width=100 * mm, max_h=150 * mm, caption="Rys. 10. Po zakończeniu awarii: komunikat o przywróceniu ruchu."),

    Paragraph("7. Dobrze wiedzieć", h2),
    bullets([
        "Program liczy na podstawie mapy OpenStreetMap. Pętle i przejazdy, których nie ma na mapie, nie zostaną zaproponowane. Jeśli wiesz, że czegoś brakuje albo jest źle, daj znać Piotrowi, da się to dopisać ręcznie.",
        "Typ składu (jedno- czy dwukierunkowy) program rozpoznaje po numerze taborowym z tabeli. Jeśli jakiś numer jest przypisany źle, też daj znać.",
        "Pozycje tramwajów pochodzą z publicznego feedu ZTM i mogą mieć kilkanaście sekund opóźnienia.",
        "Nic, co robisz w programie, nie wychodzi na zewnątrz. Komunikaty trafiają tylko do schowka, dalej wysyłasz je sam, swoimi kanałami.",
    ]),
]

doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=16 * mm, bottomMargin=16 * mm,
                        title="Dyspozytor tramwajowy Gdańsk – instrukcja obsługi", author="Piotr Szatkowski")


def footer(canvas, doc_):
    canvas.saveState()
    canvas.setFont("Arial", 8.5)
    canvas.setFillColor(colors.HexColor("#777"))
    canvas.drawString(MARGIN, 9 * mm, "Dyspozytor tramwajowy Gdańsk – instrukcja obsługi")
    canvas.drawRightString(W - MARGIN, 9 * mm, f"strona {doc_.page}")
    canvas.restoreState()


doc.build(story, onFirstPage=footer, onLaterPages=footer)
print("zapisano", OUT, OUT.stat().st_size // 1024, "KB")
