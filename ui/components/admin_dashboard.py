"""Shelter administration: analytics, fund allocation, cases, adoptions, inventory, users, data & audit."""
import pandas as pd
import streamlit as st

from analytics import numpy_stats as ns
from analytics import pandas_engine as pe
from config import ALLOCATABLE_FUNDS, ALLOCATION_PURPOSES, ANIMAL_TYPES, CASE_STATUSES, SCHEMAS
from ui.api_session import ApiError, api
from ui.components.donor_dashboard import render_transparency
from ui.styles import card_row, empty_state, esc, hero, inr, kpi, pill, section, show_problems
from ui.styles import table as show_table   # zebra-striped st.dataframe


def render(user) -> None:
    hero("Shelter administration", f"Good to see you, {user.first_name}",
         "Run the network: watch the numbers, move money to the animals who need it, "
         "approve adoptions and keep the books clean.")
    tabs = st.tabs(["📊 Overview", "💰 Fund allocation", "🚑 Rescue cases", "🏡 Adoptions",
                    "📦 Inventory", "👥 Users", "✉️ E-mail", "🗂️ Data & audit"])
    with tabs[0]:
        _overview()
    with tabs[1]:
        _funds()
    with tabs[2]:
        _cases()
    with tabs[3]:
        _adoptions()
    with tabs[4]:
        _inventory()
    with tabs[5]:
        _users()
    with tabs[6]:
        _email_tab(user)
    with tabs[7]:
        _data_and_audit()


# ======================================================================= overview
def _overview() -> None:
    summary = api().summary()           # NumPy statistics are worked out by GET /analytics/summary
    money, response, beds = summary["money"], summary["response_hours"], summary["beds"]

    c1, c2, c3, c4 = st.columns(4)
    kpi(c1, "Total funds raised", inr(money["total"]), f"{int(money['count'])} successful donations", accent=True)
    kpi(c2, "Recovery rate", f"{summary['recovery_rate']:.0f}%", "recovered ÷ rescued × 100", tone="success")
    kpi(c3, "Avg response time", f"{response['mean']:.1f} h", f"{response['within_2h']:.0f}% picked up within 2 h",
        tone="accent2")
    kpi(c4, "Shelter beds", f"{beds['in_use']}/{beds['total']}", "in use / total", tone="accent3")
    st.write("")
    c1, c2, c3, c4 = st.columns(4)
    kpi(c1, "Average donation", inr(round(money["mean"])), f"median {inr(round(money['median']))}", tone="accent")
    kpi(c2, "Std deviation", inr(round(money["std"])), f"spread of gift sizes (CV {money['cv']:.0f}%)", tone="accent2")
    monthly_spend = summary["monthly_expenditure"]
    kpi(c3, "Monthly spend std dev", inr(round(summary["monthly_spend_std"])), f"across {len(monthly_spend)} months", tone="success")
    kpi(c4, "Open cases", str(summary["open_cases"]), f"{summary['waiting_cases']} waiting for a rescuer",
        tone="accent3")
    st.write("")
    _attention_and_email(summary)

    left, right = st.columns(2)
    left.pyplot(ns.plot_monthly_trend(summary["monthly_donations"], monthly_spend))
    right.pyplot(ns.plot_fund_utilization(summary["utilization"]))
    left, right = st.columns(2)
    left.pyplot(ns.plot_case_status(summary["cases_by_status"]))
    right.pyplot(ns.plot_donation_distribution(summary["donation_amounts"]))

    section("Month-on-month donation growth", "Calculated with numpy.diff on monthly totals.")
    monthly = summary["monthly_donations"]
    growth = summary["growth_percent"]
    if len(growth):
        frame = pd.DataFrame({"Month": monthly.index[1:].strftime("%b %Y"),
                              "Donations (₹)": monthly.values[1:].round(0), "Growth %": growth})
        show_table(frame, hide_index=True, column_config={
            "Donations (₹)": st.column_config.NumberColumn(format="₹%d"),
            "Growth %": st.column_config.NumberColumn(format="%.1f%%")})

    donations = pe.clean_donations(api().donations())       # admins receive every donation
    outliers = ns.zscore_outliers(donations["amount"].values)
    if len(outliers):
        section("Unusually large donations", "Flagged for the audit team (|z-score| > 3).")
        flagged = donations.iloc[outliers][["timestamp", "transaction_id", "donor_name", "amount",
                                            "contribution_type"]]
        show_table(flagged, hide_index=True,
                     column_config={"amount": st.column_config.NumberColumn(format="₹%d")})


