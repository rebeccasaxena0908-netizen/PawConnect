"""Field rescuer dashboard: SOS queue for my area, accept, update status and medical notes."""
from datetime import datetime

import pandas as pd
import streamlit as st

from config import COLORS
from core.models import RescueCase
from ui.api_session import ApiError, api
from ui.styles import (empty_state, esc, hero, injury_pill, kpi, pill, progress_bar, section,
                       show_problems)


def _cases(df: pd.DataFrame) -> list[RescueCase]:
    return [RescueCase.from_dict(r) for r in df.to_dict(orient="records")]


def render(user) -> None:
    hero("Field rescuer dashboard", f"Ready to roll, {user.first_name}?",
         f"SOS calls from your area (pincodes starting {user.area_code}) appear first, most urgent on top.")
    all_cases = api().cases()        # waiting SOS calls + the cases assigned to me
    pending = all_cases[all_cases["status"] == "Reported"]
    mine = all_cases[all_cases["rescuer_id"] == user.user_id]
    active = mine[mine["status"] != "Recovered"]
    in_area = pending[pending["pincode"].str[:3] == user.area_code]

    c1, c2, c3, c4 = st.columns(4)
    kpi(c1, "Open SOS in my area", str(len(in_area)), "waiting for a rescuer", tone="danger" if len(in_area) else "success")
    kpi(c2, "My active rescues", str(len(active)), tone="accent2")
    kpi(c3, "Recovered by me", str((mine["status"] == "Recovered").sum()), tone="success")
    kpi(c4, "Critical waiting", str((pending["injury_level"] == "Critical").sum()), "anywhere", tone="accent3")
    st.write("")

    queue, current = st.tabs(["🚨 SOS queue", "🩺 My active rescues & map"])
    with queue:
        left, right = st.columns([2.2, 1], gap="large")
        with left:
            _queue(user, pending)
        with right:
            _today_card(user, pending, mine)
            _area_card(user, pending)
    with current:
        left, right = st.columns([1.5, 1], gap="large")
        with left:
            _active(user, active)
        with right:
            _map(pending, active)


def _today_card(user, pending: pd.DataFrame, mine: pd.DataFrame) -> None:
    """Today's numbers for this rescuer, shown beside the queue."""
    today = datetime.now().strftime("%Y-%m-%d")
    accepted_today = int((mine["assigned_at"].str[:10] == today).sum()) if not mine.empty else 0
    taken = mine[mine["assigned_at"] != ""]
    hours = ((pd.to_datetime(taken["assigned_at"]) - pd.to_datetime(taken["reported_at"]))
             .dt.total_seconds() / 3600) if not taken.empty else pd.Series(dtype=float)
    average = f"{hours.mean():.1f} h" if len(hours) else "–"
    critical = pending[pending["injury_level"] == "Critical"]
    in_area = int((critical["pincode"].str[:3] == user.area_code).sum()) if not critical.empty else 0
    st.markdown(
        '<div class="pc-card"><h4>Today ☀️</h4>'
        f'<div class="pc-fund-row"><span>Cases you accepted today</span><b>{accepted_today}</b></div>'
        f'<div class="pc-fund-row"><span>Your average response time</span><b>{average}</b></div>'
        f'<div class="pc-fund-row"><span>Critical cases waiting (all areas)</span><b>{len(critical)}</b></div>'
        f'<div class="pc-fund-row"><span>…of those in your area</span><b>{in_area}</b></div></div>',
        unsafe_allow_html=True)


def _area_card(user, pending: pd.DataFrame) -> None:
    waiting = pending.assign(area=pending["pincode"].str[:3]).groupby("area").size().sort_values(ascending=False)
    rows = "".join(f'<div class="pc-fund-row"><span>{esc(area)}xxx{" (your area)" if area == user.area_code else ""}'
                   f'</span><b>{count}</b></div>' for area, count in waiting.head(5).items())
    st.markdown('<div class="pc-card"><h4>Waiting by area</h4>'
                + (rows or '<div class="meta">No SOS calls are waiting – well done!</div>')
                + '<div class="meta" style="margin-top:10px">Accepting a case takes it off every other rescuer\'s '
                  'list, so confirm you can reach it first.</div></div>', unsafe_allow_html=True)


