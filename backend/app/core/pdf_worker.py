"""Sous-processus d'extraction PDF (PyMuPDF isolé).

Lancé via ``python -m app.core.pdf_worker IN.pdf OUT.txt [max_pages]``.
Un crash natif (double free, SIGSEGV) tue uniquement ce process, pas le
worker PoE qui l'a spawn. Le process parent n'importe jamais ``fitz``.

Si le PDF n'a pas de couche texte (scan de Gaceta, leçon Venezuela
règlement capitanías), on OCR les pages via tesseract s'il est installé.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_OCR_MIN_CHARS = 80
_OCR_LANGS = "spa+eng+fra"
_SEMAR_MARKS = frozenset({"si", "sí", "x", "+"})


def _semar_turistica_block(pdf, max_pages: int = 180) -> str:
    """Colonne TURÍSTICA du PDF SCT : les marques (si / x / +) ont une abscisse.

    Le texte linéaire perd cette colonne. On réémet les lignes taguées pour
    que le parseur ne garde que l'activité touristique.
    """
    tur_x = None
    rows: list[tuple[int, str]] = []
    for page in list(pdf[:max_pages]):
        words = page.get_text("words") or []
        if tur_x is None:
            for w in words:
                key = (w[4] or "").upper().replace("Í", "I")
                if key == "TURISTICA":
                    tur_x = float(w[0])
                    break
        if tur_x is None:
            continue
        bands: dict[float, list] = {}
        for w in words:
            bands.setdefault(round(float(w[1]) * 2) / 2, []).append(w)
        for ws in bands.values():
            ws = sorted(ws, key=lambda t: t[0])
            if not ws or not (ws[0][4] or "").isdigit() or float(ws[0][0]) > 70:
                continue
            name_parts = [w[4] for w in ws if 60 <= float(w[0]) < 112]
            if not name_parts:
                continue
            if any(abs(float(w[0]) - tur_x) < 12
                   and (w[4] or "").lower() in _SEMAR_MARKS for w in ws):
                rows.append((int(ws[0][4]), " ".join(name_parts)))
    if not rows:
        return ""
    lines = [f"{n} {name}" for n, name in rows]
    return "\n[ACTIVIDAD_TURISTICA]\n" + "\n".join(lines) + "\n"


def _ocr_page(page, lang: str = _OCR_LANGS) -> str:
    import fitz
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as tmp:
        pix.save(tmp.name)
        try:
            return subprocess.check_output(
                ["tesseract", tmp.name, "stdout", "-l", lang, "--psm", "6"],
                stderr=subprocess.DEVNULL, text=True, timeout=90,
            )
        except (OSError, subprocess.SubprocessError):
            return ""


def extract_pdf_file(inp: str, out: str, max_pages: int = 180) -> None:
    import fitz

    with fitz.open(inp) as pdf:
        pages = list(pdf[:max_pages])
        native = "\n".join((p.get_text() or "") for p in pages)
        text = native
        if len(native.strip()) < _OCR_MIN_CHARS and shutil.which("tesseract"):
            ocr = "\n".join(_ocr_page(p) for p in pages)
            if len(ocr.strip()) > len(native.strip()):
                text = ocr
        extra = _semar_turistica_block(pdf, max_pages)
        if extra:
            text = (text or "") + extra
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
