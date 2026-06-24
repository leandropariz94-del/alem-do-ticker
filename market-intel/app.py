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
    page_title="Além do Ticker",
    page_icon="📈",
    layout="wide",
)

DB_PATH = os.path.join(os.path.dirname(__file__), "market_intel.db")

INVESTOR_LENSES = [
    "Fundamentos Financeiros",
    "Alocação de Capital",
    "Vantagem Competitiva (Moat)",
    "Gestão e Governança",
    "Riscos Declarados",
    "Guidance e Perspectivas",
]

INVESTOR_LENS_ICONS = {
    "Fundamentos Financeiros":     "💰",
    "Alocação de Capital":         "📊",
    "Vantagem Competitiva (Moat)": "🏰",
    "Gestão e Governança":         "👔",
    "Riscos Declarados":           "⚠️",
    "Guidance e Perspectivas":     "🔭",
}

# ── Scores de metodologia ──────────────────────────────────────────────────────
# Cada análise gera 3 notas de 1 a 10, cada uma baseada em uma metodologia de
# investimento reconhecida, com uma justificativa curta ancorada no relatório.
# Exibidas como um painel de avaliação no topo, antes das lentes detalhadas.
SCORE_METHODOLOGIES = ["Score Buffett", "Score Barsi", "Score Graham"]

SCORE_META = {
    "Score Buffett": {
        "icon": "🏰",
        "investor": "Warren Buffett",
        "subtitle": "Qualidade do negócio",
        "criteria": [
            "ROE consistente",
            "Margem líquida estável",
            "Dívida controlada",
            "Vantagem competitiva durável (moat)",
            "Gestão transparente",
            "Crescimento previsível",
        ],
    },
    "Score Barsi": {
        "icon": "💵",
        "investor": "Luiz Barsi",
        "subtitle": "Dividendos & renda",
        "criteria": [
            "Dividend yield histórico",
            "Consistência de proventos",
            "Solidez do setor",
            "Empresa perene",
            "Fluxo de caixa estável",
        ],
    },
    "Score Graham": {
        "icon": "🛡️",
        "investor": "Benjamin Graham",
        "subtitle": "Margem de segurança",
        "criteria": [
            "Margem de segurança",
            "P/L conservador",
            "Liquidez",
            "Baixo endividamento",
            "Estabilidade de lucros nos últimos anos",
        ],
    },
}

# Lista completa de seções que a IA gera e que o parser precisa reconhecer:
# as 6 lentes analíticas + os 3 scores de metodologia.
INVESTOR_SECTIONS = INVESTOR_LENSES + SCORE_METHODOLOGIES

def lenses_for_mode(mode: str = "investor") -> list[str]:
    return INVESTOR_LENSES


def icons_for_mode(mode: str = "investor") -> dict[str, str]:
    return INVESTOR_LENS_ICONS


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
    # Migration: add `mode` column and backfill from existing results.
    cols = [r[1] for r in con.execute("PRAGMA table_info(analyses)").fetchall()]
    if "mode" not in cols:
        con.execute("ALTER TABLE analyses ADD COLUMN mode TEXT NOT NULL DEFAULT 'fornecedor'")
        for rid, rj in con.execute("SELECT id, results_json FROM analyses").fetchall():
            try:
                detected = _detect_mode(json.loads(rj))
            except Exception:
                detected = "investor"
            con.execute("UPDATE analyses SET mode = ? WHERE id = ?", (detected, rid))
    con.commit()
    con.close()


def _detect_mode(results: dict) -> str:
    """App de propósito único: toda análise é do investidor pessoa física."""
    return "investor"


def compute_investor_score(results: dict) -> float:
    """Score geral — média das 3 notas de metodologia (Buffett, Barsi, Graham),
    de 1 a 10, convertida para a escala 0–100 (média × 10)."""
    notas = []
    for name in SCORE_METHODOLOGIES:
        nota = _extract_nota(_compat_md(results.get(name, "")))
        if nota is not None:
            notas.append(nota)
    if notas:
        avg = sum(notas) / len(notas)
        return round(min(100.0, max(0.0, avg * 10)), 1)
    # Fallback: composto a partir das lentes analíticas, caso as notas faltem.
    total = 0.0
    count = 0
    for lens in INVESTOR_LENSES:
        md = _compat_md(results.get(lens, ""))
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


def _score_for_mode(mode: str, results: dict) -> float:
    return compute_investor_score(results)


