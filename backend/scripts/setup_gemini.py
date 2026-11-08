from __future__ import annotations

import getpass
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
GITIGNORE_PATH = ROOT / ".gitignore"


def main():
    print("\n" + "=" * 55)
    print(" DISPATCHRESOLVE AI — GEMINI CONNECTION SETUP")
    print("=" * 55)
    print("Get key: https://aistudio.google.com/api-keys")
    print("Paste your key below. Input is hidden.\n")

    key = getpass.getpass("GEMINI API KEY: ").strip()

    if not key or any(c.isspace() for c in key):
        print("ERROR: Enter a valid API key.")
        sys.exit(1)

    print("\nConnecting to Gemini...")

    try:
        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents="Reply with exactly: CONNECTED",
        )

        if "CONNECTED" not in (response.text or "").upper():
            raise RuntimeError("Unexpected API response")

    except Exception as exc:
        print("CONNECTION FAILED")
        print("Error type:", type(exc).__name__)
        print("Check your API key, internet, model access and quota.")
        sys.exit(1)

    existing = (
        ENV_PATH.read_text(encoding="utf-8")
        if ENV_PATH.exists()
        else ""
    )

    lines = [
        line
        for line in existing.splitlines()
        if not re.match(
            r"^\s*(?:export\s+)?GEMINI_API_KEY\s*=",
            line,
        )
    ]

    lines.append(f"GEMINI_API_KEY={key}")

    ENV_PATH.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    os.chmod(ENV_PATH, 0o600)

    existing_ignore = (
        GITIGNORE_PATH.read_text(encoding="utf-8")
        if GITIGNORE_PATH.exists()
        else ""
    )

    if ".env" not in existing_ignore.splitlines():
        with GITIGNORE_PATH.open("a", encoding="utf-8") as file:
            file.write("\n.env\n")

    load_dotenv(ENV_PATH, override=True)

    print("\n" + "=" * 55)
    print("SUCCESS! GEMINI CONNECTED")
    print("Model: gemini-2.5-flash")
    print("API key saved to backend/.env")
    print("Key was not displayed.")
    print("=" * 55)


if __name__ == "__main__":
    main()
