"""Citizen dashboard: SOS reporting with photo + pincode geocoding, own reports, adoption."""
import pandas as pd
import streamlit as st

from config import ANIMAL_TYPES, INJURY_LEVELS
from core.models import RescueCase
from ui.api_session import ApiError, api
from ui.components import adopter_dashboard
from ui.styles import (empty_state, esc, hero, injury_pill, kpi, pill, progress_bar, section,
                       show_problems)


def render(user) -> None:
    hero("Citizen dashboard", f"Namaste, {user.first_name} 🐾",
         "Seen an injured or sick stray? Send an SOS – the nearest rescuer gets it straight away.")
    sos, mine, adopt = st.tabs(["🚨 Report an injured animal", "📋 My reports", "🏡 Adopt a pet"])
    with sos:
        _sos_form(user)
    with mine:
        _my_reports(user)
    with adopt:
        adopter_dashboard.render_catalogue(user)


def _sos_form(user) -> None:
    left, right = st.columns([1.7, 1], gap="large")
    with right:
        _sos_side_panel(user)
    with left:
        _sos_form_body(user)


def _sos_side_panel(user) -> None:
    """Fills the space beside the form: safety tips and the citizen's own numbers."""
    st.markdown(
        '<div class="pc-card"><h4>While you wait 🐾</h4><ul class="pc-side-list">'
        "<li><b>Keep a safe distance</b> – hurt animals may bite out of fear.</li>"
        "<li><b>Don't give water or food</b> to a badly injured animal; it may need surgery.</li>"
        "<li><b>Shade and quiet</b> help – keep people and traffic away if you can.</li>"
        "<li><b>A clear photo</b> lets the rescuer bring the right kit.</li>"
        "<li><b>Stay reachable</b> – the rescuer may e-mail or call you for directions.</li></ul></div>",
        unsafe_allow_html=True)
    cases = api().cases()
    open_cases = cases[cases["status"] != "Recovered"] if not cases.empty else cases
    st.markdown(
        f'<div class="pc-card"><h4>Your reports</h4>'
        f'<div class="pc-fund-row"><span>Sent</span><b>{len(cases)}</b></div>'
        f'<div class="pc-fund-row"><span>Still being helped</span><b>{len(open_cases)}</b></div>'
        f'<div class="pc-fund-row"><span>Recovered</span><b>{int((cases["status"] == "Recovered").sum()) if not cases.empty else 0}</b></div>'
        + (f'<div class="meta" style="margin-top:10px">Latest: <b>{esc(cases.iloc[0]["case_id"])}</b> · '
           f'{pill(cases.iloc[0]["status"])}</div>' if not cases.empty else
           '<div class="meta" style="margin-top:10px">Your SOS reports will appear here.</div>')
        + "</div>", unsafe_allow_html=True)


def _sos_form_body(user) -> None:
    section("Send an SOS", "Stay at a safe distance. Don't feed or move a badly injured animal.")
    with st.form("sos_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        animal_type = c1.selectbox("Animal", ANIMAL_TYPES)
        injury = c2.radio("How serious is it?", INJURY_LEVELS, index=1, horizontal=True,
                          help="Critical = bleeding heavily, can't stand, hit by a vehicle.")
        description = st.text_area("What do you see?", max_chars=500,
                                   placeholder="e.g. Brown dog limping, back leg bleeding, near Gate 2 of the park")
        c3, c4 = st.columns([1, 2])
        pincode = c3.text_input("Pincode", value=user.pincode, max_chars=6)
        address = c4.text_input("Landmark / street", placeholder="Near the metro station exit")
        photo = st.file_uploader("Photo (helps the rescuer bring the right kit)",
                                 type=["jpg", "jpeg", "png", "webp"])
        online = st.checkbox("Find exact map coordinates online (India Post + OpenStreetMap)", value=True)
        submitted = st.form_submit_button("🚨 Send SOS", type="primary")
    if not submitted:
        return
    try:
        case = api().create_case(animal_type, injury, description, pincode, address, use_network=online,
                                 photo_bytes=photo.getvalue() if photo else None,
                                 photo_name=photo.name if photo else "")
    except ApiError as error:
        show_problems(error)
        return
    st.success(f"SOS sent! Your case number is **{case['case_id']}**. Rescuers in area "
               f"{case['pincode'][:3]} have been alerted.")
    st.caption(f"Location found via {case['location_source']}: {case['latitude']}, {case['longitude']}")
    st.map(pd.DataFrame({"lat": [float(case["latitude"])], "lon": [float(case["longitude"])]}), zoom=11)


def _my_reports(user) -> None:
    cases = api().cases()            # the API returns only this citizen's own reports, newest first
    if cases.empty:
        empty_state("📋", "You haven't reported anything yet",
                    "When you send an SOS, you can follow the animal's recovery here.")
        return
    c1, c2, c3 = st.columns(3)
    kpi(c1, "Reports", str(len(cases)), tone="accent")
    kpi(c2, "Being treated", str(cases["status"].isin(["Assigned", "In Transit", "Sheltered/In Treatment"]).sum()), tone="accent2")
    kpi(c3, "Recovered", str((cases["status"] == "Recovered").sum()), tone="success")
    st.write("")
    for row in cases.to_dict(orient="records"):
        case = RescueCase.from_dict(row)
        rescuer = row.get("rescuer_name") or case.rescuer_id
        st.markdown(
            f'<div class="pc-card"><h4>{esc(case.case_id)} · {esc(case.animal_type)} '
            f'<span class="pc-badges">{injury_pill(case.injury_level)} {pill(case.status)}</span></h4>'
            f'<div class="meta">{esc(case.description)}</div>'
            f"{progress_bar(case.progress)}"
            f'<div class="meta">Reported {esc(case.reported_at[:16])} · pincode {esc(case.pincode)}'
            + (f" · rescuer {esc(rescuer)}" if case.rescuer_id else "")
            + "</div></div>", unsafe_allow_html=True)
        if case.photo_path or case.notes_list():
            with st.expander("Photo and treatment notes" if case.photo_path else "Treatment notes"):
                photo = api().photo(case.case_id) if case.photo_path else None
                if photo:
                    st.image(photo, width=320)
                for note in case.notes_list():
                    st.caption(note)
