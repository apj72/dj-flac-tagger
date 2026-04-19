import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def app_module(monkeypatch, tmp_path):
    import app as app_mod

    monkeypatch.setattr(app_mod, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(app_mod, "LOG_PATH", str(tmp_path / "processing_log.json"))
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "source_dir": str(tmp_path),
                "destination_dir": str(tmp_path),
                "platinum_notes_app": "",
                "pn_output_suffix": "_PN",
                "target_lufs": -14.0,
                "target_true_peak": -1.0,
            }
        ),
        encoding="utf-8",
    )
    return app_mod


@pytest.fixture(autouse=True)
def _no_external_flac_cli(monkeypatch, app_module):
    """Tests always use libavcodec FLAC; avoid optional `flac` CLI + temp WAV path."""
    import shutil as sh

    real_which = sh.which

    def which(name, mode=os.F_OK, path=None):
        if name == "flac":
            return None
        return real_which(name, mode, path)

    monkeypatch.setattr(app_module.shutil, "which", which)


@pytest.fixture
def client(app_module):
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()
