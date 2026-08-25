import io
import re

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
# DATE PATTERN
# ============================================================

DATE_PATTERN = re.compile(
    r"""
    ['"`]?
    ([A-Za-z]{3,9})
    \s*
    (\d{1,2})
    \s*
    [,./-]
    \s*
    (\d{4})
    """,
    re.IGNORECASE | re.VERBOSE
)


# ============================================================
# MONEY PATTERN
# ============================================================

MONEY_PATTERN = re.compile(
    r"""
    \(?
    \d[\d,]*\.\d{2}
    \)?
    """,
    re.VERBOSE
)


# ============================================================
# TRANSACTION ID
# ============================================================

TRANSACTION_ID_PATTERN = re.compile(
    r"\b\d{8,15}\b"
)


# ============================================================
# NORMALIZE TEXT
# ============================================================

def normalize_line(line):
    if not line:
        return ""

    line = line.replace("\t", " ")

    line = re.sub(
        r"\s+",
        " ",
        line
    )

    return line.strip()


# ============================================================
# FIND TRANSACTION TYPE
# ============================================================

def find_transaction_type(line):
    lower_line = line.lower()

    for transaction_type in TRANSACTION_TYPES:
        if transaction_type.lower() in lower_line:
            return transaction_type

    return None


# ============================================================
# CLEAN MONEY
# ============================================================

def clean_money(value):
    if not value:
        return ""

    value = value.replace(",", "")
    value = value.replace("(", "")
    value = value.replace(")", "")

    return value.strip()


# ============================================================
# CLEAN TAX
# ============================================================

def clean_tax_value(value):
    """
    Safely clean a Tax value.

    IMPORTANT:
    Tax must NEVER be taken from Amount.

    If a valid Tax value is not available,
    return 0.00.
    """

    if value is None:
        return "0.00"

    value = str(value).strip()

    if not value:
        return "0.00"

    try:
        number = float(
            value
            .replace(",", "")
            .replace("(", "")
            .replace(")", "")
        )
    except (ValueError, TypeError):
        return "0.00"

    return f"{number:.2f}"


# ============================================================
# CLEAN DESCRIPTION
# ============================================================

def clean_description(text):
    if not text:
        return ""

    # Remove money values from description
    text = MONEY_PATTERN.sub(
        "",
        text
    )

    # Remove transaction IDs
    text = TRANSACTION_ID_PATTERN.sub(
        "",
        text
    )

    # Remove unnecessary symbols
    text = re.sub(
        r"[\|\[\]\{\}]",
        " ",
        text
    )

    # Normalize spaces
    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip(
        " -:.,"
    )


# ============================================================
# EXTRACT OCR TEXT FROM PDF
# ============================================================

def pdf_to_text(uploaded_file):

    pdf_bytes = uploaded_file.getvalue()

    document = fitz.open(
        stream=pdf_bytes,
        filetype="pdf"
    )

    pages_text = []

    for page in document:

        # Higher resolution gives OCR better accuracy
        pix = page.get_pixmap(
            matrix=fitz.Matrix(3, 3),
            alpha=False
        )

        image = Image.open(
            io.BytesIO(
                pix.tobytes("png")
            )
        )

        # OCR
        text = pytesseract.image_to_string(
            image,
            config="--psm 6"
        )

        pages_text.append(
            text
        )

    document.close()

    return "\n".join(
        pages_text
    )


# ============================================================
# PARSE TRANSACTION HEADER
# ============================================================

def parse_transaction_header(line):

    date_match = DATE_PATTERN.search(
        line
    )

    if not date_match:
        return None

    transaction_type = find_transaction_type(
        line
    )

    if not transaction_type:
        return None

    # --------------------------------------------------------
    # DATE
    # --------------------------------------------------------

    month = date_match.group(1).title()
    day = date_match.group(2)
    year = date_match.group(3)

    date = (
        f"{day} "
        f"{month} "
        f"{year}"
    )

    # --------------------------------------------------------
    # Remove date from line
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
        flags=re.IGNORECASE
    )

    remaining = remaining.strip(
        " -:"
    )

    # --------------------------------------------------------
    # Find money values
    # --------------------------------------------------------

    money_values = MONEY_PATTERN.findall(
        remaining
    )

    amount = ""
    balance_after = ""

    # --------------------------------------------------------
    # Extract values
    # --------------------------------------------------------

    if len(money_values) >= 3:

        # Transaction amount is normally
        # the parenthesized value

        parenthesized = [
            value
            for value in money_values
            if "(" in value
        ]

        if parenthesized:

            amount = clean_money(
                parenthesized[0]
            )

        else:

            amount = clean_money(
                money_values[-2]
            )

        balance_after = clean_money(
            money_values[-1]
        )

    elif len(money_values) == 2:

        parenthesized = [
            value
            for value in money_values
            if "(" in value
        ]

        if parenthesized:

            amount = clean_money(
                parenthesized[0]
            )

        else:

            amount = clean_money(
                money_values[0]
            )

        balance_after = clean_money(
            money_values[-1]
        )

    elif len(money_values) == 1:

        amount = clean_money(
            money_values[0]
        )

    # --------------------------------------------------------
    # Description
    # --------------------------------------------------------

    description = clean_description(
        remaining
    )

    # --------------------------------------------------------
    # Create transaction
    # --------------------------------------------------------

    return {

        "Date": date,

        "Transaction Type":
            transaction_type,

        "Description":
            description,

        "Amount":
            amount,

        "Balance After":
            balance_after,

        "Transaction ID":
            "",

        # IMPORTANT:
        # Default Tax is ALWAYS zero.
        # We do NOT copy Amount into Tax.
        "Tax":
            "0.00",
    }


