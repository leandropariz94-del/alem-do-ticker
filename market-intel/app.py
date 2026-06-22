import streamlit as st
import anthropic
import fitz
import json
import os
import sqlite3
from datetime import datetime

st.set_page_config(
    page_title="Market Intel",
    page_icon="📊",
    layout="wide",
)

DB_PATH = os.path.join(os.path.dirname(__file__), "market_intel.db")

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


# ─── Database ────────────────────────────────────────────────────────────────

def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS analyses (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            company       TEXT    NOT NULL,
            period        TEXT    NOT NULL DEFAULT '',
            created_at    TEXT    NOT NULL,
            files_count   INTEGER NOT NULL DEFAULT 1,
            results_json  TEXT    NOT NULL,
            score         REAL    NOT NULL DEFAULT 0.0
        )
    """)
    con.commit()
    con.close()


def compute_opportunity_score(results: dict) -> float:
    total = 0.0
    for lens_data in results.values():
        ops    = len(lens_data.get("oportunidades", []))
        alerts = len(lens_data.get("alertas", []))
        trend  = lens_data.get("tendencia", "").lower()

        if any(w in trend for w in ["alta", "crescimento", "aumento", "aceleração", "aceleracao", "expansão"]):
            trend_score = 2.0
        elif any(w in trend for w in ["transformação", "transformacao", "mudança", "evolução", "transição", "disrupção"]):
            trend_score = 1.0
        elif any(w in trend for w in ["queda", "redução", "reducao", "declínio", "recuo", "desaceleração"]):
            trend_score = -2.0
        else:
            trend_score = 0.0

        total += ops * 3.0 + trend_score - alerts * 0.5

    # Normalize: min ≈ -31.5  max ≈ 126
    normalized = (total + 31.5) / 157.5 * 100
    return round(max(0.0, min(100.0, normalized)), 1)


def save_analysis(company: str, period: str, files_count: int, results: dict) -> int:
    score = compute_opportunity_score(results)
    con = sqlite3.connect(DB_PATH)
    cur = con.execute(
        "INSERT INTO analyses (company, period, created_at, files_count, results_json, score) VALUES (?, ?, ?, ?, ?, ?)",
        (company, period, datetime.now().isoformat(timespec="seconds"), files_count, json.dumps(results, ensure_ascii=False), score),
    )
    row_id = cur.lastrowid
    con.commit()
    con.close()
    return row_id


def list_analyses() -> list[dict]:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, company, period, created_at, files_count, score FROM analyses ORDER BY created_at DESC"
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def list_periods() -> list[str]:
    con = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT DISTINCT period FROM analyses WHERE period != '' ORDER BY period DESC"
    ).fetchall()
    con.close()
    return [r[0] for r in rows]


def load_analysis(analysis_id: int) -> dict | None:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
    con.close()
    if row is None:
        return None
    rec = dict(row)
    rec["results"] = json.loads(rec["results_json"])
    return rec


def delete_analysis(analysis_id: int):
    con = sqlite3.connect(DB_PATH)
    con.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,))
    con.commit()
    con.close()


def analyses_for_period(period: str) -> list[dict]:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, company, period, created_at, files_count, score, results_json FROM analyses WHERE period = ? ORDER BY score DESC",
        (period,),
    ).fetchall()
    con.close()
    result = []
    for r in rows:
        rec = dict(r)
        rec["results"] = json.loads(rec["results_json"])
        result.append(rec)
    return result


# ─── PDF / Claude ─────────────────────────────────────────────────────────────

def extract_text_from_pdf(pdf_bytes: bytes, filename: str = "") -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = "".join(page.get_text() for page in doc)
    doc.close()
    return text


def merge_pdf_texts(files_and_texts: list[tuple[str, str]]) -> str:
    sep = "\n\n" + "=" * 60 + "\n\n"
    parts = [f"=== DOCUMENTO: {fn} ===\n\n{txt}" for fn, txt in files_and_texts]
    return "\n\n" + sep.join(parts)


def build_prompt(pdf_text: str, company: str, period: str) -> str:
    lenses_list = "\n".join(f"- {l}" for l in LENSES)
    parts = [f"Empresa: {company}" if company else "", f"Período: {period}" if period else ""]
    header = " | ".join(p for p in parts if p)
    header_line = f"Contexto: {header}\n\n" if header else ""

    return f"""Você é um analista sênior especializado em inteligência de mercado B2B para empresas de tecnologia, dados e serviços corporativos.

