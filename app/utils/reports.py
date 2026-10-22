"""Excel (openpyxl) ve PDF (ReportLab) rapor üreticileri.

PDF'lerde Türkçe karakterlerin doğru görünmesi için proje ile birlikte gelen
DejaVuSans yazı tipi kullanılır (app/static/fonts).
"""
from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..models import (
    PRESENT_LIKE,
    STATUS_ABSENT,
    STATUS_EXCUSED,
    STATUS_LABELS,
    STATUS_LATE,
    STATUS_PRESENT,
    STATUS_REPORTED,
)

FONT_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts"
BASE_FONT = "Helvetica"
BOLD_FONT = "Helvetica-Bold"

# Kısa durum kodları (dönem matrisi için)
SHORT_CODES = {
    STATUS_PRESENT: "M",
    STATUS_LATE: "G",
    STATUS_EXCUSED: "İ",
    STATUS_REPORTED: "R",
    STATUS_ABSENT: "Y",
}

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
SUBHEADER_FILL = PatternFill("solid", fgColor="D9E2F3")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _register_fonts() -> None:
    """DejaVu yazı tiplerini (varsa) kaydeder."""
    global BASE_FONT, BOLD_FONT
    regular = FONT_DIR / "DejaVuSans.ttf"
    bold = FONT_DIR / "DejaVuSans-Bold.ttf"
    try:
        if regular.exists() and "DejaVuSans" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("DejaVuSans", str(regular)))
        if bold.exists() and "DejaVuSans-Bold" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", str(bold)))
        if "DejaVuSans" in pdfmetrics.getRegisteredFontNames():
            BASE_FONT = "DejaVuSans"
            BOLD_FONT = (
                "DejaVuSans-Bold"
                if "DejaVuSans-Bold" in pdfmetrics.getRegisteredFontNames()
                else "DejaVuSans"
            )
    except Exception:  # yazı tipi yüklenemezse varsayılanla devam
        BASE_FONT, BOLD_FONT = "Helvetica", "Helvetica-Bold"


_register_fonts()


def _pdf_styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="TRTitle",
            fontName=BOLD_FONT,
            fontSize=15,
            leading=19,
            alignment=TA_CENTER,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TRSub",
            fontName=BASE_FONT,
            fontSize=9.5,
            leading=13,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#555555"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="TRBody", fontName=BASE_FONT, fontSize=9, leading=12
        )
    )
    styles.add(
        ParagraphStyle(
            name="TRSmall",
            fontName=BASE_FONT,
            fontSize=7.5,
            leading=10,
            textColor=colors.HexColor("#666666"),
        )
    )
    return styles


def _table_style(header_rows: int = 1) -> TableStyle:
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, header_rows - 1), colors.HexColor("#1F3864")),
            ("TEXTCOLOR", (0, 0), (-1, header_rows - 1), colors.white),
            ("FONTNAME", (0, 0), (-1, header_rows - 1), BOLD_FONT),
            ("FONTNAME", (0, header_rows), (-1, -1), BASE_FONT),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#9DB2D6")),
            ("ROWBACKGROUNDS", (0, header_rows), (-1, -1),
             [colors.white, colors.HexColor("#F2F5FB")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ]
    )


# --------------------------------------------------------------------------- #
# Excel: tek oturum
# --------------------------------------------------------------------------- #
def session_excel(session_obj, dorm_name: str = "") -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "Yoklama"

    headers = [
        "#", "Ad Soyad", "Öğrenci No", "Oda", "Durum", "Yöntem",
        "Kayıt Saati", "Açıklama", "Düzenleyen",
    ]
    ws.append([dorm_name or "Yurt Yoklama Raporu"])
    ws.append(
        [
            f"{session_obj.title} | {session_obj.session_date:%d.%m.%Y} "
            f"{session_obj.start_time:%H:%M}-{session_obj.end_time:%H:%M} "
            f"| Durum: {session_obj.status_label}"
        ]
    )
    ws.append([])
    ws.append(headers)

    title_cell = ws.cell(row=1, column=1)
    title_cell.font = Font(bold=True, size=14, color="1F3864")
    ws.cell(row=2, column=1).font = Font(size=10, color="404040")

    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=4, column=col)
        cell.fill = HEADER_FILL
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = BORDER

    records = sorted(session_obj.records, key=lambda r: r.student.full_name)
    for index, record in enumerate(records, start=1):
        ws.append(
            [
                index,
                record.student.full_name,
                record.student.student_no or "-",
                record.student.room_no or "-",
                record.status_label,
                record.method_label,
                record.marked_at.strftime("%d.%m.%Y %H:%M:%S")
                if record.marked_at
                else "-",
                record.note or "",
                record.updated_by.full_name if record.updated_by else "",
            ]
        )
        row = ws.max_row
        for col in range(1, len(headers) + 1):
            ws.cell(row=row, column=col).border = BORDER
            ws.cell(row=row, column=col).alignment = Alignment(
                horizontal="left" if col in (2, 8, 9) else "center",
                vertical="center",
                wrap_text=col == 8,
            )

    summary = session_obj.summary()
    ws.append([])
    ws.append(["ÖZET"])
    ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
    for key in (STATUS_PRESENT, STATUS_LATE, STATUS_EXCUSED, STATUS_REPORTED,
                STATUS_ABSENT):
        ws.append([STATUS_LABELS[key], summary.get(key, 0)])
    ws.append(["Toplam Öğrenci", summary["total"]])
    ws.append(["Katılım Oranı (%)", summary["rate"]])

    widths = [5, 28, 14, 8, 12, 12, 20, 36, 20]
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    ws.freeze_panes = "A5"

    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)
    return stream