# ============================================================
# PARSE EASYPAISA TRANSACTIONS
# ============================================================

def parse_easypaisa_transactions(text):

    lines = text.splitlines()

    records = []

    current = None

    for raw_line in lines:

        line = normalize_line(
            raw_line
        )

        if not line:
            continue

        upper_line = line.upper()

        # ====================================================
        # IGNORE HEADERS
        # ====================================================

        ignored_headers = [

            "STATEMENT OF ACCOUNT",

            "ACCOUNT HOLDER NAME",

            "ACCOUNT NUMBER",

            "IBAN",

            "CURRENCY",

            "DATE ISSUED",

            "THIS IS A SYSTEM GENERATED",

        ]

        if any(
            header in upper_line
            for header in ignored_headers
        ):
            continue

        if line.lower().startswith(
            "from:"
        ):
            continue

        # ====================================================
        # CHECK IF NEW TRANSACTION
        # ====================================================

        transaction = parse_transaction_header(
            line
        )

        if transaction is not None:

            # Save previous transaction
            if current is not None:

                records.append(
                    current
                )

            current = transaction

            continue

        # ====================================================
        # TRANSACTION ID
        # ====================================================

        if current is not None:

            transaction_ids = (
                TRANSACTION_ID_PATTERN.findall(
                    line
                )
            )

            if transaction_ids:

                current[
                    "Transaction ID"
                ] = transaction_ids[0]

                continue

        # ====================================================
        # DESCRIPTION CONTINUATION
        # ====================================================

        if current is not None:

            # Ignore lines containing only numbers

            if re.fullmatch(
                r"[\d,.\-\(\) ]+",
                line
            ):
                continue

            # Don't append unrelated header lines

            if any(
                header in upper_line
                for header in ignored_headers
            ):
                continue

            # Add continuation text

            extra_text = clean_description(
                line
            )

            if extra_text:

                if current["Description"]:

                    current["Description"] = (
                        current["Description"]
                        + " "
                        + extra_text
                    )

                else:

                    current["Description"] = (
                        extra_text
                    )

    # ========================================================
    # SAVE LAST TRANSACTION
    # ========================================================

    if current is not None:

        records.append(
            current
        )

    # ========================================================
    # NO TRANSACTIONS
    # ========================================================

    if not records:

        return pd.DataFrame(
            columns=[
                "Date",
                "Transaction Type",
                "Description",
                "Amount",
                "Balance After",
                "Transaction ID",
                "Tax",
            ]
        )

    # ========================================================
    # CREATE DATAFRAME
    # ========================================================

    df = pd.DataFrame(
        records
    )

    # ========================================================
    # FORCE COLUMN ORDER
    # ========================================================

    columns = [

        "Date",

        "Transaction Type",

        "Description",

        "Amount",

        "Balance After",

        "Transaction ID",

        "Tax",

    ]

    for column in columns:

        if column not in df.columns:

            if column == "Tax":

                df[column] = "0.00"

            else:

                df[column] = ""

    df = df[
        columns
    ]

    # ========================================================
    # CLEAN COLUMNS
    # ========================================================

    for column in columns:

        df[column] = (
            df[column]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    # ========================================================
    # TAX SAFETY
    # ========================================================
    #
    # VERY IMPORTANT:
    #
    # Amount must NEVER become Tax.
    #
    # If Tax is empty, invalid, NaN, None,
    # or unavailable, use 0.00.
    #
    # ========================================================

    df["Tax"] = (
        df["Tax"]
        .fillna("0.00")
        .astype(str)
        .str.strip()
    )

    df.loc[
        df["Tax"].isin(
            [
                "",
                "nan",
                "NaN",
                "None",
                "null",
                "NULL",
            ]
        ),
        "Tax"
    ] = "0.00"

    # --------------------------------------------------------
    # Normalize Tax number format
    # --------------------------------------------------------

    def normalize_tax_cell(value):

        try:

            number = float(
                str(value)
                .replace(",", "")
                .replace("(", "")
                .replace(")", "")
                .strip()
            )

            return f"{number:.2f}"

        except (
            ValueError,
            TypeError
        ):

            return "0.00"

    df["Tax"] = df["Tax"].apply(
        normalize_tax_cell
    )

    # ========================================================
    # REMOVE COMPLETELY EMPTY ROWS
    # ========================================================

    df = df[
        ~(
            (df["Date"] == "")
            &
            (df["Description"] == "")
            &
            (df["Amount"] == "")
        )
    ]

    # ========================================================
    # RESET INDEX
    # ========================================================

    df = df.reset_index(
        drop=True
    )

    return df


# ============================================================
# MAIN EXTRACTION FUNCTION
# ============================================================

def extract_transactions(
    uploaded_file
):

    # OCR
    text = pdf_to_text(
        uploaded_file
    )

    if not text.strip():

        return pd.DataFrame()

    # Parse transactions
    df = parse_easypaisa_transactions(
        text
    )

    return df
