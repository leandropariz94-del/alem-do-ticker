import streamlit as st
import anthropic
import fitz
import json
import os

st.set_page_config(
    page_title="Market Intel",
    page_icon="📊",
    layout="wide",
)

LENSES = [
    "Marketing & Mídia Digital",
    "Dados / IA / Analytics",
    "Infraestrutura & Cloud",
    "CX & Relacionamento",
    "RH & Cultura",
    "Educação Corporativa",
    "Jurídico & Compliance",
    "Saúde Financeira",
    "ESG",
]

LENS_ICONS = {
    "Marketing & Mídia Digital": "📣",
    "Dados / IA / Analytics": "🤖",
    "Infraestrutura & Cloud": "☁️",
    "CX & Relacionamento": "💬",
    "RH & Cultura": "👥",
    "Educação Corporativa": "🎓",
    "Jurídico & Compliance": "⚖️",
    "Saúde Financeira": "💰",
    "ESG": "🌿",
}


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text


def build_prompt(pdf_text: str) -> str:
    lenses_list = "\n".join(f"- {l}" for l in LENSES)
    return f"""Você é um analista especializado em inteligência de mercado B2B.

Analise o release trimestral abaixo e extraia insights estruturados em exatamente 9 lentes estratégicas.

Para cada lente, forneça um objeto JSON com os campos:
- "destaques": lista de strings com os principais destaques mencionados no release
- "oportunidades": lista de strings com oportunidades para fornecedores/parceiros nessa área
- "alertas": lista de strings com riscos, desafios ou pontos de atenção
- "tendencia": string com a tendência geral observada para esse segmento (ex: "Alta", "Estável", "Queda", "Em transformação")

Lentes a analisar:
{lenses_list}

Responda APENAS com um JSON válido no seguinte formato (sem markdown, sem texto antes ou depois):
{{
  "Marketing & Mídia Digital": {{
    "destaques": [...],
    "oportunidades": [...],
    "alertas": [...],
    "tendencia": "..."
  }},
  "Dados / IA / Analytics": {{...}},
  "Infraestrutura & Cloud": {{...}},
  "CX & Relacionamento": {{...}},
  "RH & Cultura": {{...}},
  "Educação Corporativa": {{...}},
  "Jurídico & Compliance": {{...}},
  "Saúde Financeira": {{...}},
  "ESG": {{...}}
}}

RELEASE TRIMESTRAL:
{pdf_text[:60000]}
"""


def analyze_with_claude(pdf_text: str) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY não encontrada nas variáveis de ambiente.")

    client = anthropic.Anthropic(api_key=api_key)

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": build_prompt(pdf_text),
            }
        ],
    )

    raw = message.content[0].text.strip()

    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1])

    return json.loads(raw)


def render_trend_badge(trend: str) -> str:
    trend_lower = trend.lower()
    if "alta" in trend_lower or "crescimento" in trend_lower or "aumento" in trend_lower:
        color = "#22c55e"
        icon = "↑"
    elif "queda" in trend_lower or "redução" in trend_lower or "declínio" in trend_lower:
        color = "#ef4444"
        icon = "↓"
    elif "transformação" in trend_lower or "mudança" in trend_lower or "evolução" in trend_lower:
        color = "#f59e0b"
        icon = "⟳"
    else:
        color = "#6b7280"
        icon = "→"
    return f'<span style="background:{color};color:white;padding:2px 10px;border-radius:12px;font-size:0.78rem;font-weight:600;">{icon} {trend}</span>'


