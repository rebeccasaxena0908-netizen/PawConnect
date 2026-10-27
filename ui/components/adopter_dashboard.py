"""Adopter dashboard: browse animals, smart screening questionnaire, application status."""
import streamlit as st

from config import PREAPPROVAL_THRESHOLD
from core.models import QUESTIONNAIRE, Animal
from ui.api_session import ApiError, api
from ui.styles import empty_state, esc, hero, kpi, pill, progress_bar, section, show_problems

APP_COLORS = {"Pre-Approved": "success", "Under Review": "accent3", "Approved": "success",
              "Rejected": "danger", "Closed": "muted"}


def render(user) -> None:
    hero("Adopter dashboard", f"Find your new best friend, {user.first_name}",
         "Every animal here was rescued, treated and is ready for a loving home.")
    browse, mine = st.tabs(["🏡 Browse & apply", "📄 My applications"])
    with browse:
        left, right = st.columns([3, 1], gap="large")
        with left:
            render_catalogue(user)
        with right:
            _tips_card()
            _my_summary_card()
    with mine:
        render_applications(user)


def _tips_card() -> None:
    st.markdown(
        '<div class="pc-card"><h4>Adoption tips 🐾</h4><ul class="pc-side-list">'
        "<li><b>Visit first</b> – spend time with the animal before you decide.</li>"
        "<li><b>Plan the budget</b> – food and vet care are a monthly cost.</li>"
        "<li><b>Give it time</b> – a rescued animal may need weeks to settle.</li>"
        "<li><b>Vaccinate and sterilise</b> – the shelter will tell you what is done.</li>"
        "<li><b>It's for life</b> – the care promise on the form is a real promise.</li></ul></div>",
        unsafe_allow_html=True)


def _my_summary_card() -> None:
    apps = api().applications()
    if apps.empty:
        body = '<div class="meta">You have not applied yet. Pick an animal and press <b>Apply</b>.</div>'
    else:
        counts = apps["status"].value_counts()
        rows = "".join(f'<div class="pc-fund-row"><span>{esc(status)}</span><b>{count}</b></div>'
                       for status, count in counts.items())
        body = rows + f'<div class="pc-fund-row"><span>Best score</span><b>{int(apps["score"].astype(int).max())}/100</b></div>'
    st.markdown(f'<div class="pc-card"><h4>My applications</h4>{body}</div>', unsafe_allow_html=True)


def render_catalogue(user) -> None:
    animals = api().animals(available_only=True)
    chosen = st.session_state.get("apply_animal")
    if chosen and chosen in set(animals["animal_id"]):
        _questionnaire(user, Animal.from_dict(animals[animals["animal_id"] == chosen].iloc[0].to_dict()))
        st.divider()

    section("Ready for adoption", f"{len(animals)} animals looking for a home.")
    if animals.empty:
        empty_state("🏡", "Everyone has found a home!", "Check back soon for new friends.")
        return
    species = st.radio("Show", ["All"] + sorted(animals["species"].unique()), horizontal=True,
                       key=f"species_filter_{user.role}")
    if species != "All":
        animals = animals[animals["species"] == species]
    columns = st.columns(3)
    for index, row in enumerate(animals.to_dict(orient="records")):
        animal = Animal.from_dict(row)
        with columns[index % 3]:
            badges = (pill("Vaccinated", "success") if animal.vaccinated == "yes" else pill("Needs vaccine", "accent3")) + \
                     (pill("Sterilised", "accent2") if animal.sterilized == "yes" else "")
            age = f"{float(animal.age_years):g} yr" if animal.age_years else ""
            st.markdown(
                f'<div class="pc-card pc-animal clickable"><div class="pc-animal-art">{animal.emoji}</div>'
                f"<h4>{esc(animal.name)}</h4>"
                f'<div class="meta">{esc(animal.breed)} · {esc(animal.gender)} · {esc(age)}</div>'
                f"<div>{badges}</div>"
                f'<div class="meta pc-clamp" style="margin-top:6px">{esc(animal.description)}</div></div>',
                unsafe_allow_html=True)
            if st.button(f"Apply to adopt {animal.name}", key=f"apply_{animal.animal_id}", type="primary"):
                st.session_state.apply_animal = animal.animal_id
                st.rerun()


def _questionnaire(user, animal: Animal) -> None:
    section(f"Adoption questionnaire for {animal.name} {animal.emoji}",
            f"Scored out of 100. {PREAPPROVAL_THRESHOLD}+ is pre-approved automatically; "
            "everything else is reviewed by the shelter team.")
    with st.form("adoption_form"):
        answers = {}
        for key, item in QUESTIONNAIRE.items():
            answers[key] = st.radio(item["question"], list(item["options"]), index=None, key=f"q_{key}")
        reason = st.text_area("Why would you like to adopt?", max_chars=400)
        promise = st.checkbox("I'll keep the animal indoors/safe, vaccinate it yearly and never abandon it.")
        c1, c2 = st.columns([1, 1])
        submitted = c1.form_submit_button("Submit application", type="primary")
        cancel = c2.form_submit_button("Cancel")
    if cancel:
        st.session_state.pop("apply_animal", None)
        st.rerun()
    if submitted:
        if not promise:
            st.error("Please accept the care promise.")
            return
        try:
            application = api().apply_adoption(animal.animal_id, {k: a or "" for k, a in answers.items()}, reason)
        except ApiError as error:
            show_problems(error)
            return
        st.session_state.pop("apply_animal", None)
        if application["status"] == "Pre-Approved":
            st.success(f"Score {application['score']}/100 – you're pre-approved! "
                       "The shelter will call you to arrange a home visit.")
            st.balloons()
        else:
            st.info(f"Score {application['score']}/100 – your application is under review. "
                    "We'll contact you within 3 days.")


def render_applications(user) -> None:
    apps = api().applications()           # only this user's applications
    if apps.empty:
        empty_state("📄", "No applications yet", "Browse the animals and apply for one you love.")
        return
    animals = api().animals().set_index("animal_id")
    c1, c2, c3 = st.columns(3)
    kpi(c1, "Applications", str(len(apps)))
    kpi(c2, "Pre-approved / approved", str(apps["status"].isin(["Pre-Approved", "Approved"]).sum()))
    kpi(c3, "Best score", f"{apps['score'].astype(int).max()}/100", tone="success")
    st.write("")
    for row in apps.iloc[::-1].to_dict(orient="records"):
        name = animals.loc[row["animal_id"], "name"] if row["animal_id"] in animals.index else row["animal_id"]
        score = int(row["score"])
        st.markdown(
            f'<div class="pc-card"><h4>{esc(name)} '
            f'<span class="pc-badges">{pill(row["status"], APP_COLORS.get(row["status"]))}</span></h4>'
            f'<div class="meta">{esc(row["application_id"])} · submitted {esc(row["submitted_at"][:10])}</div>'
            f"{progress_bar(score / 100)}<div class='meta'>Screening score {score}/100</div></div>",
            unsafe_allow_html=True)
