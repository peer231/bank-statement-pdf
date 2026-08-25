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
# Works with Streamlit Cloud if Tesseract is available.
# Also works on Windows if Tesseract is in PATH.
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
    Normalize OCR line.
    """

    if not line:
        return ""

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
    Convert OCR money value to clean numeric string.
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
    Always return money in 0.00 format.
    """

    if value is None or value == "":
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
    # Remove transaction detail headers
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
    # Remove transaction IDs
    # --------------------------------------------------------

    text = re.sub(
        r"\b\d{8,15}\b",
        "",
        text,
    )

    # --------------------------------------------------------
    # Remove money values from description
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
    # Remove excessive spaces
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

    pdf_bytes = uploaded_file.getvalue()

    document = fitz.open(
        stream=pdf_bytes,
        filetype="pdf",
    )

    pages = []

    try:

        for page in document:

            # ------------------------------------------------
            # High resolution OCR
            # ------------------------------------------------

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

            pages.append(text)

    finally:

        document.close()

    return "\n".join(pages)


# ============================================================
# FIND MONEY VALUES
# ============================================================

def find_money_values(
    text: str,
):

    if not text:
        return []

    values = MONEY_PATTERN.findall(
        text
    )

    cleaned = []

    for value in values:

        value = value.strip()

        if value:
            cleaned.append(value)

    return cleaned


# ============================================================
# EXTRACT BALANCES
# ============================================================

def extract_balances(
    line: str,
):

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
    # EasyPaisa format:
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
    # Determine Receipts / Payments
    # from balance movement.
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
        re.escape(
            transaction_type
        ),
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

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # Tax/Fees/Discount/Total initially zero.
    #
    # Detail line will update Fees/Discount/Total
    # when actual values are found.
    #
    # Tax remains ZERO.
    # --------------------------------------------------------

    return {
        "Date": date,
        "Transaction Type": transaction_type,
        "Description": description,
        "Opening Balance": format_money(
            opening
        ),
        "Receipts": receipts,
        "Payments": payments,
        "Closing Balance": format_money(
            closing
        ),
        "Transaction ID": "",
        "Amount": amount,

        # TAX IS ALWAYS ZERO
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
    )

    has_amount = (
        "amount" in low
    )

    has_tax = (
        "tax" in low
    )

    has_fees = (
        "fee" in low
        or "fees" in low
    )

    return (
        has_transaction
        and (
            has_amount
            or has_tax
            or has_fees
        )
    )


# ============================================================
# DETAIL LINE PARSER
# ============================================================

