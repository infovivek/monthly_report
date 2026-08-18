from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from urllib.parse import urlparse

from .askeva import AskEvaError, build_payload, send_template
from . import config
from . import db as database
from .db import db, utcnow
from .phones import normalize_in_mobile


def public_url_looks_local() -> bool:
    host = urlparse(config.PUBLIC_BASE_URL).hostname or ""
    return host in {"127.0.0.1", "localhost", "0.0.0.0", "::1"}


def setup_status() -> dict:
    with db() as conn:
        counts = database.member_counts(conn)
    return {
        "has_token": bool(config.ASKEVA_TOKEN),
        "public_base_url": config.PUBLIC_BASE_URL,
        "public_url_is_local": public_url_looks_local(),
        "members": counts["members"],
        "clubs": counts["clubs"],
        "clubs_with_file": counts.get("clubs_with_file", 0),
        "delay_ms": config.SEND_DELAY_MS,
        "template": config.ASKEVA_TEMPLATE,
    }


def save_pdf(data: bytes, original_name: str) -> tuple[str, str, str]:
    if len(data) > config.MAX_PDF_MB * 1024 * 1024:
        raise ValueError(f"PDF is larger than {config.MAX_PDF_MB} MB")
    if len(data) < 10:
        raise ValueError("PDF file is empty")
    file_id = secrets.token_urlsafe(16)
    filename = f"{file_id}.pdf"
    stored = config.STATIC_MEDIA_DIR / filename
    stored.write_bytes(data)
    pdf_url = f"{config.PUBLIC_BASE_URL}/app/static/media/{filename}"
    display = Path(original_name or "club-report.pdf").name
    if not display.lower().endswith(".pdf"):
        display += ".pdf"
    return str(stored), pdf_url, display


def queue_job(*, club_no: str, month_label: str, pdf_url: str, pdf_filename: str, pdf_path: str | None):
    with db() as conn:
        club = database.get_club(conn, club_no)
        if not club:
            raise ValueError("Club not found")
        members = database.list_members(conn, club_no)
        job_id = database.create_job(
            conn,
            club_no=club["club_no"],
            club_name=club["club_name"],
            month_label=month_label,
            pdf_filename=pdf_filename,
            pdf_path=pdf_path,
            pdf_url=pdf_url,
            total=len(members),
        )
    return job_id, club, members


def run_job(job_id: int, on_progress=None) -> dict:
    with db() as conn:
        job = database.get_job(conn, job_id)
        if not job:
            raise ValueError("Job not found")
        members = database.list_members(conn, job["club_no"])
        conn.execute("UPDATE send_jobs SET status = 'running' WHERE id = ?", (job_id,))

    sent = skipped = failed = 0
    fatal = None
    delay = max(config.SEND_DELAY_MS, 0) / 1000.0
    logs: list[dict] = []

    try:
        for member in members:
            ten, wa_to = normalize_in_mobile(member.get("mobile_digits") or member.get("mobile"))
            name = (member.get("name") or "").strip()
            if not ten or not wa_to or not name:
                skipped += 1
                reason = "invalid or missing mobile" if not wa_to else "missing name"
                entry = _log(
                    job_id,
                    member,
                    job,
                    status="skipped",
                    skip_reason=reason,
                    wa_to=wa_to,
                )
                logs.append(entry)
                _bump(job_id, sent, skipped, failed)
                if on_progress:
                    on_progress(sent, skipped, failed, job["total"], logs)
                continue

            payload = build_payload(
                to=wa_to,
                name=name,
                club_name=job["club_name"],
                month_label=job["month_label"],
                pdf_url=job["pdf_url"],
                pdf_filename=job["pdf_filename"] or "club-report.pdf",
            )
            try:
                http_status, body = send_template(payload)
                ok = 200 <= http_status < 300
                try:
                    parsed = json.loads(body) if body else {}
                except json.JSONDecodeError:
                    parsed = {}
                if isinstance(parsed, dict) and str(parsed.get("status", "")).lower() in {"error", "failed"}:
                    ok = False
                if isinstance(parsed, dict) and parsed.get("error"):
                    ok = False
                if ok:
                    sent += 1
                    status = "sent"
                    skip_reason = None
                else:
                    failed += 1
                    status = "failed"
                    skip_reason = body[:1000]
                entry = _log(
                    job_id,
                    member,
                    job,
                    status=status,
                    skip_reason=skip_reason,
                    wa_to=wa_to,
                    http_status=http_status,
                    request_json=json.dumps(payload),
                    response_text=body[:4000],
                )
            except AskEvaError as exc:
                failed += 1
                entry = _log(
                    job_id,
                    member,
                    job,
                    status="failed",
                    skip_reason=str(exc),
                    wa_to=wa_to,
                    http_status=exc.status_code,
                    request_json=json.dumps(payload),
                    response_text=exc.body,
                )
            except Exception as exc:
                failed += 1
                entry = _log(
                    job_id,
                    member,
                    job,
                    status="failed",
                    skip_reason=str(exc),
                    wa_to=wa_to,
                    request_json=json.dumps(payload),
                )
            logs.append(entry)
            _bump(job_id, sent, skipped, failed)
            if on_progress:
                on_progress(sent, skipped, failed, job["total"], logs)
            if delay:
                time.sleep(delay)
    except Exception as exc:
        fatal = str(exc)

    with db() as conn:
        conn.execute(
            """
            UPDATE send_jobs
            SET status = ?, sent = ?, skipped = ?, failed = ?, error = ?, finished_at = ?
            WHERE id = ?
            """,
            (
                "failed" if fatal else "completed",
                sent,
                skipped,
                failed,
                fatal,
                utcnow(),
                job_id,
            ),
        )
        job = database.get_job(conn, job_id)
    return job


