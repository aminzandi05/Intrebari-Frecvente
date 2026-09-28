import streamlit as st
import db
import ingest
import qa

st.set_page_config(page_title="Întrebări despre normative", page_icon="📘", layout="centered")


def check_password() -> bool:
    """Ecran simplu de parolă comună, ca aplicația să nu fie deschisă oricui
    are linkul. Parola se setează în secrets ca APP_PASSWORD."""
    if "APP_PASSWORD" not in st.secrets:
        return True  # dacă nu s-a setat nicio parolă, aplicația e liberă

    if st.session_state.get("authed"):
        return True

    st.title("📘 Bază de date normative")
    pwd = st.text_input("Parolă acces", type="password")
    if st.button("Intră"):
        if pwd == st.secrets["APP_PASSWORD"]:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Parolă greșită.")
    return False


def page_admin():
    st.subheader("📤 Administrare documente")

    uploaded_files = st.file_uploader(
        "Încarcă normative (PDF, DOCX sau TXT)",
        type=["pdf", "docx", "txt"],
        accept_multiple_files=True,
    )

    if uploaded_files and st.button("Procesează și adaugă în baza de date"):
        progress = st.progress(0, text="Se procesează...")
        for i, f in enumerate(uploaded_files):
            try:
                text = ingest.extract_text(f)
                chunks = ingest.chunk_text(text)
                if not chunks:
                    st.warning(f"Nu s-a putut extrage text din {f.name} (posibil scanat, fără text selectabil).")
                    continue
                doc_id = db.add_document(f.name)
                db.add_chunks(doc_id, chunks)
                st.success(f"{f.name}: {len(chunks)} fragmente adăugate.")
            except Exception as e:
                st.error(f"Eroare la {f.name}: {e}")
            progress.progress((i + 1) / len(uploaded_files))

    st.divider()
    st.markdown("**Documente existente în baza de date:**")
    docs = db.list_documents()
    if not docs:
        st.info("Nu există încă documente încărcate.")
    for d in docs:
        col1, col2 = st.columns([5, 1])
        col1.write(f"📄 {d['filename']} — {d['n_chunks']} fragmente — {d['uploaded_at'].strftime('%d.%m.%Y %H:%M')}")
        if col2.button("Șterge", key=f"del_{d['id']}"):
            db.delete_document(d["id"])
            st.rerun()


def page_ask():
    st.subheader("❓ Pune o întrebare")
    question = st.text_area("Întrebarea ta despre normative", height=100)

    if st.button("Răspunde", type="primary") and question.strip():
        with st.spinner("Caut în normative (pot fi mai multe căutări) și formulez răspunsul..."):
            try:
                # Claude caută singur, de mai multe ori și cu formulări diferite,
                # până găsește fragmentele relevante, apoi răspunde.
                answer, chunks, terms = qa.answer_with_search(question, db.search_chunks)
            except Exception:
                # Rezervă: o singură căutare cu termenii traduși în limbajul normativelor.
                terms = qa.expand_query(question)
                search_q = qa.build_search_query(terms + [question]) if terms else question
                chunks = db.search_chunks(search_q, limit=8)
                if not chunks and terms:
                    chunks = db.search_chunks(question, limit=6)
                answer = qa.answer_question(question, chunks)

        st.markdown("### Răspuns")
        st.write(answer)

        if terms:
            st.caption("Termeni căutați: " + ", ".join(terms))

        if chunks:
            with st.expander("Vezi fragmentele sursă folosite"):
                for c in chunks:
                    st.markdown(f"**{c['filename']}** (fragment #{c['chunk_index']})")
                    st.text(c["content"][:800])
                    st.divider()


def main():
    if not check_password():
        st.stop()

    db.init_db()

    st.title("📘 Bază de date normative")
    st.caption("Încarcă documente normative și pune întrebări pe baza lor.")

    tab1, tab2 = st.tabs(["❓ Întrebări", "📤 Administrare"])
    with tab1:
        page_ask()
    with tab2:
        page_admin()


if __name__ == "__main__":
    main()