{header_line}Analise o(s) documento(s) abaixo com profundidade analítica e extraia insights estruturados e consolidados em exatamente 9 lentes estratégicas.

Para cada lente, forneça um objeto JSON com os seguintes campos:

CAMPOS DE RESUMO (visão rápida):
- "destaques": lista de 2 a 4 strings com os principais destaques mencionados
- "oportunidades": lista de 2 a 4 strings com oportunidades para fornecedores/parceiros nessa área
- "alertas": lista de 1 a 3 strings com riscos, desafios ou pontos de atenção
- "tendencia": string curta com a tendência geral (ex: "Alta", "Estável", "Queda", "Em transformação", "Aceleração")

CAMPOS DE DETALHES (análise aprofundada — seja específico e rico em informação):
- "detalhes": objeto com:
    - "citacoes": lista de 3 a 6 strings com trechos ou frases REAIS extraídas dos documentos que embasam os insights. Cada citação deve vir com contexto mínimo (ex: "[Seção X]" ou "[CEO na call]"). Use aspas duplas ao redor do trecho.
    - "numeros": lista de 3 a 6 strings com métricas, valores absolutos, percentuais, variações YoY/QoQ, metas, investimentos ou indicadores ESPECÍFICOS. Inclua unidade e contexto (ex: "R$ 2,3 bilhões investidos em tecnologia em 2025, crescimento de 18% vs 2024").
    - "projetos": lista de 2 a 5 strings com nomes de projetos, produtos, plataformas, programas, iniciativas ou parcerias específicas citadas. Inclua uma frase sobre o que é e seu status/objetivo.
    - "contexto_oportunidades": lista de 2 a 4 strings — uma análise aprofundada por oportunidade: por que existe, quais sinais a sustentam, como um fornecedor pode endereçá-la concretamente.
    - "contexto_alertas": lista de 1 a 3 strings — uma análise aprofundada por alerta: causas, implicações para fornecedores, como a empresa está reagindo.

Lentes a analisar:
{lenses_list}

Seja específico. Evite generalidades. Use os dados reais do documento.

