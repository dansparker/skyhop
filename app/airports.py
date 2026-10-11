"""Airfields available on Skyhop (ICAO, name, city, country, lat, lon)."""

AIRPORTS = [
    # Österreich
    ("LOWW", "Flughafen Wien-Schwechat", "Wien", "AT", 48.1103, 16.5697),
    ("LOAV", "Flugplatz Vöslau", "Bad Vöslau", "AT", 47.9650, 16.2600),
    ("LOAN", "Flugplatz Wiener Neustadt Ost", "Wiener Neustadt", "AT", 47.8433, 16.2600),
    ("LOAG", "Flugplatz Krems-Langenlois", "Krems", "AT", 48.4464, 15.6342),
    ("LOAU", "Flugplatz Stockerau", "Stockerau", "AT", 48.4100, 16.1917),
    ("LOWG", "Flughafen Graz", "Graz", "AT", 46.9911, 15.4396),
    ("LOGK", "Flugplatz Kapfenberg", "Kapfenberg", "AT", 47.4583, 15.3303),
    ("LOWL", "Flughafen Linz", "Linz", "AT", 48.2332, 14.1875),
    ("LOLW", "Flugplatz Wels", "Wels", "AT", 48.1833, 14.0408),
    ("LOWS", "Salzburg Airport", "Salzburg", "AT", 47.7933, 13.0043),
    ("LOGO", "Flugplatz Niederöblarn", "Niederöblarn", "AT", 47.4783, 14.0083),
    ("LOWZ", "Flugplatz Zell am See", "Zell am See", "AT", 47.2925, 12.7875),
    ("LOIJ", "Flugplatz St. Johann in Tirol", "St. Johann in Tirol", "AT", 47.5200, 12.4497),
    ("LOWI", "Flughafen Innsbruck", "Innsbruck", "AT", 47.2602, 11.3440),
    ("LOIH", "Flugplatz Hohenems-Dornbirn", "Hohenems", "AT", 47.3850, 9.7000),
    ("LOWK", "Flughafen Klagenfurt", "Klagenfurt", "AT", 46.6425, 14.3377),
    # Deutschland
    ("EDDM", "Flughafen München", "München", "DE", 48.3538, 11.7861),
    ("EDMO", "Sonderflughafen Oberpfaffenhofen", "Oberpfaffenhofen", "DE", 48.0814, 11.2831),
    ("EDMA", "Augsburg Airport", "Augsburg", "DE", 48.4253, 10.9317),
    ("EDMS", "Flugplatz Straubing-Wallmühle", "Straubing", "DE", 48.9008, 12.5181),
    ("EDJA", "Allgäu Airport Memmingen", "Memmingen", "DE", 47.9888, 10.2395),
    ("EDNY", "Bodensee-Airport Friedrichshafen", "Friedrichshafen", "DE", 47.6713, 9.5115),
    ("EDDN", "Albrecht Dürer Airport Nürnberg", "Nürnberg", "DE", 49.4987, 11.0669),
    ("EDDS", "Flughafen Stuttgart", "Stuttgart", "DE", 48.6899, 9.2220),
    ("EDTF", "Flugplatz Freiburg", "Freiburg", "DE", 48.0222, 7.8325),
    ("EDDF", "Flughafen Frankfurt", "Frankfurt", "DE", 50.0333, 8.5706),
    ("EDFE", "Flugplatz Frankfurt-Egelsbach", "Egelsbach", "DE", 49.9608, 8.6436),
    ("EDDK", "Flughafen Köln/Bonn", "Köln", "DE", 50.8659, 7.1427),
    ("EDDP", "Flughafen Leipzig/Halle", "Leipzig", "DE", 51.4324, 12.2416),
    ("EDDC", "Flughafen Dresden", "Dresden", "DE", 51.1328, 13.7672),
    ("EDDB", "Flughafen Berlin Brandenburg", "Berlin", "DE", 52.3667, 13.5033),
    ("EDAZ", "Flugplatz Schönhagen", "Trebbin", "DE", 52.2036, 13.1586),
    ("EDDH", "Flughafen Hamburg", "Hamburg", "DE", 53.6304, 9.9882),
    ("EDXW", "Flughafen Sylt", "Westerland (Sylt)", "DE", 54.9132, 8.3405),
    ("EDXH", "Flugplatz Helgoland-Düne", "Helgoland", "DE", 54.1853, 7.9158),
    ("EDWY", "Flugplatz Norderney", "Norderney", "DE", 53.7069, 7.2300),
    ("EDWJ", "Flugplatz Juist", "Juist", "DE", 53.6811, 7.0558),
    ("EDBH", "Ostseeflughafen Stralsund-Barth", "Barth", "DE", 54.3383, 12.7103),
    # Schweiz
    ("LSZH", "Flughafen Zürich", "Zürich", "CH", 47.4647, 8.5492),
    ("LSZB", "Flughafen Bern-Belp", "Bern", "CH", 46.9141, 7.4971),
    ("LSGG", "Flughafen Genf", "Genf", "CH", 46.2381, 6.1090),
    ("LSZA", "Flughafen Lugano", "Lugano", "CH", 46.0040, 8.9106),
    ("LSZS", "Engadin Airport Samedan", "Samedan (St. Moritz)", "CH", 46.5341, 9.8841),
    ("LSGS", "Flughafen Sion", "Sion", "CH", 46.2196, 7.3268),
    ("LSZR", "Flughafen St. Gallen-Altenrhein", "Altenrhein", "CH", 47.4850, 9.5608),
    # Italien
    ("LIPB", "Flughafen Bozen", "Bozen", "IT", 46.4603, 11.3264),
    ("LIPZ", "Flughafen Venedig Marco Polo", "Venedig", "IT", 45.5053, 12.3519),
    ("LIPH", "Flughafen Treviso", "Treviso", "IT", 45.6484, 12.1944),
    ("LIPQ", "Flughafen Triest", "Triest", "IT", 45.8275, 13.4722),
    ("LIML", "Flughafen Mailand-Linate", "Mailand", "IT", 45.4451, 9.2767),
    # Slowenien
    ("LJLJ", "Flughafen Ljubljana", "Ljubljana", "SI", 46.2237, 14.4576),
    ("LJBL", "Flugplatz Lesce-Bled", "Bled", "SI", 46.3572, 14.1739),
    ("LJPZ", "Flughafen Portorož", "Portorož", "SI", 45.4734, 13.6150),
    # Kroatien
    ("LDZA", "Flughafen Zagreb", "Zagreb", "HR", 45.7429, 16.0688),
    ("LDPL", "Flughafen Pula", "Pula", "HR", 44.8935, 13.9222),
    ("LDRI", "Flughafen Rijeka (Krk)", "Krk", "HR", 45.2169, 14.5703),
    ("LDLO", "Flughafen Lošinj", "Mali Lošinj", "HR", 44.5658, 14.3931),
    ("LDZD", "Flughafen Zadar", "Zadar", "HR", 44.1083, 15.3467),
    ("LDSP", "Flughafen Split", "Split", "HR", 43.5389, 16.2980),
    # Tschechien / Slowakei / Ungarn
    ("LKPR", "Flughafen Prag", "Prag", "CZ", 50.1008, 14.2600),
    ("LKTB", "Flughafen Brünn", "Brünn", "CZ", 49.1513, 16.6944),
    ("LKCS", "Flughafen České Budějovice", "Budweis", "CZ", 48.9464, 14.4275),
    ("LZIB", "Flughafen Bratislava", "Bratislava", "SK", 48.1702, 17.2127),
    ("LHBP", "Flughafen Budapest", "Budapest", "HU", 47.4369, 19.2556),
    ("LHSM", "Hévíz-Balaton Airport", "Sármellék (Balaton)", "HU", 46.6864, 17.1591),
    # Frankreich
    ("LFSB", "EuroAirport Basel-Mulhouse", "Basel", "FR", 47.5896, 7.5299),
    ("LFST", "Flughafen Straßburg", "Straßburg", "FR", 48.5383, 7.6282),
    ("LFPN", "Flugplatz Toussus-le-Noble", "Paris", "FR", 48.7519, 2.1061),
    ("LFMN", "Flughafen Nizza", "Nizza", "FR", 43.6584, 7.2159),
]


def seed_airports(db):
    from .models import Airport

    existing = {a.icao for a in Airport.query.all()}
    for icao, name, city, country, lat, lon in AIRPORTS:
        if icao not in existing:
            db.session.add(Airport(icao=icao, name=name, city=city, country=country, lat=lat, lon=lon))
    db.session.commit()
