import io
import os
import re
import shutil
from typing import Optional

import fitz
import pandas as pd
import pytesseract
from PIL import Image


# ============================================================
# TESSERACT OCR CONFIGURATION
# Works on Streamlit Cloud + Windows
# ============================================================
def configure_tesseract() -> str:
    # 1. Try Tesseract from PATH.
    # Streamlit Cloud should find /usr/bin/tesseract here.
    found = shutil.which("tesseract")

    if found:
        pytesseract.pytesseract.tesseract_cmd = found
        return found

    # 2. Common Windows locations.
    windows_paths = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]

    # 3. Common Linux locations.
    linux_paths = [
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
    ]

    for path in windows_paths + linux_paths:
        if os.path.isfile(path):
            pytesseract.pytesseract.tesseract_cmd = path
            return path

    raise RuntimeError(
        "Tesseract OCR was not found. "
        "For Streamlit Cloud, make sure packages.txt contains "
        "'tesseract-ocr' and redeploy the app."
    )


TESSERACT_PATH = configure_tesseract()


# ============================================================
# TRANSACTION TYPES
# ============================================================
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
    r"['`\u2018\u2019\"]?\s*"
    r"([A-Za-z]{3,9})\s*[\-/.,]?\s*"
    r"(\d{1,2})\s*[,./-]\s*"
    r"(\d{4})",
    re.I,
)

MONEY_PATTERN = re.compile(
    r"\(?\s*\d[\d,]*\.\d{2}\s*\)?"
)

ID_PATTERN = re.compile(
    r"\b\d{8,15}\b"
)

TIME_PATTERN = re.compile(
    r"\b\d{1,2}:\d{2}\s*(?:AM|PM)?\b",
    re.I,
)

DETAIL_HEADER_WORDS = (
    "transaction",
    "transacton",
    "amount",
    "tax",
    "fees",
    "discount",
    "total",
    "tureen",
    "torecion",
    "termin",
    "teansacton",
)


# ============================================================
# HELPER FUNCTIONS
# ============================================================
def normalize_line(line: str) -> str:
    line = (line or "").replace("\t", " ")
    line = re.sub(r"\s+", " ", line)
    return line.strip()


def clean_money(value: str) -> str:
    if not value:
        return ""

    return (
        value
        .replace(",", "")
        .replace("(", "")
        .replace(")", "")
        .strip()
    )


def money_float(value: str) -> Optional[float]:
    try:
        return float(clean_money(value)) if value else None
    except (ValueError, TypeError):
        return None


def find_transaction_type(line: str) -> Optional[str]:
    low = line.lower()

    for transaction_type in TRANSACTION_TYPES:
        if transaction_type.lower() in low:
            return transaction_type

    return None


