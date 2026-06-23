import streamlit as st
import anthropic
import fitz
import json
import os
import re
import sqlite3
import time
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
    """Score fornecedor mode — parse Tendência and bullet counts from markdown strings."""
    total = 0.0
    for md in results.values():
        md = _compat_md(md)
        n_ops    = _count_bullets(md, "Oportunidades para Fornecedores")
        n_alerts = _count_bullets(md, "Alertas")
        trend    = _extract_tendencia(md).lower()
        if any(w in trend for w in ["alta", "crescimento", "aumento", "aceleração", "aceleracao", "expansão"]):
            trend_score = 2.0
        elif any(w in trend for w in ["transformação", "transformacao", "mudança", "evolução", "transição", "disrupção"]):
            trend_score = 1.0
        elif any(w in trend for w in ["queda", "redução", "reducao", "declínio", "recuo", "desaceleração"]):
            trend_score = -2.0
        else:
            trend_score = 0.0
        total += n_ops * 3.0 + trend_score - n_alerts * 0.5
    normalized = (total + 31.5) / 157.5 * 100
    return round(max(0.0, min(100.0, normalized)), 1)


def compute_investor_score(results: dict) -> float:
    """Score investor mode — extract Buffett nota from markdown (×10 → 0–100 scale)."""
    buffett_md = _compat_md(results.get("Score Buffett", ""))
    m = re.search(r'\*\*Nota:\*\*\s*(\d+)', buffett_md, re.IGNORECASE)
    if m:
        nota = int(m.group(1))
        return round(min(100.0, max(0.0, nota * 10)), 1)
    # Fallback: composite from regular investor lenses
    total = 0.0
    count = 0
    for lens, raw in results.items():
        if lens == "Score Buffett":
            continue
        md = _compat_md(raw)
        n_i = _count_bullets(md, "Insights de Investimento")
        n_r = _count_bullets(md, "Riscos")
        trend = _extract_tendencia(md).lower()
        ts = (2.0 if any(w in trend for w in ["alta", "crescimento", "aceleração"])
              else 1.0 if "transformação" in trend
              else -2.0 if any(w in trend for w in ["queda", "declínio"])
              else 0.0)
        total += n_i * 3.0 + ts - n_r * 0.5
        count += 1
    if count == 0:
        return 50.0
    return round(max(0.0, min(100.0, (total + 15.0) / 105.0 * 100)), 1)


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


# ── Markdown helpers ──────────────────────────────────────────────────────────

def _parse_md_sections(raw: str, lenses: list[str]) -> dict[str, str]:
    """Split a Claude markdown response (## headers) into a per-lens dict of strings."""
    raw = raw.strip()
    # Split on level-2 headers
    parts = re.split(r'\n##\s+', '\n' + raw)
    result: dict[str, str] = {}
    for part in parts:
        part = part.strip()
        if not part:
            continue
        newline = part.find('\n')
        if newline == -1:
            header, content = part, ""
        else:
            header  = part[:newline].strip()
            content = part[newline:].strip()
        # Remove trailing --- separator
        content = re.sub(r'\n?---\s*$', '', content).strip()
        # Match header to a known lens (case-insensitive)
        header_l = header.lower()
        for lens in lenses:
            if lens.lower() in header_l or header_l in lens.lower():
                result[lens] = content
                break
    for lens in lenses:
        result.setdefault(lens, "")
    return result


def _extract_tendencia(md: str) -> str:
    """Parse **Tendência:** value from markdown text."""
    m = re.search(r'\*\*Tend[êe]ncia:\*\*\s*([^\n]+)', md, re.IGNORECASE)
    return m.group(1).strip() if m else "Estável"


def _count_bullets(md: str, section_header: str) -> int:
    """Count '- ' bullet lines that appear under a **SectionHeader:** in markdown."""
    escaped = re.escape(section_header)
    m = re.search(
        rf'\*\*{escaped}[:\*]{{0,2}}\*?\*?\s*\n((?:\s*-[^\n]+\n?)+)',
        md, re.IGNORECASE,
    )
    if m:
        return len(re.findall(r'^\s*-\s', m.group(1), re.MULTILINE))
    return 0


