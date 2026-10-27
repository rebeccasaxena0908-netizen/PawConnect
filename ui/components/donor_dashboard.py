"""Donor portal: secure contribution form, receipts, and the financial transparency hub."""
import pandas as pd
import streamlit as st

from analytics import numpy_stats as ns
from analytics import pandas_engine as pe
from config import CONTRIBUTION_TYPES, MAX_DONATION, MIN_DONATION
from ui.api_session import ApiError, api
from ui.styles import empty_state, esc, hero, inr, kpi, progress_bar, section, show_problems
from ui.styles import table as show_table   # zebra-striped st.dataframe

FUND_HELP = {
    "General Shelter Fund": "Surgeries, medicines and shelter running costs – the team sends it where it's needed most.",
    "Specific Medical Case": "Pay towards one animal's treatment. You'll see its recovery in the transparency tab.",
    "Emergency Feed Fund": "Food for sheltered animals and street feeding during floods and heatwaves.",
}


def render(user) -> None:
    hero("Donor portal", f"Thank you for being here, {user.first_name} 💝",
         "Every rupee is tracked – from your payment to the animal it treated.")
    donate, mine, transparency = st.tabs(["💝 Donate", "🧾 My donations", "🔍 Where the money goes"])
    with donate:
        _donate(user)
    with mine:
        _my_donations(user)
    with transparency:
        render_transparency()


# ======================================================================= donate
def _donate(user) -> None:
    gateway = api().payment_config()["gateway"]
    left, right = st.columns([3, 2], gap="large")
    with left:
        section("Make a contribution",
                "Razorpay TEST mode – no real money moves." if gateway == "razorpay"
                else "Sandbox payments – no real money moves.")
        fund = st.radio("Fund", CONTRIBUTION_TYPES, horizontal=True, key="donate_fund")
        st.caption(FUND_HELP[fund])
        case_id = ""
        if fund == "Specific Medical Case":
            table = api().case_funding()
            needy = table[(table["gap"] > 0) & (table["status"] != "Recovered")] if not table.empty else table
            if needy.empty:
                st.info("Every open case is fully funded right now – the General Shelter Fund helps the next one.")
                return
            labels = {r.case_id: f"{r.case_id} · {r.animal_type} · {r.injury_level} · {inr(r.gap)} still needed"
                      for r in needy.itertuples()}
            case_id = st.selectbox("Choose an animal to support", list(labels), format_func=labels.get)
        methods = ["UPI", "Card"] + (["Razorpay"] if gateway == "razorpay" else [])
        method = st.radio("Pay with", methods, horizontal=True, key="donate_method",
                          format_func=lambda m: "Razorpay Checkout (test)" if m == "Razorpay" else m)

        with st.form("donation_form"):
            amount = st.text_input("Amount (₹)", value="1000",
                                   help=f"Between ₹{MIN_DONATION} and ₹{MAX_DONATION:,}.")
            st.caption("Suggested: ₹500 feeds a dog for a month · ₹1,500 vaccinates three · ₹6,000 covers a fracture")
            details = {}
            if method == "UPI":
                details["upi"] = st.text_input("UPI ID", placeholder="yourname@okaxis")
            elif method == "Card":
                details["card_name"] = st.text_input("Name on card")
                details["card_number"] = st.text_input("Card number", max_chars=19,
                                                       placeholder="4111 1111 1111 1111")
                c1, c2 = st.columns(2)
                details["expiry"] = c1.text_input("Expiry (MM/YY)", max_chars=5)
                details["cvv"] = c2.text_input("CVV", type="password", max_chars=3)
            else:
                st.caption("You'll pay on Razorpay's own secure page – PawConnect never sees your card.")
            pan_note = st.checkbox("Send me an 80G tax receipt by e-mail", value=True)
            submitted = st.form_submit_button("Donate securely 🔒", type="primary")

        with st.expander("Test payment details"):
            st.markdown("- Any valid UPI ID works, e.g. `ananya@okaxis`. `fail@upi` is always declined.\n"
                        "- Card `4111 1111 1111 1111`, any future expiry, any 3-digit CVV succeeds.\n"
                        "- Card `4000 0000 0000 0002` is always declined.\n"
                        "- Card numbers and CVVs are checked with regex + the Luhn checksum and are **never saved** – "
                        "only a masked version like `Visa •••• 1111`."
                        + ("\n- Razorpay test mode: UPI `success@razorpay`, or the test cards in Razorpay's docs."
                           if gateway == "razorpay" else ""))

        if submitted:
            try:
                reply = api().donate(amount, fund, method, details, case_id)
            except ApiError as error:
                show_problems(error)
            else:
                tx = reply["donation"]
                if reply.get("checkout"):
                    st.session_state.pending_checkout = tx["transaction_id"]
                    st.session_state.checkout_url = reply["checkout"]["url"]
                else:
                    st.session_state.last_receipt = (tx["transaction_id"], reply["receipt"])
                    st.success(f"Payment successful – {inr(tx['amount'])} received. Reference **{tx['transaction_id']}**"
                               + (". Receipt e-mailed." if pan_note else "."))
                    st.balloons()
        _pending_checkout()
    with right:
        last = st.session_state.get("last_receipt")
        if last:
            section("Your receipt")
            st.markdown(f'<div class="pc-receipt">{esc(last[1])}</div>', unsafe_allow_html=True)
            st.download_button("Download receipt", last[1], file_name=f"{last[0]}.txt")
        _impact_card(user)
        section("Where the funds stand")
        for name, row in api().funds_overview().iterrows():
            used = row["allocated"] / row["raised"] if row["raised"] else 0
            st.markdown(f'<div class="pc-card"><h4>{esc(name)}</h4>{progress_bar(used)}'
                        f'<div class="pc-fund-row"><span>Raised</span><b>{inr(row["raised"])}</b></div>'
                        f'<div class="pc-fund-row"><span>Used for animals</span><b>{inr(row["allocated"])}</b></div>'
                        f'<div class="pc-fund-row"><span>Still available</span><b>{inr(row["available"])}</b></div></div>',
                        unsafe_allow_html=True)


