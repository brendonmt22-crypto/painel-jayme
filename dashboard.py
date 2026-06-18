"""
Dashboard AGM Tráfego - Painel client-facing de Meta Ads em tempo (quase) real.

COMO FUNCIONA
-------------
- Puxa métricas direto da Meta Graph API (Insights) por ad_account_id.
- Auto-refresh: rebusca os dados a cada N minutos (configurável na barra lateral).
- NÃO mostra custo/gasto por padrão (regra fixa AGM para relatórios de cliente).
  Para ligar, mude MOSTRAR_CUSTO = True logo abaixo.

SEGURANÇA
---------
- O token NUNCA fica no código. Coloque em .streamlit/secrets.toml (ver instruções
  no fim do arquivo) ou na variável de ambiente META_ACCESS_TOKEN.

RODAR LOCAL
-----------
    pip install streamlit requests pandas plotly streamlit-autorefresh
    streamlit run dashboard.py
"""

import os
import datetime as dt

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ───────────────────────── CONFIG ─────────────────────────
MOSTRAR_CUSTO = False           # regra AGM: cliente NÃO vê gasto. True só pra uso interno.
GRAPH_VERSION = "v23.0"         # ajuste para a versão que você usa hoje na sua integração
CACHE_TTL = 300                 # segundos de cache (evita estourar rate limit da Meta)

# Cliente desse painel. Cada cliente = um app/deploy com seu próprio account_id.
NOME_CLIENTE = "Jayme Campos"
AD_ACCOUNT_ID = "act_197281793017681"   # Jayme Campos

CORES = {"primaria": "#1a73e8", "fundo": "#0e1117", "destaque": "#00c896"}
# ───────────────────────────────────────────────────────────


st.set_page_config(
    page_title=f"Painel {NOME_CLIENTE} | AGM Tráfego",
    page_icon="📊",
    layout="wide",
)