def _compat_md(data) -> str:
    """Convert old JSON-dict analysis (from previous DB entries) to a minimal markdown string."""
    if isinstance(data, str):
        return data
    if not isinstance(data, dict):
        return ""
    parts: list[str] = []
    if data.get("tendencia"):
        parts.append(f"**Tendência:** {data['tendencia']}")
    for key, label in [
        ("destaques",    "Destaques"),
        ("insights",     "Insights de Investimento"),
        ("oportunidades","Oportunidades para Fornecedores"),
    ]:
        items = data.get(key, [])
        if items:
            parts.append(f"**{label}:**\n" + "\n".join(f"- {i}" for i in items))
    for key, label in [("alertas", "Alertas"), ("riscos", "Riscos")]:
        items = data.get(key, [])
        if items:
            parts.append(f"**{label}:**\n" + "\n".join(f"- {i}" for i in items))
    det = data.get("detalhes", {})
    if isinstance(det, dict):
        for key, label in [
            ("numeros",  "Métricas & Números"),
            ("citacoes", "Citações"),
            ("projetos", "Projetos & Iniciativas"),
        ]:
            items = det.get(key, [])
            if items:
                parts.append(f"**{label}:**\n" + "\n".join(f"- {i}" for i in items))
    # Score Buffett (old format)
    if "nota" in data:
        nota = data.get("nota", "?")
        just = data.get("justificativa", "")
        parts.insert(0, f"**Nota:** {nota}/10")
        if just:
            parts.append(f"**Justificativa:** {just}")
    return "\n\n".join(parts)


# ── Phase 1: markdown extraction from a single PDF ─────────────────────────

def _build_extraction_prompt(pdf_text: str, filename: str, company: str, period: str) -> str:
    lenses_list = "\n".join(f"- {l}" for l in LENSES)
    header_line = _context_header(company, period)
    return f"""Você é um analista de inteligência de mercado B2B.

{header_line}Analise o documento abaixo e produza um relatório em markdown com exatamente 9 seções.

LENTES A ANALISAR:
{lenses_list}

FORMATO DE CADA SEÇÃO — use EXATAMENTE estes headers e subheaders:

## [Nome da Lente]

**Tendência:** [Alta | Estável | Queda | Em transformação | Aceleração]

**Destaques:**
- ponto principal (específico, com dados reais)

**Oportunidades para Fornecedores:**
- oportunidade concreta

**Alertas:**
- risco ou ponto de atenção

**Métricas & Números:**
- métrica com valor e contexto

**Citações:**
- "trecho real do documento [seção ou contexto]"

**Projetos & Iniciativas:**
- Nome do Projeto: descrição de uma frase

---

REGRAS:
- Copie o nome de cada lente EXATAMENTE como na lista acima no header `## `
- 2 a 4 bullets por subseção; omita subseções sem dados relevantes
- Separe cada lente com `---`
- Seja específico; use apenas dados presentes no documento

DOCUMENTO — {filename}:
{pdf_text[:20000]}
"""


def _build_investor_extraction_prompt(pdf_text: str, filename: str, company: str, period: str) -> str:
    regular = [l for l in INVESTOR_LENSES if l != "Score Buffett"]
    lenses_list = "\n".join(f"- {l}" for l in regular)
    header_line = _context_header(company, period)
    return f"""Você é um analista de investimentos especializado em value investing.

{header_line}Analise o documento abaixo e produza um relatório em markdown com 7 seções de análise de investimento.

LENTES REGULARES:
{lenses_list}

FORMATO PARA CADA LENTE REGULAR:

## [Nome da Lente]

**Tendência:** [Alta | Estável | Queda | Em transformação | Aceleração]

**Destaques:**
- fato principal (específico)

**Insights de Investimento:**
- insight relevante para um investidor de longo prazo

**Riscos:**
- risco identificado

**Métricas & Dados:**
- métrica com valor e contexto

**Citações:**
- "trecho [contexto]"

---

FORMATO PARA SCORE BUFFETT (última seção, obrigatória):

## Score Buffett

**Nota:** [número de 1 a 10]/10

**Justificativa:** Parágrafo de 3-4 frases explicando a nota com base nos critérios de Buffett.

**Por critério:**
- 🔍 **Negócio Compreensível:** avaliação
- 🏰 **Vantagem Durável:** avaliação
- 👔 **Gestão Confiável:** avaliação
- 📈 **Histórico de Lucratividade:** avaliação
- 💰 **Retorno sobre Capital:** avaliação
- 🔭 **Perspectiva de Longo Prazo:** avaliação

---

REGRAS:
- Copie o nome de cada lente EXATAMENTE como na lista acima
- Score Buffett sempre por último
- 2-4 bullets por subseção; omita sem dados

DOCUMENTO — {filename}:
{pdf_text[:20000]}
"""


# ── Phase 2: consolidation (text-in, markdown-out — zero JSON) ─────────────

