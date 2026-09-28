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


# ---------------------------------------------------------------------------
# 3) Căutare iterativă: Claude caută singur, de mai multe ori, cu formulări
#    diferite, până găsește fragmentele relevante, apoi răspunde.
# ---------------------------------------------------------------------------

AGENT_PROMPT = """Ești un asistent expert în normativele tehnice românești pentru \
instalații în construcții. Răspunzi la întrebări folosind EXCLUSIV fragmentele din \
documentele încărcate de utilizator, pe care le găsești cu unealta \
`cauta_in_normative`.

Cum lucrezi:
1. Înțelege ce vrea utilizatorul, chiar dacă folosește limbaj colocvial, de șantier, \
abrevieri, greșeli de scriere sau o descriere indirectă ("chestia aia roșie de pe \
perete pe care o apeși la foc" = declanșator manual de alarmare).
2. Caută folosind TERMINOLOGIA DIN NORMATIVE: denumirea oficială, sinonime tehnice, \
noțiuni înrudite, numele sistemului din care face parte, articolele/capitolele \
probabile. Poți da mai mulți termeni într-o singură căutare.
3. Dacă rezultatele nu răspund la întrebare, caută din nou cu alte formulări \
(mai generale, mai specifice sau din alt unghi). Fă cel puțin 2 căutări diferite \
înainte să concluzionezi că informația lipsește.
4. Când ai fragmentele relevante, răspunde.

Reguli pentru răspuns:
- Doar pe baza fragmentelor găsite. Nu inventa și nu completa din cunoștințe generale.
- Menționează denumirea oficială din normativ a elementului întrebat.
- Citează articole/paragrafe/valori exacte când apar în text.
- La final, indică documentele sursă (nume fișier).
- Dacă după căutări informația nu apare, spune clar că nu a fost găsită în \
documentele încărcate și menționează ce termeni ai căutat.
- Fii precis și concis."""

SEARCH_TOOL = {
    "name": "cauta_in_normative",
    "description": (
        "Caută full-text în normativele încărcate. Întoarce fragmentele care conțin "
        "oricare dintre termeni (toate cuvintele unui termen trebuie să apară în "
        "fragment). Folosește termeni scurți (1-3 cuvinte), în limbajul normativelor."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "termeni": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Termenii de căutare, ex: [\"declanșator manual\", \"alarmare manuală\"]",
            }
        },
        "required": ["termeni"],
    },
}

MAX_SEARCHES = 6


def answer_with_search(question: str, search_fn, limit: int = 8):
    """Răspunde lăsând-o pe Claude să caute iterativ.

    search_fn(query_string, limit) -> listă de fragmente (dict cu content,
    filename, chunk_index). Întoarce (răspuns, fragmente_găsite, termeni_căutați).
    """
    client = get_client()
    messages = [{"role": "user", "content": question}]
    found = {}          # (filename, chunk_index) -> fragment
    searched = []       # toți termenii încercați

    for step in range(MAX_SEARCHES + 1):
        allow_tools = step < MAX_SEARCHES
        kwargs = dict(model=MODEL, max_tokens=2000, system=AGENT_PROMPT,
                      messages=messages, tools=[SEARCH_TOOL])
        if not allow_tools:
            # ultima tură: nu mai are voie să caute, răspunde cu ce a găsit
            kwargs["tool_choice"] = {"type": "none"}
            messages[-1]["content"].append({
                "type": "text",
                "text": "Ai atins limita de căutări. Răspunde acum pe baza fragmentelor găsite.",
            })
        response = client.messages.create(**kwargs)

        tool_calls = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason != "tool_use" or not tool_calls:
            text = "".join(b.text for b in response.content if b.type == "text").strip()
            return text, list(found.values()), searched

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for call in tool_calls:
            terms = [t for t in call.input.get("termeni", []) if isinstance(t, str)]
            searched.extend(terms)
            query = build_search_query(terms)
            chunks = search_fn(query, limit) if query else []
            parts = []
            for c in chunks:
                key = (c["filename"], c["chunk_index"])
                if key in found:
                    parts.append(f"--- {c['filename']} (fragment #{c['chunk_index']}) --- [deja primit mai sus]")
                else:
                    found[key] = c
                    parts.append(f"--- {c['filename']} (fragment #{c['chunk_index']}) ---\n{c['content']}")
            results.append({
                "type": "tool_result",
                "tool_use_id": call.id,
                "content": "\n\n".join(parts) if parts else "Niciun fragment găsit pentru acești termeni.",
            })
        messages.append({"role": "user", "content": results})

    return "Nu am putut formula un răspuns.", list(found.values()), searched
