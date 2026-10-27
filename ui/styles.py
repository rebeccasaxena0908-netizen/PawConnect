"""
Look and feel for the Streamlit app – the "Dusk Rose" theme.

Dark, warm and caring, like a shelter at dusk: a warm charcoal page with a soft
rose glow top-right and a blue glow bottom-left, cards with a 1px border and a
faint inner highlight, dusty rose for actions and key numbers, soft blue for
information, warm sand for warnings and mint green for good news.

How theming works
-----------------
* Every colour comes from config.THEMES (dark or light). We turn the chosen
  palette into CSS variables (--bg, --text, --accent ...) and the stylesheet below
  only ever uses those variables – so switching theme just swaps the variables.
* Streamlit's own widgets are dark from .streamlit/config.toml; the rules below
  restyle them with the same variables so they follow the light theme too.
* The sidebar toggle stores the choice in a small cookie (pc_theme) so the app
  remembers it next time. Dark is the default.
"""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from analytics import numpy_stats as ns
from config import DEFAULT_THEME, FONTS, THEMES, injury_colors, status_colors

# ---------------------------------------------------------------- the stylesheet (uses only CSS variables)
CSS = """
html, body, .stApp, .stMarkdown, p, label, input, textarea, button, li {
  font-family: var(--font-body), system-ui, -apple-system, 'Segoe UI', sans-serif;
}
.stApp {
  background:
    radial-gradient(1100px 640px at 100% -8%, var(--glow-rose), transparent 62%),
    radial-gradient(900px 640px at -8% 108%, var(--glow-blue), transparent 60%),
    var(--bg) !important;
  background-attachment: fixed !important;
  color: var(--text);
}
.stApp, .stApp p, .stApp li, .stApp label, .stApp span, .stApp div[data-testid="stMarkdownContainer"],
.stApp [data-testid="stWidgetLabel"] p { color: var(--text); }
.stApp [data-testid="stCaptionContainer"], .stApp [data-testid="stCaptionContainer"] p,
.stApp small { color: var(--muted) !important; }
h1, h2, h3, h4, .pc-hero h1, .pc-section, .pc-card h4 {
  font-family: var(--font-heading), Georgia, serif !important; color: var(--text) !important;
  letter-spacing: -.01em;
}
.stApp a, .stApp a:visited, [data-testid="stSidebar"] a { color: var(--accent2) !important; }
[data-testid="stHeader"] { background: transparent !important; }
/* use the whole screen – no narrow centre column with empty sides */
.block-container { padding: 1.6rem 2.4rem 3rem !important; max-width: 100% !important; }
@media (min-width: 1800px) { .block-container { padding-left: 4rem !important; padding-right: 4rem !important; } }
/* cards in the same row line up to the same height */
.stApp [data-testid="stHorizontalBlock"] { align-items: stretch; }
.stApp [data-testid="stColumn"] > div > [data-testid="stVerticalBlock"] { height: 100%; }
.stApp [data-testid="stColumn"] .pc-kpi { min-height: 132px; }
/* tabular numbers for all money and counts */
.pc-num, .pc-kpi .value, .pc-receipt, [data-testid="stMetricValue"], .pc-pill { font-variant-numeric: tabular-nums; }

/* ---------- sidebar */
[data-testid="stSidebar"] {
  background: color-mix(in srgb, var(--surface) 92%, transparent) !important;
  border-right: 1px solid var(--border);
}
[data-testid="stSidebar"] * { color: var(--text); }

/* ---------- hero */
.pc-hero {
  border-radius: 20px; padding: 26px 30px; margin-bottom: 18px; position: relative; overflow: hidden;
  background: linear-gradient(135deg, var(--raised), var(--surface) 70%);
  border: 1px solid var(--border);
  box-shadow: inset 0 1px 0 var(--highlight), 0 18px 40px -24px var(--shadow);
}
.pc-hero::after {
  content: "🐾"; position: absolute; right: 24px; top: 4px; font-size: 96px; opacity: .07; transform: rotate(18deg);
}
.pc-hero .eyebrow { text-transform: uppercase; letter-spacing: .16em; font-size: 12px; font-weight: 700; color: var(--accent); }
.pc-hero h1 { margin: 4px 0 6px; font-size: 32px; line-height: 1.15; }
.pc-hero p { margin: 0; color: var(--muted) !important; font-size: 15.5px; max-width: 760px; }

/* ---------- KPI tiles: muted uppercase label, big Fraunces number, 2px line along the bottom */
.pc-kpi {
  position: relative; overflow: hidden; height: 100%;
  background: var(--surface); border: 1px solid var(--border); border-radius: 18px;
  padding: 16px 18px 16px; box-shadow: inset 0 1px 0 var(--highlight), 0 10px 26px -20px var(--shadow);
}
.pc-kpi::after {
  content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 2px; background: var(--tone, var(--border));
}
.pc-kpi .label { font-size: 12px; color: var(--muted); font-weight: 700; text-transform: uppercase; letter-spacing: .08em; }
.pc-kpi .value { font-family: var(--font-heading), Georgia, serif; font-size: 28px; font-weight: 700; color: var(--text); margin-top: 4px; }
.pc-kpi .note { font-size: 13px; color: var(--muted); margin-top: 2px; }
.pc-kpi.accent { background: linear-gradient(150deg, color-mix(in srgb, var(--accent) 16%, var(--surface)), var(--surface) 75%); }
.pc-kpi.accent .value { color: var(--accent); }

/* ---------- cards (lift only when the card is something you act on) */
.pc-card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 18px;
  padding: 16px 18px; margin-bottom: 12px;
  box-shadow: inset 0 1px 0 var(--highlight), 0 12px 28px -22px var(--shadow);
  transition: transform 150ms ease, border-color 150ms ease, box-shadow 150ms ease;
}
.pc-card.clickable:hover { transform: translateY(-2px); border-color: var(--border-strong);
                           box-shadow: inset 0 1px 0 var(--highlight), 0 18px 34px -20px var(--shadow); }
.pc-card h4 { margin: 0 0 6px; font-size: 19px; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.pc-card .meta { color: var(--muted) !important; font-size: 13.5px; line-height: 1.55; }
.pc-card .meta b { color: var(--text); }
.pc-steps { line-height: 1.9 !important; }
.pc-badges { font-size: 13px; font-family: var(--font-body); }
/* adoption catalogue: a big emoji / photo area on top of the card */
.pc-animal { padding: 0 0 16px; overflow: hidden; }
.pc-animal { min-height: 372px; }          /* same height for every card in a row → buttons line up */
.pc-clamp { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.pc-animal .pc-animal-art {
  height: 130px; display: grid; place-items: center; font-size: 64px; margin-bottom: 12px;
  background: radial-gradient(circle at 50% 120%, color-mix(in srgb, var(--accent) 22%, transparent), transparent 70%), var(--raised);
  border-bottom: 1px solid var(--border);
}
.pc-animal > :not(.pc-animal-art) { margin-left: 18px; margin-right: 18px; }

/* ---------- sign-in page blocks */
.pc-steps-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 18px; margin-top: 6px; }
.pc-step { display: flex; gap: 10px; align-items: flex-start; padding: 10px 12px; border-radius: 12px;
           background: var(--raised); border: 1px solid var(--border); }
.pc-step-icon { font-size: 20px; line-height: 1.2; }
.pc-step .meta { font-size: 13px; }
.pc-mini-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 6px; }
.pc-mini-animal { display: flex; gap: 12px; align-items: center; padding: 10px; border-radius: 14px;
                  background: var(--raised); border: 1px solid var(--border); }
.pc-mini-art { width: 52px; height: 52px; flex: none; display: grid; place-items: center; font-size: 30px;
               border-radius: 12px; background: color-mix(in srgb, var(--accent) 16%, var(--surface)); }
.pc-cards-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px;
                align-items: stretch; margin-bottom: 12px; }
.pc-cards-row > .pc-card { margin-bottom: 0; height: 100%; }
.pc-demo-row { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 12px; padding: 7px 0;
               border-top: 1px solid var(--border); }
.pc-demo-row:first-of-type { border-top: none; }
.pc-demo-row .pc-pill { min-width: 66px; text-align: center; }
.pc-demo-mail { flex: 1 1 200px; font-size: 13.5px; color: var(--text); overflow-wrap: anywhere; }
.pc-demo-pass { font-size: 12.5px; color: var(--muted); background: var(--raised); padding: 2px 8px; border-radius: 8px; }
.pc-feature { height: 100%; }
.pc-feature-icon { font-size: 28px; margin-bottom: 6px; }
.pc-side-list { margin: 6px 0 0; padding-left: 18px; color: var(--muted); font-size: 13.5px; line-height: 1.7; }
.pc-side-list b { color: var(--text); }
.pc-fund-row { display: flex; justify-content: space-between; font-size: 13.5px; color: var(--muted); margin-top: 4px; }
.pc-fund-row b { color: var(--text); font-variant-numeric: tabular-nums; }
@media (max-width: 900px) { .pc-steps-grid, .pc-mini-grid { grid-template-columns: 1fr; } }

/* ---------- pills: translucent tint, tinted border, same-colour text */
.pc-pill {
  display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 12px; font-weight: 700;
  margin: 2px 4px 2px 0; white-space: nowrap; font-family: var(--font-body);
  color: var(--pill); background: color-mix(in srgb, var(--pill) 15%, transparent);
  border: 1px solid color-mix(in srgb, var(--pill) 38%, transparent);
}
.stApp .pc-pill, [data-testid="stSidebar"] .pc-pill { color: var(--pill) !important; }
.pc-pill.strong { background: color-mix(in srgb, var(--pill) 24%, transparent); border-color: var(--pill); }

.pc-section { font-size: 21px; font-weight: 700; margin: 14px 0 2px; }
.pc-caption { color: var(--muted); font-size: 14px; margin-bottom: 10px; }
.pc-empty {
  text-align: center; padding: 28px 16px; border: 1.5px dashed var(--border-strong); border-radius: 18px;
  color: var(--muted); background: color-mix(in srgb, var(--surface) 60%, transparent);
}
.pc-empty .big { font-size: 36px; }
.pc-empty b { color: var(--text); }
.pc-receipt {
  font-family: ui-monospace, 'SF Mono', Menlo, monospace; font-size: 13px; white-space: pre-wrap;
  background: var(--raised); color: var(--text); border: 1px dashed var(--border-strong);
  border-radius: 14px; padding: 16px;
}
.pc-progress { height: 8px; background: var(--raised); border-radius: 99px; overflow: hidden; margin: 8px 0 4px; }
.pc-progress > span { display: block; height: 100%; border-radius: 99px;
                      background: linear-gradient(90deg, var(--accent), var(--accent2)); }

/* ---------- buttons: secondary = transparent with a border, primary = rose gradient with a glow */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button, .stLinkButton > a {
  border-radius: 12px !important; font-weight: 700; background: transparent !important;
  color: var(--text) !important; border: 1px solid var(--border-strong) !important;
  transition: transform 150ms ease, background 150ms ease, border-color 150ms ease, box-shadow 150ms ease;
}
.stButton > button:hover, .stDownloadButton > button:hover, .stFormSubmitButton > button:hover,
.stLinkButton > a:hover { border-color: var(--accent) !important; background: var(--raised) !important; }
.stButton > button:active, .stFormSubmitButton > button:active { transform: translateY(1px); }
.stApp button[kind^="primary"], .stApp a[kind^="primary"] {
  background: linear-gradient(135deg, var(--accent-fill), var(--accent-fill-deep)) !important;
  color: var(--on-accent) !important; border: 1px solid transparent !important;
  box-shadow: 0 8px 22px -10px var(--accent);
}
.stApp button[kind^="primary"] *, .stApp a[kind^="primary"] * { color: var(--on-accent) !important; }
.stApp button[kind^="primary"]:hover, .stApp a[kind^="primary"]:hover {
  box-shadow: 0 12px 28px -10px var(--accent); filter: brightness(1.05);
}
.stApp button:disabled { opacity: .5; cursor: not-allowed; }

/* ---------- focus ring: 3px rose at 22 % */
.stApp button:focus-visible, .stApp a:focus-visible, .stApp [role="tab"]:focus-visible,
.stApp [role="checkbox"]:focus-visible, .stApp [role="radio"]:focus-visible, .stApp [role="switch"]:focus-visible {
  outline: none !important; box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 22%, transparent),
                                        0 0 0 1px var(--accent) !important;
}

/* ---------- inputs: page-coloured fill, border, rose border + glow on focus */
.stApp [data-baseweb="input"], .stApp [data-baseweb="base-input"], .stApp [data-baseweb="textarea"],
.stApp [data-baseweb="select"] > div, .stApp [data-testid="stNumberInputContainer"],
.stApp [data-testid="stTextInputRootElement"], .stApp [data-testid="stTextAreaRootElement"],
.stApp [data-testid="stSelectbox"] [role="combobox"], .stApp [data-testid="stMultiSelect"] [role="combobox"] {
  background: var(--bg) !important; border-color: var(--border) !important; border-radius: 12px !important;
  transition: border-color 150ms ease, box-shadow 150ms ease;
}
.stApp [data-testid="stTextInputRootElement"]:focus-within, .stApp [data-testid="stTextAreaRootElement"]:focus-within,
.stApp [data-baseweb="input"]:focus-within, .stApp [data-baseweb="textarea"]:focus-within,
.stApp [data-baseweb="select"] > div:focus-within, .stApp [data-testid="stNumberInputContainer"]:focus-within {
  border-color: var(--accent) !important; box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 22%, transparent) !important;
}
.stApp input, .stApp textarea, .stApp [data-baseweb="select"] * { color: var(--text) !important; -webkit-text-fill-color: var(--text); }
.stApp input::placeholder, .stApp textarea::placeholder { color: var(--muted) !important; -webkit-text-fill-color: var(--muted); opacity: 1; }
.stApp [data-testid="stNumberInputContainer"] button { background: var(--raised) !important; color: var(--text) !important; }
.stApp [data-baseweb="tag"] { background: color-mix(in srgb, var(--accent) 18%, transparent) !important; }
.stApp [data-baseweb="tag"] span { color: var(--text) !important; }
[data-baseweb="popover"] [role="listbox"], [data-baseweb="popover"] ul, [data-baseweb="menu"] {
  background: var(--raised) !important; border: 1px solid var(--border-strong); border-radius: 12px;
}
[data-baseweb="popover"] li { color: var(--text) !important; background: transparent; }
[data-baseweb="popover"] li:hover, [data-baseweb="popover"] li[aria-selected="true"] {
  background: color-mix(in srgb, var(--accent) 16%, transparent) !important;
}
.stApp [data-testid="stFileUploaderDropzone"] {
  background: var(--bg) !important; border: 1.5px dashed var(--border-strong) !important; border-radius: 14px;
}
.stApp [data-testid="stFileUploaderDropzone"] * { color: var(--muted); }

/* ---------- forms, expanders, alerts */
[data-testid="stForm"] {
  background: var(--surface); border: 1px solid var(--border) !important; border-radius: 18px;
  box-shadow: inset 0 1px 0 var(--highlight); padding: 18px 18px 8px;
}
[data-testid="stExpander"] details { background: var(--surface); border: 1px solid var(--border) !important; border-radius: 14px; }
[data-testid="stExpander"] summary { color: var(--text) !important; border-radius: 14px; }
[data-testid="stExpander"] summary:hover { color: var(--accent) !important; }
.stApp [data-testid="stAlertContainer"] { background: var(--surface) !important; border: 1px solid var(--border); border-radius: 14px; }
.stApp [data-testid="stAlertContainer"] * { color: var(--text) !important; }
.stApp [data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) { border-left: 3px solid var(--danger) !important; }
.stApp [data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) { border-left: 3px solid var(--accent3) !important; }
.stApp [data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) { border-left: 3px solid var(--success) !important; }
.stApp [data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) { border-left: 3px solid var(--accent2) !important; }
.stApp hr { border-color: var(--border) !important; }

/* ---------- tabs: muted text; the active tab is a raised pill with rose text */
.stTabs [role="tablist"] {
  gap: 4px; flex-wrap: wrap; background: var(--surface); border: 1px solid var(--border);
  border-radius: 14px; padding: 5px; width: fit-content; max-width: 100%; border-bottom: 1px solid var(--border) !important;
}
.stTabs [role="tab"] {
  border-radius: 10px; padding: 8px 14px !important; font-weight: 700; color: var(--muted) !important;
  background: transparent; height: auto; transition: background 150ms ease, color 150ms ease;
  border: none !important;
}
.stTabs [role="tab"] [data-testid="stMarkdownContainer"], .stTabs [role="tab"] p,
.stTabs [role="tab"] span { color: inherit !important; font-weight: 700; }
.stTabs [role="tab"] > div:not([data-testid]) { display: none !important; }      /* default underline */
.stTabs [role="tab"]:hover { color: var(--text) !important; }
.stTabs [role="tab"][aria-selected="true"] { background: var(--raised) !important; color: var(--accent) !important; }
.stTabs [role="tablist"] > :not([role="tab"]) { display: none !important; }    /* default underline */

/* ---------- data tables (cells are coloured by table(); the header stays put while scrolling) */
.stApp [data-testid="stDataFrame"], .stApp [data-testid="stTable"] {
  border: 1px solid var(--border); border-radius: 14px; overflow: hidden;
}

/* ---------- radio dots, checkboxes and the toggle switch follow the palette too
   (Streamlit 1.66 markup: <label><span><input …></span><div>box / track</div>…</label>) */
.stApp label[data-testid="stRadioOption"]:not([data-selected="true"]) > div > div:first-child {
  background: var(--bg) !important; border: 1.5px solid var(--border-strong) !important;
}
.stApp label:has(> span > input[type="checkbox"]:not([role="switch"]):not(:checked)) > span + div {
  background: var(--bg) !important; border: 1.5px solid var(--border-strong) !important;
}
.stApp label:has(> span > input[role="switch"]) > span + div { background: var(--border-strong) !important; }
.stApp label:has(> span > input[role="switch"]) > span + div > div { background: var(--surface) !important;
  box-shadow: 0 1px 3px var(--shadow); }
.stApp label:has(> span > input[role="switch"]:checked) > span + div { background: var(--accent) !important; }
.stApp label:has(> span > input[role="switch"]:checked) > span + div > div { background: var(--on-accent) !important; }
.stApp [data-testid="stRadio"] label p, .stApp [data-testid="stCheckbox"] label p,
.stApp [data-testid="stToggle"] label p { color: var(--text) !important; }

@media (max-width: 640px) {
  .pc-hero { padding: 20px; } .pc-hero h1 { font-size: 25px; } .pc-kpi .value { font-size: 23px; }
}
@media (prefers-reduced-motion: reduce) {
  .pc-card, .stButton > button { transition: none !important; }
  .pc-card.clickable:hover { transform: none; }
}
"""