def _queue(user, pending: pd.DataFrame) -> None:
    only_mine = st.toggle("Only my area", value=True)
    if only_mine:
        pending = pending[pending["pincode"].str[:3] == user.area_code]
    cases = sorted(_cases(pending), key=lambda c: (-c.priority, c.reported_at))
    if not cases:
        empty_state("✅", "No waiting SOS calls", "Switch off 'Only my area' to help elsewhere.")
        return
    for case in cases:
        st.markdown(
            f'<div class="pc-card"><h4>{esc(case.case_id)} · {esc(case.animal_type)} '
            f'<span class="pc-badges">{injury_pill(case.injury_level)}</span></h4>'
            f'<div class="meta">{esc(case.description)}</div>'
            f'<div class="meta">📍 {esc(case.address or "No landmark")} · {esc(case.pincode)} · '
            f"reported {esc(case.reported_at[:16])}</div></div>", unsafe_allow_html=True)
        c1, c2 = st.columns([1, 3])
        if c1.button("Accept rescue", key=f"accept_{case.case_id}", type="primary"):
            try:
                api().accept_case(case.case_id)           # 409 if another rescuer was quicker
                st.toast(f"{case.case_id} is yours. Drive safe!")
                st.rerun()
            except ApiError as error:
                show_problems(error)
        if case.latitude and case.longitude:
            c2.link_button("Open in Google Maps",
                           f"https://www.google.com/maps/search/?api=1&query={case.latitude},{case.longitude}")


def _active(user, active: pd.DataFrame) -> None:
    cases = sorted(_cases(active), key=lambda c: (-c.priority, c.reported_at))
    if not cases:
        empty_state("🩺", "No active rescues", "Accept an SOS from the queue to start.")
        return
    for case in cases:
        with st.expander(f"{case.case_id} · {case.animal_type} · {case.status}", expanded=len(cases) <= 3):
            left, right = st.columns([3, 2])
            with left:
                st.markdown(f"{injury_pill(case.injury_level)} {pill(case.status)}", unsafe_allow_html=True)
                st.markdown(progress_bar(case.progress), unsafe_allow_html=True)
                st.write(case.description)
                st.caption(f"📍 {case.address or 'No landmark'} · {case.pincode} · reported {case.reported_at[:16]}")
                for note in case.notes_list()[-5:]:
                    st.caption("• " + note)
            with right:
                photo = api().photo(case.case_id) if case.photo_path else None
                if photo:
                    st.image(photo, width=220)
            with st.form(f"update_{case.case_id}"):
                note = st.text_input("Medical / field note", placeholder="e.g. Wound dressed, given painkiller")
                cost = st.number_input("Estimated treatment cost (₹)", min_value=0, step=500,
                                       value=int(float(case.estimated_cost or 0)))
                c1, c2 = st.columns(2)
                save = c1.form_submit_button("Save note")
                nxt = case.next_status()
                move = c2.form_submit_button(f"Move to: {nxt}", type="primary") if nxt else False
            if save or move:
                try:
                    if save:
                        api().add_note(case.case_id, note, float(cost))
                        st.toast("Saved.")
                    if move:
                        if float(cost) != float(case.estimated_cost or 0):
                            api().add_note(case.case_id, "", float(cost))
                        api().advance_case(case.case_id, note)
                        st.toast(f"{case.case_id} → {nxt}")
                    st.rerun()
                except ApiError as error:
                    show_problems(error)


def _map(pending: pd.DataFrame, active: pd.DataFrame) -> None:
    section("Where help is needed", "Red = waiting SOS, blue = your active rescues.")
    frames = []
    for df, color in ((pending, COLORS["danger"]), (active, COLORS["accent2"])):
        if not df.empty:
            points = pd.DataFrame({"lat": pd.to_numeric(df["latitude"], errors="coerce"),
                                   "lon": pd.to_numeric(df["longitude"], errors="coerce")}).dropna()
            points["color"] = color
            frames.append(points)
    if not frames:
        empty_state("🗺️", "Nothing to show on the map")
        return
    st.map(pd.concat(frames), color="color", size=60)
