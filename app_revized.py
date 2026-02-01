import os
import json
import random
import html
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st


# --- Optional Gemini dependency ---
try:
    import google.generativeai as genai
except Exception:  # pragma: no cover
    genai = None


# =============================
# UI / App config
# =============================
st.set_page_config(
    page_title="Startup Survivor RPG",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)


# =============================
# Constants & Domain
# =============================

MODES = {
    "Normal": {
        "desc": "Dengeli. İyi kararlar ödüllenir, kötü kararlar acıtır.",
        "temp": 0.7,
        "difficulty": 1.0,
        "tone_directives": "Ton: net, gerçekçi, yüksek tempo. Abartı yok.",
    },
    "Hard": {
        "desc": "Daha sert. Yanlış kararlar çarpanlı gelir.",
        "temp": 0.75,
        "difficulty": 1.15,
        "tone_directives": "Ton: gerçekçi ama daha stresli. Risk ve belirsizlik daha yüksek.",
    },
    "Spartan": {
        "desc": "Kaynak kısıtlı. Her seçim trade-off.",
        "temp": 0.75,
        "difficulty": 1.25,
        "tone_directives": "Ton: disiplinli, keskin, 'az kaynakla savaş' hissi.",
    },
    "Extreme": {
        "desc": "Kaos ve absürt. Paylaşmalık olaylar. Sonuç metriklere çarpar.",
        "temp": 0.9,
        "difficulty": 1.35,
        "tone_directives": (
            "Ton: kaotik + kara mizah + viral anlar. "
            "Her ay bir 'internet olayı' veya beklenmedik ters köşe üret.\n"
            "Aylık olay tipleri dağılımı: "
            "%50 platform/influencer/PR krizi, %30 sürreal metafor, %20 easter-egg (kült referans)."
        ),
    },
}


CASES = {
    "Serbest (Rastgele)": {
        "seed": "",
        "desc": "Kendi fikrine göre rastgele olaylar.",
    },
    "Gerçek vaka esinli: Pazar yeri çöküşü": {
        "seed": (
            "Bir marketplace büyüyor ama arz-talep dengesiz. "
            "Kullanıcılar 'kalite düştü' diyor; tedarikçiler komisyonu suçluyor. "
            "Bir yandan regülasyon/risk, bir yandan rakip indirimleri."
        ),
        "desc": "Marketplace: kalite, komisyon, güven, arz-talep, regülasyon.",
    },
    "Gerçek vaka esinli: Viral büyüme → altyapı yangını": {
        "seed": (
            "Ürün bir gecede viral oluyor. Trafik 20x. "
            "Herkes demo istiyor, support patlıyor, altyapı sürünüyor. "
            "PR fırsat mı felaket mi?"
        ),
        "desc": "Viral büyüme, scale sorunu, support/infra yükü.",
    },
    "Gerçek vaka esinli: Kurumsal müşterinin 'Excel'e çevirme' baskısı": {
        "seed": (
            "Kurumsal müşteri 'AI güzel ama bizde süreç Excel' deyip ürünü Excel'e çevirmeye çalışıyor. "
            "17 kolonluk istek listesi, rapor talepleri, scope creep."
        ),
        "desc": "Enterprise, scope creep, rapor/feature baskısı.",
    },
    "Gerçek vaka esinli: Yanlış kitle / yanlış algı": {
        "seed": (
            "Ürün beklenmedik bir kitle tarafından farklı amaçla kullanılmaya başlanıyor. "
            "Bir grup bayılıyor, bir grup 'bu dolandırıcılık' diye bağırıyor. "
            "Mesajın kayıyor, itibar sallanıyor."
        ),
        "desc": "Positioning drift, yanlış beklenti, itibar krizi.",
    },
}


@dataclass
class Metrics:
    cash: int
    mrr: int
    reputation: int
    support_load: int
    infra_load: int
    churn_pct: float

    def clamp(self) -> "Metrics":
        self.cash = max(0, int(self.cash))
        self.mrr = max(0, int(self.mrr))
        self.reputation = int(max(0, min(100, self.reputation)))
        self.support_load = int(max(0, min(100, self.support_load)))
        self.infra_load = int(max(0, min(100, self.infra_load)))
        self.churn_pct = float(max(0.0, min(25.0, self.churn_pct)))
        return self


