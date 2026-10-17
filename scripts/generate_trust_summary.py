"""Create the LAB's one-page Traditional Chinese trustworthiness PDF.

Requires reportlab and pypdf. Uses an embedded TrueType CJK font; on other
machines supply --font and --bold-font. Final deployment/API outcomes are
required arguments so an unfinished run cannot silently become a passing result.
Example (replace result arguments with the completed, evidenced outcomes):
  python scripts/generate_trust_summary.py --offline-result "..." --local-result "..." --api-result "..."
"""

import argparse
from pathlib import Path
from xml.sax.saxutils import escape

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
INK = colors.HexColor("#183044")
MUTED = colors.HexColor("#50616C")
ACCENT = colors.HexColor("#087F8C")
PALE = colors.HexColor("#EEF6F7")
LINE = colors.HexColor("#D3DEE3")


def register_fonts(regular, bold):
    for name, path in (("CJK", regular), ("CJK-Bold", bold)):
        if not path.is_file():
            raise SystemExit(f"CJK font missing: {path}; supply --font and --bold-font")
        pdfmetrics.registerFont(TTFont(name, str(path), subfontIndex=0))
    pdfmetrics.registerFontFamily("CJK", normal="CJK", bold="CJK-Bold", italic="CJK", boldItalic="CJK-Bold")


def generate(output, offline_result, local_result, api_result, date):
    page_w, page_h = A4
    margin = 35
    width = page_w - margin * 2
    body = ParagraphStyle("body", fontName="CJK", fontSize=9.2, leading=14,
                          textColor=INK, wordWrap="CJK", spaceAfter=0)
    small = ParagraphStyle("small", parent=body, fontSize=8.25, leading=12, textColor=MUTED)
    section = ParagraphStyle("section", parent=body, fontName="CJK-Bold", fontSize=11,
                             leading=16, textColor=ACCENT, spaceBefore=10, spaceAfter=5)
    title = ParagraphStyle("title", parent=body, fontName="CJK-Bold", fontSize=23, leading=29)
    subtitle = ParagraphStyle("subtitle", parent=small, fontSize=9, leading=14, spaceAfter=12)

    def paragraph(text, style=body):
        return Paragraph(text, style)

    def evidence_row(label, result):
        return [paragraph(label), paragraph(result)]

    story = [paragraph("EZStore Agent｜可信賴度摘要", title),
             paragraph(f"資料探勘與知識開發 · 完整評鑑 LAB · {escape(date)}", subtitle)]
    callout = Table([[paragraph("<b>怎麼看</b>　本頁是本輪修正後的功能驗證。真模型只用 Gemini 3.1 Flash-Lite；歷史 LAB 的 Qwen 評分及前輪 Gemini 98.4／99.2 分另存報告，不代表本輪重新評分。")]], colWidths=[width])
    callout.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE), ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [callout, paragraph("01　評估對象與判準", section),
              paragraph("第一個 Agent：六個報價單操作、離題拒答、多輪追問。第二個 Agent：知識庫依據、改價試算、核准判斷、A2A 改資料後的核對。程式判定連結、原單有沒有動、新單內容；LLM 評審看回覆品質和該拒答還是該做事。"),
              paragraph("02　本次驗證結果與證據範圍", section)]
    rows = [evidence_row("項目", "結果"),
            evidence_row("離線與整合", escape(offline_result)),
            evidence_row("自我驗收", escape(local_result)),
            evidence_row("實際對話", escape(api_result)),
            evidence_row("OKF 與資料", "17 個條目，validate 0 error、0 warning；verify 對照原始碼與執行中的系統 10／10。另 7 個條目未經機器驗證，不能算 17 個全部自動驗證。")]
    table = Table(rows, colWidths=[104, width - 104], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PALE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.7, LINE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.35, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [table, paragraph("03　修復重點與資料保護", section),
              paragraph("否定、教學句不再被關鍵字補判成寫入。顧問轉單逾時或取消後保留結果未確認狀態，避免再次送單。後端修正更換客戶沒存進去、並行更新混合明細、舊草稿覆蓋已發佈狀態；前端修正儲存後立刻再編輯仍讀舊快取。改總價不可達時仍照講義先複製、再誠實回報。"),
              paragraph("04　尚未覆蓋與使用界線", section),
              paragraph("講義預設 Gemini 3.8 Flash，本輪用帳號現有的 3.1 Flash-Lite。測試不能涵蓋所有自然語句或老師私下題庫。第一 Agent 依教師契約允許重複轉單；顧問防重只在單一程序有效，重啟或多容器不保證，結果未確認時須先核對遠端任務和訂單，不能靠重啟清除。"),
              Spacer(1, 10),
              paragraph("詳細內容：同目錄《本輪完整檢查紀錄.md》與 artifacts/recheck-20261017/。歷史 LAB 方法與分數保留於《可信賴度報告.md》，前輪修正保留於《修正與驗證紀錄.md》。", small)]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.line(margin, 31, page_w - margin, 31)
        canvas.setFont("CJK", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(margin, 19, "本輪原始回覆、資料核對與失敗重現均保留，可回查證據。")
        canvas.drawRightString(page_w - margin, 19, f"{doc.page} / 1")
        canvas.restoreState()

    output.parent.mkdir(parents=True, exist_ok=True)
    draft = output.with_name(output.stem + ".building.pdf")
    doc = SimpleDocTemplate(str(draft), pagesize=A4, rightMargin=margin, leftMargin=margin,
                            topMargin=30, bottomMargin=42, title="EZStore Agent 可信賴度摘要",
                            author="EZStore 課程專題", allowSplitting=0)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    count = len(PdfReader(str(draft)).pages)
    if count != 1:
        raise SystemExit(f"Expected one page, generated {count}; shorten result text or adjust layout. Draft: {draft}")
    draft.replace(output)
    print(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline-result", required=True, help="Completed offline/integration outcomes and exact test counts")
    parser.add_argument("--local-result", required=True, help="Completed main deployment outcome and precise scope")
    parser.add_argument("--api-result", required=True, help="Completed API outcome, model, sample/call counts; or explicit not-run status")
    parser.add_argument("--date", default="2026-10-17")
    parser.add_argument("--font", type=Path, default=Path("C:/Windows/Fonts/msjh.ttc"))
    parser.add_argument("--bold-font", type=Path, default=Path("C:/Windows/Fonts/msjhbd.ttc"))
    parser.add_argument("--output", type=Path, default=ROOT / "reports/可信賴度報告_一頁摘要.pdf")
    args = parser.parse_args()
    register_fonts(args.font, args.bold_font)
    generate(args.output, args.offline_result, args.local_result, args.api_result, args.date)


if __name__ == "__main__":
    main()
