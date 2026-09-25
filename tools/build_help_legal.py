#!/usr/bin/env python3
"""Genera la pagina «Note legali» della guida (GitHub Pages) a partire dai
documenti legali in ``legal/`` e dai documenti condivisi nella radice.

Fonte unica = file Markdown. Output = ``docs/help/note-legali.html``
(replica dei Termini + Privacy + Disclaimer + Uso accettabile, IT ed EN).

Uso:
    .venv/bin/python tools/build_help_legal.py
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "help" / "note-legali.html"

# (titolo, percorso relativo alla radice)
DOCS = [
    ("Termini d'uso", "legal/TERMS.it.md"),
    ("Esclusione di garanzia", "legal/DISCLAIMER.it.md"),
    ("Privacy", "legal/PRIVACY.it.md"),
    ("Uso accettabile", "legal/ACCEPTABLE_USE.it.md"),
    ("Termini aggiuntivi (AGPL §7)", "ADDITIONAL_TERMS.md"),
    ("Marchio", "TRADEMARK.md"),
    ("Sicurezza", "SECURITY.md"),
    ("Terms of Use", "legal/TERMS.en.md"),
    ("Disclaimer", "legal/DISCLAIMER.en.md"),
    ("Privacy Policy", "legal/PRIVACY.en.md"),
    ("Acceptable Use", "legal/ACCEPTABLE_USE.en.md"),
]

PAGE = """<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Note legali — Noesis PDF Cloner Service</title>
  <link rel="stylesheet" href="css/help.css">
</head>
<body>
  <header class="topbar">
    <a class="brand" href="it/">🧬 Noesis PDF Cloner — <em>Note legali</em></a>
    <div class="lang-switch">
      <a href="it/" lang="it">🇮🇹 Italiano</a>
      <a href="en/" lang="en">🇬🇧 English</a>
      <a href="../../terms">Pagina Termini (istanza locale)</a>
    </div>
  </header>
  <div class="wrap">
    <nav class="sidebar">
      <div class="group-label">Indice</div>
{index}
    </nav>
    <main class="content">
      <h1>Note legali</h1>
      <p>Questa pagina è la <strong>replica</strong> dei documenti legali del
      servizio, generata automaticamente dalla fonte unica in <code>legal/</code>.
      La versione <strong>italiana è autoritativa</strong>; l'inglese è una
      traduzione di cortesia. <em>Ultima generazione: {today}.</em></p>
{body}
    </main>
  </div>
</body>
</html>
"""


def _slug(title: str) -> str:
    out = []
    for ch in title.lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in " -":
            out.append("-")
    return "".join(out).strip("-")


def main() -> int:
    index_lines: list[str] = []
    body_parts: list[str] = []
    for title, rel in DOCS:
        path = ROOT / rel
        if not path.is_file():
            continue
        slug = _slug(title)
        index_lines.append(f'      <a href="#{slug}">{title}</a>')
        html = markdown.markdown(
            path.read_text(encoding="utf-8"),
            extensions=["extra", "toc", "sane_lists"],
        )
        body_parts.append(f'      <section id="{slug}">\n{html}\n      </section>')
    OUT.write_text(
        PAGE.format(index="\n".join(index_lines), body="\n".join(body_parts),
                    today=date.today().isoformat()),
        encoding="utf-8",
    )
    print(f"Scritto {OUT.relative_to(ROOT)} ({len(body_parts)} documenti)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