def _log(job_id, member, job, *, status, skip_reason=None, wa_to=None, http_status=None, request_json=None, response_text=None):
    created = utcnow()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO send_logs (
                job_id, member_id, name, club_name, mobile, wa_to, status,
                skip_reason, http_status, request_json, response_text, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                member.get("id"),
                member.get("name"),
                job["club_name"],
                member.get("mobile"),
                wa_to,
                status,
                skip_reason,
                http_status,
                request_json,
                response_text,
                created,
            ),
        )
    return {
        "name": member.get("name"),
        "wa_to": wa_to,
        "status": status,
        "skip_reason": skip_reason,
        "http_status": http_status,
        "created_at": created,
    }


def _bump(job_id, sent, skipped, failed):
    with db() as conn:
        conn.execute(
            "UPDATE send_jobs SET sent = ?, skipped = ?, failed = ? WHERE id = ?",
            (sent, skipped, failed, job_id),
        )


def filename_from_url(pdf_url: str, fallback: str = "club-report.pdf") -> str:
    name = Path(urlparse(pdf_url).path).name or fallback
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name


def clubs_ready_to_send() -> list[dict]:
    with db() as conn:
        clubs = database.list_clubs(conn)
    return [
        c
        for c in clubs
        if (c.get("pdf_url") or "").startswith("http") and int(c.get("sendable_count") or 0) > 0
    ]


def run_all_clubs(month_label: str, on_progress=None) -> dict:
    ready = clubs_ready_to_send()
    totals = {"clubs": len(ready), "sent": 0, "skipped": 0, "failed": 0, "jobs": []}
    for index, club in enumerate(ready, start=1):
        pdf_url = club["pdf_url"]
        display_name = filename_from_url(pdf_url, f"{club['club_name']}.pdf")
        job_id, _club, _members = queue_job(
            club_no=club["club_no"],
            month_label=month_label,
            pdf_url=pdf_url,
            pdf_filename=display_name,
            pdf_path=None,
        )

        def club_progress(sent, skipped_n, failed, total, logs, club=club, index=index, job_id=job_id):
            if on_progress:
                on_progress(
                    {
                        "club_index": index,
                        "club_total": len(ready),
                        "club_name": club["club_name"],
                        "job_id": job_id,
                        "sent": sent,
                        "skipped": skipped_n,
                        "failed": failed,
                        "total": total,
                        "logs": logs,
                    }
                )

        job = run_job(job_id, on_progress=club_progress)
        totals["sent"] += int(job.get("sent") or 0)
        totals["skipped"] += int(job.get("skipped") or 0)
        totals["failed"] += int(job.get("failed") or 0)
        totals["jobs"].append(job)
    return totals