# --------------------------------------------------------------------------- #
# Excel: dönem raporu (öğrenci x tarih matrisi + özet sayfası)
# --------------------------------------------------------------------------- #
def period_excel(
    *, sessions, students_stats, matrix, start: date, end: date, dorm_name: str = ""
) -> BytesIO:
    wb = Workbook()

    # 1) Özet
    ws = wb.active
    ws.title = "Özet"
    ws.append([dorm_name or "Dönemlik Yoklama Raporu"])
    ws.cell(row=1, column=1).font = Font(bold=True, size=14, color="1F3864")
    ws.append([f"Dönem: {start:%d.%m.%Y} - {end:%d.%m.%Y} | Oturum sayısı: {len(sessions)}"])
    ws.cell(row=2, column=1).font = Font(size=10, color="404040")
    ws.append([])

    headers = [
        "#", "Ad Soyad", "Öğrenci No", "Oda", "Mevcut", "Geç Geldi",
        "İzinli", "Raporlu", "Yok", "Toplam", "Katılım %", "Devamsızlık %",
    ]
    ws.append(headers)
    header_row = ws.max_row
    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=header_row, column=col)
        cell.fill = HEADER_FILL
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = BORDER

    for index, stat in enumerate(students_stats, start=1):
        ws.append(
            [
                index,
                stat["full_name"],
                stat["student_no"],
                stat["room_no"],
                stat.get(STATUS_PRESENT, 0),
                stat.get(STATUS_LATE, 0),
                stat.get(STATUS_EXCUSED, 0),
                stat.get(STATUS_REPORTED, 0),
                stat.get(STATUS_ABSENT, 0),
                stat["total"],
                stat["attendance_rate"],
                stat["absence_rate"],
            ]
        )
        row = ws.max_row
        for col in range(1, len(headers) + 1):
            ws.cell(row=row, column=col).border = BORDER
        if stat["absence_rate"] >= 20:
            for col in range(1, len(headers) + 1):
                ws.cell(row=row, column=col).fill = PatternFill(
                    "solid", fgColor="FCE4E4"
                )

    for idx, width in enumerate([5, 28, 14, 8, 10, 11, 9, 10, 8, 9, 11, 14], start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    ws.freeze_panes = f"A{header_row + 1}"

    # 2) Günlük matris
    ws2 = wb.create_sheet("Gün Bazlı")
    head = ["Ad Soyad", "Öğrenci No", "Oda"] + [
        s.session_date.strftime("%d.%m") for s in sessions
    ]
    ws2.append(head)
    for col in range(1, len(head) + 1):
        cell = ws2.cell(row=1, column=col)
        cell.fill = HEADER_FILL
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row_data in matrix:
        ws2.append(
            [row_data["full_name"], row_data["student_no"], row_data["room_no"]]
            + [SHORT_CODES.get(code, "-") for code in row_data["codes"]]
        )
    ws2.column_dimensions["A"].width = 28
    ws2.column_dimensions["B"].width = 14
    ws2.column_dimensions["C"].width = 8
    for idx in range(4, len(head) + 1):
        ws2.column_dimensions[get_column_letter(idx)].width = 7
    ws2.freeze_panes = "D2"
    ws2.append([])
    ws2.append(["Kısaltmalar: M=Mevcut, G=Geç Geldi, İ=İzinli, R=Raporlu, Y=Yok"])

    # 3) Oturumlar
    ws3 = wb.create_sheet("Oturumlar")
    ws3.append(
        ["Tarih", "Başlık", "Saat", "Durum", "Mevcut", "Geç", "İzinli", "Raporlu",
         "Yok", "Katılım %", "Açan Görevli"]
    )
    for col in range(1, 12):
        cell = ws3.cell(row=1, column=col)
        cell.fill = HEADER_FILL
        cell.font = Font(bold=True, color="FFFFFF")
    for session_obj in sessions:
        summary = session_obj.summary()
        ws3.append(
            [
                session_obj.session_date.strftime("%d.%m.%Y"),
                session_obj.title,
                f"{session_obj.start_time:%H:%M}-{session_obj.end_time:%H:%M}",
                session_obj.status_label,
                summary.get(STATUS_PRESENT, 0),
                summary.get(STATUS_LATE, 0),
                summary.get(STATUS_EXCUSED, 0),
                summary.get(STATUS_REPORTED, 0),
                summary.get(STATUS_ABSENT, 0),
                summary["rate"],
                session_obj.created_by.full_name if session_obj.created_by else "-",
            ]
        )
    for idx, width in enumerate([12, 24, 14, 10, 9, 7, 9, 10, 7, 11, 22], start=1):
        ws3.column_dimensions[get_column_letter(idx)].width = width

    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)
    return stream