DEFAULT_EXPENSES = {
    "Salaries": 50_000,
    "Servers": 6_100,
    "Marketing": 5_300,
}


# =============================
# Helpers
# =============================

def pick_api_key() -> Optional[str]:
    """
    Reads Gemini API key from Streamlit secrets or env.
    Supports:
      GEMINI_API_KEY = "..."
      GEMINI_API_KEY = ["key1","key2"]
    """
    key = None

    # Streamlit secrets
    try:
        if hasattr(st, "secrets") and "GEMINI_API_KEY" in st.secrets:
            key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass

    # Env fallback
    if key is None:
        key = os.getenv("GEMINI_API_KEY")

    if isinstance(key, (list, tuple)):
        key = random.choice([str(k).strip() for k in key if str(k).strip()] or [""])
    if isinstance(key, str):
        key = key.strip()
    return key or None


def get_model(mode: str) -> Any:
    if genai is None:
        st.error("google-generativeai paketi yok. requirements.txt'e eklemelisin.")
        st.stop()

    api_key = pick_api_key()
    if not api_key:
        st.error("GEMINI_API_KEY bulunamadı. Streamlit Secrets veya env değişkeni olarak ekle.")
        st.stop()

    genai.configure(api_key=api_key)

    model_name = None
    try:
        if hasattr(st, "secrets") and "GEMINI_MODEL" in st.secrets:
            model_name = st.secrets["GEMINI_MODEL"]
    except Exception:
        pass
    model_name = model_name or os.getenv("GEMINI_MODEL") or "gemini-1.5-flash"

    temp = MODES.get(mode, MODES["Normal"])["temp"]
    system = (
        "Sen bir 'startup kriz RPG' yazarı ve ürün stratejisti gibi davranırsın.\n"
        "Çıktıların Türkçe olacak.\n"
        "Asla çok kısa geçme; somut detay ve bağlam üret.\n"
        "Asla kullanıcıya 'seçersen metrikler şöyle olur' diye spoiler verme (etkiler JSON'da saklı).\n"
    )

    # High token budget to avoid short answers
    gen_cfg = {
        "temperature": temp,
        "top_p": 0.9,
        "top_k": 40,
        # Long-form narrative + richer crises/options.
        "max_output_tokens": 4096,
    }

    try:
        return genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system,
            generation_config=gen_cfg,
        )
    except TypeError:
        # Older SDKs may not support system_instruction
        return genai.GenerativeModel(
            model_name=model_name,
            generation_config=gen_cfg,
        )


def safe_json_loads(text: str) -> Optional[dict]:
    if not text:
        return None
    text = text.strip()

    # Strip code fences if present
    if text.startswith("```"):
        text = text.strip("`")
        # naive: drop first line marker
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        text = "\n".join(lines).strip()

    # Find first {...} block if model wrapped extra
    if not (text.startswith("{") and text.endswith("}")):
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]

    try:
        return json.loads(text)
    except Exception:
        return None


def _word_count(s: str) -> int:
    return len(re.findall(r"\w+", s or ""))


def needs_expansion(month_payload: Dict[str, Any]) -> bool:
    """Heuristic guardrail: Gemini sometimes returns too-short content."""
    try:
        sit = month_payload["situation"]["text"]
        kriz = month_payload["crisis"]["text"]
        a_txt = month_payload["choices"][0]["text"]
        b_txt = month_payload["choices"][1]["text"]
    except Exception:
        return True

    # Word-based thresholds (roughly)
    if _word_count(sit) < 220:
        return True
    if _word_count(kriz) < 190:
        return True
    if _word_count(a_txt) < 120 or _word_count(b_txt) < 120:
        return True
    return False


