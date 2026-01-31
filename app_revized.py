# app.py
# Startup Survivor RPG — Streamlit single-file app
# Fixes:
# - No duplicate "same crisis/analysis" logs (proper state locks)
# - Real chat flow with persistent chat history
# - Mode behaviors: Realist, Hard, Spartan, Extreme, Turkey (no "dayı factor")
# - Character customization restored
#
# Secrets: Prefer
#   GEMINI_API_KEY="AIza..."
# (If you set it as a list GEMINI_API_KEY=[...], we will take the first item.)

from __future__ import annotations

import os
import json
import random
import textwrap
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

# Optional Gemini import (works if installed on Streamlit Cloud)
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except Exception:
    GEMINI_AVAILABLE = False


# -----------------------------
# Styling
# -----------------------------
st.set_page_config(page_title="Startup Survivor RPG", layout="wide")

APP_TITLE = "Startup Survivor RPG"
APP_SUB = "Sohbet akışı korunur. Ay 1'den başlar. Durum Analizi → Kriz → A/B seçimi."

# -----------------------------
# Helpers
# -----------------------------
def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def fmt_try(n: float) -> str:
    # Turkish number formatting-ish
    n_int = int(round(n))
    s = f"{n_int:,}".replace(",", ".")
    return f"{s} ₺"

def safe_get_secret_key() -> Optional[str]:
    key = None
    # 1) streamlit secrets
    try:
        if "GEMINI_API_KEY" in st.secrets:
            key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        key = None
    # 2) env
    if not key:
        key = os.getenv("GEMINI_API_KEY")

    # If user stored it as list in secrets TOML:
    # GEMINI_API_KEY=["k1","k2"]
    if isinstance(key, (list, tuple)):
        if len(key) > 0:
            key = key[0]
        else:
            key = None

    if isinstance(key, str):
        key = key.strip().strip('"').strip("'")
        if key == "":
            return None
    return key

def model_ready() -> Tuple[bool, str]:
    key = safe_get_secret_key()
    if not key:
        return (False, "GEMINI_API_KEY bulunamadı. Secrets/env eklemeden model çağrıları çalışmaz.")
    if not GEMINI_AVAILABLE:
        return (False, "google-generativeai paketi yok gibi görünüyor. (Streamlit Cloud'da genelde var.)")
    return (True, "Gemini anahtarı görüldü. Model çağrıları çalışmalı.")

def init_gemini() -> Optional[Any]:
    ok, _ = model_ready()
    if not ok:
        return None
    key = safe_get_secret_key()
    try:
        genai.configure(api_key=key)
        # You can change model if you want
        return genai.GenerativeModel("gemini-1.5-flash")
    except Exception:
        return None

def llm_generate(prompt: str, temperature: float = 0.9) -> str:
    """
    Uses Gemini if available; otherwise returns a deterministic-ish placeholder.
    """
    model = st.session_state.get("gemini_model")
    if model is None:
        # Offline fallback: still keep gameplay functional.
        # (You can remove this if you want hard-fail without API.)
        seed = st.session_state.get("rng_seed", 42)
        r = random.Random(seed + st.session_state.get("month", 1) * 997)
        lines = [
            "Model yok: Yerel anlatıcı devrede.",
            "Bu tur, sistem test modunda ilerliyor.",
            f"Prompt özeti: {prompt[:120].replace(chr(10),' ')}...",
            f"Şans faktörü: {r.randint(1, 100)}/100",
        ]
        return "\n".join(lines)

    try:
        # generation_config varies by version; keep it simple:
        resp = model.generate_content(
            prompt,
            generation_config={"temperature": temperature, "max_output_tokens": 600},
        )
        txt = getattr(resp, "text", None)
        if not txt:
            return "Model cevap vermedi (boş çıktı)."
        return txt.strip()
    except Exception as e:
        return f"Model çağrısı hata verdi: {e}"


# -----------------------------
# Game Data
# -----------------------------
MODES = ["Realist", "Hard", "Spartan", "Extreme", "Türkiye"]

@dataclass
class Character:
    name: str = "İsimsiz Girişimci"
    archetype: str = "Genel"
    tone: str = "Sert"
    risk_appetite: str = "Dengeli"