_cookie_writer = None


# ======================================================================= theme
def theme_name() -> str:
    """'dark' or 'light' for this browser session (remembered in the pc_theme cookie)."""
    if "theme" not in st.session_state:
        try:
            saved = st.context.cookies.get("pc_theme")
        except Exception:        # noqa: BLE001 – no browser (e.g. tests)
            saved = None
        st.session_state.theme = saved if saved in THEMES else DEFAULT_THEME
    return st.session_state.theme


def palette() -> dict:
    return THEMES[theme_name()]


def _variables(colors: dict) -> str:
    names = {key: "--" + key.replace("_", "-") for key in colors}
    lines = [f"{names[k]}: {v};" for k, v in colors.items()]
    lines += [f"--font-heading: '{FONTS['heading']}'; --font-body: '{FONTS['body']}';",
              f"color-scheme: {theme_name()};"]
    return ":root, .stApp { " + " ".join(lines) + " }"


def inject_css() -> None:
    """Put the theme variables + stylesheet on the page and point the charts at the same palette."""
    colors = palette()
    ns.use_theme(colors)               # charts drawn in this session use the same colours
    st.markdown(f'<style>@import url("{FONTS["google_css"]}");\n{_variables(colors)}\n{CSS}</style>',
                unsafe_allow_html=True)


