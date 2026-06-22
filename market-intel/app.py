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

INVESTOR_LENSES = [
    "Fundamentos Financeiros",
    "Alocação de Capital",
    "Vantagem Competitiva (Moat)",
    "Gestão e Governança",
    "Riscos Declarados",
    "Guidance e Perspectivas",
    "Score Buffett",
]

INVESTOR_LENS_ICONS = {
    "Fundamentos Financeiros":     "💰",
    "Alocação de Capital":         "📊",
    "Vantagem Competitiva (Moat)": "🏰",
    "Gestão e Governança":         "👔",
    "Riscos Declarados":           "⚠️",
    "Guidance e Perspectivas":     "🔭",
    "Score Buffett":               "🧾",
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


def _detect_mode(results: dict) -> str:
    """Return 'investor' if results contain investor lenses, else 'fornecedor'."""
    return "investor" if "Fundamentos Financeiros" in results else "fornecedor"


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


def compute_investor_score(results: dict) -> float:
    """Investor mode: primary score is the Buffett note (1–10 → 10–100).
    If not available, fall back to a composite from other lenses."""
    buffett = results.get("Score Buffett", {})
    nota = buffett.get("nota")
    if nota is not None:
        try:
            return round(min(100.0, max(0.0, float(nota) * 10)), 1)
        except (TypeError, ValueError):
            pass
    # Fallback: composite from non-Buffett investor lenses
    total = 0.0
    count = 0
    for lens, lens_data in results.items():
        if lens == "Score Buffett":
            continue
        insights = len(lens_data.get("insights", []))
        riscos   = len(lens_data.get("riscos", []))
        trend    = lens_data.get("tendencia", "").lower()
        trend_score = 2.0 if any(w in trend for w in ["alta", "crescimento", "aceleração"]) else (
                      1.0 if any(w in trend for w in ["transformação", "evolução"]) else (
                     -2.0 if any(w in trend for w in ["queda", "declínio"]) else 0.0))
        total += insights * 3.0 + trend_score - riscos * 0.5
        count += 1
    if count == 0:
        return 50.0
    normalized = (total + 15.0) / 105.0 * 100
    return round(max(0.0, min(100.0, normalized)), 1)


def save_analysis(company: str, period: str, files_count: int, results: dict) -> int:
    mode = _detect_mode(results)
    score = compute_investor_score(results) if mode == "investor" else compute_opportunity_score(results)
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


def _context_header(company: str, period: str) -> str:
    parts = [f"Empresa: {company}" if company else "", f"Período: {period}" if period else ""]
    header = " | ".join(p for p in parts if p)
    return f"Contexto: {header}\n\n" if header else ""


def _parse_json_response(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        # drop first (```json or ```) and last (```) lines
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return json.loads(raw)


# ── Phase 1: compact extraction from a single PDF ──────────────────────────

def _build_extraction_prompt(pdf_text: str, filename: str, company: str, period: str) -> str:
    lenses_list = "\n".join(f"- {l}" for l in LENSES)
    header_line = _context_header(company, period)
    return f"""Você é um analista de inteligência de mercado B2B.

{header_line}Analise o documento abaixo e extraia sinais estruturados em 9 lentes estratégicas.

Para cada lente, forneça EXATAMENTE este JSON (sem campos extras):
- "destaques": lista de até 3 strings com destaques principais
- "oportunidades": lista de até 3 strings com oportunidades para fornecedores
- "alertas": lista de até 2 strings com riscos ou pontos de atenção
- "tendencia": string curta com tendência geral ("Alta", "Estável", "Queda", "Em transformação", "Aceleração")
- "citacoes": lista de até 4 trechos reais do documento com contexto mínimo entre colchetes
- "numeros": lista de até 4 métricas ou indicadores específicos com unidade e contexto
- "projetos": lista de até 3 nomes de projetos/produtos/plataformas com descrição de uma frase

Seja conciso e específico. Use apenas dados presentes no documento.

Lentes:
{lenses_list}

Responda APENAS com JSON válido, sem markdown:
{{
  "Marketing & Mídia Digital": {{"destaques":[...],"oportunidades":[...],"alertas":[...],"tendencia":"...","citacoes":[...],"numeros":[...],"projetos":[...]}},
  "Dados / IA / Analytics": {{...}},
  "Infraestrutura & Cloud": {{...}},
  "CX & Relacionamento": {{...}},
  "RH & Cultura": {{...}},
  "Educação Corporativa": {{...}},
  "Jurídico & Compliance": {{...}},
  "Saúde Financeira": {{...}},
  "ESG": {{...}}
}}

DOCUMENTO — {filename}:
{pdf_text[:30000]}
"""


# ── Phase 2: consolidation of multiple extractions ─────────────────────────

def _build_consolidation_prompt(extractions: list[dict], filenames: list[str], company: str, period: str) -> str:
    lenses_list = "\n".join(f"- {l}" for l in LENSES)
    header_line = _context_header(company, period)

    parts = []
    for i, (fname, ext) in enumerate(zip(filenames, extractions), 1):
        parts.append(f"=== Extração {i} — {fname} ===\n{json.dumps(ext, ensure_ascii=False, indent=2)}")
    extractions_text = "\n\n".join(parts)

    return f"""Você é um analista sênior de inteligência de mercado B2B.

{header_line}Abaixo estão {len(extractions)} extração(ões) individuais de documentos da mesma empresa, cada uma cobrindo 9 lentes estratégicas.

Seu trabalho é CONSOLIDAR todas as extrações em um único JSON final, seguindo estas regras:
1. Mescle e deduplicle destaques, oportunidades, alertas, citacoes, numeros e projetos (mantenha os mais relevantes e específicos, até os limites indicados)
2. Para "tendencia", use a tendência predominante ou mais relevante entre as extrações
3. Gere "contexto_oportunidades": para cada oportunidade consolidada, escreva uma análise de 2-3 frases explicando por que existe, quais sinais a sustentam e como um fornecedor pode agir
4. Gere "contexto_alertas": para cada alerta consolidado, escreva uma análise de 2-3 frases sobre causas, implicações para fornecedores e como a empresa está reagindo

Limites por lente no JSON final:
- "destaques": até 4 itens
- "oportunidades": até 4 itens
- "alertas": até 3 itens
- "citacoes": até 5 itens
- "numeros": até 5 itens
- "projetos": até 4 itens
- "contexto_oportunidades": um item por oportunidade (até 4)
- "contexto_alertas": um item por alerta (até 3)

Lentes:
{lenses_list}

Responda APENAS com JSON válido, sem markdown:
{{
  "Marketing & Mídia Digital": {{
    "destaques":[...],"oportunidades":[...],"alertas":[...],"tendencia":"...",
    "detalhes":{{"citacoes":[...],"numeros":[...],"projetos":[...],"contexto_oportunidades":[...],"contexto_alertas":[...]}}
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

EXTRAÇÕES:
{extractions_text}
"""


# ── Orchestrator ──────────────────────────────────────────────────────────

def analyze_with_claude(
    files_and_texts: list[tuple[str, str]],
    company: str,
    period: str,
    progress_callback=None,
    mode: str = "fornecedor",
) -> dict:
    """
    Two-phase processing:
      Phase 1 — extract compact signals from each PDF individually (small payloads → no truncation)
      Phase 2 — consolidate all extractions into the final rich JSON
    mode: 'fornecedor' | 'investor'
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY não encontrada nas variáveis de ambiente.")

    client = anthropic.Anthropic(api_key=api_key)
    total = len(files_and_texts)

    build_ext_prompt  = _build_investor_extraction_prompt   if mode == "investor" else _build_extraction_prompt
    build_cons_prompt = _build_investor_consolidation_prompt if mode == "investor" else _build_consolidation_prompt
    promote_fn        = _promote_single_extraction_investor  if mode == "investor" else _promote_single_extraction

    # ── Phase 1 ──────────────────────────────────────────────────────────────
    extractions: list[dict] = []
    filenames: list[str] = []

    for i, (filename, text) in enumerate(files_and_texts):
        if progress_callback:
            progress_callback(i, total, filename)

        prompt = build_ext_prompt(text, filename, company, period)
        msg = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        extraction = _parse_json_response(msg.content[0].text)
        extractions.append(extraction)
        filenames.append(filename)

    # ── Phase 2 ──────────────────────────────────────────────────────────────
    if progress_callback:
        progress_callback(total, total, "consolidando…")

    # Single PDF: skip consolidation, promote flat extraction to final shape directly
    if len(extractions) == 1:
        return promote_fn(extractions[0])

    prompt = build_cons_prompt(extractions, filenames, company, period)
    msg = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json_response(msg.content[0].text)


def _promote_single_extraction(ext: dict) -> dict:
    """Wrap flat per-PDF fornecedor extraction into the full shape expected by the UI."""
    result = {}
    for lens in LENSES:
        raw = ext.get(lens, {})
        result[lens] = {
            "destaques":    raw.get("destaques", []),
            "oportunidades": raw.get("oportunidades", []),
            "alertas":      raw.get("alertas", []),
            "tendencia":    raw.get("tendencia", "Estável"),
            "detalhes": {
                "citacoes":              raw.get("citacoes", []),
                "numeros":               raw.get("numeros", []),
                "projetos":              raw.get("projetos", []),
                "contexto_oportunidades": [],
                "contexto_alertas":      [],
            },
        }
    return result


# ── Investor prompts ──────────────────────────────────────────────────────────

_INVESTOR_LENS_LIST = "\n".join(f"- {l}" for l in INVESTOR_LENSES if l != "Score Buffett")

def _build_investor_extraction_prompt(pdf_text: str, filename: str, company: str, period: str) -> str:
    header_line = _context_header(company, period)
    return f"""Você é um analista de investimentos especializado em value investing.

{header_line}Analise o documento abaixo e extraia sinais para avaliação de investimento em 7 dimensões.

Para as lentes regulares (todas exceto "Score Buffett"), forneça:
- "destaques": lista de até 3 strings com os principais fatos observados
- "insights": lista de até 3 strings com interpretações relevantes para um investidor
- "riscos": lista de até 2 strings com riscos ou pontos negativos para o investidor
- "tendencia": string curta com tendência ("Alta", "Estável", "Queda", "Em transformação", "Aceleração")
- "citacoes": lista de até 4 trechos reais do documento com contexto entre colchetes
- "numeros": lista de até 4 métricas específicas com unidade e contexto
- "projetos": lista de até 3 iniciativas, programas ou produtos mencionados com descrição de uma frase

Para "Score Buffett", forneça:
- "nota": número inteiro de 1 a 10 baseado nos critérios públicos de Warren Buffett
- "justificativa": parágrafo de 3-4 frases explicando a nota de forma fundamentada
- "criterios": objeto com 6 chaves fixas (string explicativa de 1-2 frases cada):
    - "negocio_compreensivel": o negócio é simples e previsível?
    - "vantagem_duravel": possui moat defensável de longo prazo?
    - "gestao_confiavel": a gestão age no interesse dos acionistas?
    - "historico_lucratividade": histórico consistente de lucros e margens?
    - "retorno_capital_proprio": ROE/ROIC são satisfatórios?
    - "perspectiva_longo_prazo": perspectivas de crescimento sustentável?

Lentes a analisar:
{_INVESTOR_LENS_LIST}
- Score Buffett

Responda APENAS com JSON válido, sem markdown:
{{
  "Fundamentos Financeiros": {{"destaques":[...],"insights":[...],"riscos":[...],"tendencia":"...","citacoes":[...],"numeros":[...],"projetos":[...]}},
  "Alocação de Capital": {{...}},
  "Vantagem Competitiva (Moat)": {{...}},
  "Gestão e Governança": {{...}},
  "Riscos Declarados": {{...}},
  "Guidance e Perspectivas": {{...}},
  "Score Buffett": {{"nota":7,"justificativa":"...","criterios":{{"negocio_compreensivel":"...","vantagem_duravel":"...","gestao_confiavel":"...","historico_lucratividade":"...","retorno_capital_proprio":"...","perspectiva_longo_prazo":"..."}}}}
}}

DOCUMENTO — {filename}:
{pdf_text[:30000]}
"""


def _build_investor_consolidation_prompt(
    extractions: list[dict], filenames: list[str], company: str, period: str
) -> str:
    header_line = _context_header(company, period)
    parts = []
    for i, (fname, ext) in enumerate(zip(filenames, extractions), 1):
        parts.append(f"=== Extração {i} — {fname} ===\n{json.dumps(ext, ensure_ascii=False, indent=2)}")
    extractions_text = "\n\n".join(parts)

    return f"""Você é um analista sênior de investimentos especializado em value investing.

{header_line}Abaixo estão {len(extractions)} extração(ões) de documentos da mesma empresa cobrindo 7 dimensões de investimento.

CONSOLIDE tudo em um único JSON final seguindo estas regras:
1. Mescle e deduplique destaques, insights, riscos, citacoes, numeros e projetos
2. Para "tendencia", use a tendência predominante entre as extrações
3. Gere "contexto_insights": para cada insight consolidado, escreva 2-3 frases explicando as implicações para um investidor de longo prazo
4. Gere "contexto_riscos": para cada risco consolidado, escreva 2-3 frases sobre magnitude, probabilidade e mitigantes
5. Para "Score Buffett": consolide as notas (média ponderada ou julgamento analítico), reescreva a justificativa e consolide os critérios

Limites no JSON final (lentes regulares):
- destaques: até 4; insights: até 4; riscos: até 3
- citacoes: até 5; numeros: até 5; projetos: até 4
- contexto_insights: um por insight; contexto_riscos: um por risco

Responda APENAS com JSON válido, sem markdown:
{{
  "Fundamentos Financeiros": {{
    "destaques":[...],"insights":[...],"riscos":[...],"tendencia":"...",
    "detalhes":{{"citacoes":[...],"numeros":[...],"projetos":[...],"contexto_insights":[...],"contexto_riscos":[]}}
  }},
  "Alocação de Capital": {{...}},
  "Vantagem Competitiva (Moat)": {{...}},
  "Gestão e Governança": {{...}},
  "Riscos Declarados": {{...}},
  "Guidance e Perspectivas": {{...}},
  "Score Buffett": {{"nota":7,"justificativa":"...","criterios":{{"negocio_compreensivel":"...","vantagem_duravel":"...","gestao_confiavel":"...","historico_lucratividade":"...","retorno_capital_proprio":"...","perspectiva_longo_prazo":"..."}}}}
}}

EXTRAÇÕES:
{extractions_text}
"""


def _promote_single_extraction_investor(ext: dict) -> dict:
    """Wrap flat per-PDF investor extraction into the full shape expected by the UI."""
    result = {}
    for lens in INVESTOR_LENSES:
        raw = ext.get(lens, {})
        if lens == "Score Buffett":
            result[lens] = {
                "nota":         raw.get("nota", 5),
                "justificativa": raw.get("justificativa", ""),
                "criterios":    raw.get("criterios", {}),
            }
        else:
            result[lens] = {
                "destaques":  raw.get("destaques", []),
                "insights":   raw.get("insights", []),
                "riscos":     raw.get("riscos", []),
                "tendencia":  raw.get("tendencia", "Estável"),
                "detalhes": {
                    "citacoes":         raw.get("citacoes", []),
                    "numeros":          raw.get("numeros", []),
                    "projetos":         raw.get("projetos", []),
                    "contexto_insights": [],
                    "contexto_riscos":  [],
                },
            }
    return result


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


def render_investor_lens_card(lens_name: str, data: dict, card_index: int):
    """Card for investor mode — regular lenses (not Score Buffett)."""
    icon = INVESTOR_LENS_ICONS.get(lens_name, "📌")
    trend_html = render_trend_badge(data.get("tendencia", "Estável"))

    with st.container():
        st.markdown(
            f"""<div style="border:1px solid #e2e8f0;border-radius:12px;padding:20px 24px 4px 24px;
                margin-bottom:4px;background:#fafbff;box-shadow:0 1px 4px rgba(0,0,0,0.06);">
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
            st.markdown("**📈 Insights de Investimento**")
            for item in data.get("insights", []):
                st.markdown(f"- {item}")
        with col3:
            st.markdown("**🚨 Riscos**")
            for item in data.get("riscos", []):
                st.markdown(f"- {item}")

        detalhes  = data.get("detalhes", {})
        insights  = data.get("insights", [])
        riscos    = data.get("riscos", [])

        if detalhes:
            with st.expander("🔍 Ver detalhes aprofundados"):
                citacoes      = detalhes.get("citacoes", [])
                numeros       = detalhes.get("numeros", [])
                projetos      = detalhes.get("projetos", [])
                ctx_insights  = detalhes.get("contexto_insights", [])
                ctx_riscos    = detalhes.get("contexto_riscos", [])

                st.markdown("---")
                r1c1, r1c2, r1c3 = st.columns(3)

                with r1c1:
                    st.markdown("#### 💬 Citações do Relatório")
                    if citacoes:
                        for c in citacoes:
                            st.markdown(
                                f'<blockquote style="border-left:3px solid #0ea5e9;padding:8px 14px;margin:8px 0;'
                                f'background:#f0f9ff;border-radius:0 8px 8px 0;font-size:0.87rem;color:#374151;'
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
                    st.markdown("#### 🏗️ Projetos & Iniciativas")
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
                    st.markdown("#### 📈 Contexto dos Insights")
                    if ctx_insights:
                        for i, ctx in enumerate(ctx_insights):
                            label = insights[i] if i < len(insights) else f"Insight {i+1}"
                            st.markdown(
                                f'<div style="margin-bottom:12px;">'
                                f'<div style="font-size:0.82rem;font-weight:700;color:#0369a1;margin-bottom:4px;'
                                f'text-transform:uppercase;letter-spacing:0.03em;">↳ {label}</div>'
                                f'<div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:8px;'
                                f'padding:10px 14px;font-size:0.87rem;color:#0c4a6e;line-height:1.65;">{ctx}</div></div>',
                                unsafe_allow_html=True,
                            )
                    else:
                        st.caption("Sem contexto adicional para os insights.")

                with r2c2:
                    st.markdown("#### 🚨 Contexto dos Riscos")
                    if ctx_riscos:
                        for i, ctx in enumerate(ctx_riscos):
                            label = riscos[i] if i < len(riscos) else f"Risco {i+1}"
                            st.markdown(
                                f'<div style="margin-bottom:12px;">'
                                f'<div style="font-size:0.82rem;font-weight:700;color:#b91c1c;margin-bottom:4px;'
                                f'text-transform:uppercase;letter-spacing:0.03em;">↳ {label}</div>'
                                f'<div style="background:#fff1f2;border:1px solid #fecdd3;border-radius:8px;'
                                f'padding:10px 14px;font-size:0.87rem;color:#881337;line-height:1.65;">{ctx}</div></div>',
                                unsafe_allow_html=True,
                            )
                    else:
                        st.caption("Sem contexto adicional para os riscos.")

        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("<div style='margin-bottom:12px'></div>", unsafe_allow_html=True)


def render_buffett_score_card(data: dict):
    """Special card for the Score Buffett lens."""
    nota        = data.get("nota", 5)
    justificativa = data.get("justificativa", "")
    criterios   = data.get("criterios", {})

    try:
        nota = int(nota)
    except (TypeError, ValueError):
        nota = 5

    nota_color = "#22c55e" if nota >= 8 else ("#f59e0b" if nota >= 6 else "#ef4444")
    pct = nota / 10

    CRITERIO_LABELS = {
        "negocio_compreensivel":   ("🔍", "Negócio Compreensível"),
        "vantagem_duravel":        ("🏰", "Vantagem Durável (Moat)"),
        "gestao_confiavel":        ("👔", "Gestão Confiável"),
        "historico_lucratividade": ("📈", "Histórico de Lucratividade"),
        "retorno_capital_proprio": ("💰", "Retorno sobre Capital"),
        "perspectiva_longo_prazo": ("🔭", "Perspectiva de Longo Prazo"),
    }

    with st.container():
        st.markdown(
            f"""<div style="border:2px solid #d97706;border-radius:16px;padding:24px 28px 12px 28px;
                margin-bottom:4px;background:linear-gradient(135deg,#fffbeb 0%,#fef3c7 100%);
                box-shadow:0 2px 8px rgba(217,119,6,0.12);">
                <div style="display:flex;align-items:center;gap:16px;margin-bottom:18px;">
                    <div style="font-size:3.5rem;font-weight:900;color:{nota_color};line-height:1;">{nota}</div>
                    <div>
                        <div style="font-size:1.1rem;font-weight:700;color:#92400e;">🧾 Score Buffett</div>
                        <div style="font-size:0.8rem;color:#b45309;">Critérios públicos de Warren Buffett · escala 1–10</div>
                    </div>
                    <div style="flex:1;"></div>
                </div>""",
            unsafe_allow_html=True,
        )
        st.progress(pct)

        if justificativa:
            st.markdown(
                f'<p style="margin:14px 0 6px 0;font-size:0.93rem;color:#451a03;line-height:1.7;">{justificativa}</p>',
                unsafe_allow_html=True,
            )

        if criterios:
            with st.expander("📋 Ver avaliação por critério"):
                c1, c2 = st.columns(2)
                for j, (key, (icon, label)) in enumerate(CRITERIO_LABELS.items()):
                    texto = criterios.get(key, "—")
                    col = c1 if j % 2 == 0 else c2
                    with col:
                        st.markdown(
                            f'<div style="margin-bottom:14px;">'
                            f'<div style="font-size:0.82rem;font-weight:700;color:#92400e;margin-bottom:4px;">{icon} {label}</div>'
                            f'<div style="background:#fffbeb;border:1px solid #fde68a;border-radius:8px;'
                            f'padding:9px 13px;font-size:0.87rem;color:#451a03;line-height:1.6;">{texto}</div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

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
    period_suffix  = f" · {period}" if period else ""
    mode           = _detect_mode(results)
    is_investor    = mode == "investor"
    all_lenses_ref = INVESTOR_LENSES if is_investor else LENSES
    score_label    = "Score Buffett" if is_investor else "Score / 100"
    mode_badge     = "📈 Modo Investidor" if is_investor else "🏢 Modo Fornecedor"

    hdr_col, score_col = st.columns([5, 1])
    with hdr_col:
        st.title(f"📊 {company}{period_suffix}")
        st.caption(f"{mode_badge} · Análise salva em {date_lbl} · {rec['files_count']} arquivo(s)")
    with score_col:
        score_display = f"{score / 10:.1f}/10" if is_investor else f"{score:.0f}"
        st.markdown(
            f'<div style="text-align:center;padding-top:10px;">'
            f'<div style="font-size:2rem;font-weight:800;color:{s_color};">{score_display}</div>'
            f'<div style="font-size:0.75rem;color:#94a3b8;">{score_label}</div>'
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

    n_total = len(all_lenses_ref)
    st.markdown(
        f"Exibindo **{len(lenses_to_show)}** de {n_total} lentes · "
        f"clique em **🔍 Ver detalhes** em cada card para análise aprofundada."
    )
    st.divider()

    if is_investor:
        for i, lens in enumerate(lenses_to_show):
            if lens not in results:
                continue
            if lens == "Score Buffett":
                render_buffett_score_card(results[lens])
            else:
                render_investor_lens_card(lens, results[lens], i)
    else:
        for i, lens in enumerate(lenses_to_show):
            if lens in results:
                render_lens_card(lens, results[lens], i)


def page_new_analysis(selected_lenses: list[str], mode: str = "fornecedor"):
    is_investor = mode == "investor"
    if is_investor:
        st.title("📈 Market Intel — Visão Investidor")
        st.markdown(
            "Faça upload de **um ou mais PDFs** de uma empresa e extraia análise orientada a **decisão de investimento**: "
            "fundamentos, moat, gestão, riscos e Score Buffett."
        )
    else:
        st.title("📊 Market Intel — Visão Fornecedor")
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
            # ── Step 1: extract text from all PDFs ──────────────────────────
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

            total_files = len(files_and_texts)
            total_chars = sum(len(t) for _, t in files_and_texts)
            st.info(
                f"**{total_files} arquivo(s)** · **{total_chars:,} chars** extraídos. "
                f"Processando em {total_files} chamada(s) separada(s) + consolidação..."
            )

            # ── Step 2: two-phase Claude analysis with live progress ────────
            progress_bar  = st.progress(0)
            status_text   = st.empty()

            def on_progress(current: int, total: int, filename: str):
                if current < total:
                    pct = current / (total + 1)   # +1 reserves space for consolidation step
                    progress_bar.progress(pct)
                    status_text.markdown(
                        f"**Fase 1 — Extração** · arquivo {current + 1}/{total}: `{filename}`"
                    )
                else:
                    progress_bar.progress(total / (total + 1))
                    step_label = "consolidando os resultados..." if total > 1 else "gerando análise completa..."
                    status_text.markdown(f"**Fase 2 —** {step_label}")

            try:
                results = analyze_with_claude(
                    files_and_texts, company_name, period,
                    progress_callback=on_progress,
                    mode=mode,
                )
            except json.JSONDecodeError as e:
                progress_bar.empty()
                status_text.empty()
                st.error(f"Erro ao interpretar resposta da IA: {e}")
                return
            except Exception as e:
                progress_bar.empty()
                status_text.empty()
                st.error(f"Erro na análise: {e}")
                return

            progress_bar.progress(1.0)
            status_text.empty()

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

def render_sidebar() -> tuple[list[str], str]:
    with st.sidebar:
        st.markdown("## 📊 Market Intel")

        # ── Mode toggle ──────────────────────────────────────────────────────
        st.markdown("**Modo de análise**")
        mode_choice = st.radio(
            "modo",
            options=["🏢 Fornecedor", "📈 Investidor"],
            index=1 if st.session_state.get("mode") == "investor" else 0,
            horizontal=True,
            label_visibility="collapsed",
            key="mode_radio",
        )
        new_mode = "investor" if "Investidor" in mode_choice else "fornecedor"
        if new_mode != st.session_state.get("mode"):
            st.session_state["mode"] = new_mode
            # Reset to new analysis when mode changes
            st.session_state["page"] = "nova_analise"
            if "loaded_analysis_id" in st.session_state:
                del st.session_state["loaded_analysis_id"]
            st.rerun()

        st.divider()

        if st.button("✏️ Nova Análise", use_container_width=True):
            st.session_state["page"] = "nova_analise"
            if "loaded_analysis_id" in st.session_state:
                del st.session_state["loaded_analysis_id"]
            st.rerun()

        if st.button("📈 Visão Geral", use_container_width=True):
            st.session_state["page"] = "visao_geral"
            st.rerun()

        st.divider()

        # ── Lens filter (only on analysis/new pages) ─────────────────────────
        current_page  = st.session_state.get("page", "nova_analise")
        mode          = st.session_state.get("mode", "fornecedor")
        is_investor   = mode == "investor"
        active_lenses = INVESTOR_LENSES if is_investor else LENSES
        active_icons  = INVESTOR_LENS_ICONS if is_investor else LENS_ICONS
        selected_lenses: list[str] = list(active_lenses)

        if current_page != "visao_geral":
            st.markdown("**🔍 Filtrar por Lente**")
            select_all = st.checkbox("Selecionar todas", value=True)
            if select_all:
                for lens in active_lenses:
                    st.checkbox(f"{active_icons.get(lens, '📌')} {lens}", value=True, disabled=True, key=f"cb_{lens}")
            else:
                selected_lenses = []
                for lens in active_lenses:
                    if st.checkbox(f"{active_icons.get(lens, '📌')} {lens}", value=True, key=f"cb_{lens}"):
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

    return selected_lenses, mode


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    init_db()

    if "page" not in st.session_state:
        st.session_state["page"] = "nova_analise"
    if "mode" not in st.session_state:
        st.session_state["mode"] = "fornecedor"

    selected_lenses, mode = render_sidebar()
    page = st.session_state["page"]

    if page == "visao_geral":
        page_overview()
    elif page == "analise_detalhe" and "loaded_analysis_id" in st.session_state:
        page_analysis(selected_lenses)
    else:
        page_new_analysis(selected_lenses, mode=mode)


if __name__ == "__main__":
    main()