@dataclass
class Metrics:
    cash: float = 1_000_000
    mrr: float = 0
    churn: float = 0.05  # 0-1
    reputation: float = 50  # 0-100
    support_load: float = 20  # 0-100
    infra_load: float = 20  # 0-100
    monthly_salary: float = 50_000
    monthly_server: float = 6_100
    monthly_marketing: float = 5_300

    @property
    def burn(self) -> float:
        return self.monthly_salary + self.monthly_server + self.monthly_marketing

@dataclass
class TurnContent:
    month: int
    situation: str
    crisis: str
    option_a_title: str
    option_a_body: str
    option_b_title: str
    option_b_body: str
    # for Extreme: keep which event used
    event_id: Optional[str] = None


# -----------------------------
# Extreme event pool (shareable, meme-able)
# -----------------------------
# Tip: These should be "absurd but metric-linked". We'll also let LLM remix them.
EXTREME_EVENTS = [
    {
        "id": "excel-cult",
        "hook": "Kurumsal müşteri ürünü Excel’e çevirmeye çalışıyor: 'AI güzel ama bizde süreç Excel'.",
        "impact": "scope patlar, support yükselir, itibar 'enterprise-ready' beklentisine kilitlenir.",
    },
    {
        "id": "influencer-wrong-feature",
        "hook": "Influencer ürünü övüyor ama yanlış özelliği övüyor: trafik geldi, kafa da geldi.",
        "impact": "churn artar; doğru vaadi söylemezsen MRR büyümesi 'yanlış kullanıcı' ile zehirlenir.",
    },
    {
        "id": "twitter-misread",
        "hook": "X (Twitter) seni yanlış anlıyor: ürünün adı 'dolandırıcılık thread’i'ne düşüyor.",
        "impact": "itibar düşer, support patlar, ama doğru karşı hamleyle viral toparlanma şansı doğar.",
    },
    {
        "id": "appstore-review-poetry",
        "hook": "App Store’da 1 yıldız: 'Uygulama beni duygulandırdı' — nedenini kimse bilmiyor.",
        "impact": "itibar dalgalanır; belirsizlik churn’ü artırır ama anlatıyı çevirirsen MRR sıçrayabilir.",
    },
    {
        "id": "payment-meme",
        "hook": "Ödeme sayfası meme oldu: 'Kredi kartım bile vazgeçti' diye paylaşım dönüyor.",
        "impact": "conversion düşer, support yükselir; düzeltirsen bir anda MRR toparlar.",
    },
    {
        "id": "kedi-filter-ddos",
        "hook": "Kedi filtresi trendi: kullanıcılar ekranı kediye çevirip senin OCR’ı kırıyor, aynı anda DDOS gibi.",
        "impact": "infra load tavan, support 'kedi dili' ticket’ı, itibar komediye döner.",
    },
    {
        "id": "corporate-legal-moment",
        "hook": "Kurumsal hukuk, 'AI kelimesini 14 kez yazmışsınız' diye 17 sayfa düzeltme ister.",
        "impact": "satış döngüsü uzar; cash burn sürer; ama doğru paketle MRR büyük gelebilir.",
    },
    {
        "id": "viral-wrong-country",
        "hook": "Viral oldun ama yanlış ülkede: trafik Peru’dan, ödeme Türkiye IBAN istiyor.",
        "impact": "support yükü + ödeme hataları; churn yükselir; doğru lokalizasyonla MRR artabilir.",
    },
    {
        "id": "founder-hot-take",
        "hook": "Senin eski bir tweet’in gündem: 'Onboarding gereksiz' demişsin; onboarding’in şu an 6 adım.",
        "impact": "itibar sarsılır; ürün ekibi birbirine girer; yalınlaştırırsan kazanırsın.",
    },
    {
        "id": "b2b-procurement-portal",
        "hook": "Procurement portalı: müşteri seni 9 farklı portala davet ediyor; her portal şifre istiyor.",
        "impact": "time sink + churn riski; ama kapatırsan büyük MRR gelebilir.",
    },
]

# For non-extreme modes, we still want variety, but less absurd.
REALIST_CRISIS_THEMES = [
    "onboarding sürtünmesi", "netlik/vaat belirsizliği", "pricing kararsızlığı",
    "performans/altyapı darboğazı", "support yükü", "kanal verimsizliği", "churn artışı",
]
TURKEY_THEMES = [
    "kur sıçraması ve SaaS maliyeti", "tahsilat gecikmesi (30-60 gün)",
    "KDV/stopaj sürprizi", "e-fatura/e-arşiv zorunluluğu", "platform komisyonu artışı",
    "asgari ücret/yan hak baskısı", "pazarlama CPM zıplaması", "kurumsal 'fatura kesemezsen olmaz' şartı",
]