def _attention_and_email(summary: dict) -> None:
    """Two cards under the KPI tiles: what needs doing, and whether e-mail works."""
    cases = api().cases()
    unassigned = int((cases["status"] == "Reported").sum()) if not cases.empty else 0
    critical = int(((cases["status"] == "Reported") & (cases["injury_level"] == "Critical")).sum()) if not cases.empty else 0
    low = pe.low_stock(api().inventory())
    apps = api().applications()
    waiting = int(apps["status"].isin(["Pre-Approved", "Under Review"]).sum()) if not apps.empty else 0
    mail = api().email_status()

    def row(label: str, count: int, tone: str) -> str:
        return (f'<div class="pc-fund-row"><span>{esc(label)}</span>'
                f'<b>{pill(str(count), tone if count else "success")}</b></div>')

    state = pill("Sending real e-mail", "success") if mail["enabled"] else pill("Demo mode – not sending", "accent3")
    attention = (
        '<div class="pc-card"><h4>Needs attention</h4>'
        + row("SOS cases without a rescuer", unassigned, "danger")
        + row("…of them critical", critical, "danger")
        + row("Inventory items at or below reorder level", len(low), "accent3")
        + row("Adoption applications waiting for a decision", waiting, "accent3")
        + ('<div class="meta" style="margin-top:8px">Low on: ' + esc(", ".join(low["item"].head(4))) + "</div>"
           if len(low) else "") + "</div>")
    email_card = (
        f'<div class="pc-card"><h4>E-mail status {state}</h4>'
        f'<div class="pc-fund-row"><span>SMTP server</span><b>{esc(mail["host"])}:{mail["port"]}</b></div>'
        f'<div class="pc-fund-row"><span>Sender account</span><b>{esc(mail["user"] or "not set")}</b></div>'
        f'<div class="pc-fund-row"><span>App password</span><b>{"set" if mail["password_set"] else "not set"}</b></div>'
        '<div class="meta" style="margin-top:8px">Open the <b>✉️ E-mail</b> tab to send a test message and see '
        "the latest delivery results.</div></div>")
    card_row(attention, email_card)


# ======================================================================= e-mail
def _email_tab(admin) -> None:
    mail = api().email_status()
    c1, c2, c3, c4 = st.columns(4)
    kpi(c1, "Real e-mail", "On" if mail["enabled"] else "Off", "SMTP is configured" if mail["enabled"]
        else "demo mode: e-mails are only logged", tone="success" if mail["enabled"] else "accent3",
        accent=mail["enabled"])
    kpi(c2, "Mail server", f'{mail["host"]}', f'port {mail["port"]} (STARTTLS)', tone="accent2")
    kpi(c3, "Sender account", mail["user"] or "not set", mail["sender"] or "set SMTP_USER in .env", tone="accent")
    kpi(c4, "App password", "Set" if mail["password_set"] else "Not set", "never shown here",
        tone="success" if mail["password_set"] else "danger")
    st.write("")
    left, right = st.columns([1.6, 1], gap="large")
    with left:
        section("Latest e-mails", "One line per message – the log never contains the text, codes or passwords.")
        recent = pd.DataFrame(mail["recent"])
        if recent.empty:
            empty_state("✉️", "No e-mails yet", "Register an account or make a donation to create some.")
        else:
            recent = recent.rename(columns={"at": "When", "to": "To", "subject": "Subject", "status": "Result"})
            show_table(recent[["When", "To", "Subject", "Result"]], hide_index=True, height=360)
    with right:
        section("Send a test e-mail", "Checks the whole path: login to the mail server, sending, delivery.")
        if not mail["enabled"]:
            st.markdown(
                '<div class="pc-card"><h4>Real e-mail is not set up</h4><div class="meta">Add '
                "<b>SMTP_USER</b> and <b>SMTP_PASSWORD</b> to the <b>.env</b> file, then restart "
                "<b>python main.py --all</b>. For Gmail the password must be an <b>app password</b> "
                "(Google Account → Security → 2-Step Verification → App passwords).</div></div>",
                unsafe_allow_html=True)
        with st.form("test_email"):
            to = st.text_input("Send to", value=admin.email)
            go = st.form_submit_button("Send test e-mail", type="primary")
        if go:
            try:
                result = api().send_test_email(to)
            except ApiError as error:
                show_problems(error)
            else:
                if result["status"] == "simulated":
                    st.info("Demo mode: the message was only written to the log – nothing was sent.")
                elif result["ok"]:
                    st.success(f"Sent to {to}. Check the inbox and the spam folder.")
                else:
                    st.error(result["error"])


