"""Streamlit app: browse, search and ask questions about Indiana Supreme Court opinions.

Deployed as a Databricks App, so the workspace's single sign-on handles login: only people
with access to the app can open it, and the app reads their identity from request headers.
Run locally with `uv run streamlit run app/app.py` (uses your Databricks CLI login).
"""

from __future__ import annotations

import pandas as pd
import rag
import streamlit as st
from backend import CHAT_MODEL, Backend
from display import author_names, cite_links, escape_md, highlight, html_url, tidy_snippet

st.set_page_config(page_title="Indiana Opinions Explorer", page_icon="⚖️", layout="wide")

EXAMPLES = [
    "Who were the victims in the murder cases, and when were they killed?",
    "Which attorneys were disciplined, and what had they done?",
    "What happened in 1998 according to these opinions?",
]


# ---- Data (cached) ------------------------------------------------------------------------
@st.cache_resource
def backend() -> Backend:
    return Backend()


@st.cache_data(ttl=3600, show_spinner="Loading cases…")
def documents() -> pd.DataFrame:
    docs = backend().documents()
    docs["authors"] = docs.opinion_authors.apply(author_names)
    return docs


@st.cache_data(ttl=3600, show_spinner=False)
def case(doc_id: str) -> tuple[dict | None, pd.DataFrame, pd.DataFrame]:
    b = backend()
    return b.document(doc_id), b.entities(doc_id), b.events([doc_id])


@st.cache_data(ttl=600, show_spinner="Searching…")
def search(mode: str, query: str):
    b = backend()
    if mode == "keyword":
        return b.keyword_search(query)
    if mode == "people":
        return b.people_search(query)
    return b.semantic_search(query, k=30)


def current_user() -> str | None:
    headers = st.context.headers
    return headers.get("X-Forwarded-Email") or headers.get("X-Forwarded-Preferred-Username")


@st.cache_data(ttl=3600, show_spinner=False)
def case_labels() -> dict[str, str]:
    docs = documents()
    return {
        d: f"{n} ({when})"
        for d, n, when in zip(docs.doc_id, docs.case_name_short, docs.decision_date, strict=True)
    }


def set_scope(doc_id: str | None) -> None:
    """Button callback: limit the Ask tab to one case. The dialog reruns on its own, so the
    request is applied just before the Ask tab's selectbox is next drawn."""
    st.session_state.scope_request = doc_id


# ---- Case detail ---------------------------------------------------------------------------
@st.dialog("Case", width="large", on_dismiss="rerun")
def case_dialog(doc_id: str) -> None:
    doc, people, events = case(doc_id)
    if doc is None:
        st.error("Case not found.")
        return
    st.subheader(doc["case_name_short"])
    st.caption(
        f"{doc['citation']} · decided {doc['decision_date']} · docket {doc['docket_number']}"
    )
    st.markdown(escape_md(doc["case_name"]))
    c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
    c1.metric("People", len(people))
    c2.metric("Events", len(events))
    c3.metric("Length", f"{doc['char_count'] // 1000}k chars")
    with c4:
        st.link_button("Read on case.law", html_url(doc["source_url"]))
        if st.button("Ask about this case", key=f"ask-{doc_id}", on_click=set_scope, args=[doc_id]):
            st.success("Done. Questions in the **Ask** tab now cover only this case.")

    timeline, cast, text = st.tabs(["Timeline", "People", "Opinion text"])
    with timeline:
        if events.empty:
            st.info("No events were extracted from this case.")
        else:
            st.caption("Extracted by the LLM. ✓ means the quote appears word for word.")
            show = pd.DataFrame(
                {
                    "When": events.event_date_iso.fillna(events.date_text).fillna("—"),
                    "Who": events.actor,
                    "Did": events.action,
                    "To / what": events.target,
                    "✓": events.quote_verified,
                    "Quote": events.evidence_quote,
                }
            )
            st.dataframe(show, hide_index=True)
    with cast:
        st.dataframe(
            people.rename(
                columns={
                    "name": "Name",
                    "entity_type": "Type",
                    "role": "Role",
                    "description": "Description",
                    "mention_count": "Mentions",
                }
            ),
            hide_index=True,
        )
    with text, st.container(height=500):
        st.markdown(escape_md(doc["full_text"]).replace("\n", "\n\n"))


def open_once(table: str, doc_id: str) -> bool:
    """Open the case selected in a table, once. Selections survive reruns, so without this the
    dialog would pop up again after every click elsewhere. Returns True if it opened."""
    key = f"opened_{table}"
    if st.session_state.get(key) == doc_id:
        return False
    st.session_state[key] = doc_id
    case_dialog(doc_id)
    return True


