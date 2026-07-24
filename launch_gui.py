"""
Desktop entrypoint for DJ MetaManager.

Uses pywebview to open a native macOS window (WebKit) instead of the system
browser.  Falls back to browser-open if pywebview is not installed.

Bundled builds (PyInstaller .app) and direct `python launch_gui.py` both
use this file.  `python app.py` still starts a plain dev server.
"""

from __future__ import annotations

import threading
import time


_HOST = "127.0.0.1"
_PORT = 5123
_URL = f"http://{_HOST}:{_PORT}"


def _start_flask_server(app_module) -> None:
    app_module.app.run(
        host=_HOST,
        port=_PORT,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


def _open_browser() -> None:
    import webbrowser

    time.sleep(0.75)
    webbrowser.open(_URL, new=2)


def main() -> None:
    import logging
    import sys

    if getattr(sys, "frozen", False):
        logging.getLogger("werkzeug").setLevel(logging.ERROR)

    import app as app_module

    try:
        import webview
    except ImportError:
        webview = None

    if webview is not None:
        server = threading.Thread(
            target=_start_flask_server,
            args=(app_module,),
            daemon=True,
        )
        server.start()
        time.sleep(0.5)

        webview.create_window(
            "DJ MetaManager",
            _URL,
            width=1280,
            height=900,
        )
        webview.start()
    else:
        threading.Thread(target=_open_browser, daemon=True).start()
        _start_flask_server(app_module)


if __name__ == "__main__":
    main()