def theme_toggle() -> None:
    """Light / dark switch for the sidebar. Changes at once; the cookie remembers it for next time."""
    dark = st.toggle("🌙 Dark mode", value=theme_name() == "dark", key="theme_toggle")
    wanted = "dark" if dark else "light"
    if wanted != st.session_state.theme:
        st.session_state.theme = wanted
        st.rerun()
    _remember_theme(wanted)


def _remember_theme(name: str) -> None:
    """Write the pc_theme cookie from the browser (a tiny st.components.v2 component, no iframe)."""
    global _cookie_writer
    if _cookie_writer is None:
        _cookie_writer = st.components.v2.component(
            "pc_theme_cookie",
            js="""
export default function ({ data }) {
  if (data === "dark" || data === "light") {
    document.cookie = `pc_theme=${data}; path=/; max-age=31536000; SameSite=Lax`;
  }
}
""")
    _cookie_writer(data=name, key="pc_theme_cookie")


# ======================================================================= building blocks
def esc(value) -> str:
    """Escape user text before putting it into HTML."""
    return html.escape("" if value is None else str(value))


def color(name_or_hex: str | None) -> str:
    """'accent2' → the current theme's soft blue; '#123456' stays as it is."""
    colors = palette()
    if not name_or_hex:
        return colors["accent2"]
    return colors.get(name_or_hex, name_or_hex)


