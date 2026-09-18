import streamlit as st
import pandas as pd
from nl_to_sql import (
    get_schema,
    question_to_sql,
    run_query,
    explain_result,
    UnsafeSQLError,
    DB_FILE,
)

st.set_page_config(page_title="NL-to-SQL Analytics Agent", page_icon="🗂️", layout="centered")

# ---------- Light custom styling (on top of .streamlit/config.toml theme colors) ----------
st.markdown(
    """
    <style>
    .stApp { font-family: 'Inter', -apple-system, sans-serif; }

    h1 { font-weight: 800; letter-spacing: -0.01em; }

    /* Rounded, bordered containers for expanders and code blocks */
    div[data-testid="stExpander"] {
        border-radius: 12px;
        border: 1px solid rgba(38,36,31,0.15);
        overflow: hidden;
    }

    /* Style the primary "Ask" button as a solid pill */
    button[kind="primary"] {
        border-radius: 999px;
        font-weight: 600;
        padding: 0.5rem 1.6rem;
    }

    /* Clean up the dataframe container */
    div[data-testid="stDataFrame"] {
        border-radius: 10px;
        overflow: hidden;
        border: 1px solid rgba(38,36,31,0.12);
    }

    /* Answer callout box */
    .answer-box {
        background: #E7EADC;
        border-left: 4px solid #8C3B5E;
        border-radius: 8px;
        padding: 1rem 1.25rem;
        font-size: 1.02rem;
        line-height: 1.55;
    }

    .footer-note {
        font-size: 0.82rem;
        color: rgba(38,36,31,0.6);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------- Header ----------
st.title("🗂️ Natural Language to SQL Analytics Agent")
st.markdown(
    "Ask a question about the **Chinook music store database** in plain English — "
    "an LLM writes the SQL, runs it, and explains the result."
)

st.divider()

# ---------- Schema (collapsed by default, cleanly formatted) ----------
@st.cache_data
def load_schema():
    return get_schema(DB_FILE)

schema = load_schema()

with st.expander("📚 View database schema"):
    for line in schema.strip().split("\n"):
        if ":" in line:
            table_part, cols_part = line.split(":", 1)
            st.markdown(f"**{table_part.strip()}**")
            st.caption(cols_part.strip())

# ---------- Question input ----------
question = st.text_input(
    "Ask a question",
    placeholder="e.g. Which 5 artists have the most tracks?",
)

col1, col2 = st.columns([1, 5])
with col1:
    ask_clicked = st.button("Ask", type="primary")

if ask_clicked and question:
    with st.spinner("Writing SQL..."):
        sql = question_to_sql(question, schema)

    if sql.upper().startswith("REFUSED"):
        reason = sql.split(":", 1)[1].strip() if ":" in sql else sql
        st.warning(f"⚠️ **Request declined:** {reason}")
    else:
        with st.expander("🔍 Generated SQL", expanded=False):
            st.code(sql, language="sql")

        try:
            columns, rows = run_query(sql, DB_FILE)

            # Build a clean DataFrame: reset index, format numeric columns nicely
            df = pd.DataFrame(rows, columns=columns)
            for c in df.columns:
                if pd.api.types.is_float_dtype(df[c]):
                    df[c] = df[c].round(2)

            st.subheader("Result")
            if df.empty:
                st.info("No rows returned.")
            else:
                st.dataframe(
                    df,
                    use_container_width=True,
                    hide_index=True,
                )

            with st.spinner("Summarizing..."):
                answer = explain_result(question, columns, rows)

            st.subheader("Answer")
            st.markdown(f'<div class="answer-box">{answer}</div>', unsafe_allow_html=True)

        except UnsafeSQLError as e:
            st.error(f"🚫 Query blocked by safety guardrail: {e}")

elif ask_clicked and not question:
    st.info("Type a question above first.")

st.divider()
st.markdown(
    '<p class="footer-note">Built by Sahithi Kadudula — SQL/Python pipelines + Claude API. '
    "Guardrails: read-only SQL validation, forbidden-keyword blocklist, row limits.</p>",
    unsafe_allow_html=True,
)