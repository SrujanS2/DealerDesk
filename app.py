import os
import sys
import json
from decimal import Decimal
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import altair as alt

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Initialize Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dealerdesk.settings")
import django
django.setup()

from django.db import transaction
from django.utils import timezone
from catalog.models import Product, Inventory, StockMovement
from dealers.models import Dealer
from orders.models import Order
from orders import services as order_services
from supplier import sync as supplier_sync
from assistant import agent as assistant_agent
from forecasting import services as forecast_services
from semantic_bloom_renderer import get_semantic_bloom_html
from shader_button_renderer import get_iridescent_glass_html

# Page Configuration
st.set_page_config(
    page_title="DealerDesk — Automotive Inventory & Order Suite",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Custom High-End Modern CSS Design System
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root {
  --primary-glow: rgba(59, 130, 246, 0.15);
  --accent-blue: #3b82f6;
  --accent-emerald: #10b981;
  --accent-purple: #8b5cf6;
  --accent-amber: #f59e0b;
  --accent-rose: #ef4444;
  --surface-base: #07080a;
  --surface-card: #0e1117;
  --surface-border: rgba(255, 255, 255, 0.08);
  --text-muted: #8b949e;
}

html, body, [class*="css"] {
    font-family: 'Outfit', -apple-system, BlinkMacSystemFont, sans-serif;
    color: #e6edf3;
}

/* Background gradient styling */
.stApp {
    background:
        radial-gradient(58% 62% at 5% 100%, rgba(83, 103, 125, 0.28) 0%, rgba(48, 68, 90, 0.13) 42%, transparent 78%),
        radial-gradient(48% 54% at 46% 58%, rgba(48, 68, 90, 0.18) 0%, transparent 76%),
        linear-gradient(180deg, #090a0c 0%, #111820 44%, #142437 100%);
    background-attachment: fixed;
}
header[data-testid="stHeader"] { background: transparent; }

/* ThreeUI Shader Frame */
.shader-frame {
    position: relative;
    border-radius: 0;
    border: 0;
    background: transparent;
    box-shadow: none;
    overflow: hidden;
    margin-bottom: 1.5rem;
}

/* Glassmorphism Metric Cards */
.metric-glass-card {
    background: rgba(14, 17, 23, 0.7);
    border: 1px solid var(--surface-border);
    backdrop-filter: blur(16px);
    border-radius: 12px;
    padding: 1.1rem 1.25rem;
    transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}
.metric-glass-card:hover {
    transform: translateY(-2px);
    border-color: rgba(59, 130, 246, 0.4);
    box-shadow: 0 8px 24px var(--primary-glow);
}
.metric-title {
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-muted);
    font-weight: 500;
    margin-bottom: 0.35rem;
}
.metric-value {
    font-size: 1.85rem;
    font-weight: 700;
    color: #ffffff;
    font-family: 'JetBrains Mono', monospace;
    letter-spacing: -0.02em;
}
.metric-badge {
    display: inline-block;
    font-size: 0.72rem;
    padding: 0.15rem 0.5rem;
    border-radius: 6px;
    font-weight: 600;
    margin-top: 0.4rem;
}

/* Badges */
.badge-draft { background: rgba(148, 163, 184, 0.15); color: #cbd5e1; border: 1px solid rgba(148, 163, 184, 0.3); }
.badge-confirmed { background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }
.badge-dispatched { background: rgba(139, 92, 246, 0.15); color: #a78bfa; border: 1px solid rgba(139, 92, 246, 0.3); }
.badge-delivered { background: rgba(6, 182, 212, 0.15); color: #22d3ee; border: 1px solid rgba(6, 182, 212, 0.3); }
.badge-cancelled { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }

/* Part & Order Cards */
.part-card {
    background: rgba(14, 17, 23, 0.65);
    border: 1px solid var(--surface-border);
    border-radius: 12px;
    padding: 1.1rem;
    margin-bottom: 1rem;
    backdrop-filter: blur(12px);
    transition: all 0.2s ease;
}
.part-card:hover {
    border-color: rgba(99, 102, 241, 0.35);
    background: rgba(18, 22, 32, 0.85);
}

/* Custom Tabs Styling */
div[data-baseweb="tab-list"] {
    gap: 8px;
    background: rgba(14, 17, 23, 0.5);
    padding: 6px;
    border-radius: 12px;
    border: 1px solid var(--surface-border);
}
div[data-baseweb="tab"] {
    border-radius: 8px !important;
    padding: 8px 18px !important;
    font-weight: 500 !important;
    font-size: 0.92rem !important;
    color: #94a3b8 !important;
    border: none !important;
    transition: all 0.2s ease !important;
}
div[aria-selected="true"] {
    background: rgba(59, 130, 246, 0.15) !important;
    color: #60a5fa !important;
    border: 1px solid rgba(59, 130, 246, 0.3) !important;
}

/* Keep the catalogue search field visually open against the dashboard background. */
div[data-testid="stTextInput"]:has(input[aria-label="🔍 Search the live catalogue"]) [data-baseweb="base-input"],
div[data-testid="stTextInput"]:has(input[aria-label="🔍 Search the live catalogue"]) [data-testid="stTextInputRootElement"] {
    background: transparent !important;
    box-shadow: none !important;
}
div[data-testid="stTextInput"]:has(input[aria-label="🔍 Search the live catalogue"]) input {
    background: transparent !important;
}

div[data-testid="stChatMessage"] {
    border: 1px solid rgba(255, 255, 255, .065);
    border-radius: 16px;
    background: rgba(10, 13, 19, .62);
    backdrop-filter: blur(14px);
}

/* Persistent AI assistant orb and compact chat drawer. */
.st-key-assistant-floating-widget {
    position: fixed !important;
    left: max(18px, env(safe-area-inset-left)) !important;
    right: auto !important;
    bottom: max(18px, env(safe-area-inset-bottom)) !important;
    z-index: 999999 !important;
    display: flex !important;
    flex-direction: column !important;
    align-items: flex-start !important;
    gap: 12px !important;
    width: min(390px, calc(100vw - 32px)) !important;
    pointer-events: none;
}
.st-key-assistant-floating-widget > div { width: 100%; pointer-events: auto; }
.st-key-assistant-floating-panel {
    box-sizing: border-box;
    width: 100%;
    padding: 16px 16px 14px;
    border: 1px solid rgba(177, 170, 255, .23);
    border-radius: 22px;
    max-height: min(70vh, 580px);
    overflow-y: auto;
    background:
        radial-gradient(ellipse 65% 30% at 0% 100%, rgba(255, 138, 114, .09), transparent 100%),
        radial-gradient(ellipse 65% 35% at 100% 0%, rgba(83, 112, 255, .13), transparent 100%),
        rgba(8, 10, 17, .94);
    box-shadow: 0 24px 80px rgba(0, 0, 0, .55), 0 0 32px rgba(112, 105, 255, .12);
    backdrop-filter: blur(24px);
}
.assistant-float-heading { padding: 4px 0 12px; }
.assistant-float-heading strong {
    display: block;
    color: #f4f4ff;
    font-size: 1rem;
    font-weight: 600;
}
.assistant-float-heading span {
    display: block;
    margin-top: 3px;
    color: #9da4bb;
    font-size: .76rem;
}
.st-key-assistant-floating-panel [data-testid="stChatMessage"] {
    margin: 5px 0;
    padding: 8px 11px;
    border-radius: 13px;
    background: rgba(19, 22, 34, .72);
}
.st-key-assistant-floating-panel [data-testid="stTextInput"] input {
    min-height: 42px;
    border: 1px solid rgba(183, 190, 220, .18);
    border-radius: 14px;
    background: rgba(4, 6, 12, .45);
}
.st-key-assistant-floating-panel [data-testid="stForm"] {
    border: 0;
    padding: 0;
}
.st-key-assistant-floating-panel [data-testid="stFormSubmitButton"] button {
    min-height: 42px;
    border: 1px solid rgba(185, 169, 255, .45);
    border-radius: 14px;
    color: white;
    background: linear-gradient(115deg, rgba(113, 88, 218, .9), rgba(64, 112, 222, .92));
}
.st-key-assistant-floating-close button {
    width: 38px;
    height: 38px;
    min-height: 38px;
    padding: 0;
    border: 1px solid rgba(255, 255, 255, .12);
    border-radius: 50%;
    color: #dce2f5;
    background: rgba(255, 255, 255, .06);
}
.st-key-assistant-orb-launcher { width: 78px !important; }
.st-key-assistant-orb-launcher [data-testid="stButton"] { width: 78px; }
.st-key-assistant-orb-launcher button {
    position: relative;
    width: 72px;
    height: 72px;
    min-height: 72px;
    padding: 0;
    overflow: visible;
    border: 1px solid rgba(191, 180, 255, .72);
    border-radius: 50%;
    color: transparent !important;
    font-size: 0 !important;
    background:
        radial-gradient(ellipse 42% 18% at 28% 16%, rgba(255, 255, 255, .27), transparent 100%),
        radial-gradient(ellipse at 72% 78%, rgba(230, 87, 255, .28), transparent 44%),
        radial-gradient(ellipse at 24% 75%, rgba(71, 135, 255, .3), transparent 48%),
        radial-gradient(circle at 38% 30%, #29253a 0%, #110e1c 56%, #080911 100%) !important;
    box-shadow:
        inset 0 0 13px rgba(220, 215, 255, .18),
        0 0 10px rgba(155, 134, 255, .55),
        0 0 30px rgba(107, 109, 255, .32),
        0 12px 32px rgba(0, 0, 0, .48);
    animation: dealerdesk-orb-aura 4.8s ease-in-out infinite;
    transition: box-shadow .25s ease, border-color .25s ease;
}
.st-key-assistant-orb-launcher button:hover {
    border-color: rgba(224, 211, 255, .95);
    color: transparent !important;
    transform: scale(1.04);
    box-shadow:
        inset 0 0 16px rgba(220, 215, 255, .22),
        0 0 15px rgba(155, 134, 255, .72),
        0 0 40px rgba(107, 109, 255, .4),
        0 14px 36px rgba(0, 0, 0, .5);
}
.st-key-assistant-orb-launcher button::before {
    content: "";
    position: absolute;
    inset: 0;
    border-radius: 50%;
    background:
        radial-gradient(ellipse 4px 9px at 40% 50%, rgba(255, 255, 255, .98) 0 82%, transparent 100%),
        radial-gradient(ellipse 4px 9px at 60% 50%, rgba(255, 255, 255, .98) 0 82%, transparent 100%);
    filter: drop-shadow(0 0 5px rgba(230, 226, 255, .9));
    animation: dealerdesk-orb-blink 6.6s ease-in-out infinite, dealerdesk-orb-gaze 9s ease-in-out infinite;
    pointer-events: none;
}
.st-key-assistant-orb-launcher button::after {
    content: "";
    position: absolute;
    inset: 4px;
    border-radius: 50%;
    background:
        radial-gradient(ellipse 33% 12% at 30% 16%, rgba(255,255,255,.24), transparent 100%),
        radial-gradient(ellipse 60% 45% at 50% 110%, rgba(76, 119, 255, .16), transparent 100%);
    box-shadow: inset 0 1px 2px rgba(255, 255, 255, .22);
    animation: dealerdesk-orb-reflection 4.8s ease-in-out infinite;
    pointer-events: none;
}
@keyframes dealerdesk-orb-aura {
    0%, 100% {
        box-shadow: inset 0 0 13px rgba(220, 215, 255, .18), 0 0 10px rgba(155, 134, 255, .5), 0 0 28px rgba(107, 109, 255, .28), 0 12px 32px rgba(0, 0, 0, .48);
    }
    50% {
        box-shadow: inset 0 0 16px rgba(220, 215, 255, .23), 0 0 14px rgba(155, 134, 255, .7), 0 0 36px rgba(107, 109, 255, .38), 0 12px 32px rgba(0, 0, 0, .48);
    }
}
@keyframes dealerdesk-orb-reflection {
    0%, 100% { transform: translateY(0); }
    50% { transform: translateY(-2px); }
}
@keyframes dealerdesk-orb-blink {
    0%, 43%, 48%, 86%, 91%, 100% { transform: scaleY(1); }
    45%, 89% { transform: scaleY(.18); }
}
@keyframes dealerdesk-orb-gaze {
    0%, 20%, 80%, 100% { translate: 0 0; }
    34%, 44% { translate: -1px 1px; }
    58%, 68% { translate: 1px 0; }
}
@media (max-width: 760px) {
    .st-key-assistant-floating-widget { left: 12px !important; right: auto !important; bottom: 12px !important; width: min(360px, calc(100vw - 24px)) !important; }
    .st-key-assistant-orb-launcher { width: 68px !important; }
    .st-key-assistant-orb-launcher [data-testid="stButton"] { width: 68px; }
    .st-key-assistant-orb-launcher button { width: 64px; height: 64px; min-height: 64px; }
}
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------
# GLOBAL FLOATING AI ASSISTANT
# Render before the dashboard and forecast work so the launcher appears promptly.
# -------------------------------------------------------------
def open_assistant_floating_widget():
    st.session_state.assistant_float_open = True


def close_assistant_floating_widget():
    st.session_state.assistant_float_open = False


if "assistant_float_open" not in st.session_state:
    st.session_state.assistant_float_open = False
if "assistant_float_histories" not in st.session_state:
    st.session_state.assistant_float_histories = {}

with st.container(key="assistant-floating-widget"):
    if st.session_state.assistant_float_open:
        with st.container(key="assistant-floating-panel"):
            header_col, close_col = st.columns([5, 1], vertical_alignment="center")
            with header_col:
                st.markdown(
                    '<div class="assistant-float-heading"><strong>DealerDesk AI</strong>'
                    '<span>Live parts, stock and order help</span></div>',
                    unsafe_allow_html=True,
                )
            with close_col:
                st.button(
                    "×",
                    key="assistant-floating-close",
                    help="Close assistant",
                    on_click=close_assistant_floating_widget,
                )

            floating_dealers = list(Dealer.objects.order_by("dealer_code"))
            if not floating_dealers:
                st.warning("Add a dealer before starting an assistant conversation.")
            else:
                floating_dealer = st.selectbox(
                    "Dealer",
                    floating_dealers,
                    format_func=lambda dealer: f"{dealer.dealer_code} — {dealer.name}",
                    key="assistant-floating-dealer",
                    label_visibility="collapsed",
                )
                floating_history_key = str(floating_dealer.pk)
                floating_histories = st.session_state.assistant_float_histories
                floating_history = floating_histories.get(floating_history_key, [])
                messages_slot = st.container()

                with st.form("assistant-floating-form", clear_on_submit=True):
                    input_col, send_col = st.columns([5, 1], vertical_alignment="center")
                    with input_col:
                        floating_prompt = st.text_input(
                            "Message DealerDesk AI",
                            placeholder="Ask about a part, live stock or an order…",
                            label_visibility="collapsed",
                            key="assistant-floating-prompt",
                        )
                    with send_col:
                        floating_submitted = st.form_submit_button("↑", help="Send message")

                if floating_submitted and floating_prompt.strip():
                    prompt_text = floating_prompt.strip()
                    floating_history.append({"role": "user", "text": prompt_text})
                    with st.spinner("Checking live DealerDesk data…"):
                        try:
                            result = assistant_agent.run_turn(
                                f"floating-assistant-{floating_dealer.pk}",
                                floating_dealer,
                                prompt_text,
                            )
                            floating_history.append({
                                "role": "assistant",
                                "text": result["reply"],
                                "cited_skus": result.get("cited_skus", []),
                                "tool_calls": result.get("tool_calls", []),
                                "actions": result.get("actions", []),
                            })
                        except Exception as exc:
                            floating_history.append({
                                "role": "assistant",
                                "text": f"Assistant request failed: {exc}",
                                "cited_skus": [],
                                "tool_calls": [],
                                "actions": [],
                            })
                    floating_histories[floating_history_key] = floating_history
                    st.session_state.assistant_float_histories = floating_histories
                    st.rerun()

                with messages_slot:
                    if not floating_history:
                        st.caption("Ask about vehicle fitment, current prices, stock, or a draft order.")
                    for floating_message in floating_history[-6:]:
                        with st.chat_message(
                            floating_message["role"],
                            avatar="⚡" if floating_message["role"] == "assistant" else None,
                        ):
                            st.write(floating_message["text"])
                            if floating_message.get("cited_skus"):
                                st.caption("SKUs: " + ", ".join(floating_message["cited_skus"]))
                            if floating_message.get("tool_calls"):
                                with st.expander("Inspect tool calls"):
                                    for tool_call in floating_message["tool_calls"]:
                                        st.code(
                                            f"{tool_call['name']}({json.dumps(tool_call['arguments'])})",
                                            language="json",
                                        )
                            for action in floating_message.get("actions", []):
                                st.success(f"Draft order created: {action.get('order_number')}")

    with st.container(key="assistant-orb-launcher"):
        st.button(
            "AI assistant",
            key="assistant-orb-toggle",
            help="Open DealerDesk AI assistant",
            use_container_width=False,
            on_click=open_assistant_floating_widget,
        )

# -------------------------------------------------------------
# HERO BANNER: <SemanticBloom /> from ThreeUI
# -------------------------------------------------------------
st.markdown('<div class="shader-frame">', unsafe_allow_html=True)
hero_html = get_semantic_bloom_html(text="DealerDesk", mode="dark", size=1.0, opacity=1.0)
components.html(hero_html, height=195, scrolling=False)
st.markdown('</div>', unsafe_allow_html=True)

# -------------------------------------------------------------
# LIVE STATS TELEMETRY BAR
# -------------------------------------------------------------
total_products = Product.objects.count()
total_dealers = Dealer.objects.count()
total_orders = Order.objects.count()
confirmed_orders = Order.objects.filter(status=Order.Status.CONFIRMED).count()
total_stock_units = sum(Inventory.objects.values_list("quantity", flat=True))

col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.markdown(f"""
    <div class="metric-glass-card">
        <div class="metric-title">Catalogue SKUs</div>
        <div class="metric-value">{total_products}</div>
        <span class="metric-badge badge-confirmed">LIVE DB</span>
    </div>
    """, unsafe_allow_html=True)
with col2:
    st.markdown(f"""
    <div class="metric-glass-card">
        <div class="metric-title">Dealers Registered</div>
        <div class="metric-value">{total_dealers}</div>
        <span class="metric-badge badge-draft">25 Active</span>
    </div>
    """, unsafe_allow_html=True)
with col3:
    st.markdown(f"""
    <div class="metric-glass-card">
        <div class="metric-title">Warehouse Stock</div>
        <div class="metric-value">{total_stock_units:,}</div>
        <span class="metric-badge badge-dispatched">Units</span>
    </div>
    """, unsafe_allow_html=True)
with col4:
    st.markdown(f"""
    <div class="metric-glass-card">
        <div class="metric-title">Orders Handled</div>
        <div class="metric-value">{total_orders}</div>
        <span class="metric-badge badge-delivered">{confirmed_orders} Confirmed</span>
    </div>
    """, unsafe_allow_html=True)
with col5:
    st.markdown(f"""
    <div class="metric-glass-card">
        <div class="metric-title">Gemini Assistant</div>
        <div class="metric-value">Active</div>
        <span class="metric-badge badge-confirmed">Tool-Calling</span>
    </div>
    """, unsafe_allow_html=True)

st.write("")

# -------------------------------------------------------------
# TABS NAVIGATION
# -------------------------------------------------------------
tab_catalog, tab_inventory, tab_dealers, tab_orders, tab_supplier, tab_forecast = st.tabs([
    "📦 Products & Catalogue",
    "📊 Inventory Management",
    "👥 Dealers Directory",
    "🛒 Orders & Lifecycle",
    "🔄 Supplier Sync Hub",
    "📈 Demand Forecast & Reorders"
])

# =============================================================
# TAB 1: PRODUCTS & CATALOGUE
# =============================================================
with tab_catalog:
    st.subheader("Automotive Parts Catalogue")

    col_s1, col_shader = st.columns([3.2, 1.4], vertical_alignment="center")
    with col_s1:
        search_query = st.text_input("🔍 Search the live catalogue", placeholder="Try a part name, brand or SKU...", key="cat_search")
    with col_shader:
        components.html(
            get_iridescent_glass_html(mode="dark", hue=0, saturation=1.0, brightness=1.0),
            height=88,
            scrolling=False,
        )

    col_s2, col_s3, col_s4 = st.columns(3)
    with col_s2:
        categories = ["All Categories"] + sorted(list(Product.objects.values_list("category", flat=True).distinct()))
        sel_category = st.selectbox("Category", categories, key="cat_filter")
    with col_s3:
        vehicles = ["All Vehicles"] + sorted(list(set(Product.objects.values_list("vehicle_fitment", flat=True).distinct())))
        sel_vehicle = st.selectbox("Vehicle Fitment", vehicles, key="veh_filter")
    with col_s4:
        stock_filter = st.selectbox("Stock Status", ["All Items", "In Stock (>0)", "Low Stock (≤5)", "Out of Stock (0)"], key="stock_filter")

    # Filter Query
    qs = Product.objects.select_related("inventory").all()
    if search_query:
        qs = qs.filter(
            django.db.models.Q(sku__icontains=search_query) |
            django.db.models.Q(name__icontains=search_query) |
            django.db.models.Q(brand__icontains=search_query)
        )
    if sel_category != "All Categories":
        qs = qs.filter(category=sel_category)
    if sel_vehicle != "All Vehicles":
        qs = qs.filter(vehicle_fitment__icontains=sel_vehicle)

    # Convert to displayable dataframe
    matched_products = list(qs[:80])

    # Filter by stock in memory
    filtered_list = []
    for p in matched_products:
        qty = p.inventory.quantity if hasattr(p, "inventory") else 0
        if stock_filter == "In Stock (>0)" and qty <= 0:
            continue
        if stock_filter == "Low Stock (≤5)" and not (0 < qty <= 5):
            continue
        if stock_filter == "Out of Stock (0)" and qty > 0:
            continue
        filtered_list.append((p, qty))

    st.caption(f"Showing **{len(filtered_list)}** matching catalogue products")

    # Display in cards grid
    for i in range(0, len(filtered_list), 2):
        row_cols = st.columns(2)
        for j in range(2):
            if i + j < len(filtered_list):
                prod, stock_qty = filtered_list[i + j]
                with row_cols[j]:
                    stock_badge_class = "badge-confirmed" if stock_qty > 10 else ("badge-dispatched" if stock_qty > 0 else "badge-cancelled")
                    stock_label = f"{stock_qty} in stock" if stock_qty > 0 else "Out of stock"

                    st.markdown(f"""
                    <div class="part-card">
                        <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                            <div>
                                <span style="font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; color: #60a5fa; font-weight: 600;">{prod.sku}</span>
                                <h4 style="margin: 0.2rem 0; font-size: 1.05rem;">{prod.name}</h4>
                            </div>
                            <span class="metric-badge {stock_badge_class}">{stock_label}</span>
                        </div>
                        <div style="font-size: 0.85rem; color: #94a3b8; margin: 0.4rem 0;">
                            <strong>Brand:</strong> {prod.brand or 'Generic'} &nbsp;|&nbsp;
                            <strong>Fitment:</strong> {prod.vehicle_fitment or 'Universal'} &nbsp;|&nbsp;
                            <strong>Category:</strong> {prod.category}
                        </div>
                        <div style="display: flex; justify-content: space-between; align-items: baseline; margin-top: 0.8rem;">
                            <span style="font-size: 1.3rem; font-weight: 700; color: #34d399; font-family: 'JetBrains Mono', monospace;">₹{prod.price}</span>
                            <span style="font-size: 0.75rem; color: #64748b;">+ 18% GST on order</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

    with st.expander("➕ Add New Product to Catalogue (Contract §4)"):
        with st.form("new_product_form"):
            c_np1, c_np2, c_np3 = st.columns(3)
            with c_np1:
                np_sku = st.text_input("SKU*", placeholder="e.g. BRK-9901")
                np_name = st.text_input("Product Name*", placeholder="e.g. High Performance Brake Pads")
            with c_np2:
                np_category = st.text_input("Category", placeholder="e.g. Brakes")
                np_brand = st.text_input("Brand", placeholder="e.g. Brembo")
            with c_np3:
                np_fitment = st.text_input("Vehicle Fitment", placeholder="e.g. KTM Duke 390")
                np_price = st.text_input("Price (₹)*", placeholder="1450.00")
            np_desc = st.text_area("Description", placeholder="OEM specification brake pad set...")
            submit_np = st.form_submit_button("Create Product", width="stretch")
            if submit_np:
                try:
                    price_dec = Decimal(np_price.strip())
                    if price_dec <= 0:
                        st.error("Price must be > 0.")
                    elif Product.objects.filter(sku=np_sku.strip()).exists():
                        st.error(f"Duplicate SKU {np_sku.strip()} already exists (409 DUPLICATE).")
                    else:
                        with transaction.atomic():
                            p_new = Product.objects.create(
                                sku=np_sku.strip(),
                                name=np_name.strip(),
                                category=np_category.strip(),
                                brand=np_brand.strip(),
                                vehicle_fitment=np_fitment.strip(),
                                price=price_dec,
                                description=np_desc.strip(),
                            )
                            Inventory.objects.create(product=p_new, quantity=0)
                        st.success(f"Product {p_new.sku} successfully created with starting stock 0!")
                        st.rerun()
                except Exception as e:
                    st.error(f"Error creating product: {e}")

# =============================================================
# TAB 2: INVENTORY DESK
# =============================================================
with tab_inventory:
    st.subheader("Inventory Stock Desk (Contract §5)")
    st.markdown("Adjust warehouse inventory levels with live concurrency locking and audit trail.")

    col_inv1, col_inv2 = st.columns([1.5, 2.5])
    with col_inv1:
        st.markdown("##### ✏️ Stock Count Correction")
        all_skus = list(Product.objects.values_list("sku", flat=True))
        sel_inv_sku = st.selectbox("Select Product SKU", all_skus, key="inv_sku_select")
        current_inv_obj = Inventory.objects.filter(product__sku=sel_inv_sku).first()
        current_qty = current_inv_obj.quantity if current_inv_obj else 0
        st.info(f"Current Available Quantity: **{current_qty} units**")

        new_qty = st.number_input("New Available Quantity", min_value=0, max_value=1000000, value=current_qty, step=1)
        reason_inv = st.selectbox("Reason for Correction", [
            "stock count correction",
            "physical audit replenishment",
            "supplier arrival",
            "damaged goods write-off",
            "test adjustment"
        ])
        if st.button("Apply Inventory Correction (PUT /api/inventory/)", width="stretch"):
            with transaction.atomic():
                inv = Inventory.objects.select_for_update().get(product__sku=sel_inv_sku)
                delta = new_qty - inv.quantity
                inv.quantity = new_qty
                inv.save(update_fields=["quantity", "updated_at"])
                StockMovement.objects.create(
                    product_id=inv.product_id,
                    kind=StockMovement.Reason.MANUAL,
                    delta=delta,
                    quantity_after=new_qty,
                    note=reason_inv
                )
            st.success(f"Stock for {sel_inv_sku} updated to {new_qty} units!")
            st.rerun()

    with col_inv2:
        st.markdown("##### 📜 Recent Stock Audit Movements (Audit Ledger)")
        recent_movements = StockMovement.objects.select_related("product").order_by("-created_at")[:15]
        mov_data = []
        for m in recent_movements:
            mov_data.append({
                "Timestamp": timezone.localtime(m.created_at).strftime("%Y-%m-%d %H:%M:%S"),
                "SKU": m.product.sku,
                "Type": m.kind,
                "Delta": f"+{m.delta}" if m.delta > 0 else str(m.delta),
                "Stock After": m.quantity_after,
                "Note": m.note or "-"
            })
        if mov_data:
            st.dataframe(pd.DataFrame(mov_data), width="stretch", hide_index=True)
        else:
            st.info("No stock movements recorded yet.")

# =============================================================
# TAB 3: DEALERS DIRECTORY
# =============================================================
with tab_dealers:
    st.subheader("Registered Dealers Network (Contract §6)")
    dealers_qs = Dealer.objects.all().order_by("id")
    dealer_search = st.text_input("Filter Dealers by Name, City or Code", placeholder="e.g. Apex, Pune, DLR-007")
    if dealer_search:
        dealers_qs = dealers_qs.filter(
            django.db.models.Q(name__icontains=dealer_search) |
            django.db.models.Q(city__icontains=dealer_search) |
            django.db.models.Q(dealer_code__icontains=dealer_search)
        )

    d_list = []
    for d in dealers_qs:
        order_count = Order.objects.filter(dealer=d).count()
        d_list.append({
            "ID": d.id,
            "Dealer Code": d.dealer_code,
            "Dealership Name": d.name,
            "City": d.city,
            "Phone": d.phone,
            "Email": d.email,
            "GSTIN": d.gstin,
            "Credit Limit (₹)": f"₹{d.credit_limit:,.2f}",
            "Orders Placed": order_count,
        })
    st.dataframe(pd.DataFrame(d_list), width="stretch", hide_index=True)

# =============================================================
# TAB 4: ORDERS & LIFECYCLE
# =============================================================
with tab_orders:
    st.subheader("Order Desk & Concurrency Lifecycle (Contract §7)")

    tab_create_order, tab_manage_order = st.tabs(["📝 Create New Order", "📋 Manage Orders & Status Flow"])

    with tab_create_order:
        st.markdown("##### 🛒 Build a Draft Order")
        all_dealers = Dealer.objects.all().order_by("id")
        dealer_options = {f"{d.dealer_code} — {d.name} ({d.city})": d.id for d in all_dealers}
        sel_dealer_label = st.selectbox("Select Dealer", list(dealer_options.keys()))
        sel_dealer_id = dealer_options[sel_dealer_label]

        col_part_sel, col_part_qty = st.columns([3, 1])
        with col_part_sel:
            all_products_dict = {f"{p.sku} | {p.name} (₹{p.price})": p.sku for p in Product.objects.all()}
            sel_part_label = st.selectbox("Choose Product to Add", list(all_products_dict.keys()))
            chosen_sku = all_products_dict[sel_part_label]
        with col_part_qty:
            chosen_qty = st.number_input("Quantity", min_value=1, max_value=1000, value=1)

        # Session cart
        if "cart" not in st.session_state:
            st.session_state.cart = {}

        c_add, c_clear = st.columns([1, 1])
        with c_add:
            if st.button("➕ Add to Cart", width="stretch"):
                st.session_state.cart[chosen_sku] = st.session_state.cart.get(chosen_sku, 0) + chosen_qty
                st.toast(f"Added {chosen_qty}x {chosen_sku} to cart!")
        with c_clear:
            if st.button("🗑️ Clear Cart", width="stretch"):
                st.session_state.cart = {}
                st.rerun()

        if st.session_state.cart:
            st.markdown("###### Current Cart Lines:")
            cart_rows = []
            subtot_accum = Decimal("0.00")
            tax_accum = Decimal("0.00")
            for sku, qty in st.session_state.cart.items():
                p_item = Product.objects.get(sku=sku)
                subtot, tax, total = order_services.line_amounts(p_item.price, qty)
                subtot_accum += subtot
                tax_accum += tax
                cart_rows.append({
                    "SKU": sku,
                    "Name": p_item.name,
                    "Quantity": qty,
                    "Unit Price": f"₹{p_item.price}",
                    "Line Subtotal": f"₹{subtot}",
                    "GST (18%)": f"₹{tax}",
                    "Line Total": f"₹{total}",
                })
            st.table(pd.DataFrame(cart_rows))

            col_tot1, col_tot2, col_tot3 = st.columns(3)
            col_tot1.metric("Subtotal", f"₹{subtot_accum}")
            col_tot2.metric("Total Tax (18% GST)", f"₹{tax_accum}")
            col_tot3.metric("Grand Total", f"₹{subtot_accum + tax_accum}")

            if st.button("🚀 Submit Order (Creates DRAFT)", width="stretch"):
                try:
                    payload = {
                        "dealer_id": sel_dealer_id,
                        "items": [{"sku": k, "quantity": v} for k, v in st.session_state.cart.items()]
                    }
                    new_order, created = order_services.create_order(payload)
                    st.success(f"Successfully created Draft Order: **{new_order.order_number}**!")
                    st.session_state.cart = {}
                    st.rerun()
                except Exception as e:
                    st.error(f"Order creation failed: {e}")

    with tab_manage_order:
        st.markdown("##### 📦 Existing Orders & Transitions")
        status_filter = st.selectbox("Filter Status", ["ALL", "DRAFT", "CONFIRMED", "DISPATCHED", "DELIVERED", "CANCELLED"])
        orders_q = Order.objects.prefetch_related("items__product", "dealer").all()
        if status_filter != "ALL":
            orders_q = orders_q.filter(status=status_filter)

        for ord_obj in orders_q[:15]:
            ord_ser = order_services.serialize_order(ord_obj)
            badge_class = f"badge-{ord_obj.status.lower()}"
            with st.container():
                st.markdown(f"""
                <div class="part-card">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <span style="font-family: 'JetBrains Mono', monospace; font-size: 1.1rem; font-weight: 700; color: #60a5fa;">
                                {ord_ser['order_number']}
                            </span>
                            <span style="color: #94a3b8; font-size: 0.85rem; margin-left: 0.5rem;">
                                Dealer: {ord_obj.dealer.dealer_code} ({ord_obj.dealer.name})
                            </span>
                        </div>
                        <span class="metric-badge {badge_class}">{ord_obj.status}</span>
                    </div>
                    <div style="margin: 0.5rem 0; font-size: 0.9rem; color: #cbd5e1;">
                        <strong>Items:</strong> {len(ord_ser['items'])} &nbsp;|&nbsp;
                        <strong>Grand Total:</strong> ₹{ord_ser['grand_total']} &nbsp;|&nbsp;
                        <strong>Updated:</strong> {ord_ser['updated_at'][:19].replace('T', ' ')}
                    </div>
                </div>
                """, unsafe_allow_html=True)

                # Action buttons based on status transitions (§7.2)
                btn_cols = st.columns(4)
                if ord_obj.status == Order.Status.DRAFT:
                    with btn_cols[0]:
                        if st.button("🟢 Confirm Order", key=f"conf_{ord_obj.order_number}"):
                            try:
                                order_services.confirm_order(ord_obj.order_number)
                                st.success("Order confirmed! Stock deducted.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Cannot confirm: {e}")
                    with btn_cols[1]:
                        if st.button("❌ Cancel Order", key=f"canc_{ord_obj.order_number}"):
                            try:
                                order_services.cancel_order(ord_obj.order_number)
                                st.warning("Draft order cancelled.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
                elif ord_obj.status == Order.Status.CONFIRMED:
                    with btn_cols[0]:
                        if st.button("🚚 Dispatch Order", key=f"disp_{ord_obj.order_number}"):
                            try:
                                order_services.advance_order(ord_obj.order_number, "dispatch")
                                st.success("Order dispatched!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
                    with btn_cols[1]:
                        if st.button("❌ Cancel & Restore Stock", key=f"canc_conf_{ord_obj.order_number}"):
                            try:
                                order_services.cancel_order(ord_obj.order_number)
                                st.warning("Order cancelled! Stock restored.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
                elif ord_obj.status == Order.Status.DISPATCHED:
                    with btn_cols[0]:
                        if st.button("✅ Mark Delivered", key=f"deliv_{ord_obj.order_number}"):
                            try:
                                order_services.advance_order(ord_obj.order_number, "deliver")
                                st.success("Order delivered!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")

# =============================================================
# TAB 5: SUPPLIER SYNC HUB
# =============================================================
with tab_supplier:
    st.subheader("Supplier Synchronisation Hub (Contract §8)")
    st.markdown("Pull catalogue updates from 3rd-party suppliers with cursor pagination, 429 rate limit retries, and atomic commits.")

    c_sup1, c_sup2 = st.columns([1, 2])
    with c_sup1:
        st.markdown("""
        **Configuration:**
        - **Supplier URL:** `http://127.0.0.1:8099`
        - **Retries:** Up to 5 attempts per page on 429 / 5xx
        - **Atomic rule:** All-or-nothing (502 on fatal failure)
        """)
        if st.button("⚡ Run Full Supplier Sync", width="stretch"):
            with st.spinner("Connecting to supplier feed and processing pages..."):
                try:
                    res = supplier_sync.run_sync().as_dict()
                    st.session_state.sync_result = res
                    st.success("Sync completed successfully!")
                except Exception as e:
                    st.error(f"Supplier Sync Failed: {e}")

    with c_sup2:
        if "sync_result" in st.session_state:
            s_res = st.session_state.sync_result
            st.markdown("##### 📊 Last Sync Telemetry")
            m1, m2, m3 = st.columns(3)
            m1.metric("Created", s_res.get("created", 0))
            m2.metric("Updated", s_res.get("updated", 0))
            m3.metric("Unchanged", s_res.get("unchanged", 0))

            m4, m5 = st.columns(2)
            m4.metric("Pages Fetched", s_res.get("pages_fetched", 0))
            m5.metric("Requests Made", s_res.get("requests_made", 0))

            if s_res.get("rejected"):
                st.warning(f"{len(s_res['rejected'])} items were rejected due to invalid price/format.")
                st.json(s_res["rejected"])
        else:
            st.info("Click 'Run Full Supplier Sync' to fetch feed from mock supplier.")

# =============================================================
# TAB 6: DEMAND FORECASTING & REORDERS
# =============================================================
with tab_forecast:
    st.subheader("Machine Learning Demand Forecasting & Reorder Point Engine (Contract §10)")
    st.markdown("4-week ahead sales forecasting evaluated against Diwali festival lift and lead-time demand calculations.")

    forecast_skus = [s["sku"] for s in forecast_services.reorder_suggestions()]
    c_f1, c_f2 = st.columns([1.5, 2.5])

    with c_f1:
        sel_fc_sku = st.selectbox("Select Forecast SKU (40 SKUs)", forecast_skus)
        fc_data = forecast_services.forecast_for(sel_fc_sku)

        # Details
        prod_obj = Product.objects.filter(sku=sel_fc_sku).first()
        if prod_obj:
            st.markdown(f"**Name:** {prod_obj.name}")
            st.markdown(f"**Category:** {prod_obj.category} &nbsp;|&nbsp; **Brand:** {prod_obj.brand}")
            st.markdown(f"**Live Stock:** {prod_obj.inventory.quantity} units")

        # Table of 4 weeks
        df_fc = pd.DataFrame(fc_data["forecast"])
        st.dataframe(df_fc, hide_index=True, width="stretch")

    with c_f2:
        st.markdown(f"##### 📊 4-Week Demand Prediction Curve ({sel_fc_sku})")
        chart = alt.Chart(df_fc).mark_bar(color="#3b82f6", cornerRadiusTopLeft=6, cornerRadiusTopRight=6).encode(
            x=alt.X("week_start:O", title="Week Starting (Monday)"),
            y=alt.Y("forecast_units:Q", title="Predicted Units Sold"),
            tooltip=["week_start", "forecast_units"]
        ).properties(height=260)
        st.altair_chart(chart, width="stretch")

    st.markdown("---")
    st.markdown("##### 📋 Complete 40-SKU Reorder Recommendations (Exact Formula)")
    st.caption(r"Formula: $L$ = lead time; LTD = $\sum_{1}^L \text{forecast}$; Safety Stock = $\lceil 1.65 \times \sigma \times \sqrt{L} \rceil$; ROP = $\text{LTD} + \text{SS}$; Reorder Qty = $\max(0, \lceil \text{ROP} - \text{Stock} \rceil)$")

    all_reorders = forecast_services.reorder_suggestions()
    df_reorders = pd.DataFrame(all_reorders)

    st.dataframe(df_reorders, width="stretch", hide_index=True)