def expand_payload_with_gemini(model: Any, base_prompt: str, payload: Dict[str, Any], mode: str) -> Dict[str, Any]:
    """Second-pass rewrite to enforce richer narrative if the first pass is too short."""
    try:
        payload_str = json.dumps(payload, ensure_ascii=False)
    except Exception:
        payload_str = str(payload)

    nudge = f"""
UYARI: ÇIKTI ÇOK KISA. Aynı yapıyı koruyarak metinleri GENİŞLET.

- Durum Analizi: en az 280 kelime, 3 paragraf (Ay 1 fikir analizi; Ay 2+ önceki seçimlerin etkisi).
- Kriz: en az 240 kelime, 2-3 paragraf + en sonda 3 madde (riskler / belirsizlik / zaman baskısı).
- Seçenek metinleri: her biri en az 160 kelime, adım adım ama spoiler yok.
- Ham metrik sayıları (kasa/MRR vb.) yazma.
- 'effects' alanlarını DEĞİŞTİRME (aynı kalsın).

ÖNCEKİ JSON:
{payload_str}
"""
    prompt2 = base_prompt + "\n\n" + nudge

    raw2 = model.generate_content(prompt2).text
    data2 = safe_json_loads(raw2)
    if isinstance(data2, dict):
        # Keep effects from original if model messed them up
        try:
            for i in range(2):
                if "effects" in payload["choices"][i]:
                    data2["choices"][i]["effects"] = payload["choices"][i]["effects"]
        except Exception:
            pass
        return data2
    return payload


def clamp_int(x: Any, lo: int, hi: int) -> int:
    try:
        v = int(round(float(x)))
    except Exception:
        v = lo
    return max(lo, min(hi, v))


def clamp_float(x: Any, lo: float, hi: float) -> float:
    try:
        v = float(x)
    except Exception:
        v = lo
    return max(lo, min(hi, v))


def summarize_history(months: Dict[str, Any], max_items: int = 8) -> str:
    """
    Build a compact history string for prompting.
    """
    if not months:
        return "Henüz seçim yapılmadı."

    items = []
    for m in sorted(months.keys(), key=lambda k: int(k)):
        d = months[m]
        pick = d.get("picked")
        note = d.get("free_move") or ""
        outcome = d.get("outcome_summary") or ""
        title = d.get("crisis", {}).get("title", "")
        items.append(
            f"Ay {m}: kriz='{title}'; seçimin={pick or '-'}; not='{note[:90]}'; sonuç='{outcome[:120]}'"
        )

    # last N
    items = items[-max_items:]
    return "\n".join(items)