def render_lens_card(lens_name: str, data: dict):
    icon = LENS_ICONS.get(lens_name, "📌")
    trend_html = render_trend_badge(data.get("tendencia", "Estável"))

    with st.container():
        st.markdown(
            f"""
            <div style="
                border:1px solid #e2e8f0;
                border-radius:12px;
                padding:20px 24px;
                margin-bottom:16px;
                background:#ffffff;
                box-shadow:0 1px 4px rgba(0,0,0,0.06);
            ">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
                    <h3 style="margin:0;font-size:1.05rem;color:#1e293b;">{icon} {lens_name}</h3>
                    {trend_html}
                </div>
            """,
            unsafe_allow_html=True,
        )

        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("**✅ Destaques**")
            for item in data.get("destaques", []):
                st.markdown(f"- {item}")

        with col2:
            st.markdown("**🎯 Oportunidades para Fornecedores**")
            for item in data.get("oportunidades", []):
                st.markdown(f"- {item}")

        with col3:
            st.markdown("**⚠️ Alertas**")
            for item in data.get("alertas", []):
                st.markdown(f"- {item}")

        st.markdown("</div>", unsafe_allow_html=True)


def main():
    st.title("📊 Market Intel")
    st.markdown(
        "Faça upload do **release trimestral** de uma empresa brasileira e extraia inteligência estratégica em 9 lentes de mercado."
    )
    st.divider()

    with st.sidebar:
        st.header("🔍 Filtrar por Lente")
        st.markdown("Selecione os segmentos que deseja visualizar:")

        select_all = st.checkbox("Selecionar todas", value=True)

        if select_all:
            selected_lenses = LENSES
            for lens in LENSES:
                icon = LENS_ICONS.get(lens, "📌")
                st.checkbox(f"{icon} {lens}", value=True, disabled=True, key=f"cb_{lens}")
        else:
            selected_lenses = []
            for lens in LENSES:
                icon = LENS_ICONS.get(lens, "📌")
                checked = st.checkbox(f"{icon} {lens}", value=True, key=f"cb_{lens}")
                if checked:
                    selected_lenses.append(lens)

        st.divider()
        st.caption("**Market Intel** · Análise por IA (Claude)")

    uploaded_file = st.file_uploader(
        "Selecione o PDF do release trimestral",
        type=["pdf"],
        help="Releases de resultados, relatórios de earnings ou relatórios trimestrais em PDF.",
    )

    if uploaded_file is not None:
        st.success(f"Arquivo carregado: **{uploaded_file.name}** ({uploaded_file.size / 1024:.1f} KB)")

        analyze_btn = st.button("🚀 Analisar com Claude", type="primary", use_container_width=True)

        if analyze_btn:
            if "results" in st.session_state:
                del st.session_state["results"]

            with st.spinner("Extraindo texto do PDF..."):
                pdf_bytes = uploaded_file.read()
                pdf_text = extract_text_from_pdf(pdf_bytes)

            if not pdf_text.strip():
                st.error("Não foi possível extrair texto do PDF. Verifique se o arquivo não é escaneado ou protegido.")
                return

            st.info(f"Texto extraído: **{len(pdf_text):,} caracteres**. Enviando para análise...")

            with st.spinner("Analisando com Claude Opus... Isso pode levar alguns segundos."):
                try:
                    results = analyze_with_claude(pdf_text)
                    st.session_state["results"] = results
                    st.session_state["company_name"] = uploaded_file.name.replace(".pdf", "")
                except json.JSONDecodeError as e:
                    st.error(f"Erro ao interpretar resposta da IA: {e}")
                    return
                except Exception as e:
                    st.error(f"Erro na análise: {e}")
                    return

    if "results" in st.session_state:
        results = st.session_state["results"]
        company_name = st.session_state.get("company_name", "Empresa")

        st.success("✅ Análise concluída com sucesso!")
        st.subheader(f"Insights estratégicos — {company_name}")

        lenses_to_show = [l for l in selected_lenses if l in results]

        if not lenses_to_show:
            st.warning("Nenhuma lente selecionada. Use o filtro lateral para escolher os segmentos.")
            return

        st.markdown(f"Exibindo **{len(lenses_to_show)}** de {len(LENSES)} lentes.")
        st.divider()

        for lens in lenses_to_show:
            render_lens_card(lens, results[lens])


if __name__ == "__main__":
    main()
