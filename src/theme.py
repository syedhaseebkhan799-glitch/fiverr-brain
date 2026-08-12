"""
The Silverthread Labs Hub look, applied to Streamlit.

Everything visual lives here, and every colour lives in `PALETTE` -- one dict,
one edit, whole app changes. Nothing in this module knows what a gig or a
seller is, so restyling can never break behaviour.

Streamlit gives no theming API beyond four colours in `config.toml`, so the
rest is CSS against Streamlit's own DOM. That DOM is not a public contract, so
every selector here is written to fail *soft*: if a future Streamlit release
renames something, the rule stops applying and the widget falls back to its
default appearance. Nothing here is load-bearing for using the app -- which is
why, for instance, the nav's radio dots are hidden by matching the element that
actually contains the `input` rather than by guessing at child order. A browser
without `:has()` shows the dots; a wrong guess would have hidden the labels.

The one rule that is *not* safe to broaden is the font. Streamlit renders its
chevrons as Material icon ligatures, so a font-family applied widely enough to
reach them replaces every arrow in the app with the literal word
"keyboard_arrow_right". The stack is therefore set on the document and the icon
font is pinned back by name.
"""
import streamlit as st

# --- The palette, read off the Hub ------------------------------------------

PALETTE = {
    "bg": "#0A0A0A",           # page
    "sidebar": "#0C0C0C",      # nav rail, separated from the page by a border
    "card": "#0E0E0E",         # panels, barely lifted off the page
    "raised": "#141414",       # hover states and inputs
    "border": "#1F1F1F",       # the thin lines that define every panel
    "hairline": "#171717",     # internal dividers, quieter than a border
    "text": "#EDEDED",
    "muted": "#8A8A8A",
    "accent": "#22C55E",       # the Hub's green: active nav, positives, focus
    "accent_soft": "rgba(34, 197, 94, 0.10)",
    "accent_ink": "#06180E",   # text on a filled green button
    "danger": "#F87171",
    "danger_soft": "rgba(248, 113, 113, 0.10)",
    "warn": "#EAB308",
    "warn_soft": "rgba(234, 179, 8, 0.10)",
}

# Segoe UI on Windows, San Francisco on a Mac -- the Hub's screenshot is Segoe,
# and a system stack matches it without shipping a webfont the app would then
# have to load from a third party on every page view.
FONT_STACK = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, '
    '"Helvetica Neue", Arial, sans-serif'
)
DISPLAY_STACK = 'Georgia, "Times New Roman", serif'

_INJECTED = "_stl_theme_injected"