def build_month_prompt(
    month: int,
    mode: str,
    case_seed: str,
    player_idea: str,
    metrics: Metrics,
    expenses: Dict[str, int],
    history_text: str,
    used_crisis_titles: List[str],
) -> str:
    mode_directives = MODES.get(mode, MODES["Normal"])["tone_directives"]
    used_titles = ", ".join([f"'{t}'" for t in used_crisis_titles[-8:]]) or "Yok"

    # Nonce to reduce repetition
    nonce = random.randint(100000, 999999)

    return f"""
# ROLE
Sen bir startup kriz RPG senaryo yazarı + ürün stratejistisin.

# MODE
Seçilen mod: {mode}
Mod direktifleri:
{mode_directives}

# INPUTS
Ay: {month}
Rastgele nonce: {nonce}

Vaka tohumu (gerçek vaka esinli olabilir):
{case_seed}

Oyuncunun girişim fikri (serbest modda ana kaynak):
{player_idea}

Mevcut metrikler (SENARYODA HAM SAYI YAZMA; sadece arka plan olarak kullan):
- itibar: {metrics.reputation}/100
- support yükü: {metrics.support_load}/100
- altyapı yükü: {metrics.infra_load}/100
- kayıp oranı (churn): {metrics.churn_pct:.1f}%

Aylık gider kalemleri (ham sayı yazma, sadece arka plan):
{json.dumps(expenses, ensure_ascii=False)}

Geçmiş özet (Ay 2+ için kullan):
{history_text}

Daha önce kullanılan kriz başlıkları (BUNLARI TEKRARLAMA):
{used_titles}

# OUTPUT REQUIREMENTS
1) SADECE JSON DÖNDÜR. Ek açıklama, markdown, kod bloğu yok.
2) Durum Analizi uzun ve doyurucu olsun:
   - Ay 1'de fikir/ürün/pazar/pozisyonlama analizi yap (somut, eleştirel, net).
   - Ay 2+ ise önceki seçimlerin etkisini anlat; neler iyi gitti, neresi çatladı, hangi yanlış varsayım patladı.
   - Minimum 260 kelime, hedef 320-420 kelime. 3 paragraf.
3) Kriz net, somut ve yüksek gerilimli olsun:
   - Minimum 220 kelime, hedef 260-360 kelime. 2-3 paragraf.
   - En sonda 3 madde: (1) zaman baskısı (2) yanlış karar riski (3) bir paydaşın (müşteri/influencer/ekip) baskısı.
4) Seçenekler (A ve B):
   - Her seçenek için başlık + metin üret.
   - Metin minimum 160 kelime, hedef 180-240 kelime.
   - Metinde uygulanabilir adımlar olsun ama 'sonuç/metric etkisi' spoiler verme.
5) Durum Analizi ve Kriz metninde ham metrik sayıları (kasa/MRR/gider) ASLA yazma.
6) Tekrar etme: önceki krizlere benzer cümleleri/olayları tekrar kullanma.
7) JSON şema:
{{
  "situation": {{"title": "Durum Analizi", "text": "..."}},
  "crisis": {{"title": "Kriz", "text": "..."}},
  "choices": [
    {{
      "id": "A",
      "title": "...",
      "text": "...",
      "effects": {{
        "cash_delta": int,
        "mrr_delta": int,
        "reputation_delta": int,
        "support_delta": int,
        "infra_delta": int,
        "churn_delta": float
      }}
    }},
    {{
      "id": "B",
      "title": "...",
      "text": "...",
      "effects": {{ ... }}
    }}
  ],
  "tags": ["..."]
}}

# EFFECTS RULES (internal)
- effects alanları MANTIKLI olsun ve mod zorluğuna göre sertleşsin.
- difficulty çarpanı: {MODES.get(mode, MODES['Normal'])['difficulty']}
- cash_delta ve mrr_delta bazen negatif olmalı; her zaman iyi haber yok.
- churn_delta pozitifse kötü (kayıp artar), negatifse iyi (kayıp azalır).
"""


def apply_effects(metrics: Metrics, effects: Dict[str, Any], expenses_total: int) -> Tuple[Metrics, str]:
    """
    Applies one month's economic update:
      cash += mrr - expenses_total + cash_delta
      mrr  += mrr_delta
      other metrics +/- deltas
    """
    cash_delta = int(effects.get("cash_delta", 0) or 0)
    mrr_delta = int(effects.get("mrr_delta", 0) or 0)
    rep_delta = int(effects.get("reputation_delta", 0) or 0)
    sup_delta = int(effects.get("support_delta", 0) or 0)
    inf_delta = int(effects.get("infra_delta", 0) or 0)
    churn_delta = float(effects.get("churn_delta", 0.0) or 0.0)

    # base cashflow
    metrics.cash = metrics.cash + metrics.mrr - expenses_total + cash_delta
    metrics.mrr = metrics.mrr + mrr_delta

    metrics.reputation = metrics.reputation + rep_delta
    metrics.support_load = metrics.support_load + sup_delta
    metrics.infra_load = metrics.infra_load + inf_delta
    metrics.churn_pct = metrics.churn_pct + churn_delta

    metrics.clamp()

    summary = (
        f"Kasa: {metrics.cash:,} ₺ | MRR: {metrics.mrr:,} ₺ | "
        f"İtibar: {metrics.reputation}/100 | "
        f"Support: {metrics.support_load}/100 | "
        f"Altyapı: {metrics.infra_load}/100 | "
        f"Kayıp Oranı: %{metrics.churn_pct:.1f}"
    )
    return metrics, summary


# =============================
# Session state
# =============================

def init_state():
    if "initialized" in st.session_state:
        return

    st.session_state.initialized = True
    st.session_state.started = False
    st.session_state.mode = "Normal"
    st.session_state.case_name = "Serbest (Rastgele)"
    st.session_state.season_months = 12

    st.session_state.player_name = "İsimsiz Girişimci"
    st.session_state.idea = ""

    st.session_state.expenses = DEFAULT_EXPENSES.copy()
    st.session_state.metrics = Metrics(
        cash=1_000_000,
        mrr=0,
        reputation=50,
        support_load=20,
        infra_load=20,
        churn_pct=5.0,
    )

    # Month payloads: { "1": {...}, "2": {...} }
    st.session_state.months: Dict[str, Any] = {}

    # Chat messages: list[ {id, role, content} ]
    st.session_state.chat: List[Dict[str, str]] = []

    st.session_state.current_month = 1


