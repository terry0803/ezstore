"""Create the LAB's one-page Traditional Chinese trustworthiness PDF.

Requires reportlab and pypdf. Uses an embedded TrueType CJK font; on other
machines supply --font and --bold-font. Final deployment/API outcomes are
required arguments so an unfinished run cannot silently become a passing result.
Example (replace result arguments with the completed, evidenced outcomes):
  python scripts/generate_trust_summary.py --local-result "..." --api-result "..."
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


def generate(output, local_result, api_result, date):
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
    callout = Table([[paragraph("<b>怎麼看</b>　每一列都對得到原始結果檔。LAB 當時的評審是本機 Qwen3.5 9B，最後的自我驗收改用 Gemini 3.1 Flash-Lite，兩者分開列。")]], colWidths=[width])
    callout.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE), ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [callout, paragraph("01　評估對象與判準", section),
              paragraph("第一個 Agent：六個報價單操作、離題拒答、多輪追問。第二個 Agent：知識庫依據、改價試算、核准判斷、A2A 改資料後的核對。程式判定連結、原單有沒有動、新單內容；LLM 評審看回覆品質和該拒答還是該做事。"),
              paragraph("02　本次驗證結果與證據範圍", section)]
    rows = [evidence_row("項目", "結果"),
            evidence_row("離線測試", "報價單 Agent 133、議價顧問 159、MCP 15、scripts 28（另 28 子測試）全過；Go 後端 vet、test 通過；前端單元 7、型別檢查、隔離 E2E 12 通過。"),
            evidence_row("自我驗收", escape(local_result)),
            evidence_row("實際對話", escape(api_result)),
            evidence_row("OKF 與資料", "17 個條目，validate 0 error、0 warning；verify 對照原始碼與執行中的系統 10／10。seed 裡 9 張報價單的利潤欄位改成重算值，12 張都和品項一致。")]
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
              paragraph("數字和報價單編號改由程式從原文抓，中文數字也能解析，含糊就追問。議價顧問經 A2A 改完後，從後端重讀原單和新單核對。課程元件修了負報價因子能存、客戶名稱模糊時選第一筆、清單只讀第一頁、中文輸入法 Enter 誤送。改總價做不到時照講義流程先複製，再照實回報實際總價。主資料庫修正前有備份。"),
              paragraph("04　尚未覆蓋與使用界線", section),
              paragraph("講義指定的 Gemini 3.8 Flash 因為額度沒有跑，測試用帳號裡最便宜的 3.1 Flash-Lite。評審和 Agent 是同一個模型，可能偏寬。提示注入只測了清單裡的句型；報價單 Agent 照老師系統的設計，可以把同一張單轉兩次訂單；議價顧問那條路會排隊重新檢查，只轉一次。"),
              Spacer(1, 10),
              paragraph("詳細內容：同目錄的《可信賴度報告.md》（LAB 各節、穩定性、破壞測試、多輪題）與《修正與驗證紀錄.md》（改了什麼、測試結果、備份位置）。", small)]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.line(margin, 31, page_w - margin, 31)
        canvas.setFont("CJK", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(margin, 19, "原始結果檔的位置列在《修正與驗證紀錄.md》。")
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
    parser.add_argument("--local-result", required=True, help="Completed main deployment outcome and precise scope")
    parser.add_argument("--api-result", required=True, help="Completed API outcome, model, sample/call counts; or explicit not-run status")
    parser.add_argument("--date", default="2026-10-17")
    parser.add_argument("--font", type=Path, default=Path("C:/Windows/Fonts/msjh.ttc"))
    parser.add_argument("--bold-font", type=Path, default=Path("C:/Windows/Fonts/msjhbd.ttc"))
    parser.add_argument("--output", type=Path, default=ROOT / "reports/可信賴度報告_一頁摘要.pdf")
    args = parser.parse_args()
    register_fonts(args.font, args.bold_font)
    generate(args.output, args.local_result, args.api_result, args.date)


if __name__ == "__main__":
    main()
