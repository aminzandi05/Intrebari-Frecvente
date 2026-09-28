"""
Interogare Claude pentru a răspunde la întrebări STRICT pe baza
fragmentelor din normativele încărcate.
"""

import re

import streamlit as st
import anthropic

_client = None

MODEL = "claude-sonnet-5"


def get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
    return _client


# ---------------------------------------------------------------------------
# 1) Traducerea întrebării în termenii folosiți în normative
# ---------------------------------------------------------------------------

EXPAND_PROMPT = """Ești expert în normativele tehnice românești pentru instalații \
în construcții (P118/1-3, I7, NP 061, I9, I5, I13, NP 086, SR EN 54, SR EN 62305 etc.).

Utilizatorul pune o întrebare folosind limbaj de șantier sau colocvial. Sarcina ta \
este să generezi termenii de căutare pe care i-ar folosi TEXTUL NORMATIVELOR pentru \
același lucru, ca să găsim fragmentele relevante printr-o căutare full-text.

Exemple: "buton de incendiu" -> "declanșator manual de alarmare"; "senzor de fum" -> \
"detector de fum", "detector optic"; "centrală de incendiu" -> "echipament de control \
și semnalizare"; "sirenă" -> "dispozitiv de alarmare acustică"; "paratrăsnet" -> \
"instalație de protecție împotriva trăsnetului", "dispozitiv de captare".

Reguli:
- Răspunde DOAR cu termenii, câte unul pe linie, fără numerotare și fără explicații.
- Între 4 și 10 termeni, fiecare de 1-3 cuvinte (fără cuvinte de legătură inutile).
- Include denumirea oficială din normativ, sinonime tehnice uzuale și termenii-cheie \
din întrebarea originală.
- Scrie cu diacritice românești corecte."""


_DIAC_CEDILLA = str.maketrans({"ș": "ş", "Ș": "Ş", "ț": "ţ", "Ț": "Ţ"})
_DIAC_STRIP = str.maketrans({
    "ă": "a", "â": "a", "î": "i", "ș": "s", "ş": "s", "ț": "t", "ţ": "t",
    "Ă": "A", "Â": "A", "Î": "I", "Ș": "S", "Ş": "S", "Ț": "T", "Ţ": "T",
})


def _clean_term(term: str) -> str:
    # Scoatem caracterele cu sens special în websearch_to_tsquery
    # (ghilimele, minus = excludere) și cuvântul "or".
    term = re.sub(r'["\'\-–—()*:;,.?!/\\]', " ", term)
    words = [w for w in term.split() if w.lower() != "or"]
    return " ".join(words).strip()


def build_search_query(terms: list[str]) -> str:
    """Construiește interogarea pentru Postgres: termenii se leagă cu OR,
    iar cuvintele din același termen trebuie să apară toate (AND).
    Pentru fiecare termen adăugăm și variantele de diacritice (ș/ş, fără
    diacritice), fiindcă multe normative vechi folosesc ş/ţ cu sedilă."""
    variants = []
    for t in terms:
        t = _clean_term(t)
        if not t:
            continue
        for v in (t, t.translate(_DIAC_CEDILLA), t.translate(_DIAC_STRIP)):
            if v.lower() not in (x.lower() for x in variants):
                variants.append(v)
    return " or ".join(variants)


def expand_query(question: str) -> list[str]:
    """Cere lui Claude termenii din normative corespunzători întrebării.
    Dacă apelul eșuează, întoarce o listă goală (se caută doar întrebarea)."""
    try:
        response = get_client().messages.create(
            model=MODEL,
            max_tokens=300,
            system=EXPAND_PROMPT,
            messages=[{"role": "user", "content": question}],
        )
        lines = response.content[0].text.splitlines()
        terms = [re.sub(r"^[\s\-*•\d.)]+", "", l).strip() for l in lines]
        return [t for t in terms if t][:10]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# 2) Răspunsul pe baza fragmentelor găsite
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Ești un asistent care răspunde la întrebări despre normative \
tehnice, folosind EXCLUSIV fragmentele de text furnizate mai jos, extrase din \
documentele oficiale încărcate de utilizator.

Reguli stricte:
- Răspunde doar pe baza fragmentelor date. Nu inventa și nu completa din \
cunoștințe generale.
- Utilizatorul poate folosi denumiri colocviale sau de șantier (ex: "buton de \
incendiu" în loc de "declanșator manual de alarmare"). Tratează-le ca echivalente \
cu termenii oficiali din fragmente și precizează în răspuns denumirea oficială \
folosită în normativ.
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
        model=MODEL,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text