def reset_game(keep_settings: bool = True):
    mode = st.session_state.get("mode", "Normal")
    case_name = st.session_state.get("case_name", "Serbest (Rastgele)")
    season = st.session_state.get("season_months", 12)
    player_name = st.session_state.get("player_name", "İsimsiz Girişimci")

    init_state()
    st.session_state.started = False
    st.session_state.idea = ""
    st.session_state.months = {}
    st.session_state.chat = []
    st.session_state.current_month = 1
    st.session_state.metrics = Metrics(
        cash=int(st.session_state.metrics.cash),
        mrr=0,
        reputation=50,
        support_load=20,
        infra_load=20,
        churn_pct=5.0,
    )

    if keep_settings:
        st.session_state.mode = mode
        st.session_state.case_name = case_name
        st.session_state.season_months = season
        st.session_state.player_name = player_name


def add_chat_message(msg_id: str, role: str, content: str):
    """
    Avoid duplicates on rerun: msg_id should be stable (month-kind).
    """
    for m in st.session_state.chat:
        if m.get("id") == msg_id:
            return
    st.session_state.chat.append({"id": msg_id, "role": role, "content": content})


# =============================
# Rendering helpers
# =============================

def inject_css():
    st.markdown(
        """
<style>
/* Dark-ish theme polish */
.block-container { padding-top: 1.2rem; }
div[data-testid="stSidebar"] .stSelectbox label, 
div[data-testid="stSidebar"] .stSlider label,
div[data-testid="stSidebar"] .stTextInput label,
div[data-testid="stSidebar"] .stTextArea label { font-weight: 600; }

.choice-wrap { margin-top: 0.75rem; }
.choice-card {
  border: 1px solid rgba(255,255,255,0.10);
  border-radius: 14px;
  padding: 18px 18px 14px 18px;
  background: rgba(255,255,255,0.02);
}
.choice-title {
  font-size: 1.35rem;
  font-weight: 800;
  margin-bottom: 10px;
}
.choice-body {
  font-size: 0.98rem;
  line-height: 1.45;
  opacity: 0.95;
  min-height: 150px;
}

.choice-btn-row .stButton button {
  width: 100%;
  border-radius: 12px;
  padding: 10px 14px;
}

.small-note { opacity: 0.75; font-size: 0.9rem; }

</style>
""",
        unsafe_allow_html=True,
    )


def render_sidebar():
    with st.sidebar:
        st.title(st.session_state.player_name)

        # Mode first (requested: mod above "calendar/season")
        mode = st.selectbox(
            "Mod",
            list(MODES.keys()),
            index=list(MODES.keys()).index(st.session_state.mode),
            help="Mod senaryonun tonu ve zorluğunu değiştirir.",
        )
        st.session_state.mode = mode
        st.caption(MODES[mode]["desc"])

        case_name = st.selectbox(
            "Vaka sezonu (opsiyonel)",
            list(CASES.keys()),
            index=list(CASES.keys()).index(st.session_state.case_name),
            help="Gerçek hayattan esinli bir başlangıç tohumu seçebilirsin.",
        )
        st.session_state.case_name = case_name
        st.caption(CASES[case_name]["desc"])

        season_months = st.slider(
            "Sezon uzunluğu (ay)",
            min_value=3,
            max_value=24,
            value=int(st.session_state.season_months),
        )
        st.session_state.season_months = int(season_months)

        st.write(f"Ay: {st.session_state.current_month}/{st.session_state.season_months}")
        st.progress(min(1.0, st.session_state.current_month / max(1, st.session_state.season_months)))

        start_cash = st.slider(
            "Başlangıç kasası",
            min_value=50_000,
            max_value=2_000_000,
            step=10_000,
            value=int(st.session_state.metrics.cash) if not st.session_state.started else int(st.session_state.metrics.cash),
            disabled=st.session_state.started,
        )
        if not st.session_state.started:
            st.session_state.metrics.cash = int(start_cash)

        # Financial status
        st.subheader("Finansal Durum")
        st.metric("Kasa", f"{st.session_state.metrics.cash:,} ₺")
        st.metric("MRR", f"{st.session_state.metrics.mrr:,} ₺")

        with st.expander("Aylık Gider Detayı", expanded=False):
            st.markdown(
                "\n".join(
                    [
                        f"- Maaşlar: {DEFAULT_EXPENSES['Salaries']:,} ₺",
                        f"- Sunucu: {DEFAULT_EXPENSES['Servers']:,} ₺",
                        f"- Pazarlama: {DEFAULT_EXPENSES['Marketing']:,} ₺",
                        f"**TOPLAM:** {sum(DEFAULT_EXPENSES.values()):,} ₺",
                    ]
                )
            )

        st.divider()
        st.write(f"İtibar: {st.session_state.metrics.reputation}/100")
        st.write(f"Support yükü: {st.session_state.metrics.support_load}/100")
        st.write(f"Altyapı yükü: {st.session_state.metrics.infra_load}/100")
        st.write(f"Kayıp Oranı: %{st.session_state.metrics.churn_pct:.1f}")

        st.divider()
        if st.button("Oyunu sıfırla", use_container_width=True):
            reset_game(keep_settings=True)
            st.rerun()


