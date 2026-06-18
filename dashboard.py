"""
Dashboard AGM Tráfego - Painel client-facing de Meta Ads (Jayme Campos).

- Puxa métricas direto da Meta Graph API (Insights) por ad_account_id.
- Auto-refresh configurável na barra lateral.
- Mostra TODAS as métricas relevantes, INCLUSIVE custo (decisão do cliente).

SEGURANÇA: o token NUNCA fica no código. Vai em .streamlit/secrets.toml
(local, gitignored) ou na variável de ambiente META_ACCESS_TOKEN.
"""

import os
import datetime as dt

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ───────────────────────── CONFIG ─────────────────────────
GRAPH_VERSION = "v23.0"
CACHE_TTL = 300                      # segundos de cache (evita rate limit)

NOME_CLIENTE = "Jayme Campos"
AD_ACCOUNT_ID = "act_197281793017681"

# Cores da marca AGM (tema azul)
AZUL = "#2563eb"
AZUL_CLARO = "#60a5fa"
VERDE = "#22c55e"
FUNDO_CARD = "#141c2e"
BORDA = "#243049"
# ───────────────────────────────────────────────────────────

st.set_page_config(
    page_title=f"Painel {NOME_CLIENTE} | AGM Tráfego",
    page_icon="📊",
    layout="wide",
)

# ───────────────────────── ESTILO ─────────────────────────
st.markdown(f"""
<style>
    #MainMenu, footer, header {{visibility: hidden;}}
    .block-container {{padding-top: 1.5rem; max-width: 1400px;}}

    .hero {{
        background: linear-gradient(120deg, {AZUL} 0%, #1e3a8a 100%);
        border-radius: 16px; padding: 22px 28px; margin-bottom: 8px;
        box-shadow: 0 6px 24px rgba(37,99,235,0.25);
    }}
    .hero h1 {{color: #fff; font-size: 1.7rem; margin: 0; font-weight: 700;}}
    .hero p {{color: #dbeafe; margin: 4px 0 0; font-size: .95rem;}}
    .hero .badge {{
        display:inline-block; background: rgba(255,255,255,.15); color:#fff;
        padding: 3px 12px; border-radius: 20px; font-size: .8rem; font-weight:600;
        letter-spacing: .5px;
    }}

    .secao {{
        font-size: 1.05rem; font-weight: 700; color: {AZUL_CLARO};
        margin: 22px 0 4px; padding-bottom: 6px;
        border-bottom: 1px solid {BORDA};
    }}

    div[data-testid="stMetric"] {{
        background: {FUNDO_CARD}; border: 1px solid {BORDA};
        padding: 14px 16px; border-radius: 14px;
    }}
    div[data-testid="stMetric"] label p {{color: #93a4bf !important; font-size:.82rem;}}
    div[data-testid="stMetricValue"] {{font-size: 1.55rem;}}
</style>
""", unsafe_allow_html=True)


# ───────────────────────── DADOS ─────────────────────────
def get_token() -> str:
    if "META_ACCESS_TOKEN" in st.secrets:
        return st.secrets["META_ACCESS_TOKEN"]
    token = os.environ.get("META_ACCESS_TOKEN")
    if not token:
        st.error("Token não configurado (.streamlit/secrets.toml ou variável de ambiente).")
        st.stop()
    return token