Responda APENAS com um JSON válido no seguinte formato (sem markdown, sem texto antes ou depois):
{{
  "Marketing & Mídia Digital": {{
    "destaques": [...], "oportunidades": [...], "alertas": [...], "tendencia": "...",
    "detalhes": {{ "citacoes": [...], "numeros": [...], "projetos": [...], "contexto_oportunidades": [...], "contexto_alertas": [...] }}
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
        messages=[{"role": "user", "content": build_prompt(pdf_text, company, period)}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:-1])
    return json.loads(raw)


# ─── Render helpers ───────────────────────────────────────────────────────────

def render_trend_badge(trend: str) -> str:
    t = trend.lower()
    if any(w in t for w in ["alta", "crescimento", "aumento", "aceleração", "aceleracao", "expansão"]):
        color, icon = "#22c55e", "↑"
    elif any(w in t for w in ["queda", "redução", "reducao", "declínio", "recuo", "desaceleração"]):
        color, icon = "#ef4444", "↓"
    elif any(w in t for w in ["transformação", "transformacao", "mudança", "evolução", "transição", "disrupção"]):
        color, icon = "#f59e0b", "⟳"
    else:
        color, icon = "#6b7280", "→"
    return f'<span style="background:{color};color:white;padding:2px 10px;border-radius:12px;font-size:0.78rem;font-weight:600;">{icon} {trend}</span>'


def score_color(score: float) -> str:
    if score >= 70:
        return "#22c55e"
    elif score >= 45:
        return "#f59e0b"
    else:
        return "#ef4444"


def render_lens_card(lens_name: str, data: dict, card_index: int):
    icon = LENS_ICONS.get(lens_name, "📌")
    trend_html = render_trend_badge(data.get("tendencia", "Estável"))

    with st.container():
        st.markdown(
            f"""<div style="border:1px solid #e2e8f0;border-radius:12px;padding:20px 24px 4px 24px;
                margin-bottom:4px;background:#ffffff;box-shadow:0 1px 4px rgba(0,0,0,0.06);">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
                    <h3 style="margin:0;font-size:1.05rem;color:#1e293b;">{icon} {lens_name}</h3>
                    {trend_html}
                </div>""",
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
        alertas_list = data.get("alertas", [])

        if detalhes:
            with st.expander("🔍 Ver detalhes aprofundados"):
                citacoes  = detalhes.get("citacoes", [])
                numeros   = detalhes.get("numeros", [])
                projetos  = detalhes.get("projetos", [])
                ctx_ops   = detalhes.get("contexto_oportunidades", [])
                ctx_alts  = detalhes.get("contexto_alertas", [])

                st.markdown("---")
                r1c1, r1c2, r1c3 = st.columns(3)

                with r1c1:
                    st.markdown("#### 💬 Citações do Relatório")
                    if citacoes:
                        for c in citacoes:
                            st.markdown(
                                f'<blockquote style="border-left:3px solid #6366f1;padding:8px 14px;margin:8px 0;'
                                f'background:#f8f7ff;border-radius:0 8px 8px 0;font-size:0.87rem;color:#374151;'
                                f'font-style:italic;line-height:1.6;">{c}</blockquote>',
                                unsafe_allow_html=True,
                            )
                    else:
                        st.caption("Sem citações identificadas.")

                with r1c2:
                    st.markdown("#### 📊 Números & Métricas")
                    if numeros:
                        for n in numeros:
                            st.markdown(
                                f'<div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;'
                                f'padding:8px 12px;margin:6px 0;font-size:0.87rem;color:#166534;font-weight:500;">📌 {n}</div>',
                                unsafe_allow_html=True,
                            )
                    else:
                        st.caption("Sem métricas específicas identificadas.")

                with r1c3:
                    st.markdown("#### 🚀 Projetos & Iniciativas")
                    if projetos:
                        for p in projetos:
                            st.markdown(
                                f'<div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;'
                                f'padding:8px 12px;margin:6px 0;font-size:0.87rem;color:#1e40af;line-height:1.55;">🔷 {p}</div>',
                                unsafe_allow_html=True,
                            )
                    else:
                        st.caption("Nenhum projeto ou iniciativa identificado.")

                st.markdown("---")
                r2c1, r2c2 = st.columns(2)

                with r2c1:
                    st.markdown("#### 🎯 Contexto das Oportunidades")
                    if ctx_ops:
                        for i, ctx in enumerate(ctx_ops):
                            label = oportunidades[i] if i < len(oportunidades) else f"Oportunidade {i+1}"
                            st.markdown(
                                f'<div style="margin-bottom:12px;">'
                                f'<div style="font-size:0.82rem;font-weight:700;color:#7c3aed;margin-bottom:4px;'
                                f'text-transform:uppercase;letter-spacing:0.03em;">↳ {label}</div>'
                                f'<div style="background:#faf5ff;border:1px solid #e9d5ff;border-radius:8px;'
                                f'padding:10px 14px;font-size:0.87rem;color:#4c1d95;line-height:1.65;">{ctx}</div></div>',
                                unsafe_allow_html=True,
                            )
                    else:
                        st.caption("Sem contexto adicional para as oportunidades.")

                with r2c2:
                    st.markdown("#### ⚠️ Contexto dos Alertas")
                    if ctx_alts:
                        for i, ctx in enumerate(ctx_alts):
                            label = alertas_list[i] if i < len(alertas_list) else f"Alerta {i+1}"
                            st.markdown(
                                f'<div style="margin-bottom:12px;">'
                                f'<div style="font-size:0.82rem;font-weight:700;color:#b91c1c;margin-bottom:4px;'
                                f'text-transform:uppercase;letter-spacing:0.03em;">↳ {label}</div>'
                                f'<div style="background:#fff1f2;border:1px solid #fecdd3;border-radius:8px;'
                                f'padding:10px 14px;font-size:0.87rem;color:#881337;line-height:1.65;">{ctx}</div></div>',
                                unsafe_allow_html=True,
                            )
                    else:
                        st.caption("Sem contexto adicional para os alertas.")

        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("<div style='margin-bottom:12px'></div>", unsafe_allow_html=True)


# ─── Pages ────────────────────────────────────────────────────────────────────

def page_overview():
    st.title("📈 Visão Geral — Ranking de Oportunidades")

    periods = list_periods()
    if not periods:
        st.info("Nenhuma análise salva ainda. Faça upload de um release para começar.")
        return

    all_analyses = list_analyses()
    all_periods_option = "Todos os períodos"
    period_options = [all_periods_option] + periods
    selected_period = st.selectbox("Selecione o período", period_options)

    if selected_period == all_periods_option:
        rows = sorted(all_analyses, key=lambda x: x["score"], reverse=True)
        for r in rows:
            r["results"] = load_analysis(r["id"])["results"]
    else:
        rows = analyses_for_period(selected_period)

    if not rows:
        st.warning(f"Nenhuma análise encontrada para o período **{selected_period}**.")
        return

    st.markdown(f"**{len(rows)} empresa(s)** analisada(s) · clique em uma para ver os detalhes.")
    st.divider()

    for rank, rec in enumerate(rows, 1):
        company   = rec["company"] or "Empresa"
        period    = rec["period"]
        score     = rec["score"]
        s_color   = score_color(score)
        period_lbl = f" · {period}" if period else ""
        date_lbl  = rec["created_at"][:10]

        col_rank, col_info, col_bar, col_score, col_btn = st.columns([0.4, 2.5, 3, 0.8, 1.2])

        with col_rank:
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")
            st.markdown(
                f'<div style="font-size:1.3rem;text-align:center;padding-top:10px;">{medal}</div>',
                unsafe_allow_html=True,
            )

        with col_info:
            st.markdown(
                f'<div style="padding-top:6px;">'
                f'<div style="font-weight:700;font-size:1rem;color:#1e293b;">{company}</div>'
                f'<div style="font-size:0.82rem;color:#64748b;">{period_lbl.strip(" · ") or "—"} · Analisado em {date_lbl}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        with col_bar:
            st.markdown("<div style='padding-top:14px;'>", unsafe_allow_html=True)
            st.progress(score / 100)
            st.markdown("</div>", unsafe_allow_html=True)

        with col_score:
            st.markdown(
                f'<div style="text-align:center;padding-top:6px;">'
                f'<div style="font-size:1.4rem;font-weight:800;color:{s_color};">{score:.0f}</div>'
                f'<div style="font-size:0.7rem;color:#94a3b8;">/ 100</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        with col_btn:
            st.markdown("<div style='padding-top:8px;'>", unsafe_allow_html=True)
            if st.button("Ver análise", key=f"ov_open_{rec['id']}", use_container_width=True):
                st.session_state["page"] = "analise_detalhe"
                st.session_state["loaded_analysis_id"] = rec["id"]
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        st.divider()

    # Lense heatmap — top opportunities across companies
    st.subheader("🔥 Lentes com mais oportunidades no período")
    lens_op_count: dict[str, int] = {l: 0 for l in LENSES}
    for rec in rows:
        results = rec.get("results") or {}
        for lens in LENSES:
            lens_data = results.get(lens, {})
            lens_op_count[lens] += len(lens_data.get("oportunidades", []))

    sorted_lenses = sorted(lens_op_count.items(), key=lambda x: x[1], reverse=True)
    max_count = max(v for _, v in sorted_lenses) if sorted_lenses else 1

    h1, h2 = st.columns(2)
    for i, (lens, count) in enumerate(sorted_lenses):
        col = h1 if i % 2 == 0 else h2
        icon = LENS_ICONS.get(lens, "📌")
        pct = count / max_count if max_count > 0 else 0
        with col:
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">'
                f'<span style="width:160px;font-size:0.88rem;color:#374151;">{icon} {lens}</span>'
                f'<div style="flex:1;background:#f1f5f9;border-radius:6px;height:16px;overflow:hidden;">'
                f'<div style="width:{pct*100:.0f}%;height:100%;background:#6366f1;border-radius:6px;"></div></div>'
                f'<span style="font-size:0.82rem;font-weight:600;color:#6366f1;width:28px;text-align:right;">{count}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )


def page_analysis(selected_lenses: list[str]):
    rec = load_analysis(st.session_state["loaded_analysis_id"])
    if rec is None:
        st.error("Análise não encontrada.")
        return

    company  = rec["company"] or "Empresa"
    period   = rec["period"]
    score    = rec["score"]
    s_color  = score_color(score)
    results  = rec["results"]
    date_lbl = rec["created_at"][:10]
    period_suffix = f" · {period}" if period else ""

    hdr_col, score_col = st.columns([5, 1])
    with hdr_col:
        st.title(f"📊 {company}{period_suffix}")
        st.caption(f"Análise salva em {date_lbl} · {rec['files_count']} arquivo(s)")
    with score_col:
        st.markdown(
            f'<div style="text-align:center;padding-top:10px;">'
            f'<div style="font-size:2rem;font-weight:800;color:{s_color};">{score:.0f}</div>'
            f'<div style="font-size:0.75rem;color:#94a3b8;">Score / 100</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    del_col, _ = st.columns([1, 5])
    with del_col:
        if st.button("🗑️ Excluir análise", type="secondary"):
            delete_analysis(rec["id"])
            st.session_state["page"] = "nova_analise"
            if "loaded_analysis_id" in st.session_state:
                del st.session_state["loaded_analysis_id"]
            st.rerun()

    lenses_to_show = [l for l in selected_lenses if l in results]
    if not lenses_to_show:
        st.warning("Nenhuma lente selecionada. Use o filtro lateral.")
        return

    st.markdown(
        f"Exibindo **{len(lenses_to_show)}** de {len(LENSES)} lentes · "
        f"clique em **🔍 Ver detalhes** em cada card para análise aprofundada."
    )
    st.divider()

    for i, lens in enumerate(lenses_to_show):
        if lens in results:
            render_lens_card(lens, results[lens], i)


def page_new_analysis(selected_lenses: list[str]):
    st.title("📊 Market Intel")
    st.markdown(
        "Faça upload de **um ou mais PDFs** de uma empresa brasileira e extraia inteligência estratégica consolidada em 9 lentes de mercado."
    )
    st.divider()

    col_company, col_period = st.columns([2, 1])
    with col_company:
        company_name = st.text_input(
            "🏢 Nome da empresa",
            placeholder="Ex: Itaú, Ambev, Embraer...",
            help="Usado para salvar no histórico.",
        )
    with col_period:
        period = st.text_input(
            "📅 Período",
            placeholder="Ex: 4T25, 1T26, 2025...",
            help="Trimestre ou ano de referência.",
        )

    uploaded_files = st.file_uploader(
        "Selecione os PDFs do release trimestral (pode enviar vários)",
        type=["pdf"],
        accept_multiple_files=True,
        help="O conteúdo de todos os arquivos será consolidado em uma análise única.",
    )

    if uploaded_files:
        total_size = sum(f.size for f in uploaded_files) / 1024
        if len(uploaded_files) == 1:
            st.success(f"**1 arquivo** carregado — {uploaded_files[0].name} ({total_size:.1f} KB)")
        else:
            st.success(f"**{len(uploaded_files)} arquivos** carregados — {total_size:.1f} KB no total")
            with st.expander(f"Ver lista ({len(uploaded_files)} arquivos)"):
                for i, f in enumerate(uploaded_files, 1):
                    st.markdown(f"**{i}.** {f.name} · {f.size / 1024:.1f} KB")

        label    = company_name or "empresa"
        per_lbl  = f" · {period}" if period else ""
        if st.button(f"🚀 Analisar {label}{per_lbl} com Claude", type="primary", use_container_width=True):
            files_and_texts = []
            with st.spinner(f"Extraindo texto de {len(uploaded_files)} arquivo(s)..."):
                for f in uploaded_files:
                    text = extract_text_from_pdf(f.read(), f.name)
                    if text.strip():
                        files_and_texts.append((f.name, text))
                    else:
                        st.warning(f"⚠️ Não foi possível extrair texto de **{f.name}** — ignorado.")

            if not files_and_texts:
                st.error("Nenhum arquivo com texto válido.")
                return

            merged = merge_pdf_texts(files_and_texts)
            st.info(f"**{len(files_and_texts)} arquivo(s)** · **{len(merged):,} chars** extraídos. Analisando...")

            with st.spinner("Analisando com Claude Opus..."):
                try:
                    results = analyze_with_claude(merged, company_name, period)
                except json.JSONDecodeError as e:
                    st.error(f"Erro ao interpretar resposta da IA: {e}")
                    return
                except Exception as e:
                    st.error(f"Erro na análise: {e}")
                    return

            display_company = company_name or (
                uploaded_files[0].name.replace(".pdf", "") if len(uploaded_files) == 1 else "Empresa"
            )
            analysis_id = save_analysis(display_company, period, len(files_and_texts), results)

            st.session_state["page"] = "analise_detalhe"
            st.session_state["loaded_analysis_id"] = analysis_id
            st.rerun()

    # If there's a fresh result in session (legacy path), show it
    if "results" in st.session_state and "loaded_analysis_id" not in st.session_state:
        results       = st.session_state.pop("results")
        display_company = st.session_state.pop("display_company", "Empresa")
        period_val    = st.session_state.pop("display_period", "")
        files_count   = st.session_state.pop("files_count", 1)
        lenses_to_show = [l for l in selected_lenses if l in results]
        st.subheader(f"Insights — {display_company}")
        for i, lens in enumerate(lenses_to_show):
            render_lens_card(lens, results[lens], i)


# ─── Sidebar ──────────────────────────────────────────────────────────────────

def render_sidebar() -> list[str]:
    with st.sidebar:
        st.markdown("## 📊 Market Intel")

        if st.button("✏️ Nova Análise", use_container_width=True):
            st.session_state["page"] = "nova_analise"
            if "loaded_analysis_id" in st.session_state:
                del st.session_state["loaded_analysis_id"]
            st.rerun()

        if st.button("📈 Visão Geral", use_container_width=True):
            st.session_state["page"] = "visao_geral"
            st.rerun()

        st.divider()

        # Lens filter (only on analysis/new pages)
        current_page = st.session_state.get("page", "nova_analise")
        selected_lenses: list[str] = LENSES

        if current_page != "visao_geral":
            st.markdown("**🔍 Filtrar por Lente**")
            select_all = st.checkbox("Selecionar todas", value=True)
            if select_all:
                for lens in LENSES:
                    st.checkbox(f"{LENS_ICONS.get(lens, '📌')} {lens}", value=True, disabled=True, key=f"cb_{lens}")
            else:
                selected_lenses = []
                for lens in LENSES:
                    if st.checkbox(f"{LENS_ICONS.get(lens, '📌')} {lens}", value=True, key=f"cb_{lens}"):
                        selected_lenses.append(lens)
            st.divider()

        # History
        all_analyses = list_analyses()
        if all_analyses:
            st.markdown("**🗂️ Empresas analisadas**")
            for rec in all_analyses:
                company  = rec["company"] or "Empresa"
                period   = rec["period"]
                score    = rec["score"]
                s_color  = score_color(score)
                label    = f"{company} · {period}" if period else company
                is_active = st.session_state.get("loaded_analysis_id") == rec["id"]

                btn_style = "background:#eff6ff;border-left:3px solid #6366f1;" if is_active else "background:#f8fafc;"
                st.markdown(
                    f'<div style="{btn_style}border-radius:8px;padding:2px 0;margin-bottom:2px;">',
                    unsafe_allow_html=True,
                )
                col_btn, col_score = st.sidebar.columns([3, 1])
                with col_btn:
                    if st.button(label, key=f"hist_{rec['id']}", use_container_width=True):
                        st.session_state["page"] = "analise_detalhe"
                        st.session_state["loaded_analysis_id"] = rec["id"]
                        st.rerun()
                with col_score:
                    st.markdown(
                        f'<div style="text-align:right;padding-top:6px;font-size:0.8rem;font-weight:700;color:{s_color};">{score:.0f}</div>',
                        unsafe_allow_html=True,
                    )
                st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.caption("Nenhuma análise salva ainda.")

        st.divider()
        st.caption("**Market Intel** · Powered by Claude")

    return selected_lenses


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    init_db()

    if "page" not in st.session_state:
        st.session_state["page"] = "nova_analise"

    selected_lenses = render_sidebar()
    page = st.session_state["page"]

    if page == "visao_geral":
        page_overview()
    elif page == "analise_detalhe" and "loaded_analysis_id" in st.session_state:
        page_analysis(selected_lenses)
    else:
        page_new_analysis(selected_lenses)


if __name__ == "__main__":
    main()
