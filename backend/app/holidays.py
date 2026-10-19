"""Built-in public holidays for Austria, Germany (with states) and Switzerland. No internet needed.

Each holiday is (date, German name, English name). Half days and local holidays of single towns are
not included; HR can add company-specific days (e.g. 24 December) in the portal settings.
"""

from datetime import date, timedelta

Holiday = tuple[date, str, str]

COUNTRIES = ("AT", "DE", "CH")
DE_STATES = ("BW", "BY", "BE", "BB", "HB", "HH", "HE", "MV", "NI", "NW", "RP", "SL", "SN", "ST", "SH", "TH")


def easter_sunday(year: int) -> date:
    """Gregorian Easter Sunday (Meeus/Jones/Butcher algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741 - name from the published algorithm
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _repentance_day(year: int) -> date:
    """Buß- und Bettag: the Wednesday before 23 November."""
    day = date(year, 11, 22)
    while day.weekday() != 2:
        day -= timedelta(days=1)
    return day


def public_holidays(year: int, country: str, region: str = "") -> list[Holiday]:
    e = easter_sunday(year)
    out: list[Holiday] = []

    def add(day: date, de: str, en: str) -> None:
        out.append((day, de, en))

    if country == "AT":
        add(date(year, 1, 1), "Neujahr", "New Year's Day")
        add(date(year, 1, 6), "Heilige Drei Könige", "Epiphany")
        add(e + timedelta(days=1), "Ostermontag", "Easter Monday")
        add(date(year, 5, 1), "Staatsfeiertag", "Labour Day")
        add(e + timedelta(days=39), "Christi Himmelfahrt", "Ascension Day")
        add(e + timedelta(days=50), "Pfingstmontag", "Whit Monday")
        add(e + timedelta(days=60), "Fronleichnam", "Corpus Christi")
        add(date(year, 8, 15), "Mariä Himmelfahrt", "Assumption Day")
        add(date(year, 10, 26), "Nationalfeiertag", "National Day")
        add(date(year, 11, 1), "Allerheiligen", "All Saints' Day")
        add(date(year, 12, 8), "Mariä Empfängnis", "Immaculate Conception")
        add(date(year, 12, 25), "Christtag", "Christmas Day")
        add(date(year, 12, 26), "Stefanitag", "St. Stephen's Day")
    elif country == "DE":
        add(date(year, 1, 1), "Neujahr", "New Year's Day")
        if region in ("BW", "BY", "ST"):
            add(date(year, 1, 6), "Heilige Drei Könige", "Epiphany")
        if region == "BE" or (region == "MV" and year >= 2023):
            add(date(year, 3, 8), "Internationaler Frauentag", "International Women's Day")
        add(e - timedelta(days=2), "Karfreitag", "Good Friday")
        add(e + timedelta(days=1), "Ostermontag", "Easter Monday")
        add(date(year, 5, 1), "Tag der Arbeit", "Labour Day")
        add(e + timedelta(days=39), "Christi Himmelfahrt", "Ascension Day")
        add(e + timedelta(days=50), "Pfingstmontag", "Whit Monday")
        if region in ("BW", "BY", "HE", "NW", "RP", "SL"):
            add(e + timedelta(days=60), "Fronleichnam", "Corpus Christi")
        if region in ("BY", "SL"):
            add(date(year, 8, 15), "Mariä Himmelfahrt", "Assumption Day")
        if region == "TH" and year >= 2019:
            add(date(year, 9, 20), "Weltkindertag", "World Children's Day")
        add(date(year, 10, 3), "Tag der Deutschen Einheit", "German Unity Day")
        if region in ("BB", "HB", "HH", "MV", "NI", "SN", "ST", "SH", "TH"):
            add(date(year, 10, 31), "Reformationstag", "Reformation Day")
        if region in ("BW", "BY", "NW", "RP", "SL"):
            add(date(year, 11, 1), "Allerheiligen", "All Saints' Day")
        if region == "SN":
            add(_repentance_day(year), "Buß- und Bettag", "Day of Repentance and Prayer")
        add(date(year, 12, 25), "1. Weihnachtstag", "Christmas Day")
        add(date(year, 12, 26), "2. Weihnachtstag", "Boxing Day")
    elif country == "CH":
        add(date(year, 1, 1), "Neujahr", "New Year's Day")
        add(date(year, 1, 2), "Berchtoldstag", "St. Berchtold's Day")
        add(e - timedelta(days=2), "Karfreitag", "Good Friday")
        add(e + timedelta(days=1), "Ostermontag", "Easter Monday")
        add(e + timedelta(days=39), "Auffahrt", "Ascension Day")
        add(e + timedelta(days=50), "Pfingstmontag", "Whit Monday")
        add(date(year, 8, 1), "Bundesfeier", "Swiss National Day")
        add(date(year, 12, 25), "Weihnachten", "Christmas Day")
        add(date(year, 12, 26), "Stephanstag", "St. Stephen's Day")
    return sorted(out)