def render_header():
    # Character customize on top-right-ish
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("# Startup Survivor RPG")
        st.caption("Sohbet akışı korunur. Ay 1'den başlar. Durum Analizi → Kriz → A/B seçimi.")
    with c2:
        with st.expander("🛠️ Karakterini ve ayarlarını özelleştir (Tıkla)", expanded=False):
            player_name = st.text_input("Karakter adı", value=st.session_state.player_name, max_chars=32)
            if player_name.strip():
                st.session_state.player_name = player_name.strip()
            st.caption("Not: Oyuna başladıktan sonra adı değiştirebilirsin.")


def render_chat():
    # Render chat in order
    for msg in st.session_state.chat:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])


# =============================
# Game logic
# =============================

def get_case_seed(case_name: str, idea: str) -> str:
    seed = CASES.get(case_name, CASES["Serbest (Rastgele)"]).get("seed", "")
    if case_name == "Serbest (Rastgele)":
        return ""
    # If user also has an idea, we can blend it lightly
    if idea.strip():
        return seed + "\n\nOyuncunun fikri (vaka içine harmanla):\n" + idea.strip()
    return seed


def ensure_month_generated(month: int):
    """
    Generate month content once, store it. Also append chat messages once.
    """
    if str(month) in st.session_state.months:
        # Already generated; ensure messages exist (dedupe makes it safe)
        payload = st.session_state.months[str(month)]
        add_chat_message(f"{month}-situation", "assistant", f"🧠 **{payload['situation']['title']} (Ay {month})**\n\n{payload['situation']['text']}")
        add_chat_message(f"{month}-crisis", "assistant", f"⚠️ **{payload['crisis']['title']}**\n\n{payload['crisis']['text']}")
        return

    mode = st.session_state.mode
    idea = st.session_state.idea.strip()
    case_seed = get_case_seed(st.session_state.case_name, idea)
    history = summarize_history(st.session_state.months)
    used_titles = [st.session_state.months[k]["crisis"]["title"] for k in sorted(st.session_state.months.keys(), key=lambda x: int(x))]

    expenses_total = sum(st.session_state.expenses.values())

    prompt = build_month_prompt(
        month=month,
        mode=mode,
        case_seed=case_seed,
        player_idea=idea,
        metrics=st.session_state.metrics,
        expenses=st.session_state.expenses,
        history_text=history,
        used_crisis_titles=used_titles,
    )

    model = get_model(mode)
    raw = model.generate_content(prompt).text
    data = safe_json_loads(raw)
    if not isinstance(data, dict):
        st.error("Model JSON döndüremedi. Lütfen tekrar dene.")
        st.stop()

    # Normalize fields
    data.setdefault("situation", {"title": "Durum Analizi", "text": ""})
    data.setdefault("crisis", {"title": "Kriz", "text": ""})
    data.setdefault("choices", [])

    if not isinstance(data["choices"], list) or len(data["choices"]) < 2:
        st.error("Model seçim üretemedi. Lütfen tekrar dene.")
        st.stop()

    # Keep only first two choices
    data["choices"] = data["choices"][:2]

    # Ensure choice IDs A/B
    data["choices"][0]["id"] = "A"
    data["choices"][1]["id"] = "B"

    # Ensure effects exist
    for ch in data["choices"]:
        ch.setdefault("title", "")
        ch.setdefault("text", "")
        if not isinstance(ch.get("effects"), dict):
            ch["effects"] = {}

    # Guardrail: Gemini sometimes produces too-short content even with a big token budget.
    # We'll do a lightweight second pass to expand Situation/Crisis/Choices text.
    if needs_expansion(data):
        try:
            model2 = get_model(mode)
            data = expand_payload_with_gemini(model2, prompt, data, mode)
            # Re-apply IDs/effects constraints
            data.setdefault("situation", {"title": "Durum Analizi", "text": ""})
            data.setdefault("crisis", {"title": "Kriz", "text": ""})
            if isinstance(data.get("choices"), list) and len(data["choices"]) >= 2:
                data["choices"] = data["choices"][:2]
                data["choices"][0]["id"] = "A"
                data["choices"][1]["id"] = "B"
                for i in range(2):
                    if not isinstance(data["choices"][i].get("effects"), dict):
                        data["choices"][i]["effects"] = {}
        except Exception:
            pass

    # Normalize effect types/clamps gently
    diff = MODES.get(mode, MODES["Normal"])["difficulty"]
    for ch in data["choices"]:
        eff = ch.get("effects", {})
        ch["effects"] = {
            "cash_delta": clamp_int(eff.get("cash_delta", 0), -250_000, 250_000),
            "mrr_delta": clamp_int(eff.get("mrr_delta", 0), -30_000, 30_000),
            "reputation_delta": clamp_int(eff.get("reputation_delta", 0), -25, 25),
            "support_delta": clamp_int(eff.get("support_delta", 0), -25, 25),
            "infra_delta": clamp_int(eff.get("infra_delta", 0), -25, 25),
            "churn_delta": clamp_float(eff.get("churn_delta", 0.0), -6.0, 6.0),
        }

        # Apply difficulty scaling to negative consequences slightly
        # (Harder modes should punish more; reward slightly less)
        if diff > 1.0:
            ch["effects"]["cash_delta"] = int(round(ch["effects"]["cash_delta"] * (1.0 if ch["effects"]["cash_delta"] < 0 else 0.92)))
            ch["effects"]["mrr_delta"] = int(round(ch["effects"]["mrr_delta"] * (1.0 if ch["effects"]["mrr_delta"] < 0 else 0.92)))
            ch["effects"]["reputation_delta"] = int(round(ch["effects"]["reputation_delta"] * (1.0 if ch["effects"]["reputation_delta"] < 0 else 0.95)))
            ch["effects"]["support_delta"] = int(round(ch["effects"]["support_delta"] * (1.0 if ch["effects"]["support_delta"] > 0 else 0.95)))
            ch["effects"]["infra_delta"] = int(round(ch["effects"]["infra_delta"] * (1.0 if ch["effects"]["infra_delta"] > 0 else 0.95)))
            ch["effects"]["churn_delta"] = float(ch["effects"]["churn_delta"] * (1.0 if ch["effects"]["churn_delta"] > 0 else 0.95))

    data["unique_key"] = f"{month}-{random.randint(1000,9999)}"
    data["picked"] = None
    data["free_move"] = ""
    data["outcome_summary"] = ""
    data["expenses_total"] = expenses_total

    st.session_state.months[str(month)] = data

    # Append chat messages once (dedupe-protected)
    add_chat_message(
        f"{month}-situation",
        "assistant",
        f"🧠 **{data['situation']['title']} (Ay {month})**\n\n{data['situation']['text']}",
    )
    add_chat_message(
        f"{month}-crisis",
        "assistant",
        f"⚠️ **{data['crisis']['title']}**\n\n{data['crisis']['text']}",
    )


