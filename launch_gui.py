"""
Desktop entrypoint for bundled macOS / Windows builds (PyInstaller).
Starts the Flask server, opens the default browser to the UI, avoids debug/reloader.
"""

from __future__ import annotations

import threading
import time
import webbrowser


def _open_browser() -> None:
    time.sleep(0.75)
    webbrowser.open("http://127.0.0.1:5123/", new=2)


def main() -> None:
    import logging
    import sys

    if getattr(sys, "frozen", False):
        logging.getLogger("werkzeug").setLevel(logging.ERROR)

    import app as app_module  # defer import so multiprocessing_spawn / paths apply first

    threading.Thread(target=_open_browser, daemon=True).start()
    app_module.app.run(
        host="127.0.0.1",
        port=5123,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


if __name__ == "__main__":
    main()