# -----------------------------
# Prompts
# -----------------------------
def mode_instructions(mode: str) -> str:
    if mode == "Realist":
        return (
            "Gerçekçi, dengeli ve profesyonel bir simülasyon anlatıcısısın. "
            "Mantıklı kararları ödüllendir, piyasa koşullarını gerçek dünyaya yakın kur. "
            "Abartma; net trade-off ver."
        )
    if mode == "Hard":
        return (
            "Zorlayıcı bir finansal denetçi gibisin. "
            "Her seçenek bedel içersin; kolay çıkış yok. "
            "Küçük hataları bile maliyetlendir; ama adil ol."
        )
    if mode == "Spartan":
        return (
            "Acımasız ayı piyasası gibi davran. "
            "Hukuki/teknik/finansal engelleri artır, şans faktörünü azalt. "
            "Hayatta kalma testi; seçenekler sert ve riskli olsun."
        )
    if mode == "Extreme":
        return (
            "Kaos teorisi anlatıcısısın. Mantık ikinci planda; paylaşmalık absürtlük üret. "
            "Absürt olayların %80'i sosyal medya/platform/influencer/kurumsal saçmalık/kullanıcı davranışı kaynaklı olsun. "
            "%15'i sürreal ama metaforik (abartılmış gerçek). %5'i nadir sci-fi cameo (çok nadir). "
            "Kural: Ne kadar saçma olursa olsun sonuç startup metriklerine bağlanacak (kasa, churn, MRR, itibar, support, altyapı). "
            "Kriz ve durum analizi özgün, komik, ekran görüntüsü aldıracak kadar iyi olsun."
        )
    if mode == "Türkiye":
        return (
            "Türkiye pazarına benzeyen dengeli bir anlatıcı ol. "
            "Kur/enflasyon, tahsilat gecikmesi, KDV/stopaj, e-fatura, platform komisyonu, kurumsal fatura şartı gibi gerçek dinamikleri kat. "
            "Ama 'dayı faktörü' gibi karikatürleştirme yok; gerçekçi, günlük hayat gibi."
        )
    return "Dengeli bir simülasyon anlatıcısısın."

def build_turn_prompt(
    idea: str,
    character: Character,
    metrics: Metrics,
    mode: str,
    month: int,
    season_len: int,
    extra_hook: Optional[str] = None,
) -> str:
    # We want: Situation Analysis (story-like), Crisis (detailed), A/B short paragraph each (not too short/too long)
    # Output must be JSON so we can parse safely.
    hook_line = f"\nEK HOOK: {extra_hook}\n" if extra_hook else ""

    return f"""
Sen bir metin tabanlı girişim RPG oyun motorusun.
{mode_instructions(mode)}

OYUNCU:
- Karakter adı: {character.name}
- Arketip: {character.archetype}
- Ton: {character.tone}
- Risk: {character.risk_appetite}

GİRİŞİM FİKRİ (oyuncunun yazdığı):
{idea}

MEVCUT METRİKLER:
- Ay: {month}/{season_len}
- Kasa: {metrics.cash:.0f}
- MRR: {metrics.mrr:.0f}
- Churn: {metrics.churn:.3f}
- İtibar(0-100): {metrics.reputation:.1f}
- Support yükü(0-100): {metrics.support_load:.1f}
- Altyapı yükü(0-100): {metrics.infra_load:.1f}
- Aylık gider: {metrics.burn:.0f}

{hook_line}

ÇIKTIYI SADECE JSON OLARAK VER (markdown yok, açıklama yok).
JSON ŞEMASI:
{{
  "situation": "DURUM ANALİZİ: 1 paragraf ama dolu dolu; hikayesel, sahne gibi; fikri yorumlasın.",
  "crisis": "KRİZ: 2-4 cümle; detaylı; bu ayın somut krizi + metriklere bağ (kasa yanması, churn, support, altyapı, itibar).",
  "option_a_title": "A şıkkı kısa ama vurucu başlık",
  "option_a_body": "A: Tek paragraf. Ne yapacaksın? Krizi nasıl çözebilir? Trade-off'u ne? Çok uzun olmasın.",
  "option_b_title": "B şıkkı kısa ama vurucu başlık",
  "option_b_body": "B: Tek paragraf. Ne yapacaksın? Krizi nasıl çözebilir? Trade-off'u ne? Çok uzun olmasın."
}}

KURALLAR:
- DURUM ANALİZİ ile KRİZ birbirinin kopyası olmasın. Durum analizi 'sahne' gibi, kriz 'somut problem' gibi.
- Extreme modda komiklik ve absürtlük yüksek olmalı (ama metriklere bağlanmalı).
- Realist/Hard/Spartan/Türkiye modlarında ton mode uygun olmalı.
""".strip()

