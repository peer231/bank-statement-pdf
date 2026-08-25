import io
import re
import shutil
from typing import Optional

import fitz
import pandas as pd
import pytesseract
from PIL import Image


# ============================================================
# TESSERACT CONFIGURATION
# ============================================================
# Works locally on Windows if Tesseract is installed.
# On Streamlit Cloud, Tesseract must be installed through
# packages.txt / apt packages.
# ============================================================

tesseract_path = shutil.which("tesseract")

if tesseract_path:
    pytesseract.pytesseract.tesseract_cmd = tesseract_path


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
    r"""
    ['`\u2018\u2019"]?\s*
    ([A-Za-z]{3,9})
    \s*[\-/.,]?\s*
    (\d{1,2})
    \s*[,./-]\s*
    (\d{2,4})
    """,
    re.I | re.X,
)

MONEY_PATTERN = re.compile(
    r"""
    \(?\s*
    \d[\d,]*
    (?:\.\d{1,2})?
    \s*\)?
    """,
    re.X,
)

ID_PATTERN = re.compile(
    r"\b\d{8,15}\b"
)

TIME_PATTERN = re.compile(
    r"\b\d{1,2}:\d{2}\s*(?:AM|PM)?\b",
    re.I,
)


# ============================================================
# OUTPUT COLUMNS
# ============================================================