# ======================================================================= funds
def _funds() -> None:
    overview = api().funds_overview()
    columns = st.columns(len(overview))
    for column, (name, row) in zip(columns, overview.iterrows()):
        kpi(column, name, inr(row["available"]) if row["allocatable"] else inr(row["raised"]),
            f"available of {inr(row['raised'])} raised" if row["allocatable"] else "goes straight to the chosen case",
            accent=name == "General Shelter Fund", tone="" if name == "General Shelter Fund" else "accent2")
    st.write("")
    left, right = st.columns([2, 3], gap="large")
    with left:
        section("Allocate money to a case", "Link general or feed-fund donations to an animal's treatment.")
        table = api().case_funding()
        candidates = table[~table["status"].isin(["Recovered", "Reported"])] if not table.empty else table
        if candidates.empty:
            empty_state("💰", "No cases in treatment right now")
        else:
            labels = {r.case_id: f"{r.case_id} · {r.animal_type} · {r.injury_level} · gap {inr(r.gap)}"
                      for r in candidates.itertuples()}
            with st.form("allocate"):
                case_id = st.selectbox("Case", list(labels), format_func=labels.get)
                source = st.selectbox("From fund", ALLOCATABLE_FUNDS)
                purpose = st.selectbox("For", ALLOCATION_PURPOSES)
                amount = st.number_input("Amount (₹)", min_value=0.0, step=500.0, value=2000.0)
                notes = st.text_input("Note (optional)")
                submitted = st.form_submit_button("Allocate", type="primary")
            if submitted:
                try:
                    allocation = api().allocate(case_id, f"{amount:.2f}", purpose, source, notes)
                    st.success(f"{allocation['allocation_id']}: {inr(allocation['amount'])} sent to {case_id}.")
                    st.rerun()
                except ApiError as error:          # 409 if the fund doesn't have enough
                    show_problems(error)
    with right:
        section("Recent allocations")
        allocations = pe.clean_allocations(api().allocations()).sort_values("allocated_at", ascending=False)
        show_table(allocations[["allocated_at", "allocation_id", "case_id", "source_fund", "purpose",
                                  "amount", "notes"]].head(25), hide_index=True,
                     column_config={"amount": st.column_config.NumberColumn(format="₹%d")})
    st.divider()
    render_transparency()