def parse_json_safely(txt: str) -> Optional[Dict[str, Any]]:
    # Try to extract JSON from model response (in case it added text)
    txt = txt.strip()
    # Find first "{" and last "}"
    if "{" in txt and "}" in txt:
        start = txt.find("{")
        end = txt.rfind("}")
        candidate = txt[start:end+1]
        try:
            return json.loads(candidate)
        except Exception:
            return None
    return None


# -----------------------------
# Turn generation and state locks
# -----------------------------
def ensure_state():
    if "initialized" not in st.session_state:
        st.session_state.initialized = True
        st.session_state.character = asdict(Character())
        st.session_state.mode = "Extreme"
        st.session_state.season_len = 12
        st.session_state.metrics = asdict(Metrics())
        st.session_state.idea = ""
        st.session_state.game_started = False
        st.session_state.month = 1

        # Chat history
        st.session_state.chat = []  # list of dicts: {role, content}

        # Current pending turn content (generated but not yet resolved by A/B)
        st.session_state.pending_turn = None  # dict TurnContent

        # Locks to prevent duplicates:
        st.session_state.generated_months = set()  # months already generated+posted to chat
        st.session_state.resolved_months = set()   # months already resolved (A/B applied)

        # RNG + used events
        st.session_state.rng_seed = random.randint(1, 10_000_000)
        st.session_state.used_extreme_events = []

        # Gemini model handle
        st.session_state.gemini_model = init_gemini()

def chat_add(role: str, content: str):
    st.session_state.chat.append({"role": role, "content": content})

def render_chat():
    for msg in st.session_state.chat:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

def pick_extreme_event() -> Dict[str, str]:
    used = st.session_state.used_extreme_events
    # Choose without repeating until pool exhausted
    remaining = [e for e in EXTREME_EVENTS if e["id"] not in used]
    if not remaining:
        used.clear()
        remaining = EXTREME_EVENTS[:]
    r = random.Random(st.session_state.rng_seed + st.session_state.month * 1337)
    ev = r.choice(remaining)
    used.append(ev["id"])
    return ev

def pick_theme(mode: str) -> str:
    r = random.Random(st.session_state.rng_seed + st.session_state.month * 911)
    if mode == "Türkiye":
        return r.choice(TURKEY_THEMES)
    return r.choice(REALIST_CRISIS_THEMES)