COLUMNS = [
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


# ============================================================
# BASIC HELPERS
# ============================================================

def normalize_line(line: str) -> str:
    """
    Normalize OCR text line.
    """

    if not line:
        return ""

    line = str(line)

    line = line.replace("\t", " ")
    line = line.replace("\r", " ")

    line = re.sub(
        r"\s+",
        " ",
        line,
    )

    return line.strip()


def clean_money(value: str) -> str:
    """
    Convert money text to clean numeric string.
    """

    if value is None:
        return ""

    value = str(value).strip()

    if not value:
        return ""

    value = value.replace(",", "")
    value = value.replace("(", "")
    value = value.replace(")", "")

    return value.strip()


def money_float(value: str) -> Optional[float]:
    """
    Convert money string to float.
    """

    if value is None:
        return None

    value = clean_money(value)

    if not value:
        return None

    try:
        return float(value)

    except (
        ValueError,
        TypeError,
    ):
        return None


def format_money(value) -> str:
    """
    Always return money as 0.00 format.
    """

    if value is None:
        return ""

    if value == "":
        return ""

    try:
        return f"{float(value):.2f}"

    except (
        ValueError,
        TypeError,
    ):
        return ""


# ============================================================
# TRANSACTION TYPE
# ============================================================

def find_transaction_type(
    line: str,
) -> Optional[str]:

    low = line.lower()

    for transaction_type in TRANSACTION_TYPES:

        if transaction_type.lower() in low:
            return transaction_type

    return None


# ============================================================
# DESCRIPTION CLEANER
# ============================================================

def clean_description(
    text: str,
) -> str:
    """
    Clean OCR garbage from transaction description.
    """

    if not text:
        return ""

    # --------------------------------------------------------
    # Remove time
    # --------------------------------------------------------

    text = TIME_PATTERN.sub(
        "",
        text,
    )

    # --------------------------------------------------------
    # Remove detail table headers
    # --------------------------------------------------------

    header_patterns = [
        r"\bTransaction\s*(?:ID|1D)?\b",
        r"\bTransacton\s*(?:ID|1D)?\b",
        r"\bTureen\b",
        r"\bTorecion\b",
        r"\bTermin\b",
        r"\bAmount\b",
        r"\bTax\b",
        r"\bFees?\b",
        r"\bDiscount\b",
        r"\bTotal\b",
    ]

    for pattern in header_patterns:

        text = re.sub(
            pattern,
            "",
            text,
            flags=re.I,
        )

    # --------------------------------------------------------
    # Remove EasyPaisa footer
    # --------------------------------------------------------

    footer_patterns = [
        r"Main\s+Zamzama\s+Boulevard.*",
        r"DHA\s+Phase\s+5.*",
        r"Karachi\s*,?\s*Pakistan.*",
        r"Email\s*:\s*info@easypaisa\.com\.pk.*",
        r"info@easypaisa\.com\.pk.*",
        r"easypaisa\.com\.pk.*",
    ]

    for pattern in footer_patterns:

        text = re.sub(
            pattern,
            "",
            text,
            flags=re.I,
        )

    # --------------------------------------------------------
    # Remove transaction IDs from description
    # --------------------------------------------------------

    text = re.sub(
        r"\b\d{8,15}\b",
        "",
        text,
    )

    # --------------------------------------------------------
    # Remove balance money values from description
    #
    # Example:
    #
    # 31,356.81 (6,400.00) - 37,756.81
    # --------------------------------------------------------

    text = re.sub(
        r"\(?\s*\d[\d,]*\.\d{2}\s*\)?",
        "",
        text,
    )

    # --------------------------------------------------------
    # Remove obvious OCR symbols
    # --------------------------------------------------------

    text = re.sub(
        r"[|\[\]{}]",
        " ",
        text,
    )

    # --------------------------------------------------------
    # Remove repeated spaces
    # --------------------------------------------------------

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip(
        " -:.,_"
    )


# ============================================================
# PDF -> OCR TEXT
# ============================================================

def pdf_to_text(
    uploaded_file,
) -> str:
    """
    Convert uploaded PDF pages into OCR text.

    Tesseract path is detected automatically.
    """

    # --------------------------------------------------------
    # Check Tesseract
    # --------------------------------------------------------

    if not shutil.which("tesseract"):

        raise RuntimeError(
            "Tesseract OCR is not installed. "
            "Please install Tesseract locally or add "
            "'tesseract-ocr' to packages.txt for Streamlit Cloud."
        )

    # --------------------------------------------------------
    # Read PDF
    # --------------------------------------------------------

    pdf_bytes = uploaded_file.getvalue()

    document = fitz.open(
        stream=pdf_bytes,
        filetype="pdf",
    )

    pages = []

    # --------------------------------------------------------
    # OCR each page
    # --------------------------------------------------------

    for page in document:

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

    document.close()

    return "\n".join(pages)


# ============================================================
# FIND MONEY VALUES
# ============================================================

def find_money_values(
    text: str,
):
    """
    Find money values in a transaction line.
    """

    if not text:
        return []

    values = MONEY_PATTERN.findall(
        text
    )

    cleaned = []

    for value in values:

        value = value.strip()

        if not value:
            continue

        cleaned.append(value)

    return cleaned


# ============================================================
# EXTRACT BALANCES
# ============================================================

def extract_balances(
    line: str,
):
    """
    Extract:

    Opening Balance
    Receipts
    Payments
    Closing Balance

    from EasyPaisa transaction line.
    """

    values = find_money_values(
        line
    )

    if len(values) < 2:

        return (
            "",
            "",
            "",
            "",
        )

    # --------------------------------------------------------
    # Typical format:
    #
    # Opening
    # Transaction Amount
    # Closing
    #
    # Example:
    #
    # 31,356.81 (6,400.00) 37,756.81
    # --------------------------------------------------------

    opening = clean_money(
        values[0]
    )

    closing = clean_money(
        values[-1]
    )

    middle = values[1:-1]

    amount = ""

    if middle:

        amount = clean_money(
            middle[0]
        )

    opening_n = money_float(
        opening
    )

    closing_n = money_float(
        closing
    )

    receipts = ""
    payments = ""

    # --------------------------------------------------------
    # Determine receipt/payment from balance movement
    # --------------------------------------------------------

    if (
        opening_n is not None
        and closing_n is not None
    ):

        difference = round(
            closing_n - opening_n,
            2,
        )

        if difference > 0:

            receipts = format_money(
                difference
            )

        elif difference < 0:

            payments = format_money(
                abs(difference)
            )

    # --------------------------------------------------------
    # Fallback
    # --------------------------------------------------------

    if not receipts and not payments:

        amount_n = money_float(
            amount
        )

        if amount_n is not None:

            if (
                len(values) > 1
                and "(" in values[1]
            ):

                payments = format_money(
                    amount_n
                )

            else:

                receipts = format_money(
                    amount_n
                )

    return (
        opening,
        receipts,
        payments,
        closing,
    )


# ============================================================
# PARSE TRANSACTION HEADER
# ============================================================

def parse_header(
    line: str,
):

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

    month = date_match.group(1)
    day = date_match.group(2)
    year = date_match.group(3)

    if len(year) == 2:

        year = "20" + year

    # --------------------------------------------------------
    # Date format
    # --------------------------------------------------------

    date = (
        f"{int(day)}-"
        f"{month[:3].title()}-"
        f"{year[-2:]}"
    )

    # --------------------------------------------------------
    # Remove date
    # --------------------------------------------------------

    remaining = line[
        date_match.end():
    ]

    # --------------------------------------------------------
    # Remove transaction type
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Extract balances
    # --------------------------------------------------------

    (
        opening,
        receipts,
        payments,
        closing,
    ) = extract_balances(
        remaining
    )

    # --------------------------------------------------------
    # Amount
    # --------------------------------------------------------

    amount = ""

    if receipts:

        amount = receipts

    elif payments:

        amount = payments

    # --------------------------------------------------------
    # Description
    # --------------------------------------------------------

    description = clean_description(
        remaining
    )

    # ========================================================
    # IMPORTANT TAX RULE
    #
    # Do NOT try to calculate Tax from:
    #
    # Amount
    # Opening Balance
    # Closing Balance
    # Receipts
    # Payments
    #
    # Tax starts at 0.00.
    # ========================================================

    return {
        "Date": date,
        "Transaction Type": transaction_type,
        "Description": description,
        "Opening Balance": format_money(opening),
        "Receipts": receipts,
        "Payments": payments,
        "Closing Balance": format_money(closing),
        "Transaction ID": "",
        "Amount": amount,

        # IMPORTANT
        "Tax": "0.00",
        "Fees": "0.00",
        "Discount": "0.00",
        "Total": "0.00",
    }


# ============================================================
# DETAIL HEADER DETECTION
# ============================================================

def is_detail_header(
    line: str,
) -> bool:

    low = line.lower()

    has_transaction = (
        "transaction" in low
        or "transacton" in low
        or "tureen" in low
        or "torecion" in low
        or "termin" in low
    )

    has_amount = (
        "amount" in low
    )

    has_tax = (
        "tax" in low
    )

    has_fees = (
        "fees" in low
    )

    has_discount = (
        "discount" in low
    )

    has_total = (
        "total" in low
    )

    return (
        has_transaction
        and (
            has_amount
            or has_tax
            or has_fees
            or has_discount
            or has_total
        )
    )


# ============================================================
# DETAIL LINE PARSER
# ============================================================

def parse_detail_line(
    line: str,
    current: dict,
) -> bool:
    """
    Extract only Transaction ID from detail line.

    IMPORTANT:
    We intentionally DO NOT extract Tax/Fees/Discount/Total
    from OCR numbers.

    This prevents Amount or other numbers from accidentally
    becoming Tax.
    """

    ids = ID_PATTERN.findall(
        line
    )

    if not ids:

        return False

    # --------------------------------------------------------
    # Transaction ID
    # --------------------------------------------------------

    transaction_id = ids[0]

    current["Transaction ID"] = str(
        transaction_id
    )

    # --------------------------------------------------------
    # Amount must come from balance movement,
    # NOT from detail OCR.
    # --------------------------------------------------------

    if current.get("Receipts"):

        current["Amount"] = format_money(
            current["Receipts"]
        )

    elif current.get("Payments"):

        current["Amount"] = format_money(
            current["Payments"]
        )

    # ========================================================
    # IMPORTANT
    #
    # NEVER DO THIS:
    #
    # fields[0] -> Tax
    #
    # because OCR order is unreliable.
    #
    # Tax remains 0.00.
    # Fees remains 0.00.
    # Discount remains 0.00.
    # Total remains 0.00.
    # ========================================================

    current["Tax"] = "0.00"
    current["Fees"] = "0.00"
    current["Discount"] = "0.00"
    current["Total"] = "0.00"

    return True


# ============================================================
# CLEAN DETAIL / HEADER GARBAGE
# ============================================================

def should_ignore_line(
    line: str,
) -> bool:

    if not line:

        return True

    upper = line.upper()

    ignored = [
        "STATEMENT OF ACCOUNT",
        "ACCOUNT HOLDER NAME",
        "ACCOUNT NUMBER",
        "IBAN",
        "CURRENCY",
        "DATE ISSUED",
        "THIS IS A SYSTEM GENERATED",
        "FROM:",
        "TO:",
    ]

    for word in ignored:

        if word in upper:

            return True

    return False


# ============================================================
# PARSE ALL TRANSACTIONS
# ============================================================

def parse_transactions(
    text: str,
) -> pd.DataFrame:

    records = []

    current = None

    waiting_for_detail = False

    # ========================================================
    # PROCESS OCR LINES
    # ========================================================

    for raw_line in text.splitlines():

        line = normalize_line(
            raw_line
        )

        if not line:

            continue

        # ----------------------------------------------------
        # Ignore statement metadata
        # ----------------------------------------------------

        if should_ignore_line(
            line
        ):

            continue

        # ----------------------------------------------------
        # Detect new transaction
        # ----------------------------------------------------

        transaction = parse_header(
            line
        )

        if transaction:

            # Save previous transaction
            if current:

                records.append(
                    current
                )

            current = transaction

            waiting_for_detail = False

            continue

        # ----------------------------------------------------
        # No active transaction
        # ----------------------------------------------------

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
        # Detail line
        # ----------------------------------------------------

        if waiting_for_detail:

            if parse_detail_line(
                line,
                current,
            ):

                waiting_for_detail = False

                continue

        # ----------------------------------------------------
        # Ignore pure numeric lines
        # ----------------------------------------------------

        if re.fullmatch(
            r"[\d,\.\-() +]+",
            line,
        ):

            continue

        # ----------------------------------------------------
        # Ignore detail headers
        # ----------------------------------------------------

        if is_detail_header(
            line
        ):

            continue

        # ----------------------------------------------------
        # Clean extra description
        # ----------------------------------------------------

        extra = clean_description(
            line
        )

        if not extra:

            continue

        # ----------------------------------------------------
        # Bad OCR fragments
        # ----------------------------------------------------

        bad_fragments = [
            "easypaisa.com.pk",
            "zamzama boulevard",
            "karachi pakistan",
            "transaction id amount",
            "tax fees discount total",
        ]

        if any(
            fragment in extra.lower()
            for fragment in bad_fragments
        ):

            continue

        # ----------------------------------------------------
        # Avoid duplicate description
        # ----------------------------------------------------

        existing = current.get(
            "Description",
            "",
        )

        if (
            extra.lower()
            in existing.lower()
        ):

            continue

        # ----------------------------------------------------
        # Append description
        # ----------------------------------------------------

        if existing:

            current["Description"] = (
                existing
                + " "
                + extra
            )

        else:

            current["Description"] = extra

    # ========================================================
    # SAVE FINAL TRANSACTION
    # ========================================================

    if current:

        records.append(
            current
        )

    # ========================================================
    # CREATE DATAFRAME
    # ========================================================

    df = pd.DataFrame(
        records,
        columns=COLUMNS,
    )

    if df.empty:

        return pd.DataFrame(
            columns=COLUMNS
        )

    # ========================================================
    # ENSURE ALL COLUMNS EXIST
    # ========================================================

    for column in COLUMNS:

        if column not in df.columns:

            df[column] = ""

        df[column] = (
            df[column]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    # ========================================================
    # MONEY COLUMNS
    # ========================================================

    money_columns = [
        "Opening Balance",
        "Receipts",
        "Payments",
        "Closing Balance",
        "Amount",
        "Tax",
        "Fees",
        "Discount",
        "Total",
    ]

    for column in money_columns:

        df[column] = df[column].apply(
            lambda value:
            format_money(value)
            if value
            else ""
        )

    # ========================================================
    # TRANSACTION ID
    #
    # Keep Transaction ID as TEXT.
    #
    # This prevents Excel from converting:
    #
    # 53679963045
    #
    # into:
    #
    # 5.3679963045E+10
    # ========================================================

    df["Transaction ID"] = (
        df["Transaction ID"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.replace(
            r"\.0$",
            "",
            regex=True,
        )
    )

    # ========================================================
    # TAX SAFETY
    #
    # TAX WILL ALWAYS BE 0.00 IN THIS VERSION.
    #
    # The parser will NOT copy:
    #
    # Amount -> Tax
    # Receipts -> Tax
    # Payments -> Tax
    # Opening Balance -> Tax
    # Closing Balance -> Tax
    #
    # ========================================================

    df["Tax"] = "0.00"

    # ========================================================
    # FEES SAFETY
    # ========================================================

    df["Fees"] = (
        df["Fees"]
        .replace(
            [
                "",
                "nan",
                "None",
            ],
            "0.00",
        )
    )

    # ========================================================
    # DISCOUNT SAFETY
    # ========================================================

    df["Discount"] = (
        df["Discount"]
        .replace(
            [
                "",
                "nan",
                "None",
            ],
            "0.00",
        )
    )

    # ========================================================
    # TOTAL SAFETY
    # ========================================================

    df["Total"] = (
        df["Total"]
        .replace(
            [
                "",
                "nan",
                "None",
            ],
            "0.00",
        )
    )

    # ========================================================
    # FINAL COLUMN ORDER
    # ========================================================

    df = df[
        COLUMNS
    ]

    return df.reset_index(
        drop=True
    )


# ============================================================
# MAIN EXTRACTION FUNCTION
# ============================================================

def extract_transactions(
    uploaded_file,
) -> pd.DataFrame:
    """
    Main function called by app.py.
    """

    text = pdf_to_text(
        uploaded_file
    )

    if not text.strip():

        return pd.DataFrame(
            columns=COLUMNS
        )

    return parse_transactions(
        text
    )