def _css() -> str:
    p = PALETTE
    return f"""
<style>
:root {{
  --stl-bg: {p['bg']};
  --stl-sidebar: {p['sidebar']};
  --stl-card: {p['card']};
  --stl-raised: {p['raised']};
  --stl-border: {p['border']};
  --stl-hairline: {p['hairline']};
  --stl-text: {p['text']};
  --stl-muted: {p['muted']};
  --stl-accent: {p['accent']};
  --stl-accent-soft: {p['accent_soft']};
  --stl-danger: {p['danger']};
  --stl-danger-soft: {p['danger_soft']};
  --stl-warn: {p['warn']};
  --stl-warn-soft: {p['warn_soft']};
}}

/* --- Page shell --------------------------------------------------------- */

html, body, .stApp {{ font-family: {FONT_STACK}; }}
.stApp {{ background: var(--stl-bg); color: var(--stl-text); }}

/* Streamlit draws its chevrons and control glyphs as Material *ligatures*:
   the element's text really is "keyboard_arrow_right", and only the icon font
   turns it into an arrow. Inheriting a text font here does not restyle the
   icon, it prints the word -- so icons are pinned back explicitly. */
[data-testid="stIconMaterial"], .material-icons, [class*="material-symbols"] {{
  font-family: "Material Symbols Rounded" !important;
}}

/* The default toolbar floats over the content. Left in place so the sidebar
   collapse control survives on a phone, but made invisible. */
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stToolbar"] {{ right: 0.5rem; }}
#MainMenu, footer {{ visibility: hidden; }}

.block-container {{ padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1100px; }}

h1, h2, h3, h4 {{ color: var(--stl-text); letter-spacing: -0.01em; }}
hr {{ border-color: var(--stl-hairline); }}
a {{ color: var(--stl-accent); }}

/* --- Sidebar ------------------------------------------------------------ */

[data-testid="stSidebar"] {{
  background: var(--stl-sidebar);
  border-right: 1px solid var(--stl-border);
}}
[data-testid="stSidebar"] .block-container {{ padding-top: 1rem; }}
[data-testid="stSidebar"] hr {{ margin: 0.9rem 0; }}

/* Nav: one radio group, drawn as the Hub's rail. The dot is hidden by
   matching the wrapper that *contains* the input, so a miss leaves a visible
   dot rather than an invisible label. */
[data-testid="stSidebar"] [role="radiogroup"] {{ gap: 2px; }}
[data-testid="stSidebar"] [role="radiogroup"] label {{
  display: flex; align-items: center;
  padding: 8px 11px; margin: 0;
  border-radius: 8px;
  border-left: 2px solid transparent;
  transition: background 0.12s ease, border-color 0.12s ease;
}}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {{
  background: var(--stl-raised);
}}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
  background: var(--stl-accent-soft);
  border-left-color: var(--stl-accent);
}}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {{
  color: var(--stl-text); font-weight: 600;
}}
/* The dot itself: the box immediately before the label's text. Matched by its
   relationship to that text rather than by its emotion hash, and deliberately
   NOT by hiding the wrapper around the `input` -- that element is what keyboard
   focus lands on, so hiding it would cost the nav its tab order. */
[data-testid="stSidebar"] [role="radiogroup"] label
  div:has(> div[data-testid="stMarkdownContainer"]) > div:first-child {{
  display: none;
}}
[data-testid="stSidebar"] [role="radiogroup"] label p {{
  font-size: 0.92rem; color: var(--stl-muted);
}}

/* --- Panels ------------------------------------------------------------- */

[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) {{
  border-radius: 10px;
}}
[data-testid="stExpander"] details {{
  background: var(--stl-card);
  border: 1px solid var(--stl-border);
  border-radius: 10px;
}}
[data-testid="stExpander"] summary:hover {{ color: var(--stl-accent); }}

[data-testid="stMetric"] {{
  background: var(--stl-card);
  border: 1px solid var(--stl-border);
  border-radius: 10px;
  padding: 14px 16px;
}}
[data-testid="stMetricValue"] {{ color: var(--stl-accent); font-weight: 600; }}
[data-testid="stMetricLabel"] p {{ color: var(--stl-muted); }}

[data-testid="stAlert"] {{ border-radius: 10px; }}

[data-testid="stChatMessage"] {{
  background: var(--stl-card);
  border: 1px solid var(--stl-border);
  border-radius: 10px;
}}
[data-testid="stChatInput"] {{
  background: var(--stl-card);
  border: 1px solid var(--stl-border);
  border-radius: 10px;
}}

/* --- Controls ----------------------------------------------------------- */

.stButton > button, .stDownloadButton > button {{
  background: var(--stl-card);
  color: var(--stl-text);
  border: 1px solid var(--stl-border);
  border-radius: 8px;
  font-weight: 500;
  transition: background 0.12s ease, border-color 0.12s ease, color 0.12s ease;
}}
.stButton > button:hover, .stDownloadButton > button:hover {{
  background: var(--stl-accent-soft);
  border-color: var(--stl-accent);
  color: var(--stl-accent);
}}
.stButton > button[kind="primary"] {{
  background: var(--stl-accent);
  border-color: var(--stl-accent);
  color: {p['accent_ink']};
  font-weight: 600;
}}
.stButton > button[kind="primary"]:hover {{
  background: #1EA855; border-color: #1EA855; color: {p['accent_ink']};
}}

.stTextInput input, .stTextArea textarea, .stNumberInput input {{
  background: var(--stl-raised) !important;
  border-color: var(--stl-border) !important;
  color: var(--stl-text) !important;
}}
[data-baseweb="select"] > div {{
  background: var(--stl-raised) !important;
  border-color: var(--stl-border) !important;
}}
[data-testid="stFileUploaderDropzone"] {{
  background: var(--stl-card);
  border: 1px dashed var(--stl-border);
  border-radius: 10px;
}}
[data-testid="stFileUploaderDropzone"]:hover {{ border-color: var(--stl-accent); }}

/* --- Pieces drawn by this module --------------------------------------- */

.stl-brand {{
  display: flex; align-items: center; gap: 10px;
  padding: 4px 2px 14px 2px;
  border-bottom: 1px solid var(--stl-border);
  margin-bottom: 14px;
}}
.stl-brand-mark {{
  width: 30px; height: 30px; flex: none;
  display: grid; place-items: center;
  background: var(--stl-accent-soft);
  border: 1px solid var(--stl-border);
  border-radius: 8px;
  font-size: 15px;
}}
.stl-brand-name {{
  font-size: 0.98rem; font-weight: 650; color: var(--stl-text);
  line-height: 1.15;
}}
.stl-brand-sub {{ font-size: 0.7rem; color: var(--stl-muted); letter-spacing: 0.04em; }}

.stl-crumb {{
  font-size: 0.8rem; color: var(--stl-muted); margin-bottom: 2px;
}}
.stl-crumb b {{ color: var(--stl-text); font-weight: 500; }}
.stl-title {{
  font-family: {DISPLAY_STACK}; font-style: italic;
  font-size: 1.72rem; color: var(--stl-text);
  margin: 0 0 2px 0; line-height: 1.2;
}}
.stl-sub {{ font-size: 0.86rem; color: var(--stl-muted); margin-bottom: 4px; }}

.stl-pill {{
  display: inline-flex; align-items: center; gap: 6px;
  padding: 3px 10px; border-radius: 999px;
  font-size: 0.76rem; font-weight: 600; line-height: 1.5;
  border: 1px solid transparent;
}}
.stl-pill.ok {{
  color: var(--stl-accent); background: var(--stl-accent-soft);
  border-color: rgba(34, 197, 94, 0.35);
}}
.stl-pill.bad {{
  color: var(--stl-danger); background: var(--stl-danger-soft);
  border-color: rgba(248, 113, 113, 0.35);
}}
.stl-pill.warn {{
  color: var(--stl-warn); background: var(--stl-warn-soft);
  border-color: rgba(234, 179, 8, 0.35);
}}
.stl-pill.mute {{
  color: var(--stl-muted); background: var(--stl-raised);
  border-color: var(--stl-border);
}}

.stl-account {{
  display: flex; align-items: center; gap: 10px;
  padding: 10px; border-radius: 10px;
  background: var(--stl-card); border: 1px solid var(--stl-border);
}}
.stl-avatar {{
  width: 30px; height: 30px; flex: none;
  display: grid; place-items: center; border-radius: 8px;
  background: var(--stl-accent-soft); color: var(--stl-accent);
  font-size: 0.75rem; font-weight: 700; letter-spacing: 0.02em;
}}
.stl-account-name {{
  font-size: 0.84rem; font-weight: 600; color: var(--stl-text); line-height: 1.2;
}}
.stl-account-sub {{
  font-size: 0.72rem; color: var(--stl-muted);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}

.stl-note {{
  padding: 14px 16px; border-radius: 10px;
  background: var(--stl-card); border: 1px solid var(--stl-border);
  border-left: 3px solid var(--stl-accent);
  font-size: 0.9rem; color: var(--stl-muted);
}}
.stl-note.bad {{ border-left-color: var(--stl-danger); }}
.stl-note b {{ color: var(--stl-text); }}

.stl-section {{
  font-size: 0.68rem; font-weight: 700; letter-spacing: 0.09em;
  color: var(--stl-muted); text-transform: uppercase;
  margin: 2px 0 6px 2px;
}}
</style>
"""