def _build_consolidation_prompt(
    per_doc_sections: list[dict], filenames: list[str], company: str, period: str
) -> str:
    header_line = _context_header(company, period)
    lenses_list = "\n".join(f"- {l}" for l in LENSES)
    # Organise per-doc texts by lens
    blocks: list[str] = []
    for lens in LENSES:
        blocks.append(f"=== {lens} ===")
        for fname, sections in zip(filenames, per_doc_sections):
            text = sections.get(lens, "(sem dados)") or "(sem dados)"
            blocks.append(f"[{fname}]\n{text}")
        blocks.append("")
    combined = "\n".join(blocks)

    return f"""Você é um analista sênior de inteligência de mercado B2B.

{header_line}Abaixo estão análises por lente extraídas de {len(per_doc_sections)} documentos da mesma empresa.

Consolide em um único relatório markdown final. Use o MESMO formato de seção para cada lente:

LENTES (use exatamente estes nomes nos headers `## `):
{lenses_list}

FORMATO DE CADA SEÇÃO:

## [Nome da Lente]

**Tendência:** [valor consolidado]

**Destaques:**
- bullet consolidado (deduplicado, mais relevante)

**Oportunidades para Fornecedores:**
- bullet consolidado

**Alertas:**
- bullet consolidado

**Métricas & Números:**
- métrica

**Citações:**
- "trecho [contexto]"

**Projetos & Iniciativas:**
- projeto: descrição

---

TEXTOS POR LENTE (consolide e deduplique):
{combined}
"""


def _build_investor_consolidation_prompt(
    per_doc_sections: list[dict], filenames: list[str], company: str, period: str
) -> str:
    header_line = _context_header(company, period)
    regular = [l for l in INVESTOR_LENSES if l != "Score Buffett"]
    lenses_list = "\n".join(f"- {l}" for l in regular)
    blocks: list[str] = []
    for lens in INVESTOR_LENSES:
        blocks.append(f"=== {lens} ===")
        for fname, sections in zip(filenames, per_doc_sections):
            text = sections.get(lens, "(sem dados)") or "(sem dados)"
            blocks.append(f"[{fname}]\n{text}")
        blocks.append("")
    combined = "\n".join(blocks)

    return f"""Você é um analista sênior de investimentos especializado em value investing.

{header_line}Abaixo estão análises por lente extraídas de {len(per_doc_sections)} documentos.

Consolide em um relatório markdown final com 7 seções.

LENTES REGULARES (use exatamente estes nomes em `## `):
{lenses_list}

FORMATO LENTES REGULARES:

## [Nome da Lente]

**Tendência:** [valor]

**Destaques:**
- bullet consolidado

**Insights de Investimento:**
- bullet consolidado

**Riscos:**
- bullet consolidado

**Métricas & Dados:**
- métrica

**Citações:**
- "trecho [contexto]"

---

FORMATO SCORE BUFFETT (última seção, obrigatória):

## Score Buffett

**Nota:** [número 1-10 consolidado]/10

**Justificativa:** Parágrafo consolidado...

**Por critério:**
- 🔍 **Negócio Compreensível:** avaliação final
- 🏰 **Vantagem Durável:** avaliação final
- 👔 **Gestão Confiável:** avaliação final
- 📈 **Histórico de Lucratividade:** avaliação final
- 💰 **Retorno sobre Capital:** avaliação final
- 🔭 **Perspectiva de Longo Prazo:** avaliação final

---

TEXTOS POR LENTE:
{combined}
"""


# ── Orchestrator ──────────────────────────────────────────────────────────────

def analyze_with_claude(
    files_and_texts: list[tuple[str, str]],
    company: str,
    period: str,
    progress_callback=None,
    mode: str = "fornecedor",
) -> dict[str, str]:
    """
    Two-phase markdown pipeline — zero JSON at any step.
      Phase 1: extract free markdown per lens from each PDF
      Phase 2: consolidate multiple extractions into a single markdown report
    Returns: {lens_name: markdown_string}
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY não encontrada nas variáveis de ambiente.")

    client = anthropic.Anthropic(api_key=api_key)
    total  = len(files_and_texts)
    is_investor = mode == "investor"
    active_lenses   = INVESTOR_LENSES if is_investor else LENSES
    build_ext_prompt  = _build_investor_extraction_prompt   if is_investor else _build_extraction_prompt
    build_cons_prompt = _build_investor_consolidation_prompt if is_investor else _build_consolidation_prompt

    def _call(max_tokens: int, messages: list, retries: int = 3) -> str:
        """Call Claude with exponential-backoff retry on transient 5xx errors."""
        for attempt in range(retries):
            try:
                msg = client.messages.create(
                    model="claude-opus-4-5",
                    max_tokens=max_tokens,
                    messages=messages,
                )
                return msg.content[0].text
            except anthropic.APIStatusError as e:
                if e.status_code >= 500 and attempt < retries - 1:
                    time.sleep(2 ** attempt)  # 1s, 2s, 4s …
                    continue
                raise
        raise RuntimeError("Todas as tentativas falharam.")

    # ── Phase 1: per-PDF markdown extraction ─────────────────────────────────
    per_doc_sections: list[dict[str, str]] = []
    filenames: list[str] = []

    for i, (filename, text) in enumerate(files_and_texts):
        if progress_callback:
            progress_callback(i, total, filename)
        prompt = build_ext_prompt(text, filename, company, period)
        raw = _call(4000, [{"role": "user", "content": prompt}])
        sections = _parse_md_sections(raw, active_lenses)
        per_doc_sections.append(sections)
        filenames.append(filename)

    # ── Phase 2: consolidation (single PDF → pass-through) ───────────────────
    if progress_callback:
        progress_callback(total, total, "consolidando…")

    if len(per_doc_sections) == 1:
        return per_doc_sections[0]

    prompt = build_cons_prompt(per_doc_sections, filenames, company, period)
    raw = _call(5000, [{"role": "user", "content": prompt}])
    return _parse_md_sections(raw, active_lenses)


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


def render_lens_card(lens_name: str, raw_data, card_index: int):
    """Render a fornecedor lens card. raw_data may be a markdown string (new) or dict (legacy)."""
    md_text    = _compat_md(raw_data)
    icon       = LENS_ICONS.get(lens_name, "📌")
    tendencia  = _extract_tendencia(md_text)
    trend_html = render_trend_badge(tendencia)
    # Remove the Tendência line from body — shown as a badge
    body = re.sub(r'\*\*Tend[êe]ncia:\*\*[^\n]*\n?', '', md_text, flags=re.IGNORECASE).strip()

    hdr_col, badge_col = st.columns([5, 1])
    with hdr_col:
        st.markdown(
            f'<div style="font-size:1.05rem;font-weight:700;color:#1e293b;padding-top:2px;">'
            f'{icon} {lens_name}</div>',
            unsafe_allow_html=True,
        )
    with badge_col:
        st.markdown(trend_html, unsafe_allow_html=True)

    if body:
        st.markdown(body)
    st.divider()


def render_investor_lens_card(lens_name: str, raw_data, card_index: int):
    """Render an investor lens card. raw_data may be a markdown string or legacy dict."""
    md_text    = _compat_md(raw_data)
    icon       = INVESTOR_LENS_ICONS.get(lens_name, "📌")
    tendencia  = _extract_tendencia(md_text)
    trend_html = render_trend_badge(tendencia)
    body = re.sub(r'\*\*Tend[êe]ncia:\*\*[^\n]*\n?', '', md_text, flags=re.IGNORECASE).strip()

    hdr_col, badge_col = st.columns([5, 1])
    with hdr_col:
        st.markdown(
            f'<div style="font-size:1.05rem;font-weight:700;color:#1e293b;padding-top:2px;">'
            f'{icon} {lens_name}</div>',
            unsafe_allow_html=True,
        )
    with badge_col:
        st.markdown(trend_html, unsafe_allow_html=True)

    if body:
        st.markdown(body)
    st.divider()


def render_buffett_score_card(raw_data):
    """Render the Score Buffett card. raw_data may be markdown string or legacy dict."""
    md_text = _compat_md(raw_data)

    # Extract nota
    m = re.search(r'\*\*Nota:\*\*\s*(\d+)', md_text, re.IGNORECASE)
    nota = int(m.group(1)) if m else 5
    nota = max(1, min(10, nota))
    nota_color = "#22c55e" if nota >= 8 else ("#f59e0b" if nota >= 6 else "#ef4444")
    pct = nota / 10

    # Remove Nota line from body
    body = re.sub(r'\*\*Nota:\*\*[^\n]*\n?', '', md_text, flags=re.IGNORECASE).strip()

    nota_col, info_col = st.columns([1, 6])
    with nota_col:
        st.markdown(
            f'<div style="font-size:3.2rem;font-weight:900;color:{nota_color};'
            f'text-align:center;padding-top:4px;line-height:1;">{nota}</div>'
            f'<div style="font-size:0.72rem;color:#b45309;text-align:center;">/ 10</div>',
            unsafe_allow_html=True,
        )
    with info_col:
        st.markdown(
            '<div style="font-size:1.05rem;font-weight:700;color:#92400e;">🧾 Score Buffett</div>'
            '<div style="font-size:0.8rem;color:#b45309;">Critérios de Warren Buffett</div>',
            unsafe_allow_html=True,
        )

    st.progress(pct)
    if body:
        st.markdown(body)
    st.divider()


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
            md = _compat_md(results.get(lens, ""))
            lens_op_count[lens] += _count_bullets(md, "Oportunidades para Fornecedores")

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
