"""Dnner palette, Gradio theme and CSS.

Palette (darkest -> lightest): espresso #4A413C, terracotta #BB6C43, clay #C8906D, sand #CCB499, mist #EBEFEE.
"""
import gradio as gr

ESPRESSO = "#4A413C"
TERRACOTTA = "#BB6C43"
CLAY = "#C8906D"
SAND = "#CCB499"
MIST = "#EBEFEE"
WHITE = "#FFFFFF"

DRAWER_WIDTH = "400px"


def build_theme() -> gr.themes.Base:
    return gr.themes.Base(
        font=[gr.themes.GoogleFont("Inter"), "ui-sans-serif", "system-ui", "sans-serif"],
        radius_size=gr.themes.sizes.radius_lg,
    ).set(
        body_background_fill=MIST,
        body_text_color=ESPRESSO,
        body_text_color_subdued=ESPRESSO,
        background_fill_primary=WHITE,
        background_fill_secondary=MIST,
        border_color_primary=SAND,
        border_color_accent=TERRACOTTA,
        color_accent=TERRACOTTA,
        color_accent_soft=MIST,
        link_text_color=TERRACOTTA,
        link_text_color_hover=ESPRESSO,
        block_background_fill=WHITE,
        block_border_color=SAND,
        block_label_text_color=ESPRESSO,
        block_title_text_color=ESPRESSO,
        block_label_background_fill=MIST,
        input_background_fill=WHITE,
        input_border_color=SAND,
        input_border_color_focus=TERRACOTTA,
        input_placeholder_color=CLAY,
        checkbox_background_color=WHITE,
        checkbox_border_color=CLAY,
        checkbox_border_width="1px",
        checkbox_background_color_selected=TERRACOTTA,
        checkbox_border_color_selected=TERRACOTTA,
        checkbox_border_color_focus=TERRACOTTA,
        checkbox_label_background_fill=WHITE,
        checkbox_label_background_fill_selected=MIST,
        checkbox_label_border_color=SAND,
        checkbox_label_text_color_selected=ESPRESSO,
        button_primary_background_fill=TERRACOTTA,
        button_primary_background_fill_hover=ESPRESSO,
        button_primary_text_color=WHITE,
        button_primary_border_color=TERRACOTTA,
        button_secondary_background_fill=WHITE,
        button_secondary_background_fill_hover=MIST,
        button_secondary_border_color=SAND,
        button_secondary_text_color=ESPRESSO,
        button_cancel_background_fill=ESPRESSO,
        button_cancel_text_color=MIST,
        loader_color=TERRACOTTA,
        slider_color=TERRACOTTA,
    )


