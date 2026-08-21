import pandas as pd


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    for col in df.columns:
        df[col] = df[col].fillna("").astype(str).str.strip()
    # Remove completely empty rows only.
    mask = df.astype(str).apply(lambda r: r.str.strip().ne("").any(), axis=1)
    df = df.loc[mask]
    return df.drop_duplicates().reset_index(drop=True)