# --------------------------------------------------------------------------- #
# PDF: tek oturum
# --------------------------------------------------------------------------- #
def session_pdf(session_obj, dorm_name: str = "") -> BytesIO:
    styles = _pdf_styles()
    stream = BytesIO()
    doc = SimpleDocTemplate(
        stream,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"Yoklama {session_obj.session_date:%d.%m.%Y}",
        author="Sanal Yoklama Sistemi",
    )

    story = [
        Paragraph(dorm_name or "Yurt Yoklama Tutanağı", styles["TRTitle"]),
        Paragraph(
            f"{session_obj.title} &nbsp;|&nbsp; {session_obj.session_date:%d.%m.%Y} "
            f"&nbsp;|&nbsp; {session_obj.start_time:%H:%M}-{session_obj.end_time:%H:%M} "
            f"&nbsp;|&nbsp; Oturum No: {session_obj.id}",
            styles["TRSub"],
        ),
        Spacer(1, 8),
    ]

    data = [["#", "Ad Soyad", "Öğrenci No", "Oda", "Durum", "Yöntem", "Saat",
             "Açıklama"]]
    records = sorted(session_obj.records, key=lambda r: r.student.full_name)
    for index, record in enumerate(records, start=1):
        data.append(
            [
                str(index),
                Paragraph(record.student.full_name, styles["TRBody"]),
                record.student.student_no or "-",
                record.student.room_no or "-",
                record.status_label,
                record.method_label,
                record.marked_at.strftime("%H:%M") if record.marked_at else "-",
                Paragraph(record.note or "", styles["TRSmall"]),
            ]
        )

    table = Table(
        data,
        colWidths=[10 * mm, 42 * mm, 22 * mm, 12 * mm, 20 * mm, 18 * mm, 14 * mm,
                   44 * mm],
        repeatRows=1,
    )
    table.setStyle(_table_style())
    story.append(table)

    summary = session_obj.summary()
    story.append(Spacer(1, 10))
    summary_table = Table(
        [
            ["Mevcut", "Geç Geldi", "İzinli", "Raporlu", "Yok", "Toplam",
             "Katılım %"],
            [
                summary.get(STATUS_PRESENT, 0),
                summary.get(STATUS_LATE, 0),
                summary.get(STATUS_EXCUSED, 0),
                summary.get(STATUS_REPORTED, 0),
                summary.get(STATUS_ABSENT, 0),
                summary["total"],
                summary["rate"],
            ],
        ],
        colWidths=[25 * mm] * 7,
    )
    summary_table.setStyle(_table_style())
    story.append(summary_table)

    story.append(Spacer(1, 14))
    story.append(
        Paragraph(
            "Bu belge Sanal Yoklama Sistemi tarafından otomatik üretilmiştir. "
            f"Oturumu açan görevli: "
            f"{session_obj.created_by.full_name if session_obj.created_by else '-'}.",
            styles["TRSmall"],
        )
    )
    story.append(Spacer(1, 18))
    sign_table = Table(
        [["Yurt Görevlisi", "Yurt Yönetimi"], ["", ""]],
        colWidths=[80 * mm, 80 * mm],
        rowHeights=[8 * mm, 18 * mm],
    )
    sign_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), BASE_FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("LINEBELOW", (0, 1), (-1, 1), 0.5, colors.HexColor("#999999")),
            ]
        )
    )
    story.append(sign_table)

    doc.build(story)
    stream.seek(0)
    return stream