# ---- Sidebar -------------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### ⚖️ Indiana Opinions Explorer")
    user = current_user()
    st.caption(f"Signed in as **{user}**" if user else "Running locally (Databricks CLI login)")
    st.markdown(
        "459 Indiana Supreme Court opinions decided 2013–2019, from Harvard's "
        "[Caselaw Access Project](https://case.law) (public domain)."
    )
    st.markdown(
        f"People, dates and actions were extracted with `{CHAT_MODEL}`. Answers use hybrid "
        "Vector Search over the opinion text plus those extracted events."
    )
    st.caption("A demo, not legal advice.")

browse_tab, search_tab, ask_tab = st.tabs(["📚 Browse", "🔎 Search", "💬 Ask"])

# ---- Browse --------------------------------------------------------------------------------
with browse_tab:
    docs = documents()
    years = pd.to_datetime(docs.decision_date).dt.year
    authors = sorted({a for row in docs.authors for a in row})
    f1, f2, f3, f4 = st.columns([3, 2, 2, 2])
    name = f1.text_input("Case name or docket", placeholder="e.g. State or 49S00")
    year_range = f2.slider("Decided", int(years.min()), int(years.max()), (2013, 2019))
    kinds = f3.multiselect(
        "Has opinion type", ["dissent", "concurrence", "concurring-in-part-and-dissenting-in-part"]
    )
    by = f4.multiselect("Opinion author", authors)

    mask = years.between(*year_range)
    if name:
        mask &= docs.case_name.str.contains(
            name, case=False, regex=False
        ) | docs.docket_number.str.contains(name, case=False, regex=False)
    if kinds:
        mask &= docs.opinion_types.apply(lambda t: any(k in (t or []) for k in kinds))
    if by:
        mask &= docs.authors.apply(lambda a: any(x in a for x in by))
    shown = docs[mask].reset_index(drop=True)

    st.caption(f"Showing {len(shown)} of {len(docs)} cases. Select a row to open the case.")
    table = pd.DataFrame(
        {
            "Decided": shown.decision_date,
            "Case": shown.case_name_short,
            "Citation": shown.citation,
            "Opinions": shown.opinion_types.apply(lambda t: ", ".join(t or [])),
            "Authors": shown.authors.apply(", ".join),
            "People": shown.people,
            "Events": shown.events,
        }
    )
    picked = st.dataframe(
        table,
        hide_index=True,
        height=560,
        on_select="rerun",
        selection_mode="single-row",
        key="browse_table",
    )
    rows = picked.selection.rows
    if rows:
        doc_id = shown.doc_id[rows[0]]
        if not open_once("browse", doc_id) and st.button(f"Open {shown.case_name_short[rows[0]]}"):
            case_dialog(doc_id)

# ---- Search --------------------------------------------------------------------------------
MODES = {
    "Meaning": ("semantic", "e.g. police searched a car without a warrant"),
    "Exact words": ("keyword", "e.g. ineffective assistance"),
    "People": ("people", "e.g. Rush, or Hill"),
}

with search_tab:
    s1, s2 = st.columns([1, 3])
    mode_name = s1.radio("Search by", list(MODES), horizontal=False)
    mode, hint = MODES[mode_name]
    query = s2.text_input("Search", placeholder=hint, key=f"q-{mode}").strip()
    if mode == "semantic":
        s2.caption("Finds passages with a similar meaning, plus keyword matches (hybrid search).")
    elif mode == "people":
        s2.caption("Searches the people and organizations the LLM extracted from each case.")

    if query:
        try:
            results = search(mode, query)
        except Exception as e:  # show the error rather than a stack trace
            st.error(f"Search failed: {e}")
            results = None

        if mode == "semantic" and results is not None:
            best: dict[str, dict] = {}
            for hit in results:  # best passage per case, in rank order
                best.setdefault(hit["doc_id"], hit)
            st.caption(f"{len(best)} cases")
            for doc_id, hit in list(best.items())[:12]:
                with st.container(border=True):
                    a, b = st.columns([6, 1])
                    a.markdown(f"**{escape_md(hit['case_name_short'])}** · {hit['decision_date']}")
                    a.markdown(escape_md(tidy_snippet(rag.strip_chunk_header(hit["text"])[:600])))
                    if b.button("Open", key=f"sem-{doc_id}"):
                        case_dialog(doc_id)

        elif mode == "keyword" and results is not None:
            st.caption(f"{len(results)} cases contain “{query}”" if len(results) else "No matches.")
            for r in results.itertuples():
                with st.container(border=True):
                    a, b = st.columns([6, 1])
                    a.markdown(
                        f"**{escape_md(r.case_name_short)}** · {r.decision_date} · "
                        f"{r.matches} match{'es' if r.matches != 1 else ''}"
                    )
                    a.markdown(highlight(tidy_snippet(r.snippet), query))
                    if b.button("Open", key=f"kw-{r.doc_id}"):
                        case_dialog(r.doc_id)

        elif mode == "people" and results is not None:
            if results.empty:
                st.caption("No matches.")
            else:
                count = f"First {len(results)}" if len(results) == 100 else str(len(results))
                st.caption(f"{count} mentions. Select a row to open the case.")
                picked = st.dataframe(
                    results[
                        ["name", "role", "case_name_short", "decision_date", "description"]
                    ].rename(
                        columns={
                            "name": "Name",
                            "role": "Role",
                            "case_name_short": "Case",
                            "decision_date": "Decided",
                            "description": "Description",
                        }
                    ),
                    hide_index=True,
                    on_select="rerun",
                    selection_mode="single-row",
                    key="people_table",
                )
                if picked.selection.rows:
                    open_once("people", results.doc_id[picked.selection.rows[0]])