# ======================================================================= cases
def _cases() -> None:
    raw = api().cases().iloc[::-1]          # oldest first, like the table on disk
    rescuers = api().rescuers()
    statuses = st.multiselect("Show stages", CASE_STATUSES, default=CASE_STATUSES[:4])
    view = raw[raw["status"].isin(statuses)].iloc[::-1]
    view = view.assign(rescuer=view["rescuer_id"].map(rescuers).fillna("—"))
    show_table(view[["case_id", "reported_at", "animal_type", "injury_level", "status", "pincode",
                       "address", "rescuer", "estimated_cost", "description"]], hide_index=True, height=330)
    left, right = st.columns(2, gap="large")
    open_ids = raw[raw["status"] != "Recovered"]["case_id"].iloc[::-1].tolist()
    with left:
        section("Assign a rescuer")
        if open_ids and rescuers:
            with st.form("assign"):
                case_id = st.selectbox("Case", open_ids)
                rescuer_id = st.selectbox("Rescuer", list(rescuers), format_func=rescuers.get)
                if st.form_submit_button("Assign", type="primary"):
                    try:
                        api().assign_case(case_id, rescuer_id)
                        st.toast(f"{case_id} assigned.")
                        st.rerun()
                    except ApiError as error:
                        show_problems(error)
    with right:
        section("Correct a case stage")
        if open_ids:
            with st.form("set_status"):
                case_id = st.selectbox("Case ", raw["case_id"].iloc[::-1].tolist())
                status = st.selectbox("New stage", CASE_STATUSES)
                if st.form_submit_button("Update"):
                    try:
                        api().set_case_status(case_id, status)
                        st.toast(f"{case_id} → {status}")
                        st.rerun()
                    except ApiError as error:
                        show_problems(error)
    section("Cases by area and injury level", "Hierarchical grouping: pincode area → injury level → stage.")
    show_table(pe.cases_by_area_status(pe.clean_cases(raw)))


