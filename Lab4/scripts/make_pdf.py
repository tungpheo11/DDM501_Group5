"""
Convert lab4_written_analysis.md to HTML and then export to PDF via Edge headless.
"""
import subprocess
from pathlib import Path
import markdown

BASE_DIR = Path(__file__).resolve().parent.parent
DOCS_DIR = BASE_DIR / "docs"
MD_PATH = DOCS_DIR / "lab4_written_analysis.md"
HTML_PATH = DOCS_DIR / "lab4_written_analysis.html"
PDF_PATH = DOCS_DIR / "lab4_written_analysis.pdf"

def main():
    text = MD_PATH.read_text(encoding="utf-8")
    body = markdown.markdown(text, extensions=["tables", "fenced_code"])

    css = """
    @page {
        size: A4;
        margin: 20mm 15mm 20mm 15mm;
    }
    body {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        line-height: 1.6;
        color: #24292e;
        max-width: 900px;
        margin: 0 auto;
        padding: 10px;
        font-size: 14px;
    }
    h1 {
        font-size: 24px;
        border-bottom: 2px solid #0366d6;
        padding-bottom: 8px;
        color: #1a1f2c;
        margin-top: 0;
    }
    h2 {
        font-size: 18px;
        border-bottom: 1px solid #e1e4e8;
        padding-bottom: 6px;
        color: #24292e;
        margin-top: 24px;
    }
    h3 {
        font-size: 15px;
        color: #24292e;
        margin-top: 16px;
    }
    table {
        border-collapse: collapse;
        width: 100%;
        margin: 16px 0;
        font-size: 13px;
    }
    th, td {
        border: 1px solid #dfe2e5;
        padding: 8px 12px;
        text-align: left;
    }
    th {
        background-color: #f6f8fa;
        font-weight: 600;
    }
    tr:nth-child(even) {
        background-color: #fafbfc;
    }
    code {
        background-color: #f0f3f6;
        padding: 2px 5px;
        border-radius: 3px;
        font-family: 'Consolas', 'Courier New', monospace;
        font-size: 12px;
    }
    hr {
        border: 0;
        border-top: 1px solid #e1e4e8;
        margin: 20px 0;
    }
    ul {
        padding-left: 20px;
    }
    li {
        margin-bottom: 4px;
    }
    strong {
        color: #111;
    }
    """

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>DDM501 Lab 4 Written Analysis</title>
<style>
{css}
</style>
</head>
<body>
{body}
</body>
</html>"""

    HTML_PATH.write_text(html, encoding="utf-8")
    print(f"HTML written to {HTML_PATH}")

    edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    cmd = [
        edge_path,
        "--headless",
        "--disable-gpu",
        f"--print-to-pdf={PDF_PATH}",
        str(HTML_PATH.resolve())
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if PDF_PATH.exists() and PDF_PATH.stat().st_size > 0:
        print(f"SUCCESS: PDF generated at {PDF_PATH} ({PDF_PATH.stat().st_size} bytes)")
    else:
        print(f"ERROR: Failed to generate PDF: {res.stderr}")

if __name__ == "__main__":
    main()
