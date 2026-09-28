"""Test di ``app.engine_patch`` (patch runtime sperimentali del motore).

Le patch "reali" sono verificate con moduli ``babeldoc`` finti iniettati in
``sys.modules``: nessuna dipendenza da BabelDOC.
"""

from __future__ import annotations

import sys
import types

from app import engine_patch


class _FakeMemoryMonitor:
    def __init__(self, *args, **kwargs):
        self.peak_memory_usage = 123

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_babeldoc_modules():
    assets = types.ModuleType("babeldoc.assets.assets")
    calls = {"count": 0}

    def get_font_and_metadata(name):
        calls["count"] += 1
        return name, {"sha3_256": "x"}

    assets.get_font_and_metadata = get_font_and_metadata

    high_level = types.ModuleType("babeldoc.format.pdf.high_level")
    high_level.MemoryMonitor = _FakeMemoryMonitor

    modules = {
        "babeldoc": types.ModuleType("babeldoc"),
        "babeldoc.assets": types.ModuleType("babeldoc.assets"),
        "babeldoc.assets.assets": assets,
        "babeldoc.format": types.ModuleType("babeldoc.format"),
        "babeldoc.format.pdf": types.ModuleType("babeldoc.format.pdf"),
        "babeldoc.format.pdf.high_level": high_level,
    }
    return modules, assets, high_level, calls


def _reset():
    engine_patch._STATE = None


def test_apply_all_is_safe_without_babeldoc():
    _reset()
    state = engine_patch.apply_all()
    assert set(state) == {
        engine_patch.FONT_METADATA_CACHE,
        engine_patch.MEMORY_MONITOR,
        engine_patch.NUMERIC_LISTS,
    }
    assert all(isinstance(v, bool) for v in state.values())
    assert state[engine_patch.NUMERIC_LISTS] is False  # opt-in
    _reset()


def test_looks_like_list_marker():
    assert engine_patch._looks_like_list_marker("1. Obtain")
    assert engine_patch._looks_like_list_marker("a) Item")
    assert not engine_patch._looks_like_list_marker("1.5 g/dL")
    assert not engine_patch._looks_like_list_marker("Obtain")


def test_apply_all_is_idempotent():
    _reset()
    assert engine_patch.apply_all() == engine_patch.apply_all()
    _reset()


def test_apply_all_with_fake_babeldoc(monkeypatch):
    _reset()
    modules, assets, high_level, calls = _fake_babeldoc_modules()
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    state = engine_patch.apply_all()
    assert state[engine_patch.FONT_METADATA_CACHE] is True
    assert state[engine_patch.MEMORY_MONITOR] is True

    # La memoizzazione evita il secondo calcolo (hash).
    assets.get_font_and_metadata("f1")
    assets.get_font_and_metadata("f1")
    assert calls["count"] == 1

    # Il MemoryMonitor è lo stub no-op.
    with high_level.MemoryMonitor() as monitor:
        assert monitor.peak_memory_usage == 0
    _reset()


def test_patch_version_exposed():
    assert isinstance(engine_patch.PATCH_VERSION, str)
    assert engine_patch.PATCH_VERSION