# ---- Ask -----------------------------------------------------------------------------------
def gather_sources(question: str, scope: str | None, history: list[dict]):
    b = backend()
    chunks = b.semantic_search(rag.retrieval_query(question, history), k=12, doc_id=scope)
    doc_ids = list(dict.fromkeys(c["doc_id"] for c in chunks))[: rag.MAX_SOURCES]
    events = b.events(doc_ids or ([scope] if scope else []), rag.EVENTS_PER_SOURCE)
    years = [] if scope else rag.extract_years(question)
    year_events = b.events_in_years(years) if years else pd.DataFrame()
    return rag.build_sources(chunks, events.to_dict("records"), year_events.to_dict("records"))


def show_sources(sources: list[rag.Source], answer: str, key: str) -> None:
    cited = rag.cited_labels(answer)
    ordered = sorted(sources, key=lambda s: cited.index(s.label) if s.label in cited else 99)
    with st.expander(f"Sources: {len(cited)} cited, {len(sources)} retrieved"):
        for s in ordered:
            a, b = st.columns([6, 1])
            mark = "" if s.label in cited else " · not cited"
            a.markdown(f"**[{s.label}] {escape_md(s.case_name)}** · {s.decision_date}{mark}")
            a.caption(f"{len(s.passages)} passages, {len(s.events)} extracted events")
            if b.button("Open", key=f"src-{key}-{s.label}"):
                case_dialog(s.doc_id)


with ask_tab:
    st.session_state.setdefault("messages", [])
    options = [None, *documents().sort_values("case_name_short").doc_id]
    if "scope_request" in st.session_state:
        st.session_state.ask_scope = st.session_state.pop("scope_request")
    scope = st.selectbox(
        "Ask about",
        options,
        key="ask_scope",
        format_func=lambda d: "All 459 cases" if d is None else case_labels()[d],
    )

    messages = st.session_state.messages
    if not messages:
        st.caption("Try one of these:")
        for i, ex in enumerate(EXAMPLES):
            if st.button(ex, key=f"ex-{i}"):
                st.session_state.pending = ex
    for i, m in enumerate(messages):
        with st.chat_message(m["role"]):
            if m["role"] == "assistant":
                names = {s.label: s.case_name for s in m["sources"]}
                st.markdown(cite_links(m["content"], names))
                show_sources(m["sources"], m["content"], key=str(i))
            else:
                st.markdown(escape_md(m["content"]))
    if messages and st.button("Clear conversation"):
        st.session_state.messages = []
        st.rerun()

    question = st.chat_input("Ask about people, dates and actions in these cases")
    question = question or st.session_state.pop("pending", None)
    if question:
        history = [{"role": m["role"], "content": m["content"]} for m in messages]
        with st.chat_message("user"):
            st.markdown(escape_md(question))
        with st.chat_message("assistant"):
            try:
                with st.spinner("Finding relevant passages and events…"):
                    sources = gather_sources(question, scope, history)
                answer = st.write_stream(
                    backend().chat_stream(rag.build_messages(question, sources, history))
                )
            except Exception as e:
                st.error(f"Sorry, that failed: {e}")
            else:
                messages.append({"role": "user", "content": question})
                messages.append({"role": "assistant", "content": answer, "sources": sources})
                st.rerun()
