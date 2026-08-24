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
# TESSERACT CONFIGURATION
# Streamlit Cloud + Windows compatible
# ============================================================

def configure_tesseract() -> str:
    """
    Automatically find Tesseract.

    Streamlit Cloud:
        Usually /usr/bin/tesseract

    Windows:
        Usually C:/Program Files/Tesseract-OCR/tesseract.exe
    """

    # First check PATH
    found = shutil.which("tesseract")

    if found:
        pytesseract.pytesseract.tesseract_cmd = found
        return found

    # Common Windows locations
    windows_paths = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]

    # Common Linux locations
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
        "For Streamlit Cloud, make sure packages.txt "
        "contains: tesseract-ocr"
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


# ============================================================
# REGEX PATTERNS
# ============================================================

DATE_PATTERN = re.compile(
    r"['`\u2018\u2019\"]?\s*"
    r"([A-Za-z]{3,9})"
    r"\s*[\-/.,]?\s*"
    r"(\d{1,2})"
    r"\s*[,./-]\s*"
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
# BASIC HELPERS
# ============================================================

def normalize_line(line: str) -> str:
    """
    Clean OCR line.
    """

    line = (line or "").replace(
        "\t",
        " "
    )

    line = re.sub(
        r"\s+",
        " ",
        line
    )

    return line.strip()


def clean_money(value: str) -> str:
    """
    Convert:
        (6,400.00)
    into:
        6400.00
    """

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
    """
    Convert money string to float.
    """

    try:
        if value:
            return float(
                clean_money(value)
            )

        return None

    except (
        ValueError,
        TypeError,
    ):
        return None


def find_transaction_type(
    line: str,
) -> Optional[str]:
    """
    Find transaction type from OCR line.
    """

    low = line.lower()

    for transaction_type in TRANSACTION_TYPES:

        if transaction_type.lower() in low:
            return transaction_type

    return None


def clean_description(
    text: str,
) -> str:
    """
    Remove OCR noise from description.
    """

    text = TIME_PATTERN.sub(
        "",
        text or "",
    )

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

    return text.strip(
        " -:.,_"
    )


# ============================================================
# PDF TO TEXT
# ============================================================

def pdf_to_text(
    uploaded_file,
) -> str:
    """
    Convert uploaded PDF into OCR text.
    """

    pdf_bytes = uploaded_file.getvalue()

    document = fitz.open(
        stream=pdf_bytes,
        filetype="pdf",
    )

    pages = []

    try:

        for page in document:

            # 3x resolution for OCR
            pix = page.get_pixmap(
                matrix=fitz.Matrix(
                    3,
                    3,
                ),
                alpha=False,
            )

            image = Image.open(
                io.BytesIO(
                    pix.tobytes(
                        "png"
                    )
                )
            )

            text = pytesseract.image_to_string(
                image,
                config="--psm 6",
            )

            pages.append(
                text
            )

    finally:

        document.close()

    return "\n".join(
        pages
    )


# ============================================================
# PARSE TRANSACTION HEADER
# ============================================================

def parse_header(
    line: str,
):
    """
    Parse transaction line.

    Expected general structure:

    Date
    Transaction Type
    Description
    Opening Balance
    Incoming
    Outgoing
    Closing Balance
    """

    date_match = DATE_PATTERN.search(
        line
    )

    transaction_type = find_transaction_type(
        line
    )

    if (
        not date_match
        or not transaction_type
    ):
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
    )

    remaining = remaining.strip(
        " -:"
    )

    # Find money values
    values = MONEY_PATTERN.findall(
        remaining
    )

    if len(values) < 2:
        return None

    values = [
        value.strip()
        for value in values
    ]

    # First balance
    opening = clean_money(
        values[0]
    )

    # Last balance
    closing = clean_money(
        values[-1]
    )

    # Values between opening and closing
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

    # ========================================================
    # Determine Incoming / Outgoing
    # using balance movement
    # ========================================================

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

        # Detail fields
        "Transaction ID": "",
        "Amount": amount,
        "Tax": "",
        "Fees": "",
        "Discount": "",
        "Total": "",
    }


# ============================================================
# DETAIL HEADER DETECTION
# ============================================================

def is_detail_header(
    line: str,
) -> bool:
    """
    Detect:

    Transaction ID | Amount | Tax | Fees | Discount | Total
    """

    low = line.lower()

    has_word = any(
        word in low
        for word in DETAIL_HEADER_WORDS
    )

    has_transaction = (
        "transaction" in low
        or "transacton" in low
        or "tureen" in low
    )

    return (
        has_word
        and has_transaction
    )


# ============================================================
# DETAIL LINE PARSER
# ============================================================

