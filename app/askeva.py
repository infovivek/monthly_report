from __future__ import annotations

import httpx

from .config import ASKEVA_API_URL, ASKEVA_TEMPLATE, ASKEVA_TEMPLATE_LANG, ASKEVA_TOKEN


class AskEvaError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def build_payload(
    *,
    to: str,
    name: str,
    club_name: str,
    month_label: str,
    pdf_url: str,
    pdf_filename: str,
) -> dict:
    return {
        "to": to,
        "type": "template",
        "template": {
            "language": {"policy": "deterministic", "code": ASKEVA_TEMPLATE_LANG},
            "name": ASKEVA_TEMPLATE,
            "components": [
                {
                    "type": "header",
                    "parameters": [
                        {
                            "type": "document",
                            "document": {"link": pdf_url, "filename": pdf_filename},
                        }
                    ],
                },
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": name},
                        {"type": "text", "text": club_name},
                        {"type": "text", "text": month_label},
                    ],
                },
            ],
        },
    }


def send_template(payload: dict) -> tuple[int, str]:
    if not ASKEVA_TOKEN:
        raise AskEvaError("ASKEVA_TOKEN is not set in .env")
    url = ASKEVA_API_URL
    with httpx.Client(timeout=45.0) as client:
        response = client.post(url, params={"token": ASKEVA_TOKEN}, json=payload)
    return response.status_code, response.text
