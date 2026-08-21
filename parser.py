import io
import re
from typing import Optional

import fitz
import pandas as pd
import pytesseract
from PIL import Image

# If Tesseract is not in PATH, this fallback works with the normal Windows install.
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if __import__('os').path.exists(TESSERACT_PATH):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

TRANSACTION_TYPES = [
    "Money Transfer",
    "Raast Payment",
    "Bank Transfer",
    "Cash Withdrawal",
    "Cash Deposit",
    "Bill Payment",
    "Bundles",
    "Insurance",
]

DATE_PATTERN = re.compile(
    r"['`\u2018\u2019\"]?\s*([A-Za-z]{3,9})\s*[\-/.,]?\s*(\d{1,2})\s*[,./-]\s*(\d{4})",
    re.I,
)

MONEY_PATTERN = re.compile(r"\(?\s*\d[\d,]*\.\d{2}\s*\)?")
ID_PATTERN = re.compile(r"\b\d{8,15}\b")
TIME_PATTERN = re.compile(r"\b\d{1,2}:\d{2}\s*(?:AM|PM)?\b", re.I)

DETAIL_HEADER_WORDS = (
    "transaction", "transacton", "amount", "tax", "fees", "discount", "total",
    "tureen", "torecion", "termin", "teansacton"
)


def normalize_line(line: str) -> str:
    line = (line or "").replace("\t", " ")
    line = re.sub(r"\s+", " ", line)
    return line.strip()


def clean_money(value: str) -> str:
    if not value:
        return ""
    return value.replace(",", "").replace("(", "").replace(")", "").strip()


def money_float(value: str) -> Optional[float]:
    try:
        return float(clean_money(value)) if value else None
    except ValueError:
        return None


def find_transaction_type(line: str) -> Optional[str]:
    low = line.lower()
    for t in TRANSACTION_TYPES:
        if t.lower() in low:
            return t
    return None


def clean_description(text: str) -> str:
    text = TIME_PATTERN.sub("", text or "")
    text = re.sub(r"\b(?:Transaction|Transacton|Tureen|Torecion|Termin)\b.*$", "", text, flags=re.I)
    text = re.sub(r"[|\[\]{}]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -:.,_")


def pdf_to_text(uploaded_file) -> str:
    pdf_bytes = uploaded_file.getvalue()
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = []
    for page in document:
        # 3x gives OCR good quality for this scanned statement.
        pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
        image = Image.open(io.BytesIO(pix.tobytes("png")))
        text = pytesseract.image_to_string(image, config="--psm 6")
        pages.append(text)
    document.close()
    return "\n".join(pages)


def parse_header(line: str):
    date_match = DATE_PATTERN.search(line)
    tx_type = find_transaction_type(line)
    if not date_match or not tx_type:
        return None

    date = f"{date_match.group(2)} {date_match.group(1).title()} {date_match.group(3)}"
    remaining = line[date_match.end():]
    remaining = re.sub(re.escape(tx_type), "", remaining, count=1, flags=re.I).strip(" -:")

    # The EasyPaisa statement has four balance columns after the description:
    # Opening | Receipts | Payments | Closing.
    values = MONEY_PATTERN.findall(remaining)
    if len(values) < 2:
        return None

    values = [v.strip() for v in values]
    opening = clean_money(values[0])
    closing = clean_money(values[-1])

    middle = values[1:-1]
    candidates = [clean_money(v) for v in middle if clean_money(v)]
    amount = candidates[0] if candidates else ""

    opening_n = money_float(opening)
    closing_n = money_float(closing)
    amount_n = money_float(amount)

    receipts = ""
    payments = ""
    if opening_n is not None and closing_n is not None:
        delta = round(closing_n - opening_n, 2)
        # The statement's parentheses alone are not enough to determine debit/credit:
        # the balance movement is authoritative.
        if delta > 0:
            receipts = f"{abs(delta):.2f}"
        elif delta < 0:
            payments = f"{abs(delta):.2f}"
    elif amount_n is not None:
        # Fallback if OCR misses one balance.
        if values[1].startswith("("):
            payments = amount_n
        else:
            receipts = amount_n

    description = clean_description(remaining)
    return {
        "Date": date,
        "Transaction Type": tx_type,
        "Description": description,
        "Opening Balance": opening,
        "Receipts": receipts,
        "Payments": payments,
        "Closing Balance": closing,
        "Transaction ID": "",
        "Amount": amount,
        "Tax": "",
        "Fees": "",
        "Discount": "",
        "Total": "",
    }