def apply_choice(month: int, picked: str, free_move: str = ""):
    data = st.session_state.months[str(month)]
    if data.get("picked") is not None:
        return  # already applied

    picked = picked.upper().strip()
    if picked not in ("A", "B"):
        return

    data["picked"] = picked
    data["free_move"] = (free_move or "").strip()

    # Apply effects
    idx = 0 if picked == "A" else 1
    effects = data["choices"][idx]["effects"]
    metrics, summary = apply_effects(st.session_state.metrics, effects, data["expenses_total"])
    st.session_state.metrics = metrics
    data["outcome_summary"] = summary
    st.session_state.months[str(month)] = data

    # Chat: user pick
    user_line = f"Seçtim: **{picked}** — {data['choices'][idx]['title']}"
    if data["free_move"]:
        user_line += f"\n\n_Not:_ {data['free_move']}"
    add_chat_message(f"{month}-pick", "user", user_line)

    # Chat: outcome
    add_chat_message(
        f"{month}-outcome",
        "assistant",
        f"✅ **Seçimin işlendi.**\n\n{summary}",
    )

    # Move to next month
    st.session_state.current_month = min(st.session_state.current_month + 1, st.session_state.season_months)


# =============================
# Main
# =============================

def main():
    init_state()
    inject_css()
    render_sidebar()
    render_header()

    # Idea input / start
    if not st.session_state.started:
        st.markdown("---")
        st.info("Oyuna başlamak için girişim fikrini yaz.")
        idea = st.text_area("Girişim fikrin ne?", value=st.session_state.idea, height=120)
        st.session_state.idea = idea

        colA, colB = st.columns([1, 3])
        with colA:
            if st.button("🚀 Oyunu Başlat", use_container_width=True):
                if not st.session_state.idea.strip() and st.session_state.case_name == "Serbest (Rastgele)":
                    st.warning("Serbest modda başlamak için girişim fikrini yazmalısın.")
                else:
                    st.session_state.started = True
                    # Initial assistant intro
                    add_chat_message(
                        "intro-1",
                        "assistant",
                        f"Tamam **{st.session_state.player_name}**. Ay 1'den başlıyoruz. Mod: **{st.session_state.mode}**.",
                    )
                    add_chat_message(
                        "intro-2",
                        "assistant",
                        "Önce Durum Analizi gelecek, sonra Kriz, sonra A/B seçeceksin.",
                    )
                    st.rerun()

        st.stop()

    st.markdown("---")

    # Generate current month if needed
    month = st.session_state.current_month
    ensure_month_generated(month)

    # Render chat
    render_chat()

    # Render choices for the current month (if not yet picked)
    data = st.session_state.months[str(month)]
    if data.get("picked") is None:
        st.markdown("")
        st.markdown("👉 **Şimdi seçim zamanı. A mı B mi?** (İstersen serbest hamleni de yazabilirsin.)")

        free_move = st.text_input(
            "İstersen kısa bir not yaz (opsiyonel). Seçim yine A/B ile ilerler.",
            value="",
            max_chars=240,
        )

        choices = data["choices"]
        st.markdown("<div class='choice-wrap'>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        for col, ch in zip([c1, c2], choices):
            with col:
                body_html = html.escape(ch.get("text", "")).replace("\n", "<br>")
                st.markdown(
                    f"<div class='choice-card'><div class='choice-title'>{html.escape(ch.get('id',''))}) {html.escape(ch.get('title',''))}</div>"
                    f"<div class='choice-body'>{body_html}</div></div>",
                    unsafe_allow_html=True,
                )

        st.markdown("</div>", unsafe_allow_html=True)

        b1, b2 = st.columns(2)
        with b1:
            if st.button("A seç", use_container_width=True, key=f"pickA-{month}"):
                apply_choice(month, "A", free_move=free_move)
                st.rerun()
        with b2:
            if st.button("B seç", use_container_width=True, key=f"pickB-{month}"):
                apply_choice(month, "B", free_move=free_move)
                st.rerun()

    else:
        st.caption("Bu ayın seçimi işlendi. Devam etmek için sonraki ay üretilecek.")


if __name__ == "__main__":
    main()