CAMPOS_TOTAIS = ",".join([
    "impressions", "reach", "frequency", "spend", "cpm", "cpc", "cpp", "ctr",
    "clicks", "inline_link_clicks", "cost_per_inline_link_click",
    "actions", "cost_per_action_type",
    "video_thruplay_watched_actions",
    "estimated_ad_recallers", "estimated_ad_recall_rate",
])


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def buscar_insights(account_id: str, token: str, date_preset: str) -> dict:
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{account_id}/insights"
    params = {"access_token": token, "date_preset": date_preset,
              "level": "account", "fields": CAMPOS_TOTAIS}
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    return data[0] if data else {}


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def buscar_serie_diaria(account_id: str, token: str, date_preset: str) -> pd.DataFrame:
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{account_id}/insights"
    params = {"access_token": token, "date_preset": date_preset, "level": "account",
              "time_increment": 1,
              "fields": "impressions,reach,inline_link_clicks,spend,actions"}
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    linhas = []
    for d in resp.json().get("data", []):
        acts = d.get("actions", [])
        linhas.append({
            "data": d.get("date_start"),
            "Alcance": int(d.get("reach", 0) or 0),
            "Impressões": int(d.get("impressions", 0) or 0),
            "Cliques no link": int(d.get("inline_link_clicks", 0) or 0),
            "Investimento": round(float(d.get("spend", 0) or 0), 2),
            "Engajamento": extrair_acao(acts, "post_engagement"),
            "Views de vídeo": extrair_acao(acts, "video_view"),
        })
    df = pd.DataFrame(linhas)
    if not df.empty:
        df["data"] = pd.to_datetime(df["data"])
    return df


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def buscar_por_campanha(account_id: str, token: str, date_preset: str) -> pd.DataFrame:
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{account_id}/insights"
    params = {"access_token": token, "date_preset": date_preset, "level": "campaign",
              "fields": "campaign_name,impressions,reach,frequency,ctr,cpm,spend,actions"}
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    linhas = []
    for d in resp.json().get("data", []):
        acts = d.get("actions", [])
        linhas.append({
            "Campanha": d.get("campaign_name", "—"),
            "Alcance": int(d.get("reach", 0) or 0),
            "Impressões": int(d.get("impressions", 0) or 0),
            "Freq.": round(float(d.get("frequency", 0) or 0), 2),
            "CTR (%)": round(float(d.get("ctr", 0) or 0), 2),
            "CPM (R$)": round(float(d.get("cpm", 0) or 0), 2),
            "Engajamento": extrair_acao(acts, "post_engagement"),
            "Views vídeo": extrair_acao(acts, "video_view"),
            "Investimento (R$)": round(float(d.get("spend", 0) or 0), 2),
        })
    df = pd.DataFrame(linhas)
    if not df.empty:
        df = df.sort_values("Investimento (R$)", ascending=False)
    return df


# ───────────────────────── HELPERS ─────────────────────────
def extrair_acao(actions, action_type) -> int:
    for a in actions or []:
        if a.get("action_type") == action_type:
            return int(float(a.get("value", 0)))
    return 0


def extrair_custo(cost_list, action_type) -> float:
    for a in cost_list or []:
        if a.get("action_type") == action_type:
            return float(a.get("value", 0))
    return 0.0


def fmt(n) -> str:
    try:
        return f"{int(float(n)):,}".replace(",", ".")
    except (ValueError, TypeError):
        return "0"


def fmt_money(v) -> str:
    try:
        s = f"{float(v):,.2f}"
    except (ValueError, TypeError):
        return "—"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_ou_traco(n) -> str:
    return fmt(n) if (n and float(n) > 0) else "—"


# ───────────────────────── SIDEBAR ─────────────────────────
with st.sidebar:
    st.markdown("### 📊 AGM Tráfego")
    st.caption(f"Painel exclusivo · {NOME_CLIENTE}")
    st.divider()

    periodo_label = st.selectbox(
        "Período",
        ["Hoje", "Ontem", "Últimos 7 dias", "Últimos 14 dias", "Últimos 30 dias"],
        index=2,
    )
    mapa_periodo = {"Hoje": "today", "Ontem": "yesterday", "Últimos 7 dias": "last_7d",
                    "Últimos 14 dias": "last_14d", "Últimos 30 dias": "last_30d"}
    date_preset = mapa_periodo[periodo_label]

    intervalo = st.slider("Atualizar a cada (min)", 1, 30, 5)
    st.caption(f"Última checagem: {dt.datetime.now():%H:%M:%S}")

st_autorefresh(interval=intervalo * 60 * 1000, key="refresh")


# ───────────────────────── HEADER ─────────────────────────
st.markdown(f"""
<div class="hero">
    <span class="badge">AGM TRÁFEGO</span>
    <h1>Desempenho · {NOME_CLIENTE}</h1>
    <p>Período: {periodo_label} · dados em tempo real via Meta Ads</p>
</div>
""", unsafe_allow_html=True)


# ───────────────────────── MAIN ─────────────────────────
token = get_token()

try:
    t = buscar_insights(AD_ACCOUNT_ID, token, date_preset)
except requests.HTTPError as e:
    st.error(f"Erro ao buscar dados da Meta API: {e}")
    st.stop()

if not t:
    st.info("Sem dados para o período selecionado ainda.")
    st.stop()

acoes = t.get("actions", [])
custos = t.get("cost_per_action_type", [])

# valores
spend = float(t.get("spend", 0) or 0)
engajamento = extrair_acao(acoes, "post_engagement")
reacoes = extrair_acao(acoes, "post_reaction")
comentarios = extrair_acao(acoes, "comment")
curtidas_liq = extrair_acao(acoes, "onsite_conversion.post_net_like")
salvamentos = extrair_acao(acoes, "onsite_conversion.post_save")
video_views = extrair_acao(acoes, "video_view")
thruplay = extrair_acao(t.get("video_thruplay_watched_actions", []), "video_view")
conversas = extrair_acao(acoes, "onsite_conversion.messaging_conversation_started_7d")
primeira_resp = extrair_acao(acoes, "onsite_conversion.messaging_first_reply")
recall = extrair_acao([{"action_type": "x", "value": t.get("estimated_ad_recallers", 0)}], "x")