def _impact_card(user) -> None:
    """The donor's own totals, so the column is never empty."""
    mine = api().donations()
    paid = pe.clean_donations(mine) if not mine.empty else mine
    total = float(paid["amount"].sum()) if not paid.empty else 0.0
    cases = paid[paid["case_id"] != ""]["case_id"].nunique() if not paid.empty else 0
    st.markdown(f'<div class="pc-card"><h4>Your impact 💝</h4>'
                f'<div class="pc-fund-row"><span>Given so far</span><b>{inr(total)}</b></div>'
                f'<div class="pc-fund-row"><span>Gifts</span><b>{len(paid)}</b></div>'
                f'<div class="pc-fund-row"><span>Animals you supported directly</span><b>{cases}</b></div>'
                '<div class="meta" style="margin-top:10px">Every receipt carries an 80G note for tax deduction.</div></div>',
                unsafe_allow_html=True)


def _pending_checkout() -> None:
    """A Razorpay order is waiting: link to the checkout page and a button to check the result."""
    tx_id = st.session_state.get("pending_checkout")
    if not tx_id:
        return
    st.info(f"Order created for **{tx_id}**. Finish the payment on Razorpay, then check the status here.")
    c1, c2 = st.columns(2)
    c1.link_button("Open Razorpay Checkout ↗", st.session_state.checkout_url, type="primary")
    if c2.button("I've paid – check status"):
        donation = api().donation(tx_id)
        if donation["status"] == "Pending":
            st.warning("Razorpay hasn't confirmed this payment yet. Try again in a few seconds.")
        else:
            st.session_state.pending_checkout = None
            if donation["status"] == "Success":
                st.session_state.last_receipt = (tx_id, api().receipt(tx_id))
                st.success("Payment confirmed – thank you!")
            else:
                st.error("The payment failed. Nothing was charged.")
            st.rerun()


# ======================================================================= my donations
def _my_donations(user) -> None:
    mine_all = api().donations()            # the API only returns this donor's own donations
    if mine_all.empty:
        empty_state("🧾", "No donations yet", "Your receipts will appear here.")
        return
    mine = pe.clean_donations(mine_all)
    stats = ns.financial_summary(mine["amount"])
    c1, c2, c3 = st.columns(3)
    kpi(c1, "Total given", inr(stats["total"]), accent=True)
    kpi(c2, "Donations", f"{int(stats['count'])}")
    kpi(c3, "Average gift", inr(round(stats["mean"])))
    st.write("")
    show_table(typed_view(mine_all), hide_index=True,
                 column_config={"Amount": st.column_config.NumberColumn(format="₹%d")})
    successful = mine_all[mine_all["status"] == "Success"]
    if not successful.empty:
        chosen = st.selectbox("Get a receipt again", successful["transaction_id"].iloc[::-1])
        st.download_button("Download receipt", api().receipt(chosen), file_name=f"{chosen}.txt")


def typed_view(df: pd.DataFrame) -> pd.DataFrame:
    view = df.iloc[::-1][["timestamp", "transaction_id", "amount", "contribution_type", "case_id",
                          "method", "masked_account", "status"]].copy()
    view["amount"] = pd.to_numeric(view["amount"], errors="coerce")
    view.columns = ["Date", "Reference", "Amount", "Fund", "Case", "Method", "Paid from", "Status"]
    return view


# ======================================================================= transparency
def render_transparency() -> None:
    summary, overview = api().summary(), api().funds_overview()
    raised, used = overview["raised"].sum(), overview["allocated"].sum()
    money = summary["money"]
    c1, c2, c3, c4 = st.columns(4)
    kpi(c1, "Raised so far", inr(raised), f"{int(money['count'])} donations", accent=True)
    kpi(c2, "Spent on animals", inr(used), f"{used / raised * 100:.0f}% of all money" if raised else "")
    kpi(c3, "Waiting to be used", inr(overview["available"].sum()), "general + feed fund")
    kpi(c4, "Average donation", inr(round(money["mean"])))
    st.write("")
    left, right = st.columns(2)
    left.pyplot(ns.plot_monthly_trend(summary["monthly_donations"], summary["monthly_expenditure"]))
    right.pyplot(ns.plot_fund_utilization(summary["utilization"]))

    section("Treatment funding by animal",
            "Estimated cost of each open case and how much of it donors and the shelter have covered.")
    table = api().case_funding()
    if table.empty:
        return
    table = table[table["status"] != "Reported"]
    show = table[["case_id", "animal_type", "injury_level", "status", "estimated_cost",
                  "direct_donations", "allocated_funds", "percent_funded"]].copy()
    show_table(
        show, hide_index=True,
        column_config={
            "case_id": "Case", "animal_type": "Animal", "injury_level": "Injury", "status": "Stage",
            "estimated_cost": st.column_config.NumberColumn("Est. cost", format="₹%d"),
            "direct_donations": st.column_config.NumberColumn("Given directly", format="₹%d"),
            "allocated_funds": st.column_config.NumberColumn("From shelter funds", format="₹%d"),
            "percent_funded": st.column_config.ProgressColumn("Funded", min_value=0, max_value=100,
                                                              format="%d%%"),
        })
