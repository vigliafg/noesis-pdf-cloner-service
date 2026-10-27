"""Contratto di parità col desktop ``noesis-pdf-cloner``.

A differenza degli altri due engine, ``app/engine.py`` **non** è una copia
verbatim: è un adattamento (stato per documento, cache versionata, lock,
worker). La parità quindi non può essere byte-a-byte. Questo test verifica le
parti che *devono* restare identiche al desktop e che in passato sono andate
alla deriva:

* manifest ``ENGINE_SOURCE.json`` presente e coerente;
* stessi id motore e stessi flag ``pdf2zh_next`` condivisi;
* stessi default di modello, timeout, qps e marker di cache;
* stessi preset ``normal``/``fast``/``fastest``.

Se il checkout desktop non è presente (CI del solo repo service) i test si
saltano, come fanno gli analoghi ``test_sync_parity.py`` degli altri engine.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESKTOP = ROOT.parent / "noesis-pdf-cloner"

# Flag/token che il servizio deve passare esattamente come il desktop.
SHARED_FLAG_TOKENS = (
    "--openai-timeout",
    "--no-auto-extract-glossary",
    "--pool-max-workers",
    "--openai-send-reasoning-effort",
    "--openai-enable-json-mode",
    "--skip-formula-offset-calculation",
    "--no-remove-non-formula-lines",
    "--skip-scanned-detection",
    "--clitranslator",
    "--bing",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _literal(source: str, name: str) -> str:
    match = re.search(rf'^{name}\s*=\s*"([^"]+)"', source, re.MULTILINE)
    if match is None:
        raise AssertionError(f"{name} non trovato")
    return match.group(1)


def _tuple(source: str, name: str) -> tuple[str, ...]:
    match = re.search(rf'^{name}\s*:\s*tuple\[str, \.\.\.\]\s*=\s*\(([^)]*)\)',
                      source, re.MULTILINE)
    if match is None:
        raise AssertionError(f"{name} non trovato")
    return tuple(re.findall(r'"([^"]+)"', match.group(1)))


@unittest.skipUnless(
    (DESKTOP / "clone_engine.py").is_file(),
    "checkout desktop noesis-pdf-cloner non presente",
)
class DesktopParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.desktop_engine = _read(DESKTOP / "clone_engine.py")
        cls.desktop_patch = _read(DESKTOP / "engine_patch.py")
        cls.desktop_main = _read(DESKTOP / "main.py")
        cls.service_engine = _read(ROOT / "app" / "engine.py")
        cls.service_patch = _read(ROOT / "app" / "engine_patch.py")

    def test_manifest_is_present(self):
        meta = json.loads(_read(ROOT / "ENGINE_SOURCE.json"))
        self.assertIn("desktop_commit", meta)
        self.assertIn("desktop_version", meta)
        self.assertTrue(meta.get("shared"))

    def test_engine_ids_match(self):
        self.assertEqual(
            _tuple(self.desktop_engine, "ENGINES"),
            _tuple(self.service_engine, "ENGINES"),
        )

    def test_shared_flags_exist_in_both(self):
        for token in SHARED_FLAG_TOKENS:
            self.assertIn(token, self.desktop_engine, f"{token} manca nel desktop")
            self.assertIn(token, self.service_engine, f"{token} manca nel service")

    def test_engine_defaults_match(self):
        for name in (
            "DEFAULT_MODEL", "DEFAULT_BASE_URL", "FAST_ENGINE_TAG",
        ):
            self.assertEqual(
                _literal(self.desktop_engine, name),
                _literal(self.service_engine, name),
                name,
            )
        # Il timeout LLM nel service è una costante nominata diversamente.
        self.assertEqual(
            re.search(r"^LLM_TIMEOUT\s*=\s*(\d+)", self.desktop_engine, re.M).group(1),
            re.search(r"^DEFAULT_LLM_TIMEOUT\s*=\s*(\d+)", self.service_engine, re.M).group(1),
        )
        self.assertEqual(
            re.search(r"^PATCH_VERSION\s*=\s*\"(\d+)\"", self.desktop_patch, re.M).group(1),
            re.search(r"^PATCH_VERSION\s*=\s*\"(\d+)\"", self.service_patch, re.M).group(1),
        )

    def test_fastest_preset_matches_desktop(self):
        from app.config import PRESETS

        self.assertIn("openai/gpt-oss-120b", self.desktop_main)
        self.assertEqual(PRESETS["fastest"]["model"], "openai/gpt-oss-120b")
        self.assertIn("qwen/qwen3-30b-a3b-instruct-2507", self.desktop_main)
        # Il prompt medico del preset "Massima velocità" è condiviso.
        self.assertIn("Sei un traduttore medico EN->IT", self.desktop_main)
        self.assertTrue(
            PRESETS["fastest"]["prompt"].startswith("Sei un traduttore medico EN->IT")
        )

    def test_source_commit_is_an_ancestor_of_desktop_head(self):
        """Il commit nel manifest deve appartenere alla storia del desktop."""
        import subprocess

        meta = json.loads(_read(ROOT / "ENGINE_SOURCE.json"))
        try:
            rc = subprocess.run(
                ["git", "-C", str(DESKTOP), "merge-base", "--is-ancestor",
                 meta["desktop_commit"], "HEAD"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            ).returncode
        except Exception:  # noqa: BLE001
            self.skipTest("git non disponibile")
        self.assertEqual(rc, 0, "desktop_commit non presente nella storia del desktop")


if __name__ == "__main__":
    unittest.main()