custo_engaj = extrair_custo(custos, "post_engagement")
custo_view = extrair_custo(custos, "video_view")
custo_conversa = extrair_custo(custos, "onsite_conversion.messaging_conversation_started_7d")

# ── Seção 1: Alcance & Reconhecimento ──
st.markdown('<div class="secao">📣 Alcance & Reconhecimento</div>', unsafe_allow_html=True)
c = st.columns(5)
c[0].metric("Alcance", fmt(t.get("reach")))
c[1].metric("Impressões", fmt(t.get("impressions")))
c[2].metric("Frequência", f"{float(t.get('frequency', 0) or 0):.2f}")
c[3].metric("CPM (custo/mil impr.)", fmt_money(t.get("cpm")))
c[4].metric("Lembrança do anúncio", fmt_ou_traco(recall))

# ── Seção 2: Investimento & Eficiência ──
st.markdown('<div class="secao">💰 Investimento & Eficiência</div>', unsafe_allow_html=True)
c = st.columns(5)
c[0].metric("Investimento total", fmt_money(spend))
c[1].metric("CPC (custo/clique link)", fmt_money(t.get("cost_per_inline_link_click")))
c[2].metric("Custo por engajamento", fmt_money(custo_engaj))
c[3].metric("Custo por mil alcançados", fmt_money(t.get("cpp")))
c[4].metric("Custo por view de vídeo", fmt_money(custo_view))

# ── Seção 3: Tráfego & Engajamento ──
st.markdown('<div class="secao">🔗 Tráfego & Engajamento</div>', unsafe_allow_html=True)
c = st.columns(5)
c[0].metric("Cliques no link", fmt(t.get("inline_link_clicks")))
c[1].metric("CTR", f"{float(t.get('ctr', 0) or 0):.2f}%")
c[2].metric("Engajamento total", fmt(engajamento))
c[3].metric("Reações", fmt_ou_traco(reacoes))
c[4].metric("Comentários", fmt_ou_traco(comentarios))

c = st.columns(5)
c[0].metric("Curtidas/Seguidores", fmt_ou_traco(curtidas_liq))
c[1].metric("Salvamentos", fmt_ou_traco(salvamentos))
c[2].metric("▶️ Views de vídeo", fmt(video_views))
c[3].metric("✅ ThruPlay (vídeo assistido)", fmt_ou_traco(thruplay))
c[4].metric(" ", " ")

# ── Seção 4: Mensagens (só se houver) ──
if conversas > 0 or primeira_resp > 0:
    st.markdown('<div class="secao">💬 Conversas (WhatsApp / Direct)</div>', unsafe_allow_html=True)
    c = st.columns(5)
    c[0].metric("Conversas iniciadas", fmt_ou_traco(conversas))
    c[1].metric("Custo por conversa", fmt_money(custo_conversa))
    c[2].metric("1ª resposta", fmt_ou_traco(primeira_resp))
    c[3].metric(" ", " ")
    c[4].metric(" ", " ")

st.divider()

# ── Gráfico de evolução diária ──
serie = buscar_serie_diaria(AD_ACCOUNT_ID, token, date_preset)
if not serie.empty and len(serie) > 1:
    st.markdown('<div class="secao">📈 Evolução diária</div>', unsafe_allow_html=True)
    metrica = st.radio(
        "Métrica",
        ["Alcance", "Impressões", "Cliques no link", "Investimento",
         "Engajamento", "Views de vídeo"],
        horizontal=True, label_visibility="collapsed",
    )
    fig = px.area(serie, x="data", y=metrica, markers=True)
    fig.update_traces(line_color=AZUL_CLARO, fillcolor="rgba(96,165,250,0.15)")
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=330,
                      xaxis_title=None, yaxis_title=None,
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, width="stretch")

st.divider()

# ── Tabela por campanha ──
st.markdown('<div class="secao">📋 Por campanha</div>', unsafe_allow_html=True)
camp = buscar_por_campanha(AD_ACCOUNT_ID, token, date_preset)
if not camp.empty:
    st.dataframe(
        camp, width="stretch", hide_index=True,
        column_config={
            "Investimento (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
            "CPM (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
            "CTR (%)": st.column_config.NumberColumn(format="%.2f%%"),
        },
    )
else:
    st.info("Nenhuma campanha ativa no período.")

st.caption("Painel desenvolvido por AGM Tráfego · dados atualizados automaticamente via Meta Ads.")