def hero(eyebrow: str, title: str, text: str) -> None:
    st.markdown(f'<div class="pc-hero"><div class="eyebrow">{esc(eyebrow)}</div>'
                f'<h1>{esc(title)}</h1><p>{esc(text)}</p></div>', unsafe_allow_html=True)


def kpi(column, label: str, value: str, note: str = "", accent: bool = False, tone: str = "") -> None:
    """KPI tile. accent=True → the rose headline tile; tone='accent2'/'accent3'/'success' colours its bottom line."""
    line = color("accent" if accent and not tone else tone) if (accent or tone) else ""
    style = f' style="--tone:{line}"' if line else ""
    column.markdown(f'<div class="pc-kpi{" accent" if accent else ""}"{style}><div class="label">{esc(label)}</div>'
                    f'<div class="value">{esc(value)}</div><div class="note">{esc(note)}</div></div>',
                    unsafe_allow_html=True)


def section(title: str, caption: str = "") -> None:
    st.markdown(f'<div class="pc-section">{esc(title)}</div>'
                + (f'<div class="pc-caption">{esc(caption)}</div>' if caption else ""),
                unsafe_allow_html=True)


def pill(text: str, tone: str | None = None, filled: bool = False) -> str:
    """Rounded badge. tone = a palette name ('success', 'danger', 'muted' ...); default = the stage's colour."""
    shade = color(tone) if tone else status_colors(palette()).get(text, palette()["accent2"])
    return f'<span class="pc-pill{" strong" if filled else ""}" style="--pill:{shade}">{esc(text)}</span>'