def inject():
    """Apply the stylesheet. Cheap enough to call on every rerun."""
    st.markdown(_css(), unsafe_allow_html=True)
    st.session_state[_INJECTED] = True


# --- Small pieces -----------------------------------------------------------

def brand(name: str = "Fiverr Brain", sub: str = "SILVERTHREAD LABS",
          mark: str = "🧠"):
    """The rail's masthead, matching the Hub's logo block."""
    st.markdown(
        f'<div class="stl-brand">'
        f'  <div class="stl-brand-mark">{mark}</div>'
        f'  <div>'
        f'    <div class="stl-brand-name">{name}</div>'
        f'    <div class="stl-brand-sub">{sub}</div>'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def section(label: str):
    st.markdown(f'<div class="stl-section">{label}</div>', unsafe_allow_html=True)


def page_header(section_name: str, page: str, subtitle: str = "",
                pills: str = ""):
    """Breadcrumb, title, and an optional right-hand status pill row."""
    crumb = (f'<div class="stl-crumb">{section_name} &nbsp;›&nbsp; '
             f'<b>{page}</b></div>')
    title = f'<div class="stl-title">{page}</div>'
    sub = f'<div class="stl-sub">{subtitle}</div>' if subtitle else ""

    if pills:
        left, right = st.columns([3, 2], vertical_alignment="center")
        with left:
            st.markdown(crumb + title + sub, unsafe_allow_html=True)
        with right:
            st.markdown(
                f'<div style="text-align:right">{pills}</div>',
                unsafe_allow_html=True,
            )
    else:
        st.markdown(crumb + title + sub, unsafe_allow_html=True)

    st.markdown(
        '<hr style="margin:14px 0 18px 0;border:none;'
        'border-top:1px solid var(--stl-border)">',
        unsafe_allow_html=True,
    )


def pill(text: str, kind: str = "mute") -> str:
    """A status chip. `kind` is one of: ok, bad, warn, mute."""
    return f'<span class="stl-pill {kind}">{text}</span>'


def note(html: str, kind: str = "ok"):
    css_class = "stl-note bad" if kind == "bad" else "stl-note"
    st.markdown(f'<div class="{css_class}">{html}</div>', unsafe_allow_html=True)


def account_card(name: str, sub: str):
    """The rail's footer card -- who the answers are about."""
    initials = "".join(w[0] for w in str(name).split()[:2]).upper() or "FB"
    st.markdown(
        f'<div class="stl-account">'
        f'  <div class="stl-avatar">{initials}</div>'
        f'  <div style="min-width:0">'
        f'    <div class="stl-account-name">{name}</div>'
        f'    <div class="stl-account-sub">{sub}</div>'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )
