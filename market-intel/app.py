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


def extract_text_from_pdf(pdf_bytes: bytes, filename: str = "") -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text


def merge_pdf_texts(files_and_texts: list[tuple[str, str]]) -> str:
    parts = []
    for filename, text in files_and_texts:
        parts.append(f"=== DOCUMENTO: {filename} ===\n\n{text}")
    return "\n\n" + ("\n\n" + "=" * 60 + "\n\n").join(parts)


def build_prompt(pdf_text: str, company: str, period: str) -> str:
    lenses_list = "\n".join(f"- {l}" for l in LENSES)
    company_ctx = f"Empresa: {company}" if company else ""
    period_ctx = f"Período: {period}" if period else ""
    header = " | ".join(filter(None, [company_ctx, period_ctx]))
    header_line = f"Contexto: {header}\n\n" if header else ""

    return f"""Você é um analista sênior especializado em inteligência de mercado B2B para empresas de tecnologia, dados e serviços corporativos.

{header_line}Analise o(s) documento(s) abaixo (podem ser múltiplos arquivos da mesma empresa) com profundidade analítica e extraia insights estruturados e consolidados em exatamente 9 lentes estratégicas.

Para cada lente, forneça um objeto JSON com os seguintes campos:

CAMPOS DE RESUMO (visão rápida):
- "destaques": lista de 2 a 4 strings com os principais destaques mencionados
- "oportunidades": lista de 2 a 4 strings com oportunidades para fornecedores/parceiros nessa área
- "alertas": lista de 1 a 3 strings com riscos, desafios ou pontos de atenção
- "tendencia": string curta com a tendência geral (ex: "Alta", "Estável", "Queda", "Em transformação", "Aceleração")

CAMPOS DE DETALHES (análise aprofundada — seja específico e rico em informação):
- "detalhes": objeto com:
    - "citacoes": lista de 3 a 6 strings com trechos ou frases REAIS extraídas dos documentos que embasam os insights. Cada citação deve vir com contexto mínimo (ex: "[Seção X]" ou "[CEO na call]"). Use aspas duplas ao redor do trecho. Priorize afirmações com dados, metas, posicionamentos estratégicos ou reconhecimentos de desafio.
    - "numeros": lista de 3 a 6 strings com métricas, valores absolutos, percentuais, variações YoY/QoQ, metas, investimentos ou indicadores ESPECÍFICOS mencionados para essa lente. Inclua unidade e contexto (ex: "R$ 2,3 bilhões investidos em tecnologia em 2025, crescimento de 18% vs 2024").
    - "projetos": lista de 2 a 5 strings com nomes de projetos, produtos, plataformas, programas, iniciativas ou parcerias específicas citadas nos documentos para essa lente. Inclua uma frase de contexto sobre o que é e o seu status/objetivo (ex: "Plataforma X — lançada em Q3, foco em automação de crédito para PMEs").
    - "contexto_oportunidades": lista de 2 a 4 strings, uma por oportunidade listada em "oportunidades", com análise aprofundada do por quê essa oportunidade existe, quais sinais do relatório a sustentam, e como um fornecedor pode endereçá-la de forma concreta.
    - "contexto_alertas": lista de 1 a 3 strings, uma por alerta listado em "alertas", com análise aprofundada das causas, implicações para fornecedores e como o mercado ou a empresa está reagindo a esse risco.

Lentes a analisar:
{lenses_list}

Seja específico. Evite generalidades. Use os dados reais do documento. Se não houver informação suficiente para uma lente, preencha com o que há e indique brevemente a limitação em "contexto_oportunidades".

Responda APENAS com um JSON válido no seguinte formato (sem markdown, sem texto antes ou depois):
{{
  "Marketing & Mídia Digital": {{
    "destaques": [...],
    "oportunidades": [...],
    "alertas": [...],
    "tendencia": "...",
    "detalhes": {{
      "citacoes": [...],
      "numeros": [...],
      "projetos": [...],
      "contexto_oportunidades": [...],
      "contexto_alertas": [...]
    }}
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

DOCUMENTOS:
{pdf_text[:70000]}
"""


