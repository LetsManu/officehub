"""Ready-made workbooks for "New → Spreadsheet": a budget, a to-do list and a weekly plan, in the person's language.

Written here as plain SpreadsheetML (the .xlsx format, ECMA-376) with our own text: no template files, no extra
library. Formulas are stored without results; GridCraft and other programs calculate them when they open the file.
"""

import io
import zipfile
from datetime import datetime, timezone
from xml.sax.saxutils import escape

KINDS = ("budget", "todo", "week")

# Cell styles (index into cellXfs below)
PLAIN, HEADER, MONEY, MONEY_BOLD, BOLD, DATE, TIME = range(7)

_TEXT = {
    "de": {
        "budget": ("Budget", ["Posten", "Geplant", "Tatsächlich", "Differenz"],
                   ["Personal", "Miete", "Material", "Marketing", "Reisen", "Sonstiges"], "Summe"),
        "todo": ("Aufgaben", ["Aufgabe", "Zuständig", "Fällig am", "Erledigt", "Notiz"], [], ""),
        "week": ("Wochenplan", ["Zeit", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"], [], ""),
    },
    "en": {
        "budget": ("Budget", ["Item", "Planned", "Actual", "Difference"],
                   ["Staff", "Rent", "Materials", "Marketing", "Travel", "Other"], "Total"),
        "todo": ("Tasks", ["Task", "Owner", "Due", "Done", "Note"], [], ""),
        "week": ("Week", ["Time", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"], [], ""),
    },
}


def _col(i: int) -> str:
    return "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[i]


def _cell(ref: str, value, style: int = PLAIN) -> str:
    s = f' s="{style}"' if style else ""
    if value is None or value == "":
        return f'<c r="{ref}"{s}/>' if style else ""
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"{s}><v>{value}</v></c>'
    if isinstance(value, str) and value.startswith("="):
        return f'<c r="{ref}"{s}><f>{escape(value[1:])}</f></c>'
    return f'<c r="{ref}"{s} t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'


def _rows(kind: str, lang: str) -> tuple[str, list[list[tuple]], list[float]]:
    """(sheet name, rows of (value, style), column widths in characters)."""
    name, head, items, total = _TEXT.get(lang, _TEXT["en"])[kind]
    rows: list[list[tuple]] = [[(h, HEADER) for h in head]]
    if kind == "budget":
        for n, item in enumerate(items, start=2):
            rows.append([(item, PLAIN), ("", MONEY), ("", MONEY), (f"=C{n}-B{n}", MONEY)])
        last = len(items) + 1
        rows.append([(total, BOLD)] + [(f"=SUM({c}2:{c}{last})", MONEY_BOLD) for c in "BCD"])
        return name, rows, [24, 14, 14, 14]
    if kind == "todo":
        rows += [[("", PLAIN), ("", PLAIN), ("", DATE), ("", PLAIN), ("", PLAIN)] for _ in range(20)]
        return name, rows, [36, 18, 12, 10, 30]
    # A week from 08:00 to 17:00 in half hours (times are fractions of a day)
    for half in range(18):
        rows.append([((8 + half / 2) / 24, TIME)] + [("", PLAIN)] * 5)
    return name, rows, [8, 20, 20, 20, 20, 20]


_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="2"><numFmt numFmtId="164" formatCode="#,##0.00"/><numFmt numFmtId="165" formatCode="hh:mm"/></numFmts>
<fonts count="2"><font><sz val="11"/><name val="Calibri"/><family val="2"/></font><font><b/><sz val="11"/><name val="Calibri"/><family val="2"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFDCEBDD"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border><border><left/><right/><top/><bottom style="thin"><color rgb="FF8AAE8C"/></bottom><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="7">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/>
<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="164" fontId="1" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>
<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def workbook(kind: str, lang: str = "de") -> bytes:
    """The .xlsx file of one template."""
    name, rows, widths = _rows(kind, lang)
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths))
    data = "".join(
        f'<row r="{r}">' + "".join(_cell(f"{_col(c)}{r}", v, s) for c, (v, s) in enumerate(row)) + "</row>"
        for r, row in enumerate(rows, start=1)
    )
    last = f"{_col(len(widths) - 1)}{len(rows)}"
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="A1:{last}"/>'
        '<sheetViews><sheetView workbookViewId="0" tabSelected="1">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/></sheetView></sheetViews>'
        f'<sheetFormatPr defaultRowHeight="15"/><cols>{cols}</cols><sheetData>{data}</sheetData>'
        '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/></worksheet>'
    )
    book = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{escape(name)}" sheetId="1" r:id="rId1"/></sheets><calcPr fullCalcOnLoad="1"/></workbook>'
    )
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            "</Relationships>"
        ),
        "docProps/core.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{escape(name)}</dc:title><dc:creator>OfficeHub</dc:creator>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created></cp:coreProperties>'
        ),
        "xl/workbook.xml": book,
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>"
        ),
        "xl/styles.xml": _STYLES,
        "xl/worksheets/sheet1.xml": sheet,
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for path, text in files.items():
            z.writestr(path, text)
    return out.getvalue()