def parse_detail_line(
    line: str,
    current: dict,
) -> bool:

    if not line or current is None:
        return False

    # --------------------------------------------------------
    # Find Transaction ID
    # --------------------------------------------------------

    ids = ID_PATTERN.findall(
        line
    )

    if not ids:
        return False

    transaction_id = ids[0]

    current["Transaction ID"] = str(
        transaction_id
    )

    # --------------------------------------------------------
    # Everything after Transaction ID
    # --------------------------------------------------------

    id_position = line.find(
        transaction_id
    )

    tail = line[
        id_position
        + len(transaction_id):
    ].strip()

    # --------------------------------------------------------
    # IMPORTANT
    #
    # Expected PDF detail columns:
    #
    # Transaction ID
    # Amount
    # Tax
    # Fees
    # Discount
    # Total
    #
    # Example:
    #
    # 53643266705
    # 60034.99
    # 0.00
    # 4.56
    # 30.43
    # 0.00
    #
    # We NEVER assign Amount to Tax.
    # --------------------------------------------------------

    decimal_values = re.findall(
        r"\(?\s*[+-]?\d[\d,]*\.\d{2}\s*\)?",
        tail,
    )

    fields = [
        clean_money(value)
        for value in decimal_values
    ]

    # --------------------------------------------------------
    # Amount is determined from balance movement.
    # --------------------------------------------------------

    if current.get("Receipts"):

        current["Amount"] = format_money(
            current["Receipts"]
        )

    elif current.get("Payments"):

        current["Amount"] = format_money(
            current["Payments"]
        )

    # --------------------------------------------------------
    # ALWAYS RESET THESE VALUES
    # --------------------------------------------------------

    current["Tax"] = "0.00"
    current["Fees"] = "0.00"
    current["Discount"] = "0.00"
    current["Total"] = "0.00"

    # ========================================================
    # CASE 1
    #
    # Amount | Tax | Fees | Discount | Total
    #
    # 5 values
    # ========================================================

    if len(fields) >= 5:

        # fields[0] = Amount
        # fields[1] = Tax
        # fields[2] = Fees
        # fields[3] = Discount
        # fields[4] = Total

        # ----------------------------------------------------
        # TAX
        #
        # Your PDF has Tax = 0.
        # Therefore force Tax to 0.00.
        # ----------------------------------------------------

        current["Tax"] = "0.00"

        # ----------------------------------------------------
        # FEES
        # ----------------------------------------------------

        current["Fees"] = format_money(
            fields[2]
        )

        # ----------------------------------------------------
        # DISCOUNT
        # ----------------------------------------------------

        current["Discount"] = format_money(
            fields[3]
        )

        # ----------------------------------------------------
        # TOTAL
        # ----------------------------------------------------

        current["Total"] = format_money(
            fields[4]
        )

    # ========================================================
    # CASE 2
    #
    # Amount | Tax | Fees | Discount
    #
    # 4 values
    # ========================================================

    elif len(fields) == 4:

        # fields[0] = Amount
        # fields[1] = Tax
        # fields[2] = Fees
        # fields[3] = Discount

        current["Tax"] = "0.00"

        current["Fees"] = format_money(
            fields[2]
        )

        current["Discount"] = format_money(
            fields[3]
        )

        current["Total"] = "0.00"

    # ========================================================
    # CASE 3
    #
    # Amount | Tax | Fees
    #
    # 3 values
    # ========================================================

    elif len(fields) == 3:

        # fields[0] = Amount
        # fields[1] = Tax
        # fields[2] = Fees

        current["Tax"] = "0.00"

        current["Fees"] = format_money(
            fields[2]
        )

        current["Discount"] = "0.00"
        current["Total"] = "0.00"

    # ========================================================
    # CASE 4
    #
    # Amount | Tax
    #
    # 2 values
    # ========================================================

    elif len(fields) == 2:

        # fields[0] = Amount
        # fields[1] = Tax
        #
        # Tax remains zero.

        current["Tax"] = "0.00"
        current["Fees"] = "0.00"
        current["Discount"] = "0.00"
        current["Total"] = "0.00"

    # ========================================================
    # CASE 5
    #
    # No detail values.
    # ========================================================

    else:

        current["Tax"] = "0.00"
        current["Fees"] = "0.00"
        current["Discount"] = "0.00"
        current["Total"] = "0.00"

    return True


# ============================================================
# CLEAN DETAIL GARBAGE
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
    # PROCESS EVERY OCR LINE
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

        if should_ignore_line(line):
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

        # ----------------------------------------------------
        # No transaction yet
        # ----------------------------------------------------

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
        # Ignore pure numeric garbage
        # ----------------------------------------------------

        if re.fullmatch(
            r"[\d,\.\-() +]+",
            line,
        ):

            continue

        # ----------------------------------------------------
        # Ignore detail headers
        # ----------------------------------------------------

        if is_detail_header(line):
            continue

        # ----------------------------------------------------
        # Clean additional description
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
            "transaction id",
            "tax fees discount total",
            "tax fees",
        ]

        extra_lower = extra.lower()

        if any(
            fragment in extra_lower
            for fragment in bad_fragments
        ):

            continue

        # ----------------------------------------------------
        # Existing description
        # ----------------------------------------------------

        existing = current.get(
            "Description",
            "",
        )

        # ----------------------------------------------------
        # Avoid duplicate description
        # ----------------------------------------------------

        if (
            extra_lower
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
    # ADD LAST TRANSACTION
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
    # Keep as TEXT so Excel doesn't turn:
    #
    # 53643266705
    #
    # into:
    #
    # 5.36E+10
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
    # VERY IMPORTANT:
    #
    # Tax is ZERO for this statement.
    #
    # Never copy Amount into Tax.
    # Never copy Fees into Tax.
    # Never infer Tax from balance movement.
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
    # FINAL MONEY FORMATTING
    # ========================================================

    for column in [
        "Fees",
        "Discount",
        "Total",
    ]:

        df[column] = df[column].apply(
            lambda value:
            format_money(value)
            if value
            else "0.00"
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