def parse_detail_line(
    line: str,
    current: dict,
) -> bool:
    """
    Parse:

    Transaction ID | Amount | Tax | Fees | Discount | Total

    IMPORTANT:

    First value  = Amount
    Second value = Tax
    Third value  = Fees
    Fourth value = Discount
    Fifth value  = Total

    This prevents Amount from accidentally
    being written into Tax.
    """

    ids = ID_PATTERN.findall(
        line
    )

    if not ids:
        return False

    transaction_id = ids[0]

    current["Transaction ID"] = (
        transaction_id
    )

    # --------------------------------------------------------
    # Text after transaction ID
    # --------------------------------------------------------

    id_position = line.find(
        transaction_id
    )

    tail = line[
        id_position
        + len(transaction_id):
    ].strip()

    # --------------------------------------------------------
    # Extract decimal values
    # --------------------------------------------------------

    values = re.findall(
        r"[+-]?\d[\d,]*\.\d{2}",
        tail,
    )

    values = [
        clean_money(value)
        for value in values
    ]

    # ========================================================
    # NORMAL CASE
    #
    # Amount | Tax | Fees | Discount | Total
    #
    # Example:
    #
    # 6400.00
    # 0.00
    # 0.00
    # 0.00
    # 6400.00
    # ========================================================

    if len(values) >= 5:

        current["Amount"] = values[0]

        current["Tax"] = values[1]

        current["Fees"] = values[2]

        current["Discount"] = values[3]

        current["Total"] = values[4]

        return True

    # ========================================================
    # If OCR gives 4 values
    #
    # We assume:
    #
    # Amount | Tax | Fees | Total
    #
    # Discount = 0.00
    # ========================================================

    if len(values) == 4:

        current["Amount"] = values[0]

        current["Tax"] = values[1]

        current["Fees"] = values[2]

        current["Discount"] = "0.00"

        current["Total"] = values[3]

        return True

    # ========================================================
    # If OCR gives 3 values
    #
    # Amount | Tax | Total
    #
    # Fees = 0
    # Discount = 0
    # ========================================================

    if len(values) == 3:

        current["Amount"] = values[0]

        current["Tax"] = values[1]

        current["Fees"] = "0.00"

        current["Discount"] = "0.00"

        current["Total"] = values[2]

        return True

    # ========================================================
    # If OCR gives 2 values
    #
    # Amount | Total
    #
    # Tax = 0
    # Fees = 0
    # Discount = 0
    # ========================================================

    if len(values) == 2:

        current["Amount"] = values[0]

        current["Tax"] = "0.00"

        current["Fees"] = "0.00"

        current["Discount"] = "0.00"

        current["Total"] = values[1]

        return True

    # ========================================================
    # If OCR gives only 1 value
    #
    # Treat it as Amount.
    #
    # NEVER put it into Tax.
    # ========================================================

    if len(values) == 1:

        current["Amount"] = values[0]

        current["Tax"] = "0.00"

        current["Fees"] = "0.00"

        current["Discount"] = "0.00"

        current["Total"] = values[0]

        return True

    # ========================================================
    # No detail values found
    #
    # Use balance movement as Amount.
    # ========================================================

    if current.get("Receipts"):

        current["Amount"] = (
            current["Receipts"]
        )

    elif current.get("Payments"):

        current["Amount"] = (
            current["Payments"]
        )

    # Safe defaults
    if not current.get("Tax"):
        current["Tax"] = "0.00"

    if not current.get("Fees"):
        current["Fees"] = "0.00"

    if not current.get("Discount"):
        current["Discount"] = "0.00"

    if (
        not current.get("Total")
        and current.get("Amount")
    ):
        current["Total"] = (
            current["Amount"]
        )

    return True


# ============================================================
# MAIN TRANSACTION PARSER
# ============================================================

def parse_transactions(
    text: str,
) -> pd.DataFrame:
    """
    Parse complete OCR text.
    """

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

    # ========================================================
    # Process every OCR line
    # ========================================================

    for raw_line in text.splitlines():

        line = normalize_line(
            raw_line
        )

        if not line:
            continue

        upper = line.upper()

        # ----------------------------------------------------
        # Ignore account/header information
        # ----------------------------------------------------

        if any(
            item in upper
            for item in ignored
        ):
            continue

        # ----------------------------------------------------
        # Check for new transaction
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

        if is_detail_header(
            line
        ):

            waiting_for_detail = True

            continue

        # ----------------------------------------------------
        # Detail row
        # ----------------------------------------------------

        if waiting_for_detail:

            if parse_detail_line(
                line,
                current,
            ):

                waiting_for_detail = False

                continue

        # ----------------------------------------------------
        # Ignore transaction ID-only lines
        # ----------------------------------------------------

        if ID_PATTERN.fullmatch(
            line
        ):
            continue

        # ----------------------------------------------------
        # Ignore detail header garbage
        # ----------------------------------------------------

        if is_detail_header(
            line
        ):
            continue

        # ----------------------------------------------------
        # Ignore numeric-only OCR garbage
        # ----------------------------------------------------

        if re.fullmatch(
            r"[\d,\.\-() +]+",
            line,
        ):
            continue

        # ----------------------------------------------------
        # Extra description text
        # ----------------------------------------------------

        extra = clean_description(
            line
        )

        if not extra:
            continue

        if current["Description"]:

            if extra not in current[
                "Description"
            ]:

                current["Description"] += (
                    " " + extra
                )

    # ========================================================
    # Add last transaction
    # ========================================================

    if current:

        records.append(
            current
        )

    # ========================================================
    # Final columns
    # ========================================================

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

    # ========================================================
    # Clean all columns
    # ========================================================

    for column in columns:

        df[column] = (
            df[column]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    # ========================================================
    # Final safety:
    #
    # Empty Tax/Fees/Discount should be 0.00.
    #
    # This does NOT overwrite actual values.
    # ========================================================

    for column in [
        "Tax",
        "Fees",
        "Discount",
    ]:

        df[column] = df[column].replace(
            "",
            "0.00"
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
    """
    Main function called from app.py.
    """

    text = pdf_to_text(
        uploaded_file
    )

    if not text.strip():

        return pd.DataFrame()

    return parse_transactions(
        text
    )
