from io import BytesIO
import pandas as pd


def export_csv(df):
    return df.to_csv(index=False).encode("utf-8-sig")


def export_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Bank Statement")
        ws = writer.book["Bank Statement"]
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for column_cells in ws.columns:
            letter = column_cells[0].column_letter
            max_len = max(len(str(c.value or "")) for c in column_cells)
            ws.column_dimensions[letter].width = min(max(max_len + 2, 12), 45)
    output.seek(0)
    return output.getvalue()