def is_detail_header(line: str) -> bool:
    low = line.lower()
    return any(word in low for word in DETAIL_HEADER_WORDS) and (
        "transaction" in low or "transacton" in low or "tureen" in low
    )


def parse_detail_line(line: str, current: dict) -> bool:
    ids = ID_PATTERN.findall(line)
    if not ids:
        return False

    # Only treat a numeric line as detail data when it occurs immediately after
    # a transaction's detail-header row. This prevents account numbers and dates
    # elsewhere in the statement from being mistaken for transaction IDs.
    current["Transaction ID"] = ids[0]

    tail = line[line.find(ids[0]) + len(ids[0]):].strip()
    nums = re.findall(r"[+-]?\d[\d,]*\.?\d*", tail)

    # OCR often loses decimal points in this PDF. The transaction amount is
    # already recoverable from the balance movement, so use that as the reliable
    # Amount value. Other fields are filled only when OCR gives a recognizable
    # decimal value.
    if current.get("Receipts"):
        current["Amount"] = current["Receipts"]
    elif current.get("Payments"):
        current["Amount"] = current["Payments"]

    # Try to preserve recognizable fee/tax/discount/total values from the tail.
    decimal_values = re.findall(r"[+-]?\d[\d,]*\.\d{2}", tail)
    if decimal_values:
        fields = [clean_money(x) for x in decimal_values]
        if len(fields) >= 4:
            current["Tax"] = fields[0]
            current["Fees"] = fields[1]
            current["Discount"] = fields[2]
            current["Total"] = fields[3]
    return True


def parse_transactions(text: str) -> pd.DataFrame:
    records = []
    current = None
    waiting_for_detail = False

    ignored = (
        "STATEMENT OF ACCOUNT", "ACCOUNT HOLDER NAME", "ACCOUNT NUMBER", "IBAN",
        "CURRENCY", "DATE ISSUED", "THIS IS A SYSTEM GENERATED", "FROM:",
    )

    for raw in text.splitlines():
        line = normalize_line(raw)
        if not line:
            continue
        upper = line.upper()

        if any(x in upper for x in ignored):
            continue

        tx = parse_header(line)
        if tx:
            if current:
                records.append(current)
            current = tx
            waiting_for_detail = False
            continue

        if current is None:
            continue

        if is_detail_header(line):
            waiting_for_detail = True
            continue

        if waiting_for_detail:
            if parse_detail_line(line, current):
                waiting_for_detail = False
                continue

        # Do not let OCR detail/header garbage leak into Description.
        if ID_PATTERN.fullmatch(line) or is_detail_header(line):
            continue
        if re.fullmatch(r"[\d,\.\-() +]+", line):
            continue

        # Time and isolated payment metadata can appear on the next line.
        extra = clean_description(line)
        if not extra:
            continue
        if current["Description"]:
            # Avoid adding obvious unrelated OCR fragments.
            if extra not in current["Description"]:
                current["Description"] += " " + extra

    if current:
        records.append(current)

    columns = [
        "Date", "Transaction Type", "Description", "Opening Balance",
        "Receipts", "Payments", "Closing Balance", "Transaction ID",
        "Amount", "Tax", "Fees", "Discount", "Total"
    ]
    df = pd.DataFrame(records, columns=columns)
    if df.empty:
        return pd.DataFrame(columns=columns)
    for col in columns:
        df[col] = df[col].fillna("").astype(str).str.strip()
    return df.reset_index(drop=True)


def extract_transactions(uploaded_file) -> pd.DataFrame:
    text = pdf_to_text(uploaded_file)
    if not text.strip():
        return pd.DataFrame()
    return parse_transactions(text)
