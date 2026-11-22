"""Streamlit app: browse, search and ask questions about Indiana Supreme Court opinions.

Placeholder for Phase 5. When deployed as a Databricks App, the workspace's sign-in handles login.
"""

import streamlit as st

st.set_page_config(page_title="Legal Data Demo", page_icon="⚖️", layout="wide")
st.title("⚖️ Legal Data Demo")

browse, search, ask = st.tabs(["Browse", "Search", "Ask"])
with browse:
    st.info("Document list goes here (Phase 5).")
with search:
    st.info("Keyword and semantic search go here (Phase 5).")
with ask:
    st.info("LLM Q&A about people, dates and actions goes here (Phase 5).")