def analyze_with_claude(pdf_text: str, company: str, period: str) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY não encontrada nas variáveis de ambiente.")

    client = anthropic.Anthropic(api_key=api_key)

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=8000,
        messages=[
            {
                "role": "user",
                "content": build_prompt(pdf_text, company, period),
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
    if any(w in trend_lower for w in ["alta", "crescimento", "aumento", "aceleração", "aceleracao", "expansão"]):
        color = "#22c55e"
        icon = "↑"
    elif any(w in trend_lower for w in ["queda", "redução", "declínio", "recuo", "desaceleração"]):
        color = "#ef4444"
        icon = "↓"
    elif any(w in trend_lower for w in ["transformação", "mudança", "evolução", "transição", "disrupção"]):
        color = "#f59e0b"
        icon = "⟳"
    else:
        color = "#6b7280"
        icon = "→"
    return f'<span style="background:{color};color:white;padding:2px 10px;border-radius:12px;font-size:0.78rem;font-weight:600;">{icon} {trend}</span>'


def render_lens_card(lens_name: str, data: dict, card_index: int):
    icon = LENS_ICONS.get(lens_name, "📌")
    trend_html = render_trend_badge(data.get("tendencia", "Estável"))

    with st.container():
        st.markdown(
            f"""
            <div style="
                border:1px solid #e2e8f0;
                border-radius:12px;
                padding:20px 24px 4px 24px;
                margin-bottom:4px;
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

        detalhes = data.get("detalhes", {})
        oportunidades = data.get("oportunidades", [])
        alertas = data.get("alertas", [])

        if detalhes:
            with st.expander("🔍 Ver detalhes aprofundados"):

                citacoes = detalhes.get("citacoes", [])
                numeros = detalhes.get("numeros", [])
                projetos = detalhes.get("projetos", [])
                ctx_ops = detalhes.get("contexto_oportunidades", [])
                ctx_alerts = detalhes.get("contexto_alertas", [])

                # Row 1: Citações + Números + Projetos
                st.markdown("---")
                r1c1, r1c2, r1c3 = st.columns(3)

                with r1c1:
                    st.markdown("#### 💬 Citações do Relatório")
                    if citacoes:
                        for c in citacoes:
                            st.markdown(
                                f"""<blockquote style="border-left:3px solid #6366f1;padding:8px 14px;margin:8px 0;background:#f8f7ff;border-radius:0 8px 8px 0;font-size:0.87rem;color:#374151;font-style:italic;line-height:1.6;">{c}</blockquote>""",
                                unsafe_allow_html=True,
                            )
                    else:
                        st.caption("Sem citações identificadas.")

                with r1c2:
                    st.markdown("#### 📊 Números & Métricas")
                    if numeros:
                        for n in numeros:
                            st.markdown(
                                f"""<div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:8px 12px;margin:6px 0;font-size:0.87rem;color:#166534;font-weight:500;">📌 {n}</div>""",
                                unsafe_allow_html=True,
                            )
                    else:
                        st.caption("Sem métricas específicas identificadas.")

                with r1c3:
                    st.markdown("#### 🚀 Projetos & Iniciativas")
                    if projetos:
                        for p in projetos:
                            st.markdown(
                                f"""<div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:8px 12px;margin:6px 0;font-size:0.87rem;color:#1e40af;line-height:1.55;">🔷 {p}</div>""",
                                unsafe_allow_html=True,
                            )
                    else:
                        st.caption("Nenhum projeto ou iniciativa identificado.")

                # Row 2: Contexto por Oportunidade + Contexto por Alerta
                st.markdown("---")
                r2c1, r2c2 = st.columns(2)

                with r2c1:
                    st.markdown("#### 🎯 Contexto das Oportunidades")
                    if ctx_ops and oportunidades:
                        for i, ctx in enumerate(ctx_ops):
                            op_label = oportunidades[i] if i < len(oportunidades) else f"Oportunidade {i+1}"
                            st.markdown(
                                f"""<div style="margin-bottom:12px;">
                                    <div style="font-size:0.82rem;font-weight:700;color:#7c3aed;margin-bottom:4px;text-transform:uppercase;letter-spacing:0.03em;">↳ {op_label}</div>
                                    <div style="background:#faf5ff;border:1px solid #e9d5ff;border-radius:8px;padding:10px 14px;font-size:0.87rem;color:#4c1d95;line-height:1.65;">{ctx}</div>
                                </div>""",
                                unsafe_allow_html=True,
                            )
                    elif ctx_ops:
                        for ctx in ctx_ops:
                            st.markdown(
                                f"""<div style="background:#faf5ff;border:1px solid #e9d5ff;border-radius:8px;padding:10px 14px;margin:6px 0;font-size:0.87rem;color:#4c1d95;line-height:1.65;">{ctx}</div>""",
                                unsafe_allow_html=True,
                            )
                    else:
                        st.caption("Sem contexto adicional para as oportunidades.")

                with r2c2:
                    st.markdown("#### ⚠️ Contexto dos Alertas")
                    if ctx_alerts and alertas:
                        for i, ctx in enumerate(ctx_alerts):
                            alert_label = alertas[i] if i < len(alertas) else f"Alerta {i+1}"
                            st.markdown(
                                f"""<div style="margin-bottom:12px;">
                                    <div style="font-size:0.82rem;font-weight:700;color:#b91c1c;margin-bottom:4px;text-transform:uppercase;letter-spacing:0.03em;">↳ {alert_label}</div>
                                    <div style="background:#fff1f2;border:1px solid #fecdd3;border-radius:8px;padding:10px 14px;font-size:0.87rem;color:#881337;line-height:1.65;">{ctx}</div>
                                </div>""",
                                unsafe_allow_html=True,
                            )
                    elif ctx_alerts:
                        for ctx in ctx_alerts:
                            st.markdown(
                                f"""<div style="background:#fff1f2;border:1px solid #fecdd3;border-radius:8px;padding:10px 14px;margin:6px 0;font-size:0.87rem;color:#881337;line-height:1.65;">{ctx}</div>""",
                                unsafe_allow_html=True,
                            )
                    else:
                        st.caption("Sem contexto adicional para os alertas.")

        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("<div style='margin-bottom:12px'></div>", unsafe_allow_html=True)


def main():
    st.title("📊 Market Intel")
    st.markdown(
        "Faça upload de **um ou mais PDFs** de uma empresa brasileira e extraia inteligência estratégica consolidada em 9 lentes de mercado."
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

    col_company, col_period = st.columns([2, 1])
    with col_company:
        company_name = st.text_input(
            "🏢 Nome da empresa",
            placeholder="Ex: Itaú, Ambev, Embraer...",
            help="Opcional — ajuda a contextualizar a análise.",
        )
    with col_period:
        period = st.text_input(
            "📅 Período",
            placeholder="Ex: 4T25, 1T26, 2025...",
            help="Opcional — trimestre ou ano de referência.",
        )

    uploaded_files = st.file_uploader(
        "Selecione os PDFs do release trimestral (pode enviar vários)",
        type=["pdf"],
        accept_multiple_files=True,
        help="Envie um ou mais PDFs da mesma empresa. O conteúdo será consolidado em uma análise única.",
    )

    if uploaded_files:
        total_size = sum(f.size for f in uploaded_files) / 1024
        if len(uploaded_files) == 1:
            st.success(f"**1 arquivo** carregado — {uploaded_files[0].name} ({total_size:.1f} KB)")
        else:
            st.success(f"**{len(uploaded_files)} arquivos** carregados — {total_size:.1f} KB no total")
            with st.expander(f"Ver lista de arquivos ({len(uploaded_files)})"):
                for i, f in enumerate(uploaded_files, 1):
                    st.markdown(f"**{i}.** {f.name} · {f.size / 1024:.1f} KB")

        label = company_name or "empresa"
        per_label = f" · {period}" if period else ""
        analyze_btn = st.button(
            f"🚀 Analisar {label}{per_label} com Claude",
            type="primary",
            use_container_width=True,
        )

        if analyze_btn:
            if "results" in st.session_state:
                del st.session_state["results"]

            files_and_texts = []
            with st.spinner(f"Extraindo texto de {len(uploaded_files)} arquivo(s)..."):
                for f in uploaded_files:
                    pdf_bytes = f.read()
                    text = extract_text_from_pdf(pdf_bytes, f.name)
                    if text.strip():
                        files_and_texts.append((f.name, text))
                    else:
                        st.warning(f"⚠️ Não foi possível extrair texto de **{f.name}** — ignorado.")

            if not files_and_texts:
                st.error("Nenhum arquivo com texto válido. Verifique se os PDFs não são escaneados ou protegidos.")
                return

            merged_text = merge_pdf_texts(files_and_texts)
            total_chars = len(merged_text)
            st.info(
                f"**{len(files_and_texts)} arquivo(s)** processados · **{total_chars:,} caracteres** extraídos. Enviando para análise..."
            )

            with st.spinner("Analisando com Claude Opus... Isso pode levar alguns segundos."):
                try:
                    results = analyze_with_claude(merged_text, company_name, period)
                    st.session_state["results"] = results
                    st.session_state["display_company"] = company_name or (uploaded_files[0].name.replace(".pdf", "") if len(uploaded_files) == 1 else "Empresa")
                    st.session_state["display_period"] = period
                    st.session_state["files_count"] = len(files_and_texts)
                except json.JSONDecodeError as e:
                    st.error(f"Erro ao interpretar resposta da IA: {e}")
                    return
                except Exception as e:
                    st.error(f"Erro na análise: {e}")
                    return

    if "results" in st.session_state:
        results = st.session_state["results"]
        display_company = st.session_state.get("display_company", "Empresa")
        display_period = st.session_state.get("display_period", "")
        files_count = st.session_state.get("files_count", 1)

        period_suffix = f" · {display_period}" if display_period else ""
        files_label = f"{files_count} arquivo(s) consolidado(s)" if files_count > 1 else "1 arquivo"

        st.success(f"✅ Análise concluída — {files_label}")
        st.subheader(f"Insights estratégicos — {display_company}{period_suffix}")

        lenses_to_show = [l for l in selected_lenses if l in results]

        if not lenses_to_show:
            st.warning("Nenhuma lente selecionada. Use o filtro lateral para escolher os segmentos.")
            return

        st.markdown(f"Exibindo **{len(lenses_to_show)}** de {len(LENSES)} lentes · clique em **🔍 Ver detalhes** em cada card para análise aprofundada.")
        st.divider()

        for i, lens in enumerate(lenses_to_show):
            render_lens_card(lens, results[lens], i)


if __name__ == "__main__":
    main()