def generate_turn_if_needed():
    """
    Generates a new turn for the current month exactly once, stores it in pending_turn,
    and writes situation+crisis to chat exactly once.
    """
    if not st.session_state.game_started:
        return

    month = st.session_state.month
    # If already resolved, do nothing
    if month in st.session_state.resolved_months:
        return

    # If pending already for this month, do nothing
    pending = st.session_state.pending_turn
    if pending and pending.get("month") == month:
        return

    # If we already generated+posted for this month, restore pending from cache if exists
    # (Simpler: regenerate pending from stored object is not available; so we store pending in session state.)
    # Our primary lock is "pending_turn", so if it's None we can generate.
    mode = st.session_state.mode
    idea = st.session_state.idea
    char = Character(**st.session_state.character)
    metrics = Metrics(**st.session_state.metrics)

    extra_hook = None
    event_id = None
    if mode == "Extreme":
        ev = pick_extreme_event()
        extra_hook = f"EXTREME OLAY: {ev['hook']} Etki: {ev['impact']}"
        event_id = ev["id"]
    else:
        # Give model a theme hint for variety
        extra_hook = f"TEMA: {pick_theme(mode)}"

    prompt = build_turn_prompt(
        idea=idea,
        character=char,
        metrics=metrics,
        mode=mode,
        month=month,
        season_len=st.session_state.season_len,
        extra_hook=extra_hook,
    )

    raw = llm_generate(prompt, temperature=0.95 if mode == "Extreme" else 0.8)
    data = parse_json_safely(raw)

    if not data:
        # Fallback minimal content
        data = {
            "situation": f"DURUM ANALİZİ: Ay {month}. Bir şeyler ters gidiyor ama henüz adını koymadın.",
            "crisis": f"KRİZ: Bu ay belirsizlik büyüdü. Kasa yanıyor, churn tırmanabilir.",
            "option_a_title": "A Planı",
            "option_a_body": "A: Net bir hamle yap. Tek bir hedef seç ve oraya yüklen.",
            "option_b_title": "B Planı",
            "option_b_body": "B: Hasarı azalt. Önce stabiliteyi artır, sonra büyümeyi dene.",
        }

    turn = TurnContent(
        month=month,
        situation=str(data.get("situation", "")).strip(),
        crisis=str(data.get("crisis", "")).strip(),
        option_a_title=str(data.get("option_a_title", "A Planı")).strip(),
        option_a_body=str(data.get("option_a_body", "")).strip(),
        option_b_title=str(data.get("option_b_title", "B Planı")).strip(),
        option_b_body=str(data.get("option_b_body", "")).strip(),
        event_id=event_id,
    )
    st.session_state.pending_turn = asdict(turn)

    # Post to chat once per month (prevents duplicates)
    if month not in st.session_state.generated_months:
        chat_add("assistant", f"🧠 **DURUM ANALİZİ (Ay {month})**\n\n{turn.situation}")
        chat_add("assistant", f"⚠️ **KRİZ**\n\n{turn.crisis}")
        st.session_state.generated_months.add(month)