def get_token() -> str:
    """Pega o token de forma segura (secrets do Streamlit ou variável de ambiente)."""
    if "META_ACCESS_TOKEN" in st.secrets:
        return st.secrets["META_ACCESS_TOKEN"]
    token = os.environ.get("META_ACCESS_TOKEN")
    if not token:
        st.error(
            "Token não configurado. Crie .streamlit/secrets.toml com "
            "META_ACCESS_TOKEN = \"seu_token\" ou defina a variável de ambiente."
        )
        st.stop()
    return token


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def buscar_insights(account_id: str, token: str, date_preset: str) -> dict:
    """
    Busca métricas agregadas da conta para o período.
    Retorna dict com os totais. Cacheado por CACHE_TTL segundos.
    """
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{account_id}/insights"
    params = {
        "access_token": token,
        "date_preset": date_preset,
        "level": "account",
        "fields": ",".join([
            "impressions",
            "reach",
            "frequency",
            "clicks",
            "inline_link_clicks",
            "ctr",
            "actions",
            "estimated_ad_recallers",       # reconhecimento de marca/candidato
            "estimated_ad_recall_rate",
            "video_thruplay_watched_actions",  # vídeo assistido (ThruPlay)
            "spend",  # buscamos, mas só exibimos se MOSTRAR_CUSTO=True
        ]),
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    return data[0] if data else {}


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def buscar_serie_diaria(account_id: str, token: str, date_preset: str) -> pd.DataFrame:
    """Busca métricas quebradas por dia para o gráfico de tendência."""
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{account_id}/insights"
    params = {
        "access_token": token,
        "date_preset": date_preset,
        "level": "account",
        "time_increment": 1,  # 1 = por dia
        "fields": "impressions,reach,inline_link_clicks,actions",
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    linhas = []
    for d in resp.json().get("data", []):
        linhas.append({
            "data": d.get("date_start"),
            "Alcance": int(d.get("reach", 0)),
            "Impressões": int(d.get("impressions", 0)),
            "Engajamento": extrair_acao(d.get("actions", []), "post_engagement"),
            "Views de vídeo": extrair_acao(d.get("actions", []), "video_view"),
            "Curtidas/Seguidores": extrair_acao(d.get("actions", []), "like"),
        })
    return pd.DataFrame(linhas)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def buscar_por_campanha(account_id: str, token: str, date_preset: str) -> pd.DataFrame:
    """Tabela por campanha (sem custo no client-facing)."""
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{account_id}/insights"
    params = {
        "access_token": token,
        "date_preset": date_preset,
        "level": "campaign",
        "fields": "campaign_name,impressions,reach,frequency,ctr,actions",
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    linhas = []
    for d in resp.json().get("data", []):
        linhas.append({
            "Campanha": d.get("campaign_name", "—"),
            "Alcance": int(d.get("reach", 0)),
            "Impressões": int(d.get("impressions", 0)),
            "Frequência": round(float(d.get("frequency", 0)), 2),
            "CTR (%)": round(float(d.get("ctr", 0)), 2),
            "Engajamento": extrair_acao(d.get("actions", []), "post_engagement"),
            "Views de vídeo": extrair_acao(d.get("actions", []), "video_view"),
        })
    return pd.DataFrame(linhas)


def extrair_acao(actions: list, action_type: str) -> int:
    """Extrai o valor de uma ação específica da lista de actions da Meta."""
    for a in actions or []:
        if a.get("action_type") == action_type:
            return int(float(a.get("value", 0)))
    return 0


def fmt(n) -> str:
    """Formata número grande com separador de milhar pt-BR."""
    try:
        return f"{int(n):,}".replace(",", ".")
    except (ValueError, TypeError):
        return "0"


# ───────────────────────── SIDEBAR ─────────────────────────
with st.sidebar:
    st.markdown(f"### 📊 AGM Tráfego")
    st.caption(f"Painel exclusivo · {NOME_CLIENTE}")

    periodo_label = st.selectbox(
        "Período",
        ["Hoje", "Ontem", "Últimos 7 dias", "Últimos 14 dias", "Últimos 30 dias"],
        index=2,
    )
    mapa_periodo = {
        "Hoje": "today",
        "Ontem": "yesterday",
        "Últimos 7 dias": "last_7d",
        "Últimos 14 dias": "last_14d",
        "Últimos 30 dias": "last_30d",
    }
    date_preset = mapa_periodo[periodo_label]

    intervalo = st.slider("Atualizar a cada (minutos)", 1, 30, 5)
    st.caption(f"Última checagem: {dt.datetime.now():%H:%M:%S}")

# auto-refresh: dispara rerun no intervalo escolhido
st_autorefresh(interval=intervalo * 60 * 1000, key="refresh")


# ───────────────────────── MAIN ─────────────────────────
token = get_token()

st.markdown(f"## Desempenho · {NOME_CLIENTE}")
st.caption(f"Período: {periodo_label} · dados via Meta Ads")

try:
    totais = buscar_insights(AD_ACCOUNT_ID, token, date_preset)
except requests.HTTPError as e:
    st.error(f"Erro ao buscar dados da Meta API: {e}")
    st.stop()

if not totais:
    st.info("Sem dados para o período selecionado ainda.")
    st.stop()

# KPIs principais — foco em ALCANCE / RECONHECIMENTO
acoes = totais.get("actions", [])
engajamento = extrair_acao(acoes, "post_engagement")
curtidas = extrair_acao(acoes, "like")              # curtidas de página / seguidores
video_views = extrair_acao(acoes, "video_view")
thruplay = extrair_acao(totais.get("video_thruplay_watched_actions", []),
                        "video_view")
recall = int(float(totais.get("estimated_ad_recallers", 0)))

# Linha 1 — métricas de alcance (o que importa em reconhecimento)
cols = st.columns(5)
cols[0].metric("🎯 Alcance", fmt(totais.get("reach")))
cols[1].metric("Impressões", fmt(totais.get("impressions")))
cols[2].metric("Frequência", f"{float(totais.get('frequency', 0)):.2f}")
cols[3].metric("CTR", f"{float(totais.get('ctr', 0)):.2f}%")
cols[4].metric("Lembrança do anúncio", fmt(recall))

# Linha 2 — engajamento / seguidores / vídeo
cols2 = st.columns(5)
cols2[0].metric("👍 Engajamento", fmt(engajamento))
cols2[1].metric("➕ Curtidas/Seguidores", fmt(curtidas))
cols2[2].metric("▶️ Views de vídeo", fmt(video_views))
cols2[3].metric("✅ ThruPlay", fmt(thruplay))
if MOSTRAR_CUSTO:
    cols2[4].metric("Investimento", f"R$ {float(totais.get('spend', 0)):.2f}")

st.divider()

# Gráfico de tendência
serie = buscar_serie_diaria(AD_ACCOUNT_ID, token, date_preset)
if not serie.empty:
    st.markdown("#### Evolução diária")
    metrica = st.radio(
        "Métrica",
        ["Alcance", "Impressões", "Engajamento", "Views de vídeo", "Curtidas/Seguidores"],
        horizontal=True,
        label_visibility="collapsed",
    )
    fig = px.area(serie, x="data", y=metrica, markers=True)
    fig.update_traces(line_color=CORES["destaque"], fillcolor="rgba(0,200,150,0.15)")
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=320)
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# Tabela por campanha
st.markdown("#### Por campanha")
camp = buscar_por_campanha(AD_ACCOUNT_ID, token, date_preset)
if not camp.empty:
    st.dataframe(camp, use_container_width=True, hide_index=True)
else:
    st.info("Nenhuma campanha ativa no período.")

st.caption("Painel desenvolvido por AGM Tráfego · dados atualizados automaticamente.")