# ======================================================================= adoptions
def _adoptions() -> None:
    apps = api().applications()
    animals = api().animals()
    names = animals.set_index("animal_id")["name"].to_dict()
    pending = apps[apps["status"].isin(["Pre-Approved", "Under Review"])].copy()
    pending["score_num"] = pending["score"].astype(int)
    pending = pending.sort_values("score_num", ascending=False)
    section("Applications waiting for a decision", "Highest screening score first.")
    if pending.empty:
        empty_state("🏡", "No applications to review")
    for row in pending.to_dict(orient="records"):
        tone = "success" if row["status"] == "Pre-Approved" else "accent3"
        st.markdown(
            f'<div class="pc-card"><h4>{esc(row["applicant_name"])} → {esc(names.get(row["animal_id"], row["animal_id"]))} '
            f'<span class="pc-badges">{pill(row["status"], tone)} {pill("Score " + row["score"], "accent2")}</span></h4>'
            f'<div class="meta">🏠 {esc(row["housing"])} · 🐾 {esc(row["experience"])} · ⏱️ {esc(row["hours_alone"])} · '
            f'👪 {esc(row["family"])} · 💰 {esc(row["budget"])}</div>'
            f'<div class="meta">“{esc(row["reason"])}”</div></div>', unsafe_allow_html=True)
        c1, c2, _ = st.columns([1, 1, 4])
        for column, decision, kind in ((c1, "Approved", "primary"), (c2, "Rejected", "secondary")):
            if column.button("Approve" if decision == "Approved" else "Reject",
                             key=f"{decision}_{row['application_id']}", type=kind):
                try:
                    api().review_application(row["application_id"], decision)
                    st.toast(f"{row['application_id']} {decision.lower()}.")
                    st.rerun()
                except ApiError as error:
                    show_problems(error)
    with st.expander("All applications"):
        show_table(apps.iloc[::-1], hide_index=True)

    section("List an animal for adoption")
    cases = api().cases()
    with st.form("add_animal", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Name")
        species = c2.selectbox("Species", ANIMAL_TYPES)
        breed = c3.text_input("Breed", value="Indie")
        age = c1.number_input("Age (years)", min_value=0.0, max_value=25.0, step=0.5, value=1.0)
        gender = c2.selectbox("Gender", ["Male", "Female", "Unknown"])
        case_id = c3.selectbox("From rescue case", [""] + cases[cases["status"] == "Recovered"]["case_id"].tolist())
        vaccinated = c1.checkbox("Vaccinated")
        sterilized = c2.checkbox("Sterilised")
        temperament = st.text_input("Temperament", placeholder="Friendly, good with kids")
        description = st.text_area("Description", max_chars=300)
        if st.form_submit_button("Add to catalogue", type="primary"):
            try:
                animal = api().add_animal(name, species, breed, age, gender, vaccinated, sterilized,
                                          temperament, description, case_id)
                st.success(f"{animal['name']} ({animal['animal_id']}) is now listed.")
            except ApiError as error:
                show_problems(error)
    with st.expander("Adoption catalogue"):
        show_table(animals, hide_index=True)


# ======================================================================= inventory
def _inventory() -> None:
    raw = api().inventory()
    low = pe.low_stock(raw)
    cases = pe.clean_cases(api().cases())
    in_use, beds = pe.bed_availability(raw, cases)
    c1, c2, c3 = st.columns(3)
    kpi(c1, "Beds free", f"{max(beds - in_use, 0)}", f"{in_use} of {beds} in use", tone="success")
    kpi(c2, "Items tracked", str(len(raw)))
    kpi(c3, "Low on stock", str(len(low)), "at or below reorder level", tone="danger" if len(low) else "success")
    if not low.empty:
        st.warning("Reorder soon: " + ", ".join(f"{r.item} ({int(r.quantity)} {r.unit})" for r in low.itertuples()))
    section("Stock", "Edit quantities directly, add rows at the bottom, then save.")
    editable = raw.copy()
    for column in ("quantity", "reorder_level"):
        editable[column] = pd.to_numeric(editable[column], errors="coerce").fillna(0).astype(int)
    edited = st.data_editor(editable.drop(columns=["updated_at"]), num_rows="dynamic", hide_index=True,
                            disabled=["item_id"], key="inventory_editor")
    if st.button("Save stock", type="primary"):
        try:
            count = api().save_inventory(edited.fillna(""))
            st.success(f"Saved {count} items.")
            st.rerun()
        except ApiError as error:
            show_problems(error)


# ======================================================================= users
def _users() -> None:
    users = api().users()
    counts = users["role"].value_counts()
    columns = st.columns(len(counts))
    for column, (role, count) in zip(columns, counts.items()):
        kpi(column, role + "s", str(count))
    st.write("")
    show_table(users, hide_index=True)
    st.caption("Passwords are stored only as salted PBKDF2-SHA256 hashes and are never shown or exported.")


# ======================================================================= data & audit
def _data_and_audit() -> None:
    left, right = st.columns(2, gap="large")
    with left:
        section("Download data", "CSV or structured XML for any table, generated from the database.")
        table = st.selectbox("Table", list(SCHEMAS))
        c1, c2 = st.columns(2)
        c1.download_button("⬇️ CSV", api().export(table, "csv"), file_name=f"{table}.csv", mime="text/csv")
        c2.download_button("⬇️ XML", api().export(table, "xml"), file_name=f"{table}.xml",
                           mime="application/xml")
        if st.button("Create full backup in data/exports"):
            backup = api().backup()
            st.success(f"Backup written on the server: {backup['files']} files in {backup['folder']}.")
    with right:
        section("Data quality", "Empty cells per column (pandas isna()).")
        quality_table = st.selectbox("Check table", list(SCHEMAS), index=list(SCHEMAS).index("donations"))
        report = pe.missing_value_report(api().table(quality_table))
        show_table(report[report["missing"] > 0] if (report["missing"] > 0).any() else report.head(3))

    section("Donations by month and fund", "groupby(['month', 'fund']) → MultiIndex → unstack.")
    donations = pe.clean_donations(api().donations())
    if not donations.empty:
        show_table(pe.monthly_type_breakdown(donations))
        with st.expander("Raw MultiIndex frame"):
            show_table(pe.monthly_type_multiindex(donations))
        section("Top donors")
        show_table(pe.top_donors(donations), hide_index=True,
                     column_config={"total": st.column_config.NumberColumn(format="₹%d")})

    section("Audit log", "Every sign-in, SOS, payment, allocation and decision – stored in the audit_events table.")
    log = api().audit_log()
    c1, c2 = st.columns([1, 2])
    actions = c1.multiselect("Actions", sorted(log["action"].unique()))
    search = c2.text_input("Search details")
    if actions:
        log = log[log["action"].isin(actions)]
    if search:
        log = log[log["details"].str.contains(search, case=False, regex=False)]
    show_table(log, hide_index=True, height=320)
    st.download_button("⬇️ Download audit_logs.xml", api().audit_log_xml(), file_name="audit_logs.xml",
                       mime="application/xml")
