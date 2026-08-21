import streamlit as st
from parser import extract_transactions
from cleaner import clean_dataframe
from exporter import export_csv, export_excel

st.set_page_config(page_title="BankFlow", page_icon="🏦", layout="wide")
st.title("🏦 BankFlow")
st.caption("EasyPaisa Bank Statement → Excel / CSV")

uploaded = st.file_uploader("Upload your EasyPaisa statement PDF", type=["pdf"])

if uploaded:
    st.success(f"Uploaded: {uploaded.name}")
    if st.button("🚀 Convert Statement", type="primary", use_container_width=True):
        with st.spinner("Reading PDF and extracting transactions..."):
            try:
                df = clean_dataframe(extract_transactions(uploaded))
            except Exception as e:
                st.error("PDF processing failed.")
                st.exception(e)
                st.stop()

        if df.empty:
            st.error("No transactions were found.")
            st.stop()

        st.success(f"Found {len(df)} transactions")
        st.subheader("Preview")
        st.dataframe(df, use_container_width=True, height=500)

        st.subheader("Download")
        c1, c2 = st.columns(2)
        with c1:
            st.download_button("⬇️ Download CSV", export_csv(df), "easypaisa_statement.csv", "text/csv", use_container_width=True)
        with c2:
            st.download_button("📗 Download Excel", export_excel(df), "easypaisa_statement.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