def apply_choice(choice: str):
    """
    Apply A/B choice to metrics with mode flavor.
    Keep it deterministic-ish but varied.
    """
    pending = st.session_state.pending_turn
    if not pending:
        return
    month = pending["month"]
    if month in st.session_state.resolved_months:
        return

    mode = st.session_state.mode
    metrics = Metrics(**st.session_state.metrics)

    # Base deltas
    r = random.Random(st.session_state.rng_seed + month * (777 if choice == "A" else 778))
    # make effect scales by mode
    if mode == "Realist":
        scale = 1.0
        volatility = 0.6
    elif mode == "Hard":
        scale = 1.1
        volatility = 0.9
    elif mode == "Spartan":
        scale = 1.2
        volatility = 1.1
    elif mode == "Türkiye":
        scale = 1.05
        volatility = 0.95
    else:  # Extreme
        scale = 1.0
        volatility = 1.35

    # Choice style: A tends to be bold, B tends to be defensive (but in Extreme, both can be chaotic)
    bold = 1.0 if choice == "A" else 0.7
    defend = 0.7 if choice == "A" else 1.0

    # Compute deltas
    # MRR can go up or down; churn inversely; support/infra can spike in Extreme
    mrr_delta = (r.uniform(-0.02, 0.12) * metrics.mrr + r.uniform(80, 1200) * bold) * scale
    churn_delta = (r.uniform(-0.02, 0.03) * volatility) * (1.0 if defend > 0.9 else 1.2)
    rep_delta = r.uniform(-6, 9) * (defend * 0.9 + 0.2) * scale
    support_delta = r.uniform(-8, 18) * volatility * (1.0 if choice == "A" else 0.7)
    infra_delta = r.uniform(-6, 16) * volatility * (1.0 if choice == "A" else 0.75)

    # Mode-specific twists
    if mode == "Türkiye":
        # FX/inflation bite (server + salaries creep)
        fx_hit = r.uniform(0.03, 0.11)
        metrics.monthly_server *= (1.0 + fx_hit)
        metrics.monthly_salary *= (1.0 + r.uniform(0.02, 0.08))
        # Collections delay: cash maybe doesn't reflect MRR immediately
        if r.random() < 0.35:
            mrr_delta *= 0.6  # slower realized growth
            rep_delta -= 2

    if mode == "Spartan":
        # Brutal: cash drains more, churn fights you
        churn_delta += r.uniform(0.01, 0.03)
        rep_delta -= r.uniform(1, 4)
        mrr_delta *= 0.9

    if mode == "Extreme":
        # Big swings tied to support/infra chaos
        chaos = r.uniform(0.8, 1.6)
        support_delta *= chaos
        infra_delta *= chaos
        # Viral luck sometimes
        if r.random() < 0.25:
            mrr_delta += r.uniform(500, 5000)
            rep_delta += r.uniform(4, 14)
        # But backlash sometimes
        if r.random() < 0.22:
            churn_delta += r.uniform(0.01, 0.06)
            rep_delta -= r.uniform(4, 12)

    # Apply updates
    metrics.mrr = max(0, metrics.mrr + mrr_delta)
    metrics.churn = clamp(metrics.churn + churn_delta, 0.0, 0.35)
    metrics.reputation = clamp(metrics.reputation + rep_delta, 0.0, 100.0)
    metrics.support_load = clamp(metrics.support_load + support_delta, 0.0, 100.0)
    metrics.infra_load = clamp(metrics.infra_load + infra_delta, 0.0, 100.0)

    # Cash update: +MRR (approx) - burn - extra chaos costs
    # simple monthly: cash += mrr - burn - overload penalties
    overload_penalty = 0.0
    if metrics.support_load > 80:
        overload_penalty += (metrics.support_load - 80) * 400
    if metrics.infra_load > 80:
        overload_penalty += (metrics.infra_load - 80) * 600

    # In Extreme, overload is more punishing (tickets + downtime)
    if mode == "Extreme":
        overload_penalty *= 1.3

    metrics.cash = metrics.cash + metrics.mrr - metrics.burn - overload_penalty

    # Save
    st.session_state.metrics = asdict(metrics)
    st.session_state.resolved_months.add(month)

    # Post resolution to chat ONCE
    choice_title = pending["option_a_title"] if choice == "A" else pending["option_b_title"]
    chat_add("user", f"Seçim: **{choice}** — {choice_title}")
    chat_add(
        "assistant",
        "✅ Seçimin işlendi.\n\n"
        f"- Kasa: {fmt_try(metrics.cash)}\n"
        f"- MRR: {fmt_try(metrics.mrr)}\n"
        f"- Churn: %{metrics.churn*100:.1f}\n"
        f"- İtibar: {metrics.reputation:.0f}/100\n"
        f"- Support: {metrics.support_load:.0f}/100\n"
        f"- Altyapı: {metrics.infra_load:.0f}/100"
    )

    # Advance month (if season not ended)
    if st.session_state.month < st.session_state.season_len:
        st.session_state.month += 1
        st.session_state.pending_turn = None
    else:
        chat_add("assistant", "🏁 Sezon bitti. İstersen ayarları değiştirip yeni sezon başlatabilirsin.")
        st.session_state.pending_turn = None


# -----------------------------
# Sidebar UI
# -----------------------------
def sidebar_ui():
    st.sidebar.markdown(f"## {st.session_state.character['name']}")
    st.sidebar.caption(f"Mod: **{st.session_state.mode}**")
    st.sidebar.caption(f"Ay: **{st.session_state.month}/{st.session_state.season_len}**")
    st.sidebar.progress(st.session_state.month / max(1, st.session_state.season_len))

    m = Metrics(**st.session_state.metrics)
    st.sidebar.markdown("### Finansal Durum")
    st.sidebar.metric("Kasa", fmt_try(m.cash))
    st.sidebar.metric("MRR", fmt_try(m.mrr))

    with st.sidebar.expander("Aylık Gider Detayı", expanded=False):
        st.write(f"Maaşlar: {fmt_try(m.monthly_salary)}")
        st.write(f"Sunucu: {fmt_try(m.monthly_server)}")
        st.write(f"Pazarlama: {fmt_try(m.monthly_marketing)}")
        st.markdown(f"**TOPLAM: {fmt_try(m.burn)}**")

    st.sidebar.markdown("---")
    st.sidebar.write(f"İtibar: **{m.reputation:.0f}/100**")
    st.sidebar.write(f"Support: **{m.support_load:.0f}/100**")
    st.sidebar.write(f"Altyapı: **{m.infra_load:.0f}/100**")
    st.sidebar.write(f"Churn: **%{m.churn*100:.1f}**")

    st.sidebar.markdown("---")
    if st.sidebar.button("🔄 Yeni Sezon / Reset"):
        # full reset
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()


