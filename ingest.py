"""
Extragere text din fișiere încărcate (PDF / DOCX) și împărțire în
fragmente ("chunks") potrivite pentru căutare și pentru context trimis
către Claude.
"""

from pypdf import PdfReader
from docx import Document
import io


def extract_text(uploaded_file) -> str:
    """uploaded_file: obiect UploadedFile din Streamlit (are .name și conținut binar)."""
    name = uploaded_file.name.lower()
    data = uploaded_file.read()

    if name.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(data))
        pages_text = []
        for i, page in enumerate(reader.pages):
            txt = page.extract_text() or ""
            if txt.strip():
                pages_text.append(f"[pagina {i + 1}]\n{txt}")
        return "\n\n".join(pages_text)

    elif name.endswith(".docx"):
        doc = Document(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

    elif name.endswith(".txt"):
        return data.decode("utf-8", errors="ignore")

    else:
        raise ValueError(f"Format neacceptat: {uploaded_file.name}. Folosește PDF, DOCX sau TXT.")


def chunk_text(text: str, chunk_size: int = 1500, overlap: int = 200) -> list[str]:
    """Împarte textul în fragmente de ~chunk_size caractere, cu suprapunere,
    încercând să taie la limite de paragraf pentru a nu rupe fraze/articole."""
    text = text.strip()
    if not text:
        return []

    paragraphs = [p for p in text.split("\n") if p.strip()]
    chunks = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 1 <= chunk_size:
            current += para + "\n"
        else:
            if current.strip():
                chunks.append(current.strip())
            # pornim fragmentul nou cu suprapunere din finalul celui anterior
            overlap_text = current[-overlap:] if len(current) > overlap else current
            current = overlap_text + para + "\n"

    if current.strip():
        chunks.append(current.strip())

    return chunks
