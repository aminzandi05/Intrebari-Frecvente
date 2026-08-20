"""
Strat de acces la baza de date (Postgres, găzduit ex. pe Supabase).
Stochează documentele normative și fragmentele lor de text, cu căutare
full-text în limba română.
"""

import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

_engine = None

def get_engine():
    global _engine
    if _engine is None:
        db_url = st.secrets["DATABASE_URL"]
        # NullPool: Streamlit Cloud repornește frecvent procesele; evităm
        # conexiuni "moarte" păstrate în pool între rerun-uri.
        _engine = create_engine(db_url, poolclass=NullPool, pool_pre_ping=True)
    return _engine

def init_db():
    """Creează tabelele dacă nu există deja. Se apelează la pornirea aplicației."""
    with get_engine().begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS documents (
                id SERIAL PRIMARY KEY,
                filename TEXT NOT NULL,
                uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS chunks (
                id SERIAL PRIMARY KEY,
                document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                tsv tsvector GENERATED ALWAYS AS (to_tsvector('romanian', content)) STORED
            );
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING GIN (tsv);
        """))

def add_document(filename: str) -> int:
    with get_engine().begin() as conn:
        result = conn.execute(
            text("INSERT INTO documents (filename) VALUES (:f) RETURNING id"),
            {"f": filename},
        )
        return result.scalar_one()

def add_chunks(document_id: int, chunks: list[str]):
    with get_engine().begin() as conn:
        for idx, content in enumerate(chunks):
            conn.execute(
                text("""
                    INSERT INTO chunks (document_id, chunk_index, content)
                    VALUES (:doc_id, :idx, :content)
                """),
                {"doc_id": document_id, "idx": idx, "content": content},
            )

def list_documents():
    with get_engine().begin() as conn:
        rows = conn.execute(text("""
            SELECT d.id, d.filename, d.uploaded_at, COUNT(c.id) AS n_chunks
            FROM documents d
            LEFT JOIN chunks c ON c.document_id = d.id
            GROUP BY d.id
            ORDER BY d.uploaded_at DESC
        """)).mappings().all()
        return list(rows)

def delete_document(document_id: int):
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM documents WHERE id = :id"), {"id": document_id})

def search_chunks(query: str, limit: int = 6):
    """Caută fragmentele cele mai relevante pentru o întrebare, folosind
    căutarea full-text nativă din Postgres (configurație 'romanian').

    Întâi încearcă o căutare strictă (toate cuvintele cheie trebuie să
    apară în fragment). Întrebările formulate natural (ex: "ce înseamnă
    X?", "care este rolul Y?") includ însă cuvinte de legătură care nu
    apar niciodată în textul normativelor, așa că o căutare strictă ar
    întoarce mereu 0 rezultate pentru ele. Dacă se întâmplă asta,
    reîncercăm cu o căutare mai permisivă (e suficient să apară oricare
    dintre cuvintele cheie), păstrând ordonarea după relevanță.
    """
    strict_sql = text("""
        SELECT
            c.content,
            d.filename,
            c.chunk_index,
            ts_rank(c.tsv, websearch_to_tsquery('romanian', :q)) AS rank
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.tsv @@ websearch_to_tsquery('romanian', :q)
        ORDER BY rank DESC
        LIMIT :limit
    """)
    loose_sql = text("""
        SELECT
            c.content,
            d.filename,
            c.chunk_index,
            ts_rank(c.tsv, (regexp_replace(
                websearch_to_tsquery('romanian', :q)::text, ' & ', ' | ', 'g'
            ))::tsquery) AS rank
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.tsv @@ (regexp_replace(
            websearch_to_tsquery('romanian', :q)::text, ' & ', ' | ', 'g'
        ))::tsquery
        ORDER BY rank DESC
        LIMIT :limit
    """)
    with get_engine().begin() as conn:
        rows = conn.execute(strict_sql, {"q": query, "limit": limit}).mappings().all()
        if not rows:
            rows = conn.execute(loose_sql, {"q": query, "limit": limit}).mappings().all()
        return list(rows)
