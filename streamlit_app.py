from calendar import month_name
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

from app import config
from app.db import db, init_db, list_clubs, list_jobs, list_logs, list_members, member_counts
from app.importer import import_club_files, import_excel
from app.phones import normalize_in_mobile
from app.sender import queue_job, run_all_clubs, run_job, save_pdf, setup_status

SEED_XLSX = Path("/Users/vivek/Downloads/Rotary Members List.xlsx")
SEED_FILES = Path("/Users/vivek/Desktop/file.xlsx")
MONTHS = list(month_name)[1:]

config.reload()


def bootstrap():
    init_db()
    with db() as conn:
        empty = member_counts(conn)["members"] == 0
        files_empty = member_counts(conn).get("clubs_with_file", 0) == 0
    if empty and SEED_XLSX.exists():
        import_excel(SEED_XLSX)
    if files_empty and SEED_FILES.exists():
        import_club_files(SEED_FILES)


bootstrap()

st.set_page_config(page_title="RID 3206 Monthly Report", layout="wide")
config.reload()
config.apply_request_public_url()
st.markdown(
    """
    <style>
      .stApp { background: #f4efe6; }
      h1, h2, h3 { color: #163f7a !important; font-family: Palatino, Georgia, serif; }
      div[data-testid="stMetric"] { background: #fffdf8; border: 1px solid #d9cfc0; padding: 0.4rem 0.6rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


def login_view():
    st.caption("ROTARY INTERNATIONAL DISTRICT 3206")
    st.title("Monthly Report Sender")
    st.write("Sign in to send club report PDFs on WhatsApp.")
    with st.form("login"):
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        if password == config.APP_PASSWORD:
            st.session_state.auth = True
            st.rerun()
        st.error("Incorrect password")


def club_options(clubs):
    return {
        f"{c['club_name']}  ·  {int(c['sendable_count'] or 0)}/{int(c['member_count'] or 0)} sendable": c
        for c in clubs
    }


def members_frame(members):
    rows = []
    for m in members:
        ten, wa = normalize_in_mobile(m.get("mobile_digits") or m.get("mobile"))
        rows.append(
            {
                "Name": m.get("name"),
                "Mobile": m.get("mobile") or "",
                "WhatsApp": wa or "",
                "Email": m.get("email") or "",
                "Rotary ID": m.get("rotary_id") or "",
                "Send?": "Yes" if ten else "Skip — invalid or missing mobile",
            }
        )
    return pd.DataFrame(rows)


def send_tab(clubs, status):
    if not clubs:
        st.info("No clubs yet. Import the members Excel from the Re-import tab.")
        return

    options = club_options(clubs)
    label = st.selectbox("Club", list(options.keys()))
    club = options[label]
    month_col, year_col = st.columns(2)
    month = month_col.selectbox("Month", MONTHS, index=MONTHS.index("July"))
    year = year_col.number_input("Year", min_value=2020, max_value=2100, value=datetime.now().year, step=1)
    month_label = f"{month} {int(year)}"

    pdf = st.file_uploader("Club report PDF", type=["pdf"])
    default_url = club.get("pdf_url") or ""
    pdf_url_in = st.text_input(
        "Or public PDF URL (optional)",
        value=default_url,
        placeholder="https://your-server/reports/club.pdf",
        key=f"pdf_url_{club['club_no']}",
    )
    st.caption("Each club has its own PDF. Every member of the selected club gets the same file.")

    with db() as conn:
        members = list_members(conn, club["club_no"])
    sendable = int(club["sendable_count"] or 0)
    skipped = int(club["member_count"] or 0) - sendable
    sample = members[0]["name"] if members else "Name"

    st.markdown("**WhatsApp preview**")
    st.info(
        f"Hello Rotarian **{sample}**,\n\n"
        f"**{club['club_name']} Club Report for {month_label}** is attached for your reference. "
        "It summarises the club’s activities, updates, and key outcomes during this period.\n\n"
        f"Thank you  \nRID 3206\n\n"
        f"Template: `{config.ASKEVA_TEMPLATE}`"
    )

    if not status["has_token"]:
        st.warning("ASKEVA_TOKEN is empty. Set it in the Settings tab.")
    if status["public_url_is_local"]:
        st.warning(
            f"PDFs will be served from `{status['public_base_url']}`. AskEva cannot fetch localhost. "
            "Set PUBLIC_BASE_URL in Settings to this machine’s public HTTPS address (or a Cloudflare tunnel URL)."
        )

    confirm = st.checkbox(
        f"Send the {month_label} report to {sendable} members of {club['club_name']} "
        f"({skipped} invalid numbers will be skipped)"
    )
    send_clicked = st.button("Send to club members", type="primary", disabled=not status["has_token"])

    if send_clicked:
        if not confirm:
            st.error("Tick the confirmation box before sending.")
            return
        stored_path = None
        display_name = ""
        pdf_url = (pdf_url_in or "").strip()
        try:
            if pdf is not None:
                stored_path, pdf_url, display_name = save_pdf(pdf.getvalue(), pdf.name)
            elif pdf_url.startswith("http://") or pdf_url.startswith("https://"):
                display_name = Path(urlparse(pdf_url).path).name or f"report-{month_label}.pdf"
                if not display_name.lower().endswith(".pdf"):
                    display_name += ".pdf"
            else:
                st.error("Upload a PDF or paste a public PDF URL.")
                return

            job_id, _club, _members = queue_job(
                club_no=club["club_no"],
                month_label=month_label,
                pdf_url=pdf_url,
                pdf_filename=display_name,
                pdf_path=stored_path,
            )
        except Exception as exc:
            st.error(str(exc))
            return

        st.success(f"Job {job_id} started. PDF URL used: {pdf_url}")
        progress = st.progress(0)
        summary = st.empty()
        table = st.empty()

        def on_progress(sent, skipped_n, failed, total, logs):
            done = sent + skipped_n + failed
            progress.progress(min(done / total, 1.0) if total else 1.0)
            summary.write(f"Sent {sent} · skipped {skipped_n} · failed {failed} / {total}")
            table.dataframe(pd.DataFrame(logs[::-1][:80]), use_container_width=True, hide_index=True)

        job = run_job(job_id, on_progress=on_progress)
        if job.get("error"):
            st.error(job["error"])
        else:
            st.success(
                f"Finished: sent {job['sent']}, skipped {job['skipped']}, failed {job['failed']}."
            )


def auto_send_tab(clubs, status):
    ready = [c for c in clubs if (c.get("pdf_url") or "").startswith("http") and int(c.get("sendable_count") or 0) > 0]
    missing_file = [c for c in clubs if not (c.get("pdf_url") or "").startswith("http")]
    no_members = [
        c
        for c in clubs
        if (c.get("pdf_url") or "").startswith("http") and int(c.get("sendable_count") or 0) == 0
    ]
    sendable_people = sum(int(c.get("sendable_count") or 0) for c in ready)

    month_col, year_col = st.columns(2)
    month = month_col.selectbox("Month", MONTHS, index=MONTHS.index("July"), key="auto_month")
    year = year_col.number_input(
        "Year", min_value=2020, max_value=2100, value=datetime.now().year, step=1, key="auto_year"
    )
    month_label = f"{month} {int(year)}"

    st.write(
        f"Month **{month_label}** is used for every club. Each club’s members get only that club’s PDF URL."
    )
    st.caption(
        f"{len(ready)} clubs ready · {sendable_people} sendable members · "
        f"{len(missing_file)} clubs skipped (no file) · {len(no_members)} skipped (no valid mobile)"
    )
    if ready:
        preview = [
            {
                "Club": c["club_name"],
                "Sendable": int(c.get("sendable_count") or 0),
                "PDF": c.get("pdf_url") or "",
            }
            for c in ready
        ]
        st.dataframe(pd.DataFrame(preview), use_container_width=True, hide_index=True)

    if not status["has_token"]:
        st.warning("ASKEVA_TOKEN is empty. Set it in the Settings tab.")
    if missing_file:
        st.caption("No file: " + ", ".join(c["club_name"] for c in missing_file))

    confirm = st.checkbox(
        f"Send the {month_label} report to {sendable_people} members across {len(ready)} clubs. "
        "Invalid numbers will be skipped."
    )
    start = st.button("Start auto send", type="primary", disabled=not status["has_token"] or not ready)

    if start:
        if not confirm:
            st.error("Tick the confirmation box before sending.")
            return
        club_line = st.empty()
        progress = st.progress(0)
        summary = st.empty()
        table = st.empty()

        def on_progress(info):
            club_line.write(
                f"Club {info['club_index']} / {info['club_total']}: **{info['club_name']}**"
            )
            overall = ((info["club_index"] - 1) + (info["sent"] + info["skipped"] + info["failed"]) / max(info["total"], 1)) / max(
                info["club_total"], 1
            )
            progress.progress(min(overall, 1.0))
            summary.write(
                f"This club: sent {info['sent']} · skipped {info['skipped']} · failed {info['failed']} / {info['total']}"
            )
            logs = info.get("logs") or []
            if logs:
                table.dataframe(pd.DataFrame(logs[::-1][:80]), use_container_width=True, hide_index=True)

        totals = run_all_clubs(month_label, on_progress=on_progress)
        progress.progress(1.0)
        st.success(
            f"Finished all clubs: sent {totals['sent']}, skipped {totals['skipped']}, "
            f"failed {totals['failed']} across {totals['clubs']} clubs."
        )


def members_tab(clubs):
    if not clubs:
        st.info("No members imported yet.")
        return
    options = club_options(clubs)
    label = st.selectbox("Club", list(options.keys()), key="members_club")
    club = options[label]
    with db() as conn:
        members = list_members(conn, club["club_no"])
    st.caption(f"{club['club_name']} · {len(members)} members")
    st.dataframe(members_frame(members), use_container_width=True, hide_index=True)


def import_tab():
    st.subheader("Members")
    st.write(
        "Re-import the Rotary members Excel. Existing people are updated (by Rotary ID, or club + mobile). "
        "New clubs and members are inserted. Nobody is deleted."
    )
    xlsx = st.file_uploader("Members list (.xlsx)", type=["xlsx", "xlsm"])
    if st.button("Import members", disabled=xlsx is None):
        dest = Path("data") / f"import-{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.xlsx"
        dest.write_bytes(xlsx.getvalue())
        try:
            result = import_excel(dest)
        except Exception as exc:
            st.error(str(exc))
            return
        st.success(
            f"Imported: {result['inserted']} new, {result['updated']} updated, {result['unchanged']} unchanged."
        )
        st.json(result)
        st.rerun()

    st.subheader("Club PDF files")
    st.write(
        "Excel with club name in column A and public PDF URL in column B. "
        "Matched to existing clubs by name. Members are not changed."
    )
    files_xlsx = st.file_uploader("Club files list (.xlsx)", type=["xlsx", "xlsm"], key="files_xlsx")
    if st.button("Import club files", disabled=files_xlsx is None):
        dest = Path("data") / f"club-files-{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.xlsx"
        dest.write_bytes(files_xlsx.getvalue())
        try:
            result = import_club_files(dest)
        except Exception as exc:
            st.error(str(exc))
            return
        st.success(
            f"Club files: {result['updated']} updated, {result['unchanged']} already set, "
            f"{result['unmatched']} unmatched names."
        )
        st.json(result)
        st.rerun()


def logs_tab():
    status_filter = st.selectbox("Status", ["All", "sent", "skipped", "failed"])
    with db() as conn:
        jobs = list_jobs(conn)
        logs = list_logs(conn, status=None if status_filter == "All" else status_filter)
    st.subheader("Jobs")
    if jobs:
        st.dataframe(pd.DataFrame(jobs), use_container_width=True, hide_index=True)
    else:
        st.caption("No send jobs yet.")
    st.subheader("Recent messages")
    if logs:
        view = [
            {
                "When": r.get("created_at"),
                "Club": r.get("job_club") or r.get("club_name"),
                "Name": r.get("name"),
                "To": r.get("wa_to") or "",
                "Status": r.get("status"),
                "Detail": r.get("skip_reason") or "",
            }
            for r in logs
        ]
        st.dataframe(pd.DataFrame(view), use_container_width=True, hide_index=True)
    else:
        st.caption("No message logs yet.")


def settings_tab():
    st.write(
        "These values are saved to `.env` on this machine and used immediately, "
        "except **PORT**, which needs an app restart."
    )
    if config.running_on_streamlit_cloud():
        st.info(
            "This app is on Streamlit Cloud. Settings here last until the app reboots. "
            "For a lasting AskEva token and password, paste them in "
            "[Streamlit secrets](https://share.streamlit.io) → this app → Settings → Secrets. "
            "See `.streamlit/secrets.toml.example` in the repo."
        )
    if st.session_state.pop("env_saved", False):
        st.success("Settings saved.")
    current = config.values()
    show = st.checkbox("Show secret values", value=False)
    suffix = "show" if show else "hide"
    with st.form("env_form"):
        edits = {}
        for key, label, kind in config.EDITABLE_FIELDS:
            value = current.get(key, "")
            widget_key = f"env_{key}_{suffix}"
            if kind == "int":
                edits[key] = str(
                    st.number_input(label, min_value=0, value=int(value or 0), step=1, key=widget_key)
                )
            elif kind == "password":
                edits[key] = st.text_input(
                    label,
                    value=value,
                    type="default" if show else "password",
                    key=widget_key,
                )
            else:
                edits[key] = st.text_input(label, value=value, key=widget_key)
        saved = st.form_submit_button("Save settings", type="primary")
    if saved:
        try:
            config.save_env(edits)
            st.session_state.env_saved = True
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


if not st.session_state.get("auth"):
    login_view()
    st.stop()

status = setup_status()
with db() as conn:
    clubs = list_clubs(conn)

top = st.columns([4, 1])
with top[0]:
    st.caption("ROTARY INTERNATIONAL DISTRICT 3206")
    st.title("Monthly Report Sender")
with top[1]:
    if st.button("Sign out"):
        st.session_state.clear()
        st.rerun()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Clubs", status["clubs"])
c2.metric("Members", status["members"])
c3.metric("Clubs with file", status.get("clubs_with_file", 0))
c4.metric("Template", config.ASKEVA_TEMPLATE)

auto, send, members, reimport, logs, settings = st.tabs(
    ["Auto send", "Send one club", "Members", "Re-import", "Send log", "Settings"]
)
with auto:
    auto_send_tab(clubs, status)
with send:
    send_tab(clubs, status)
with members:
    members_tab(clubs)
with reimport:
    import_tab()
with logs:
    logs_tab()
with settings:
    settings_tab()