# --------------------------------------------------------------------------- #
# PDF: dönem raporu
# --------------------------------------------------------------------------- #
def period_pdf(
    *, sessions, students_stats, matrix, start: date, end: date, dorm_name: str = ""
) -> BytesIO:
    styles = _pdf_styles()
    stream = BytesIO()
    doc = SimpleDocTemplate(
        stream,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=f"Donem Raporu {start}-{end}",
        author="Sanal Yoklama Sistemi",
    )

    story = [
        Paragraph(dorm_name or "Dönemlik Yoklama Raporu", styles["TRTitle"]),
        Paragraph(
            f"Dönem: {start:%d.%m.%Y} - {end:%d.%m.%Y} &nbsp;|&nbsp; "
            f"Oturum sayısı: {len(sessions)} &nbsp;|&nbsp; "
            f"Öğrenci sayısı: {len(students_stats)}",
            styles["TRSub"],
        ),
        Spacer(1, 8),
    ]

    data = [["#", "Ad Soyad", "Öğrenci No", "Oda", "Mevcut", "Geç", "İzinli",
             "Raporlu", "Yok", "Toplam", "Katılım %", "Devamsızlık %"]]
    for index, stat in enumerate(students_stats, start=1):
        data.append(
            [
                str(index),
                Paragraph(stat["full_name"], styles["TRBody"]),
                stat["student_no"],
                stat["room_no"],
                stat.get(STATUS_PRESENT, 0),
                stat.get(STATUS_LATE, 0),
                stat.get(STATUS_EXCUSED, 0),
                stat.get(STATUS_REPORTED, 0),
                stat.get(STATUS_ABSENT, 0),
                stat["total"],
                stat["attendance_rate"],
                stat["absence_rate"],
            ]
        )
    table = Table(
        data,
        colWidths=[10 * mm, 50 * mm, 24 * mm, 14 * mm, 18 * mm, 14 * mm, 16 * mm,
                   18 * mm, 14 * mm, 16 * mm, 22 * mm, 26 * mm],
        repeatRows=1,
    )
    table.setStyle(_table_style())
    story.append(table)

    if matrix and sessions:
        story.append(PageBreak())
        story.append(Paragraph("Gün Bazlı Yoklama Çizelgesi", styles["TRTitle"]))
        story.append(
            Paragraph(
                "M=Mevcut, G=Geç Geldi, İ=İzinli, R=Raporlu, Y=Yok",
                styles["TRSub"],
            )
        )
        story.append(Spacer(1, 6))

        # Sayfaya sığması için tarihleri 18'lik gruplara böl
        chunk = 18
        for offset in range(0, len(sessions), chunk):
            part = sessions[offset : offset + chunk]
            head = ["Ad Soyad"] + [s.session_date.strftime("%d.%m") for s in part]
            rows = [head]
            for row_data in matrix:
                codes = row_data["codes"][offset : offset + chunk]
                rows.append(
                    [Paragraph(row_data["full_name"], styles["TRSmall"])]
                    + [SHORT_CODES.get(code, "-") for code in codes]
                )
            widths = [52 * mm] + [
                min(12 * mm, (220 * mm) / max(len(part), 1)) for _ in part
            ]
            matrix_table = Table(rows, colWidths=widths, repeatRows=1)
            matrix_table.setStyle(_table_style())
            story.append(matrix_table)
            story.append(Spacer(1, 10))

    doc.build(story)
    stream.seek(0)
    return stream


# --------------------------------------------------------------------------- #
# Matris yardımcısı
# --------------------------------------------------------------------------- #
def build_matrix(sessions, records_by_student) -> list[dict]:
    """Öğrenci x oturum matrisini (durum kodları) hazırlar."""
    matrix = []
    for student, record_map in records_by_student:
        codes = [
            record_map.get(session_obj.id, "") for session_obj in sessions
        ]
        matrix.append(
            {
                "full_name": student.full_name,
                "student_no": student.student_no or "-",
                "room_no": student.room_no or "-",
                "codes": codes,
                "present_count": sum(1 for c in codes if c in PRESENT_LIKE),
            }
        )
    matrix.sort(key=lambda row: row["full_name"])
    return matrix
