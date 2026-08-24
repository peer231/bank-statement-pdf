import io
import os
import re
from typing import Optional

import fitz
import pandas as pd
import pytesseract
from PIL import Image


# ============================================================
# TESSERACT CONFIGURATION
# ============================================================

# Streamlit Cloud / Linux
if os.path.exists("/usr/bin/tesseract"):
    pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"

# Windows local computer
elif os.path.exists(r"C:\Program Files\Tesseract-OCR\tesseract.exe"):
    pytesseract.pytesseract.tesseract_cmd = (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    )

elif os.path.exists(
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"
):
    pytesseract.pytesseract.tesseract_cmd = (
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"
    )


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
    ['`\u2018\u2019"]?
    \s*
    ([A-Za-z]{3,9})
    \s*
    [\-/.,]?
    \s*
    (\d{1,2})
    \s*
    [,./-]
    \s*
    (\d{4})
    """,
    re.I | re.X,
)

MONEY_PATTERN = re.compile(
    r"""
    \(?
    \s*
    \d[\d,]*\.\d{2}
    \s*
    \)?
    """,
    re.X,
)

ID_PATTERN = re.compile(r"\b\d{8,15}\b")

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
# DATAFRAME COLUMNS
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
    """Normalize OCR text."""
    line = (line or "").replace("\t", " ")
    line = re.sub(r"\s+", " ", line)
    return line.strip()


def clean_money(value: str) -> str:
    """Convert OCR money value into a clean numeric string."""
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
    """Convert money string to float."""
    if not value:
        return None

    try:
        return float(clean_money(value))
    except (ValueError, TypeError):
        return None


def format_money(value: float) -> str:
    """Format number as 2 decimal places."""
    return f"{value:.2f}"


# ============================================================
# TRANSACTION TYPE
# ============================================================

def find_transaction_type(line: str) -> Optional[str]:
    """Find transaction type in OCR line."""

    low = line.lower()

    for transaction_type in TRANSACTION_TYPES:
        if transaction_type.lower() in low:
            return transaction_type

    return None


# ============================================================
# DESCRIPTION CLEANING
# ============================================================

def clean_description(text: str) -> str:
    """
    Clean description text without allowing transaction
    detail/header garbage into it.
    """

    if not text:
        return ""

    # Remove time
    text = TIME_PATTERN.sub("", text)

    # Remove transaction-detail words and everything after them
    text = re.sub(
        r"\b(?:Transaction|Transacton|Tureen|Torecion|Termin|Teansacton)\b.*$",
        "",
        text,
        flags=re.I,
    )

    # Remove OCR symbols
    text = re.sub(
        r"[|\[\]{}]",
        " ",
        text,
    )

    # Remove repeated whitespace
    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip(" -:.,_")


def remove_balance_section(text: str) -> str:
    """
    Remove the balance section from a transaction line.

    Examples:

    31,356.81 (6,400.00) - 37,756.81
    68,791.80 - (50,034.99) 18,756.81
    56,191.80 (6,300.00) - 62,491.80

    The description should contain only the actual
    transaction description.
    """

    if not text:
        return ""

    money = r"\(?\s*\d[\d,]*\.\d{2}\s*\)?"

    patterns = [
        # Opening Amount Closing
        rf"\s*{money}\s*[-:–—]?\s*{money}\s*[-:–—]?\s*{money}.*$",

        # Opening (Amount) Closing
        rf"\s*{money}\s*{money}\s*[-:–—]?\s*{money}.*$",

        # Opening - (Amount) Closing
        rf"\s*{money}\s*[-:–—]?\s*{money}\s*{money}.*$",
    ]

    for pattern in patterns:
        cleaned = re.sub(
            pattern,
            "",
            text,
            flags=re.X,
        )

        if cleaned != text:
            return cleaned.strip()

    # Fallback:
    # If there are 2 or more money values, keep only text before
    # the first money value.
    matches = list(
        MONEY_PATTERN.finditer(text)
    )

    if matches:
        return text[:matches[0].start()].strip()

    return text


# ============================================================
# PDF OCR
# ============================================================

def pdf_to_text(uploaded_file) -> str:
    """
    Convert uploaded PDF to OCR text.

    Tesseract is expected at:
        /usr/bin/tesseract
    on Streamlit Cloud.
    """

    pdf_bytes = uploaded_file.getvalue()

    if not pdf_bytes:
        return ""

    document = fitz.open(
        stream=pdf_bytes,
        filetype="pdf",
    )

    pages = []

    try:
        for page in document:

            # 3x resolution for better OCR
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
    """
    Parse a transaction header.

    Example:

    4 Aug 2026 Money Transfer
    JAHAN KABEER - *******3333
    31,356.81 (6,400.00) - 37,756.81
    """

    date_match = DATE_PATTERN.search(line)

    transaction_type = find_transaction_type(line)

    if not date_match or not transaction_type:
        return None

    # --------------------------------------------------------
    # Date
    # --------------------------------------------------------

    date = (
        f"{date_match.group(2)} "
        f"{date_match.group(1).title()} "
        f"{date_match.group(3)}"
    )

    # --------------------------------------------------------
    # Remove date
    # --------------------------------------------------------

    remaining = line[
        date_match.end():
    ].strip()

    # --------------------------------------------------------
    # Remove transaction type
    # --------------------------------------------------------

    remaining = re.sub(
        re.escape(transaction_type),
        "",
        remaining,
        count=1,
        flags=re.I,
    ).strip(" -:")

    # --------------------------------------------------------
    # Find money values
    # --------------------------------------------------------

    money_matches = list(
        MONEY_PATTERN.finditer(
            remaining
        )
    )

    if len(money_matches) < 2:
        return None

    values = [
        match.group()
        for match in money_matches
    ]

    # --------------------------------------------------------
    # Opening / Closing
    # --------------------------------------------------------

    opening = clean_money(
        values[0]
    )

    closing = clean_money(
        values[-1]
    )

    # --------------------------------------------------------
    # Transaction amount
    # --------------------------------------------------------

    amount = ""

    if len(values) >= 3:
        amount = clean_money(
            values[1]
        )

    opening_number = money_float(
        opening
    )

    closing_number = money_float(
        closing
    )

    amount_number = money_float(
        amount
    )

    # --------------------------------------------------------
    # Receipts / Payments
    #
    # Balance movement is considered authoritative.
    # --------------------------------------------------------

    receipts = ""
    payments = ""

    if (
        opening_number is not None
        and closing_number is not None
    ):

        difference = round(
            closing_number - opening_number,
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
    # Fallback if balance movement unavailable
    # --------------------------------------------------------

    elif amount_number is not None:

        # Parentheses around the transaction amount normally
        # indicate payment/debit.
        if (
            len(values) >= 2
            and values[1].strip().startswith("(")
        ):
            payments = format_money(
                amount_number
            )

        else:
            receipts = format_money(
                amount_number
            )

    # --------------------------------------------------------
    # Description
    # --------------------------------------------------------

    description = remaining

    # Remove balance section
    description = remove_balance_section(
        description
    )

    # Clean OCR
    description = clean_description(
        description
    )

    # --------------------------------------------------------
    # Return transaction
    # --------------------------------------------------------

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
    """
    Detect transaction detail header.
    """

    low = line.lower()

    has_transaction_word = (
        "transaction" in low
        or "transacton" in low
        or "tureen" in low
        or "torecion" in low
        or "termin" in low
        or "teansacton" in low
    )

    has_detail_word = any(
        word in low
        for word in DETAIL_HEADER_WORDS
    )

    return (
        has_transaction_word
        and has_detail_word
    )


# ============================================================
# DETAIL LINE
# ============================================================

def parse_detail_line(
    line: str,
    current: dict,
) -> bool:
    """
    Parse transaction detail line.

    Expected:

        Transaction ID
        Amount
        Tax
        Fees
        Discount
        Total

    Example:

        53679963045
        6400.00
        0.00
        0.00
        0.00
        6400.00

    Important:
    We never assume that Amount == Tax.
    """

    ids = ID_PATTERN.findall(line)

    if not ids:
        return False

    # --------------------------------------------------------
    # Transaction ID
    # --------------------------------------------------------

    transaction_id = ids[0]

    current["Transaction ID"] = transaction_id

    # --------------------------------------------------------
    # Text after ID
    # --------------------------------------------------------

    id_position = line.find(
        transaction_id
    )

    tail = line[
        id_position + len(transaction_id):
    ].strip()

    # --------------------------------------------------------
    # Extract decimal values
    # --------------------------------------------------------

    decimal_values = re.findall(
        r"\(?\s*\d[\d,]*\.\d{2}\s*\)?",
        tail,
    )

    decimal_values = [
        clean_money(value)
        for value in decimal_values
    ]

    # --------------------------------------------------------
    # Determine reliable transaction amount
    # --------------------------------------------------------

    balance_amount = ""

    if current.get("Receipts"):
        balance_amount = current["Receipts"]

    elif current.get("Payments"):
        balance_amount = current["Payments"]

    elif current.get("Amount"):
        balance_amount = current["Amount"]

    # --------------------------------------------------------
    # IMPORTANT TAX FIX
    #
    # Only accept the detail fields if we have all 5:
    #
    # Amount
    # Tax
    # Fees
    # Discount
    # Total
    #
    # This prevents:
    #
    # Amount = 6400
    # Tax    = 6400
    #
    # when OCR only captured the amount.
    # --------------------------------------------------------

    if len(decimal_values) >= 5:

        detail_amount = money_float(
            decimal_values[0]
        )

        expected_amount = money_float(
            balance_amount
        )

        # Verify that detail Amount agrees with transaction amount
        amount_matches = False

        if (
            detail_amount is not None
            and expected_amount is not None
        ):

            amount_matches = (
                abs(
                    detail_amount
                    - expected_amount
                )
                <= 0.05
            )

        if amount_matches:

            current["Amount"] = format_money(
                detail_amount
            )

            current["Tax"] = decimal_values[1]
            current["Fees"] = decimal_values[2]
            current["Discount"] = decimal_values[3]
            current["Total"] = decimal_values[4]

            return True

    # --------------------------------------------------------
    # If complete detail row was not found:
    #
    # Keep Amount from balance movement.
    # DO NOT invent Tax/Fees/Discount/Total.
    # --------------------------------------------------------

    if balance_amount:
        current["Amount"] = balance_amount

    current["Tax"] = ""
    current["Fees"] = ""
    current["Discount"] = ""
    current["Total"] = ""

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

    # --------------------------------------------------------
    # Lines to ignore
    # --------------------------------------------------------

    ignored = (
        "STATEMENT OF ACCOUNT",
        "ACCOUNT HOLDER NAME",
        "ACCOUNT NUMBER",
        "IBAN",
        "CURRENCY",
        "DATE ISSUED",
        "THIS IS A SYSTEM GENERATED",
        "FROM:",
        "TO:",
    )

    # ========================================================
    # Process OCR text line-by-line
    # ========================================================

    for raw_line in text.splitlines():

        line = normalize_line(
            raw_line
        )

        if not line:
            continue

        upper = line.upper()

        # ----------------------------------------------------
        # Ignore statement metadata
        # ----------------------------------------------------

        if any(
            item in upper
            for item in ignored
        ):
            continue

        # ----------------------------------------------------
        # New transaction?
        # ----------------------------------------------------

        transaction = parse_header(
            line
        )

        if transaction:

            # Save previous transaction
            if current is not None:
                records.append(
                    current
                )

            current = transaction

            waiting_for_detail = False

            continue

        # ----------------------------------------------------
        # Ignore text before first transaction
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
        # Ignore standalone Transaction ID
        # ----------------------------------------------------

        if ID_PATTERN.fullmatch(line):
            continue

        # ----------------------------------------------------
        # Ignore numeric-only OCR garbage
        # --------------------------------------------------------

        if re.fullmatch(
            r"[\d,\.\-() +]+",
            line,
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
        # Ignore known EasyPaisa footer OCR
        # ----------------------------------------------------

        extra_lower = extra.lower()

        footer_text = (
            "main zamzama boulevard",
            "dha phase 5 karachi",
            "email: info@easypaisa.com.pk",
            "easypaisa.com.pk",
        )

        if any(
            word in extra_lower
            for word in footer_text
        ):
            continue

        # ----------------------------------------------------
        # Don't add lines containing obvious balance values
        # ----------------------------------------------------

        if MONEY_PATTERN.search(extra):
            continue

        # ----------------------------------------------------
        # Don't add detail headers
        # ----------------------------------------------------

        if is_detail_header(extra):
            continue

        # ----------------------------------------------------
        # Add useful description
        # ----------------------------------------------------

        if current["Description"]:

            if extra not in current["Description"]:

                current["Description"] += (
                    " " + extra
                )

        else:

            current["Description"] = extra

    # ========================================================
    # Save final transaction
    # ========================================================

    if current is not None:
        records.append(
            current
        )

    # ========================================================
    # Create DataFrame
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
    # Clean DataFrame
    # ========================================================

    for column in COLUMNS:

        df[column] = (
            df[column]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    # ========================================================
    # FINAL TAX SAFETY CHECK
    #
    # If Tax somehow equals Amount and there is no evidence
    # that it is a genuine tax value, clear it.
    # ========================================================

    for index, row in df.iterrows():

        amount = money_float(
            row["Amount"]
        )

        tax = money_float(
            row["Tax"]
        )

        if (
            amount is not None
            and tax is not None
            and abs(amount - tax) <= 0.01
        ):

            df.at[
                index,
                "Tax"
            ] = ""

    return df.reset_index(
        drop=True
    )


# ============================================================
# PUBLIC FUNCTION
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
