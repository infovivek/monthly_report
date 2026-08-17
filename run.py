import os
import sys

from app.config import PORT, ROOT

if __name__ == "__main__":
    os.chdir(ROOT)
    from streamlit.web import cli as stcli

    sys.argv = [
        "streamlit",
        "run",
        str(ROOT / "streamlit_app.py"),
        "--server.port",
        str(PORT),
        "--server.address",
        "0.0.0.0",
    ]
    sys.exit(stcli.main())
