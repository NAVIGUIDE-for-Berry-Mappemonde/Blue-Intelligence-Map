"""Sous-processus d'extraction PDF (PyMuPDF isolé).

Lancé via ``python -m app.core.pdf_worker IN.pdf OUT.txt [max_pages]``.
Un crash natif (double free, SIGSEGV) tue uniquement ce process, pas le
worker PoE qui l'a spawn. Le process parent n'importe jamais ``fitz``.
"""
from __future__ import annotations

import sys
from pathlib import Path


def extract_pdf_file(inp: str, out: str, max_pages: int = 180) -> None:
    import fitz

    with fitz.open(inp) as pdf:
        text = "\n".join(page.get_text() for page in pdf[:max_pages])
    Path(out).write_text(text or "", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        print("usage: python -m app.core.pdf_worker IN.pdf OUT.txt [max_pages]",
              file=sys.stderr)
        return 2
    inp, out = argv[0], argv[1]
    max_pages = int(argv[2]) if len(argv) > 2 else 180
    try:
        extract_pdf_file(inp, out, max_pages)
    except Exception as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
