"""
Interogare Claude pentru a răspunde la întrebări STRICT pe baza
fragmentelor din normativele încărcate.
"""

import streamlit as st
import anthropic

_client = None


def get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
    return _client


SYSTEM_PROMPT = """Ești un asistent care răspunde la întrebări despre normative \
tehnice, folosind EXCLUSIV fragmentele de text furnizate mai jos, extrase din \
documentele oficiale încărcate de utilizator.

Reguli stricte:
- Răspunde doar pe baza fragmentelor date. Nu inventa și nu completa din \
cunoștințe generale.
- Dacă răspunsul nu se găsește în fragmente, spune clar că informația nu a \
fost găsită în documentele încărcate și nu specula.
- La final, indică din ce document (nume fișier) provine informația folosită.
- Fii precis și concis; citează articole/paragrafe/numere exacte când apar \
în text."""


def answer_question(question: str, chunks: list[dict]) -> str:
    if not chunks:
        return (
            "Nu am găsit niciun fragment relevant în documentele încărcate "
            "pentru această întrebare. Verifică dacă documentul potrivit a "
            "fost încărcat, sau reformulează întrebarea."
        )

    context_blocks = []
    for c in chunks:
        context_blocks.append(
            f"--- Sursă: {c['filename']} (fragment #{c['chunk_index']}) ---\n{c['content']}"
        )
    context = "\n\n".join(context_blocks)

    user_message = f"""Fragmente relevante din normative:

{context}

Întrebare: {question}"""

    client = get_client()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text