def injury_pill(level: str) -> str:
    return pill(level, injury_colors(palette()).get(level), filled=level == "Critical")


def progress_bar(fraction: float) -> str:
    fraction = max(0.0, min(1.0, float(fraction)))
    return f'<div class="pc-progress"><span style="width:{fraction * 100:.0f}%"></span></div>'


def empty_state(emoji: str, title: str, text: str = "") -> None:
    st.markdown(f'<div class="pc-empty"><div class="big">{esc(emoji)}</div><b>{esc(title)}</b>'
                + (f"<div>{esc(text)}</div>" if text else "") + "</div>", unsafe_allow_html=True)


def card_row(*cards: str) -> None:
    """Cards side by side with equal height (a CSS grid); they stack on a phone."""
    st.markdown(f'<div class="pc-cards-row">{"".join(cards)}</div>', unsafe_allow_html=True)


def table(df: pd.DataFrame, **kwargs) -> None:
    """
    st.dataframe with zebra rows in the theme's colours (pandas Styler). Streamlit
    paints tables on a canvas, so CSS can't reach the cells – the Styler can.
    """
    colors = palette()
    if len(df) > 2000:                     # very big tables: skip styling, keep it fast
        st.dataframe(df, **kwargs)
        return
    base, zebra = colors["surface"], _blend(colors["raised"], colors["surface"], 0.55)   # raised at low opacity
    styler = df.style.apply(
        lambda column: [f"background-color: {zebra if i % 2 else base}; color: {colors['text']}"
                        for i in range(len(column))], axis=0)
    st.dataframe(styler, **kwargs)


def _blend(top: str, bottom: str, alpha: float) -> str:
    """Solid colour that looks like `top` at `alpha` opacity over `bottom` (both #RRGGBB)."""
    a = [int(top[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(bottom[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * alpha + y * (1 - alpha)):02X}" for x, y in zip(a, b))


def inr(amount) -> str:
    from services.notification_service import format_inr
    return format_inr(amount or 0).replace(".00", "")


def show_problems(error) -> None:
    problems = getattr(error, "problems", [str(error)])
    st.error("\n".join(f"- {p}" for p in problems) if len(problems) > 1 else problems[0])