def save_analysis(company: str, period: str, files_count: int, results: dict, mode: str | None = None) -> int:
    if mode is None:
        mode = _detect_mode(results)
    score = _score_for_mode(mode, results)
    con = sqlite3.connect(DB_PATH)
    cur = con.execute(
        "INSERT INTO analyses (company, period, created_at, files_count, results_json, score, mode) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (company, period, datetime.now().isoformat(timespec="seconds"), files_count, json.dumps(results, ensure_ascii=False), score, mode),
    )
    row_id = cur.lastrowid
    con.commit()
    con.close()
    return row_id


def list_analyses(mode: str | None = None) -> list[dict]:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    if mode:
        rows = con.execute(
            "SELECT id, company, period, created_at, files_count, score, mode FROM analyses WHERE mode = ? ORDER BY created_at DESC",
            (mode,),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT id, company, period, created_at, files_count, score, mode FROM analyses ORDER BY created_at DESC"
        ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def list_periods(mode: str | None = None) -> list[str]:
    con = sqlite3.connect(DB_PATH)
    if mode:
        rows = con.execute(
            "SELECT DISTINCT period FROM analyses WHERE period != '' AND mode = ? ORDER BY period DESC",
            (mode,),
        ).fetchall()
    else:
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


def analyses_for_period(period: str, mode: str | None = None) -> list[dict]:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    if mode:
        rows = con.execute(
            "SELECT id, company, period, created_at, files_count, score, results_json, mode FROM analyses WHERE period = ? AND mode = ? ORDER BY score DESC",
            (period, mode),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT id, company, period, created_at, files_count, score, results_json, mode FROM analyses WHERE period = ? ORDER BY score DESC",
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

# Limite de caracteres enviados à API por PDF. Os releases concentram a
# narrativa estratégica (destaques, mensagem da gestão, guidance) no início e
# no meio; o final costuma ser tabela repetitiva e nota de rodapé. Mantemos o
# início e um trecho do meio e descartamos o fim para reduzir o custo por token.
PDF_CHAR_LIMIT = 50_000


def _trim_to_strategic_window(text: str, limit: int = PDF_CHAR_LIMIT) -> str:
    if len(text) <= limit:
        return text
    sep = "\n\n[... trecho intermediário omitido para reduzir custo ...]\n\n"
    budget = max(0, limit - len(sep))
    head_len = int(budget * 0.7)          # priorize o início
    mid_len  = budget - head_len          # e um trecho do meio
    head = text[:head_len]
    midpoint = len(text) // 2
    start = max(head_len, midpoint - mid_len // 2)
    middle = text[start:start + mid_len]
    return head + sep + middle


def extract_text_from_pdf(pdf_bytes: bytes, filename: str = "") -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = "".join(page.get_text() for page in doc)
    doc.close()
    return _trim_to_strategic_window(text)


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


def _extract_nota(md: str, default=None):
    """Parse the **Nota:** N value (1-10) from a score section's markdown."""
    m = re.search(r'\*\*Nota:\*\*\s*(\d+)', md, re.IGNORECASE)
    if not m:
        return default
    return max(1, min(10, int(m.group(1))))


def _extract_justificativa(md: str) -> str:
    """Parse the **Justificativa:** paragraph (stops at the next **Header:**)."""
    m = re.search(
        r'\*\*Justificativa:\*\*\s*(.+?)(?=\n\s*\*\*[^\n]+:\*\*|\Z)',
        md, re.IGNORECASE | re.DOTALL,
    )
    return m.group(1).strip() if m else ""


def _extract_criteria_block(md: str) -> str:
    """Parse the **Por critério:** bullet block from a score section's markdown."""
    m = re.search(r'\*\*Por crit[ée]rio:\*\*\s*(.+)', md, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""


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

def _score_format_block() -> str:
    """Markdown spec for the 3 methodology score sections (Buffett, Barsi, Graham)."""
    blocks: list[str] = []
    for name in SCORE_METHODOLOGIES:
        meta = SCORE_META[name]
        crits = "\n".join(
            f"- **{c}:** avaliação objetiva com base no documento" for c in meta["criteria"]
        )
        blocks.append(
            f"## {name}\n\n"
            f"**Nota:** [número de 1 a 10]/10\n\n"
            f"**Justificativa:** 2 a 3 linhas explicando o que NO RELATÓRIO embasou a nota, "
            f"citando dados concretos, segundo a metodologia de {meta['investor']}.\n\n"
            f"**Por critério:**\n{crits}"
        )
    return "\n\n---\n\n".join(blocks)


def _build_investor_extraction_prompt(pdf_text: str, filename: str, company: str, period: str) -> str:
    lenses_list = "\n".join(f"- {l}" for l in INVESTOR_LENSES)
    header_line = _context_header(company, period)
    n_total = len(INVESTOR_LENSES) + len(SCORE_METHODOLOGIES)
    return f"""Você é um analista de investimentos para o investidor pessoa física. \
Seu trabalho é ir ALÉM DO PREÇO DA AÇÃO: mergulhar nos números realizados, nos projetos, nas \
perspectivas e nos objetivos declarados pela gestão nos documentos de RI.

{header_line}Analise o documento abaixo e produza um relatório em markdown com exatamente {n_total} seções: \
{len(INVESTOR_LENSES)} lentes analíticas seguidas de {len(SCORE_METHODOLOGIES)} scores de metodologia.

LENTES ANALÍTICAS:
{lenses_list}

FORMATO PARA CADA LENTE ANALÍTICA:

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

SCORES DE METODOLOGIA (3 seções obrigatórias, ao final, nesta ordem):

{_score_format_block()}

---

REGRAS:
- Copie o nome de cada seção EXATAMENTE como nas listas acima
- Os 3 scores sempre por último, na ordem: Score Buffett, Score Barsi, Score Graham
- Cada Nota de 1 a 10 deve refletir os critérios da respectiva metodologia
- A Justificativa de cada score deve ter 2-3 linhas e citar dados concretos do relatório
- 2-4 bullets por subseção; omita subseções sem dados

DOCUMENTO — {filename}:
{pdf_text}
"""


# ── Phase 2: consolidation (text-in, markdown-out — zero JSON) ─────────────

def _build_investor_consolidation_prompt(
    per_doc_sections: list[dict], filenames: list[str], company: str, period: str
) -> str:
    header_line = _context_header(company, period)
    lenses_list = "\n".join(f"- {l}" for l in INVESTOR_LENSES)
    n_total = len(INVESTOR_LENSES) + len(SCORE_METHODOLOGIES)
    blocks: list[str] = []
    for lens in INVESTOR_SECTIONS:
        blocks.append(f"=== {lens} ===")
        for fname, sections in zip(filenames, per_doc_sections):
            text = sections.get(lens, "(sem dados)") or "(sem dados)"
            blocks.append(f"[{fname}]\n{text}")
        blocks.append("")
    combined = "\n".join(blocks)

    return f"""Você é um analista sênior de investimentos para o investidor pessoa física, \
focado em ir além do preço da ação: números realizados, projetos, perspectivas e objetivos da gestão.

{header_line}Abaixo estão análises por seção extraídas de {len(per_doc_sections)} documentos da mesma empresa.

Consolide em um único relatório markdown final com exatamente {n_total} seções \
({len(INVESTOR_LENSES)} lentes analíticas + {len(SCORE_METHODOLOGIES)} scores de metodologia), \
deduplicando e priorizando o mais relevante.

LENTES ANALÍTICAS (use exatamente estes nomes em `## `):
{lenses_list}

FORMATO LENTES ANALÍTICAS:

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

SCORES DE METODOLOGIA (3 seções obrigatórias, ao final, nesta ordem):

{_score_format_block()}

---

REGRAS:
- Os 3 scores sempre por último, na ordem: Score Buffett, Score Barsi, Score Graham
- Cada Nota consolidada de 1 a 10; Justificativa de 2-3 linhas ancorada nos dados do relatório

TEXTOS POR SEÇÃO (consolide e deduplique):
{combined}
"""


# ── Orchestrator ──────────────────────────────────────────────────────────────

def analyze_with_claude(
    files_and_texts: list[tuple[str, str]],
    company: str,
    period: str,
    progress_callback=None,
    mode: str = "investor",
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
    # O parser precisa reconhecer todas as seções: 6 lentes + 3 scores.
    active_lenses = INVESTOR_SECTIONS
    build_ext_prompt  = _build_investor_extraction_prompt
    build_cons_prompt = _build_investor_consolidation_prompt

    # Modelo: Haiku 4.5 (datado) como principal — muito mais barato e suficiente
    # para extração estruturada. Mantemos o alias Haiku como fallback caso o
    # modelo datado fique sobrecarregado (529) durante picos de uso.
    MODEL_CHAIN = ["claude-haiku-4-5-20251001", "claude-haiku-4-5"]

    # 8000 tokens por chamada: a saída tem 9 seções (6 lentes + 3 scores, cada um
    # com justificativa e critérios). Folga suficiente para nada truncar/ficar em
    # branco, mantendo custo controlado (saída real costuma ficar bem abaixo disso).
    out_max_tokens = 8000

    def _call(max_tokens: int, messages: list, retries: int = 2) -> str:
        """Call Claude with a model fallback chain + exponential-backoff retry.

        For each model we retry on transient errors; if 529 (overloaded)
        persists, we switch to the next model in the chain rather than failing.
        """
        last_err: Exception | None = None
        for mi, model in enumerate(MODEL_CHAIN):
            is_last_model = mi >= len(MODEL_CHAIN) - 1
            for attempt in range(retries):
                try:
                    msg = client.messages.create(
                        model=model,
                        max_tokens=max_tokens,
                        messages=messages,
                    )
                    st.session_state["_models_used"] = (
                        st.session_state.get("_models_used", set()) | {model}
                    )
                    return msg.content[0].text
                except anthropic.APIStatusError as e:
                    last_err = e
                    is_last_attempt = attempt >= retries - 1
                    if e.status_code == 529:
                        if is_last_attempt:
                            if not is_last_model and progress_callback:
                                progress_callback(
                                    -1, -1,
                                    "⏳ Modelo principal sobrecarregado — alternando para o modelo alternativo (mais rápido)…",
                                )
                            break  # move to next model in the chain
                        wait = 4 * (2 ** attempt)   # 4s, 8s
                    elif e.status_code >= 500:
                        if is_last_attempt:
                            break
                        wait = 3 * (2 ** attempt)   # 3s, 6s
                    else:
                        raise
                    if progress_callback:
                        progress_callback(
                            -1, -1,
                            f"⏳ Servidor sobrecarregado — aguardando {wait}s antes de tentar novamente…",
                        )
                    time.sleep(wait)
        if last_err is not None:
            raise last_err
        raise RuntimeError("Todas as tentativas falharam.")

    # ── Phase 1: per-PDF markdown extraction ─────────────────────────────────
    per_doc_sections: list[dict[str, str]] = []
    filenames: list[str] = []

    for i, (filename, text) in enumerate(files_and_texts):
        if progress_callback:
            progress_callback(i, total, filename)
        if i > 0:
            time.sleep(1)  # avoid rate-limiting between consecutive calls
        prompt = build_ext_prompt(text, filename, company, period)
        raw = _call(out_max_tokens, [{"role": "user", "content": prompt}])
        sections = _parse_md_sections(raw, active_lenses)
        per_doc_sections.append(sections)
        filenames.append(filename)

    # ── Phase 2: consolidation (single PDF → pass-through) ───────────────────
    if progress_callback:
        progress_callback(total, total, "consolidando…")

    if len(per_doc_sections) == 1:
        return per_doc_sections[0]

    prompt = build_cons_prompt(per_doc_sections, filenames, company, period)
    raw = _call(out_max_tokens, [{"role": "user", "content": prompt}])
    return _parse_md_sections(raw, active_lenses)


# ─── Render helpers ───────────────────────────────────────────────────────────

def render_trend_badge(trend: str) -> str:
    t = trend.lower()
    if any(w in t for w in ["alta", "crescimento", "aumento", "aceleração", "aceleracao", "expansão", "quente"]):
        color, icon = "#22c55e", "↑"
    elif any(w in t for w in ["queda", "redução", "reducao", "declínio", "recuo", "desaceleração", "frio"]):
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


def _md_escape_dollars(text: str) -> str:
    """Escape '$' so Streamlit does not treat 'R$ ... $' spans as LaTeX math.
    Brazilian financial text uses R$ / US$ heavily; unescaped pairs render as formulas."""
    return text.replace("$", "\\$")


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
        st.markdown(_md_escape_dollars(body))
    st.divider()


def render_score_panel(results: dict):
    """Painel de avaliação no topo — as 3 notas de metodologia lado a lado."""
    cols = st.columns(len(SCORE_METHODOLOGIES))
    for col, name in zip(cols, SCORE_METHODOLOGIES):
        meta     = SCORE_META[name]
        md_text  = _compat_md(results.get(name, ""))
        nota     = _extract_nota(md_text)
        justi    = _extract_justificativa(md_text)
        criteria = _extract_criteria_block(md_text)
        if nota is None:
            nota_disp, nota_color = "—", "#94a3b8"
        else:
            nota_disp = str(nota)
            nota_color = "#22c55e" if nota >= 8 else ("#f59e0b" if nota >= 6 else "#ef4444")
        with col:
            st.markdown(
                f'<div style="border:1px solid #e2e8f0;border-radius:12px;padding:14px 16px;'
                f'background:#ffffff;">'
                f'<div style="font-size:1rem;font-weight:700;color:#1e293b;">{meta["icon"]} {name}</div>'
                f'<div style="font-size:0.74rem;color:#64748b;margin-bottom:4px;">'
                f'{meta["investor"]} · {meta["subtitle"]}</div>'
                f'<div style="font-size:2.6rem;font-weight:900;color:{nota_color};line-height:1;">'
                f'{nota_disp}<span style="font-size:0.9rem;color:#94a3b8;font-weight:600;"> / 10</span>'
                f'</div></div>',
                unsafe_allow_html=True,
            )
            if justi:
                st.markdown(_md_escape_dollars(justi))
            if criteria:
                with st.expander("Por critério"):
                    st.markdown(_md_escape_dollars(criteria))
    st.divider()


# ─── Pages ────────────────────────────────────────────────────────────────────

def page_overview():
    mode = "investor"
    st.title("📈 Visão Geral — Ranking de Investimentos")
    st.caption("Ranking por Score Médio (média das 3 metodologias) · todas as empresas analisadas")

    with st.expander("❓ Como o score é calculado?"):
        st.markdown(
            "O **Score Médio** (0 a 10) é a média de três avaliações independentes do mesmo "
            "relatório, cada uma seguindo uma metodologia consagrada:\n\n"
            "- **🏰 Score Buffett** — qualidade do negócio (moat, ROE, gestão)\n"
            "- **💵 Score Barsi** — dividendos e geração de renda no longo prazo\n"
            "- **🛡️ Score Graham** — margem de segurança e preço conservador\n\n"
            "Cada nota vai de 1 a 10 com uma justificativa ancorada nos dados do relatório."
        )

    periods = list_periods(mode)
    all_analyses = list_analyses(mode)
    if not all_analyses:
        st.info("Nenhuma análise salva ainda. Faça uma nova análise para começar.")
        return

    all_periods_option = "Todos os períodos"
    period_options = [all_periods_option] + periods
    selected_period = st.selectbox("Selecione o período", period_options)

    if selected_period == all_periods_option:
        rows = sorted(all_analyses, key=lambda x: x["score"], reverse=True)
        loaded = []
        for r in rows:
            full = load_analysis(r["id"])
            if full is None:
                continue
            r["results"] = full["results"]
            loaded.append(r)
        rows = loaded
    else:
        rows = analyses_for_period(selected_period, mode)

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

        col_rank, col_info, col_bar, col_score, col_btn, col_del = st.columns([0.4, 2.3, 2.7, 0.8, 1.1, 0.9])

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
            score_val = f"{score / 10:.1f}"
            score_max = "/ 10"
            st.markdown(
                f'<div style="text-align:center;padding-top:6px;">'
                f'<div style="font-size:1.4rem;font-weight:800;color:{s_color};">{score_val}</div>'
                f'<div style="font-size:0.7rem;color:#94a3b8;">{score_max}</div>'
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

        with col_del:
            st.markdown("<div style='padding-top:8px;'>", unsafe_allow_html=True)
            if st.session_state.get("ov_confirm_del") == rec["id"]:
                if st.button("Confirmar", key=f"ov_delok_{rec['id']}", type="primary", use_container_width=True):
                    delete_analysis(rec["id"])
                    st.session_state.pop("ov_confirm_del", None)
                    st.rerun()
            else:
                if st.button("🗑️", key=f"ov_del_{rec['id']}", use_container_width=True, help="Excluir esta análise"):
                    st.session_state["ov_confirm_del"] = rec["id"]
                    st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        st.divider()

    # Heatmap — lentes com mais insights entre as empresas do período
    st.subheader("🔥 Lentes com mais insights no período")
    heatmap_lenses = list(INVESTOR_LENSES)
    bullet_label = "Insights de Investimento"
    icon_map = INVESTOR_LENS_ICONS

    lens_op_count: dict[str, int] = {l: 0 for l in heatmap_lenses}
    for rec in rows:
        results = rec.get("results") or {}
        for lens in heatmap_lenses:
            md = _compat_md(results.get(lens, ""))
            lens_op_count[lens] += _count_bullets(md, bullet_label)

    sorted_lenses = sorted(lens_op_count.items(), key=lambda x: x[1], reverse=True)
    max_count = max(v for _, v in sorted_lenses) if sorted_lenses else 1

    h1, h2 = st.columns(2)
    for i, (lens, count) in enumerate(sorted_lenses):
        col = h1 if i % 2 == 0 else h2
        icon = icon_map.get(lens, "📌")
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
    all_lenses_ref = INVESTOR_LENSES
    score_label, mode_badge = "Score Médio", "📈 Modo Investidor"

    if st.session_state.get("fallback_notice_for") == rec["id"]:
        st.info(
            "ℹ️ Os modelos principais estavam sobrecarregados (erro 529), então esta análise "
            "foi gerada com o **modelo alternativo mais rápido (Haiku)**. A análise é válida, "
            "mas pode ser menos aprofundada. Para uma análise com o modelo principal, refaça "
            "mais tarde quando a capacidade normalizar."
        )
        del st.session_state["fallback_notice_for"]

    pf = st.session_state.get("partial_failure_notice")
    if pf and pf.get("target_id") == rec["id"]:
        failed = ", ".join(pf.get("failed", []))
        st.warning(
            f"⚠️ Nesta rodada, alguns módulos não puderam ser gerados: **{failed}**. "
            "Isso costuma ser sobrecarga temporária da API da Anthropic. Você pode refazer "
            "a análise mais tarde para preencher os módulos que faltaram."
        )
        del st.session_state["partial_failure_notice"]

    hdr_col, score_col = st.columns([5, 1])
    with hdr_col:
        st.title(f"📊 {company}{period_suffix}")
        st.caption(f"{mode_badge} · Análise salva em {date_lbl} · {rec['files_count']} arquivo(s)")
    with score_col:
        score_display = f"{score / 10:.1f}/10"
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

    with st.expander("❓ Como o score é calculado?"):
        st.markdown(
            "O **Score Médio** (0 a 10) é a média de três avaliações do mesmo relatório, cada "
            "uma seguindo uma metodologia consagrada — **🏰 Buffett** (qualidade do negócio), "
            "**💵 Barsi** (dividendos e renda) e **🛡️ Graham** (margem de segurança). "
            "As três notas aparecem no painel abaixo, com a justificativa de cada uma."
        )

    st.markdown("### 🧮 Painel de Avaliação")
    render_score_panel(results)

    lenses_to_show = [l for l in selected_lenses if l in results]
    if not lenses_to_show:
        st.warning("Nenhuma lente selecionada. Use o filtro lateral.")
        return

    n_total = len(all_lenses_ref)
    st.markdown(
        f"### 🔍 Lentes detalhadas\n"
        f"Exibindo **{len(lenses_to_show)}** de {n_total} lentes · "
        f"use o filtro na barra lateral para escolher quais lentes aparecem."
    )
    st.divider()

    for i, lens in enumerate(lenses_to_show):
        if lens in results:
            render_investor_lens_card(lens, results[lens], i)


def page_new_analysis(selected_lenses: list[str], mode: str = "investor"):
    st.title("📈 Além do Ticker — Nova Análise")
    st.markdown(
        "Faça upload de **um ou mais PDFs** de RI de uma empresa brasileira e vá **além do preço da ação**: "
        "números realizados, projetos, perspectivas e objetivos da gestão — com avaliação por três "
        "metodologias (**Buffett**, **Barsi** e **Graham**)."
    )

    st.caption(
        "💡 Um único upload gera o relatório completo — 6 lentes analíticas e os 3 scores de metodologia. "
        "O resultado fica salvo no histórico."
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

    PDF_LIMIT = 3

    uploaded_files = st.file_uploader(
        f"Selecione os PDFs do release trimestral (máximo {PDF_LIMIT} arquivos)",
        type=["pdf"],
        accept_multiple_files=True,
        help=f"Máximo {PDF_LIMIT} PDFs por análise. O conteúdo será consolidado em uma análise única.",
    )

    if uploaded_files:
        if len(uploaded_files) > PDF_LIMIT:
            st.warning(
                f"⚠️ Você selecionou **{len(uploaded_files)} PDFs**. "
                f"O limite é **{PDF_LIMIT} arquivos** por análise para garantir estabilidade. "
                f"Apenas os primeiros {PDF_LIMIT} serão processados."
            )
            uploaded_files = uploaded_files[:PDF_LIMIT]

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
            # ── Step 1: extract text from all PDFs (uma única vez) ──────────
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

            modes_to_run: list[tuple[str, str]] = [("investor", "📈 Investidor")]
            n_modes = len(modes_to_run)

            st.info(
                f"**{total_files} arquivo(s)** · **{total_chars:,} chars** extraídos. "
                "Gerando o relatório completo (6 lentes + 3 scores) — pode levar alguns minutos."
            )

            # ── Step 2: roda cada modo em sequência, com progresso ao vivo ──
            module_header   = st.empty()
            progress_bar    = st.progress(0)
            status_text     = st.empty()
            display_company = company_name or (
                uploaded_files[0].name.replace(".pdf", "") if len(uploaded_files) == 1 else "Empresa"
            )

            def make_on_progress(mode_idx: int):
                base = mode_idx / n_modes
                def on_progress(current: int, total: int, filename: str):
                    if current == -1:
                        # retry status message passed from _call()
                        status_text.markdown(f"🔄 {filename}")
                        return
                    if total <= 0:
                        frac = 0.0
                    elif current < total:
                        frac = current / (total + 1)
                        status_text.markdown(
                            f"**Fase 1 — Extração** · arquivo {current + 1}/{total}: `{filename}`"
                        )
                    else:
                        frac = total / (total + 1)
                        step_label = "consolidando os resultados..." if total > 1 else "gerando análise completa..."
                        status_text.markdown(f"**Fase 2 —** {step_label}")
                    progress_bar.progress(min(1.0, base + frac / n_modes))
                return on_progress

            saved_ids: dict[str, int] = {}
            models_by_mode: dict[str, set] = {}
            failed_modes: list[tuple[str, str]] = []
            # Cada módulo roda de forma independente: se um falhar, seguimos para
            # os próximos e ainda salvamos os que deram certo (sem perder tudo).
            for mi, (m, mlabel) in enumerate(modes_to_run):
                module_header.markdown(f"#### Analisando módulo {mlabel} — {mi + 1} de {n_modes}")
                st.session_state["_models_used"] = set()  # reset per mode
                try:
                    results = analyze_with_claude(
                        files_and_texts, company_name, period,
                        progress_callback=make_on_progress(mi),
                        mode=m,
                    )
                except anthropic.APIStatusError as e:
                    if e.status_code == 529:
                        reason = "servidor da Anthropic sobrecarregado (erro 529)"
                    elif e.status_code == 500:
                        reason = "erro interno da Anthropic (erro 500) — possível quota esgotada"
                    else:
                        reason = f"erro da API da Anthropic (código {e.status_code})"
                    failed_modes.append((mlabel, reason))
                    continue
                except Exception as e:
                    failed_modes.append((mlabel, str(e)))
                    continue
                models_by_mode[m] = set(st.session_state.get("_models_used", set()))
                saved_ids[m] = save_analysis(display_company, period, total_files, results, mode=m)

            progress_bar.empty()
            status_text.empty()
            module_header.empty()

            if not saved_ids:
                # Todos os módulos falharam — nada foi salvo.
                detalhe = " · ".join(f"**{lbl}**: {why}" for lbl, why in failed_modes)
                st.error(
                    "⚠️ **Nenhum módulo pôde ser analisado.** "
                    f"{detalhe}. Geralmente é sobrecarga temporária da API — aguarde alguns "
                    "minutos e tente novamente. Se persistir, tente com apenas 1 PDF."
                )
                return

            # Abre o resultado do módulo ativo na barra lateral (ou o primeiro
            # que tiver sido salvo, caso o ativo tenha falhado).
            target_id = saved_ids.get(mode) or next(iter(saved_ids.values()))

            # Aviso de modelo alternativo (Haiku) baseado só no módulo de destino.
            models_used = models_by_mode.get(mode, set())
            if "claude-haiku-4-5" in models_used and "claude-sonnet-4-6" not in models_used:
                st.session_state["fallback_notice_for"] = target_id

            # Se alguns módulos falharam mas outros foram salvos, avisa na próxima tela.
            if failed_modes:
                st.session_state["partial_failure_notice"] = {
                    "target_id": target_id,
                    "failed": [lbl for lbl, _ in failed_modes],
                }

            st.session_state["page"] = "analise_detalhe"
            st.session_state["loaded_analysis_id"] = target_id
            st.rerun()

    # If there's a fresh result in session (legacy path), show it
    if "results" in st.session_state and "loaded_analysis_id" not in st.session_state:
        results       = st.session_state.pop("results")
        display_company = st.session_state.pop("display_company", "Empresa")
        period_val    = st.session_state.pop("display_period", "")
        files_count   = st.session_state.pop("files_count", 1)
        lenses_to_show = [l for l in selected_lenses if l in results]
        st.subheader(f"Insights — {display_company}")
        render_score_panel(results)
        for i, lens in enumerate(lenses_to_show):
            render_investor_lens_card(lens, results[lens], i)


# ─── Sidebar ──────────────────────────────────────────────────────────────────

def render_sidebar() -> tuple[list[str], str]:
    with st.sidebar:
        st.markdown("## 📈 Além do Ticker")
        st.caption("Análise de empresas além do preço da ação")
        st.session_state["mode"] = "investor"

        st.divider()

        if st.button("✏️ Nova Análise", use_container_width=True):
            st.session_state["page"] = "nova_analise"
            if "loaded_analysis_id" in st.session_state:
                del st.session_state["loaded_analysis_id"]
            st.session_state.pop("ov_confirm_del", None)
            st.session_state.pop("hist_confirm_del", None)
            st.rerun()

        if st.button("📈 Visão Geral", use_container_width=True):
            st.session_state["page"] = "visao_geral"
            st.session_state.pop("ov_confirm_del", None)
            st.session_state.pop("hist_confirm_del", None)
            st.rerun()

        st.divider()

        # ── Lens filter (only on analysis/new pages) ─────────────────────────
        current_page  = st.session_state.get("page", "nova_analise")
        mode          = "investor"
        active_lenses = INVESTOR_LENSES
        active_icons  = INVESTOR_LENS_ICONS
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
        all_analyses = list_analyses(mode)
        if all_analyses:
            st.markdown("**🗂️ Empresas analisadas**")
            for rec in all_analyses:
                company  = rec["company"] or "Empresa"
                period   = rec["period"]
                score    = rec["score"]
                s_color  = score_color(score)
                score_txt = f"{score / 10:.1f}"
                label    = f"{company} · {period}" if period else company
                is_active = st.session_state.get("loaded_analysis_id") == rec["id"]

                btn_style = "background:#eff6ff;border-left:3px solid #6366f1;" if is_active else "background:#f8fafc;"
                st.markdown(
                    f'<div style="{btn_style}border-radius:8px;padding:2px 0;margin-bottom:2px;">',
                    unsafe_allow_html=True,
                )
                col_btn, col_score, col_del = st.sidebar.columns([2.6, 0.7, 0.7])
                with col_btn:
                    if st.button(label, key=f"hist_{rec['id']}", use_container_width=True):
                        st.session_state["page"] = "analise_detalhe"
                        st.session_state["loaded_analysis_id"] = rec["id"]
                        st.rerun()
                with col_score:
                    st.markdown(
                        f'<div style="text-align:right;padding-top:6px;font-size:0.8rem;font-weight:700;color:{s_color};">{score_txt}</div>',
                        unsafe_allow_html=True,
                    )
                with col_del:
                    if st.session_state.get("hist_confirm_del") == rec["id"]:
                        if st.button("✔️", key=f"hist_delok_{rec['id']}", use_container_width=True, help="Confirmar exclusão"):
                            delete_analysis(rec["id"])
                            st.session_state.pop("hist_confirm_del", None)
                            if st.session_state.get("loaded_analysis_id") == rec["id"]:
                                st.session_state.pop("loaded_analysis_id", None)
                                st.session_state["page"] = "nova_analise"
                            st.rerun()
                    else:
                        if st.button("🗑️", key=f"hist_del_{rec['id']}", use_container_width=True, help="Excluir esta análise"):
                            st.session_state["hist_confirm_del"] = rec["id"]
                            st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.caption("Nenhuma análise salva ainda.")

        st.divider()
        st.caption("**Além do Ticker** · Powered by Claude")

    return selected_lenses, mode


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    init_db()

    if "page" not in st.session_state:
        st.session_state["page"] = "nova_analise"
    if "mode" not in st.session_state:
        st.session_state["mode"] = "investor"

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