def clean_description(text: str) -> str:
    text = TIME_PATTERN.sub("", text or "")

    text = re.sub(
        r"\b(?:Transaction|Transacton|Tureen|Torecion|Termin)\b.*$",
        "",
        text,
        flags=re.I,
    )

    text = re.sub(
        r"[|\[\]{}]",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip(" -:.,_")


# ============================================================
# PDF -> OCR
# ============================================================
def pdf_to_text(uploaded_file) -> str:

    pdf_bytes = uploaded_file.getvalue()

    document = fitz.open(
        stream=pdf_bytes,
        filetype="pdf",
    )

    pages = []

    try:

        for page in document:

            # 3x resolution for better OCR.
            pix = page.get_pixmap(
                matrix=fitz.Matrix(3, 3),
                alpha=False,
            )

            image = Image.open(
                io.BytesIO(
                    pix.tobytes("png")
                )
            )

            text = pytesseract.image_to_string(
                image,
                config="--psm 6",
            )

            pages.append(text)

    finally:
        document.close()

    return "\n".join(pages)


# ============================================================
# PARSE TRANSACTION HEADER
# ============================================================
def parse_header(line: str):

    date_match = DATE_PATTERN.search(line)

    transaction_type = find_transaction_type(line)

    if not date_match or not transaction_type:
        return None

    date = (
        f"{date_match.group(2)} "
        f"{date_match.group(1).title()} "
        f"{date_match.group(3)}"
    )

    remaining = line[
        date_match.end():
    ]

    remaining = re.sub(
        re.escape(transaction_type),
        "",
        remaining,
        count=1,
        flags=re.I,
    ).strip(" -:")

    # EasyPaisa columns:
    #
    # Opening Balance
    # Receipts / Incoming
    # Payments / Outgoing
    # Closing Balance
    #
    values = MONEY_PATTERN.findall(
        remaining
    )

    if len(values) < 2:
        return None

    values = [
        value.strip()
        for value in values
    ]

    opening = clean_money(
        values[0]
    )

    closing = clean_money(
        values[-1]
    )

    middle = values[1:-1]

    candidates = [
        clean_money(value)
        for value in middle
        if clean_money(value)
    ]

    amount = (
        candidates[0]
        if candidates
        else ""
    )

    opening_n = money_float(
        opening
    )

    closing_n = money_float(
        closing
    )

    amount_n = money_float(
        amount
    )

    receipts = ""
    payments = ""

    # --------------------------------------------------------
    # Balance movement is authoritative.
    # --------------------------------------------------------
    if (
        opening_n is not None
        and closing_n is not None
    ):

        delta = round(
            closing_n - opening_n,
            2,
        )

        if delta > 0:

            receipts = f"{delta:.2f}"

        elif delta < 0:

            payments = f"{abs(delta):.2f}"

    # --------------------------------------------------------
    # Fallback when OCR misses a balance.
    # --------------------------------------------------------
    elif amount_n is not None:

        if len(values) > 1:

            if values[1].startswith("("):

                payments = f"{amount_n:.2f}"

            else:

                receipts = f"{amount_n:.2f}"

    description = clean_description(
        remaining
    )

    return {
        "Date": date,
        "Transaction Type": transaction_type,
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


# ============================================================
# DETAIL HEADER
# ============================================================
def is_detail_header(line: str) -> bool:

    low = line.lower()

    return (
        any(
            word in low
            for word in DETAIL_HEADER_WORDS
        )
        and (
            "transaction" in low
            or "transacton" in low
            or "tureen" in low
        )
    )


# ============================================================
# TRANSACTION DETAIL
# ============================================================
def parse_detail_line(
    line: str,
    current: dict,
) -> bool:

    ids = ID_PATTERN.findall(
        line
    )

    if not ids:
        return False

    current["Transaction ID"] = ids[0]

    # Amount should match the actual balance movement.
    if current.get("Receipts"):

        current["Amount"] = (
            current["Receipts"]
        )

    elif current.get("Payments"):

        current["Amount"] = (
            current["Payments"]
        )

    tail = line[
        line.find(ids[0])
        + len(ids[0]):
    ].strip()

    # Try to extract:
    # Tax | Fees | Discount | Total
    decimal_values = re.findall(
        r"[+-]?\d[\d,]*\.\d{2}",
        tail,
    )

    if decimal_values:

        fields = [
            clean_money(value)
            for value in decimal_values
        ]

        if len(fields) >= 4:

            current["Tax"] = fields[0]
            current["Fees"] = fields[1]
            current["Discount"] = fields[2]
            current["Total"] = fields[3]

    return True


# ============================================================
# MAIN PARSER
# ============================================================
def parse_transactions(
    text: str,
) -> pd.DataFrame:

    records = []

    current = None

    waiting_for_detail = False

    ignored = (
        "STATEMENT OF ACCOUNT",
        "ACCOUNT HOLDER NAME",
        "ACCOUNT NUMBER",
        "IBAN",
        "CURRENCY",
        "DATE ISSUED",
        "THIS IS A SYSTEM GENERATED",
        "FROM:",
    )

    for raw_line in text.splitlines():

        line = normalize_line(
            raw_line
        )

        if not line:
            continue

        upper = line.upper()

        if any(
            item in upper
            for item in ignored
        ):
            continue

        # ----------------------------------------------------
        # New transaction
        # ----------------------------------------------------
        transaction = parse_header(
            line
        )

        if transaction:

            if current:
                records.append(
                    current
                )

            current = transaction

            waiting_for_detail = False

            continue

        if current is None:
            continue

        # ----------------------------------------------------
        # Detail header
        # ----------------------------------------------------
        if is_detail_header(line):

            waiting_for_detail = True

            continue

        # ----------------------------------------------------
        # Detail data
        # ----------------------------------------------------
        if waiting_for_detail:

            if parse_detail_line(
                line,
                current,
            ):

                waiting_for_detail = False

                continue

        # ----------------------------------------------------
        # Prevent OCR garbage
        # ----------------------------------------------------
        if ID_PATTERN.fullmatch(
            line
        ):
            continue

        if is_detail_header(
            line
        ):
            continue

        if re.fullmatch(
            r"[\d,\.\-() +]+",
            line,
        ):
            continue

        extra = clean_description(
            line
        )

        if not extra:
            continue

        if current["Description"]:

            if extra not in current["Description"]:

                current["Description"] += (
                    " " + extra
                )

    if current:
        records.append(
            current
        )

    columns = [
        "Date",
        "Transaction Type",
        "Description",
        "Opening Balance",
        "Receipts",
        "Payments",
        "Closing Balance",
        "Transaction ID",
        "Amount",
        "Tax",
        "Fees",
        "Discount",
        "Total",
    ]

    df = pd.DataFrame(
        records,
        columns=columns,
    )

    if df.empty:

        return pd.DataFrame(
            columns=columns
        )

    for column in columns:

        df[column] = (
            df[column]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    return df.reset_index(
        drop=True
    )


# ============================================================
# FUNCTION USED BY app.py
# ============================================================
def extract_transactions(
    uploaded_file,
) -> pd.DataFrame:

    text = pdf_to_text(
        uploaded_file
    )

    if not text.strip():

        return pd.DataFrame()

    return parse_transactions(
        text
    )