CSS = f"""
:root {{ --espresso:{ESPRESSO}; --terracotta:{TERRACOTTA}; --clay:{CLAY}; --sand:{SAND}; --mist:{MIST}; }}
body, gradio-app, .gradio-container {{ background:{MIST} !important; color:{ESPRESSO}; }}
.gradio-container {{ max-width:100% !important; padding:0 !important; margin:0 !important; }}
footer {{ display:none !important; }}

/* ---------- top bar */
#topbar {{ background:{ESPRESSO}; color:{MIST}; padding:10px 24px; align-items:center; gap:16px;
           flex-wrap:nowrap !important; position:sticky; top:0; z-index:20; border-radius:0; }}
#topbar > div:first-child {{ flex:1 1 auto !important; min-width:0 !important; }}
#brand {{ white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
#brand .name {{ font-size:22px; font-weight:700; letter-spacing:-0.02em; color:{MIST}; }}
#brand .name b {{ color:{CLAY}; }}
#brand .tag {{ font-size:13px; color:{SAND}; margin-left:10px; }}
#sidebar-toggle {{ flex:0 0 auto !important; width:auto !important; min-width:190px !important; white-space:nowrap;
                   background:{TERRACOTTA} !important; color:white !important; border:none !important;
                   padding:8px 16px !important; font-weight:600; }}
#sidebar-toggle:hover {{ background:{CLAY} !important; }}

/* ---------- layout: chat (centered, ~70% of the window) + optional right sidebar */
#main {{ padding:16px 16px 8px 16px; gap:16px; flex-wrap:nowrap !important; align-items:flex-start; }}
#chat-col {{ min-width:0 !important; }}
#chat-inner {{ width:min(100%, 70vw); max-width:1100px; margin:0 auto; gap:10px; }}
#chat {{ border:1px solid {SAND}; background:white; }}
#chat .flex-wrap.user {{ background:{SAND} !important; color:{ESPRESSO} !important; border-radius:14px;
                         padding:2px 4px; }}
#chat .message.user {{ background:transparent !important; border-color:transparent !important; color:{ESPRESSO} !important; }}
#chat .message.bot {{ background:{MIST} !important; color:{ESPRESSO} !important; border-color:{MIST} !important; }}
#chat .placeholder {{ color:{ESPRESSO}; }}
#chat .placeholder h3 {{ color:{TERRACOTTA}; }}
#composer textarea {{ font-size:16px; padding:14px 16px; }}
#chips {{ gap:8px; flex-wrap:wrap; }}
#chips button {{ border-radius:999px !important; font-size:13px; padding:4px 14px; flex:0 0 auto !important;
                 min-width:0 !important; border-color:{SAND} !important; }}
#chips button:hover {{ border-color:{TERRACOTTA} !important; color:{TERRACOTTA} !important; }}

/* ---------- right sidebar */
#sidebar {{ flex:0 0 {DRAWER_WIDTH} !important; width:{DRAWER_WIDTH}; max-width:100%; position:sticky; top:72px;
            max-height:calc(100vh - 88px); overflow-y:auto; background:{MIST}; border:1px solid {SAND};
            border-radius:12px; padding:10px 12px 12px 12px; gap:10px; }}
@media (max-width: 900px) {{ #main {{ flex-wrap:wrap !important; }} #sidebar {{ flex:1 1 100% !important; position:static;
                                                                    max-height:none; }} #chat-inner {{ width:100%; }} }}
#sidebar-views, #sidebar-demo {{ gap:10px; }}
#sidebar .tab-nav button {{ color:{ESPRESSO}; font-weight:600; }}
#sidebar .tab-nav button.selected {{ color:{TERRACOTTA}; border-color:{TERRACOTTA}; }}
.panel-title {{ margin:2px 0 0 0; color:{ESPRESSO}; font-size:17px; }}
#demo-open {{ margin-top:8px; background:{ESPRESSO} !important; color:{MIST} !important; border:none !important; }}
#demo-open:hover {{ background:{TERRACOTTA} !important; }}
#demo-back {{ align-self:flex-start; width:auto !important; flex:0 0 auto !important; }}

/* ---------- this week */
.wk {{ display:flex; flex-direction:column; gap:8px; }}
.wk-day {{ background:white; border:1px solid {SAND}; border-radius:10px; padding:8px 10px; }}
.wk-day.today {{ border-color:{TERRACOTTA}; box-shadow:0 0 0 1px {TERRACOTTA}; }}
.wk-head {{ display:flex; align-items:baseline; gap:8px; font-weight:700; font-size:14px; }}
.wk-date {{ font-weight:400; font-size:12px; color:{CLAY}; }}
.wk-today {{ margin-left:auto; font-size:11px; font-weight:700; color:white; background:{TERRACOTTA};
             border-radius:999px; padding:1px 8px; }}
.wk-tag {{ font-size:11px; font-weight:600; color:{ESPRESSO}; background:{MIST}; border:1px solid {SAND};
           border-radius:999px; padding:0 7px; }}
.wk-meal {{ display:flex; gap:8px; align-items:flex-start; margin-top:6px; font-size:13px; line-height:1.35; }}
.wk-meal .what {{ flex:1; }}
.wk-meal small {{ display:block; color:{CLAY}; font-size:12px; }}
.wk-empty {{ color:{CLAY}; font-size:13px; margin-top:4px; }}
.pill {{ display:inline-block; border-radius:999px; padding:1px 8px; font-size:11px; font-weight:700;
         white-space:nowrap; flex:0 0 auto; }}
.pill.cook_from_scratch {{ background:{TERRACOTTA}; color:white; }}
.pill.quick_meal {{ background:{CLAY}; color:{ESPRESSO}; }}
.pill.leftovers {{ background:{SAND}; color:{ESPRESSO}; }}
.pill.skip {{ background:transparent; color:{ESPRESSO}; border:1px dashed {SAND}; }}
.pill.pick {{ background:{ESPRESSO}; color:{MIST}; }}
.hint {{ background:white; border:1px dashed {SAND}; border-radius:10px; padding:14px; color:{ESPRESSO};
         font-size:14px; }}
.hint b {{ color:{TERRACOTTA}; }}
.sub {{ font-size:12px; color:{CLAY}; margin:0 0 4px 0; }}

/* ---------- shopping */
.shop-cat {{ background:white; border:1px solid {SAND}; border-radius:10px; padding:8px 12px; margin-bottom:8px; }}
.shop-cat h4 {{ margin:0 0 4px 0; font-size:12px; letter-spacing:.06em; text-transform:uppercase; color:{TERRACOTTA}; }}
.shop-item {{ display:flex; gap:8px; align-items:baseline; font-size:13px; padding:3px 0; cursor:pointer; }}
.shop-item input {{ accent-color:{TERRACOTTA}; }}
.shop-item input:checked + span {{ text-decoration:line-through; opacity:.5; }}
.shop-item .qty {{ color:{CLAY}; white-space:nowrap; }}
.shop-item small {{ color:{CLAY}; margin-left:auto; text-align:right; font-size:11px; }}

/* ---------- preferences */
#prefs-note {{ font-size:12px; color:{ESPRESSO}; }}
#prefs .block {{ border-color:{SAND}; }}
#prefs-save {{ position:sticky; bottom:0; }}

/* ---------- demo controls */
.turn {{ background:white; border:1px solid {SAND}; border-radius:10px; padding:10px; font-size:13px; }}
.turn .row {{ margin:2px 0; }}
.turn .lbl {{ color:{CLAY}; font-size:11px; text-transform:uppercase; letter-spacing:.06em; }}
.path {{ display:flex; flex-wrap:wrap; gap:4px; align-items:center; margin:4px 0 6px 0; }}
.node {{ background:{MIST}; border:1px solid {SAND}; border-radius:6px; padding:1px 6px; font-family:ui-monospace,monospace;
         font-size:12px; }}
.arrow {{ color:{CLAY}; }}
.err {{ color:#9b2c1f; font-weight:600; }}
#session-foot {{ font-size:11px; color:{CLAY}; }}
"""

# Runs once on page load: force light mode (the palette is light-only) and keep the chat scrolled to the
# newest message - a MutationObserver re-scrolls whenever messages are added or a reply renders.
ON_LOAD_JS = """() => {
  document.body.classList.remove('dark');
  document.documentElement.classList.remove('dark');
  const scrollChat = (chat) => {
    chat.querySelectorAll('*').forEach((el) => {
      if (el.scrollHeight > el.clientHeight + 2) { el.scrollTop = el.scrollHeight; }
    });
  };
  const attach = () => {
    const chat = document.getElementById('chat');
    if (!chat) { setTimeout(attach, 200); return; }
    let pending = false;
    new MutationObserver(() => {
      if (pending) return;
      pending = true;
      requestAnimationFrame(() => { scrollChat(chat); setTimeout(() => scrollChat(chat), 150); pending = false; });
    }).observe(chat, { childList: true, subtree: true, characterData: true });
  };
  attach();
}"""