# -----------------------------
# Main UI
# -----------------------------
def setup_panel():
    st.markdown(f"# {APP_TITLE}")
    st.caption(APP_SUB)

    # Key status
    ok, msg = model_ready()
    if ok:
        st.success(msg)
    else:
        st.error(msg)

    with st.expander("🛠️ Karakterini ve ayarlarını Özelleştir (Tıkla)", expanded=False):
        c = st.session_state.character
        col1, col2, col3 = st.columns(3)
        with col1:
            c["name"] = st.text_input("Karakter adı", value=c.get("name", "İsimsiz Girişimci"))
            c["archetype"] = st.selectbox("Arketip", ["Genel", "Growth", "Product", "Sales", "Engineer", "Ops"], index=["Genel","Growth","Product","Sales","Engineer","Ops"].index(c.get("archetype","Genel")))
        with col2:
            st.session_state.mode = st.selectbox("Mod", MODES, index=MODES.index(st.session_state.mode))
            c["tone"] = st.selectbox("Anlatım tonu", ["Sert", "Komik", "Dramatik", "Kuru"], index=["Sert","Komik","Dramatik","Kuru"].index(c.get("tone","Sert")))
        with col3:
            st.session_state.season_len = st.slider("Sezon uzunluğu (ay)", 6, 24, int(st.session_state.season_len))
            # starting cash can be set before game starts
            start_cash = st.slider("Başlangıç kasası", 50_000, 3_000_000, int(st.session_state.metrics["cash"]), step=50_000)
            st.session_state.metrics["cash"] = float(start_cash)
            c["risk_appetite"] = st.selectbox("Risk iştahı", ["Düşük", "Dengeli", "Yüksek"], index=["Düşük","Dengeli","Yüksek"].index(c.get("risk_appetite","Dengeli")))
        st.session_state.character = c

    st.markdown("---")

    if not st.session_state.game_started:
        st.info("Oyuna başlamak için girişim fikrini yaz.")
        idea = st.text_area("Girişim fikrin ne?", height=140, value=st.session_state.idea)
        st.session_state.idea = idea

        colA, colB = st.columns([1, 4])
        with colA:
            if st.button("🚀 Oyunu Başlat", type="primary"):
                if not st.session_state.idea.strip():
                    st.warning("Önce girişim fikrini yaz.")
                else:
                    # init gemini model now (in case secrets were added)
                    st.session_state.gemini_model = init_gemini()
                    st.session_state.game_started = True
                    st.session_state.month = 1
                    st.session_state.pending_turn = None
                    st.session_state.generated_months = set()
                    st.session_state.resolved_months = set()
                    st.session_state.chat = []
                    st.session_state.used_extreme_events = []
                    chat_add("assistant", f"Tamam **{st.session_state.character['name']}**. Ay 1'den başlıyoruz. Mod: **{st.session_state.mode}**.")
                    chat_add("assistant", "Önce **Durum Analizi**, sonra **Kriz**, sonra **A/B** seçeceksin.")
                    st.rerun()
        with colB:
            st.caption("Not: Streamlit her etkileşimde rerun yapar. Bu uygulama tekrar yazma bug’ını state kilidiyle engeller.")

def gameplay_panel():
    # Render chat
    render_chat()

    # Generate turn if needed (no duplicates)
    generate_turn_if_needed()

    # Show pending turn actions
    pending = st.session_state.pending_turn
    if pending:
        st.markdown("---")
        st.subheader("Şimdi krize karşı bir çözüm seç (A/B).")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"### A) {pending['option_a_title']}")
            st.write(pending["option_a_body"])
            if st.button("A seç", key=f"chooseA_{pending['month']}"):
                apply_choice("A")
                st.rerun()

        with col2:
            st.markdown(f"### B) {pending['option_b_title']}")
            st.write(pending["option_b_body"])
            if st.button("B seç", key=f"chooseB_{pending['month']}"):
                apply_choice("B")
                st.rerun()

    # Chat input (optional note)
    note = st.chat_input("İstersen bir not yaz (opsiyonel). Seçim yine A/B ile ilerler.")
    if note:
        chat_add("user", note)
        st.rerun()


# -----------------------------
# App
# -----------------------------
def main():
    ensure_state()
    sidebar_ui()

    if not st.session_state.game_started:
        setup_panel()
    else:
        st.markdown(f"# {APP_TITLE}")
        st.caption(APP_SUB)
        gameplay_panel()

if __name__ == "__main__":
    main()
