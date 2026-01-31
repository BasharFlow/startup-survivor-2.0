# app.py — Startup Survivor RPG (single-file)
# Fixes requested:
# - Real chat flow: everything renders via st.chat_message (including choices)
# - Crisis is longer, clearer, actionable; options are mid-length and high-quality
# - Cold open crisis teaser at the very start of each month (especially month 1)
# - UI layout: Character customization on TOP-RIGHT, mode selection above "calendar"/season controls
# - "Churn" renamed in UI to Turkish: "Kayıp Oranı"
# - Prevents duplicate month content via robust state locks (no repeating crisis)
# - More robust Gemini JSON parsing with repair attempt; strong local fallback if LLM fails

from __future__ import annotations

import os
import json
import random
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, Tuple, List

import streamlit as st

# Optional Gemini import
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except Exception:
    GEMINI_AVAILABLE = False


# -----------------------------
# Page config
# -----------------------------
st.set_page_config(page_title="Startup Survivor RPG", layout="wide")

APP_TITLE = "Startup Survivor RPG"
APP_SUB = "Akış: (Teaser) → Durum Analizi → Kriz → A/B seçimi. Her ay 1 kez üretilir, tekrar etmez."


# -----------------------------
# Utilities
# -----------------------------
def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def fmt_try(n: float) -> str:
    n_int = int(round(n))
    s = f"{n_int:,}".replace(",", ".")
    return f"{s} ₺"

def safe_get_secret_key() -> Optional[str]:
    key = None
    try:
        if "GEMINI_API_KEY" in st.secrets:
            key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        key = None

    if not key:
        key = os.getenv("GEMINI_API_KEY")

    # If stored as TOML list: GEMINI_API_KEY=[...]
    if isinstance(key, (list, tuple)):
        key = key[0] if len(key) else None

    if isinstance(key, str):
        key = key.strip().strip('"').strip("'")
        if not key:
            return None
    return key

def model_ready() -> Tuple[bool, str]:
    key = safe_get_secret_key()
    if not key:
        return (False, "GEMINI_API_KEY bulunamadı. Secrets/env eklemeden model çağrıları çalışmaz.")
    if not GEMINI_AVAILABLE:
        return (False, "google-generativeai paketi yok gibi görünüyor.")
    return (True, "Gemini anahtarı görüldü. Model çağrıları çalışmalı.")

def init_gemini():
    ok, _ = model_ready()
    if not ok:
        return None
    try:
        genai.configure(api_key=safe_get_secret_key())
        return genai.GenerativeModel("gemini-1.5-flash")
    except Exception:
        return None

def llm_call(prompt: str, temperature: float = 0.9, max_tokens: int = 800) -> str:
    model = st.session_state.get("gemini_model")
    if model is None:
        return ""  # will trigger local fallback

    try:
        resp = model.generate_content(
            prompt,
            generation_config={"temperature": temperature, "max_output_tokens": max_tokens},
        )
        txt = getattr(resp, "text", "") or ""
        return txt.strip()
    except Exception:
        return ""


def strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        # remove first fence line and last fence
        lines = s.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
            return "\n".join(lines[1:-1]).strip()
    return s

def extract_json(s: str) -> Optional[Dict[str, Any]]:
    if not s:
        return None
    s = strip_code_fences(s)
    s = s.strip()

    # Find outermost JSON object
    if "{" in s and "}" in s:
        start = s.find("{")
        end = s.rfind("}")
        candidate = s[start:end + 1].strip()
        try:
            return json.loads(candidate)
        except Exception:
            return None
    return None


# -----------------------------
# Game models
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
    churn: float = 0.05  # 0-1 (UI: Kayıp Oranı)
    reputation: float = 50
    support_load: float = 20
    infra_load: float = 20
    monthly_salary: float = 50_000
    monthly_server: float = 6_100
    monthly_marketing: float = 5_300

    @property
    def burn(self) -> float:
        return self.monthly_salary + self.monthly_server + self.monthly_marketing

@dataclass
class TurnContent:
    month: int
    teaser: str
    situation: str
    crisis: str
    option_a_title: str
    option_a_body: str
    option_b_title: str
    option_b_body: str
    event_id: Optional[str] = None


# -----------------------------
# Event pools
# -----------------------------
EXTREME_EVENTS = [
    {"id": "excel-cult", "hook": "Kurumsal müşteri ürünü Excel’e çevirmeye çalışıyor: 'AI güzel ama bizde süreç Excel'.",
     "impact": "Scope patlar, support yükselir, itibar 'enterprise-ready' beklentisine kilitlenir."},
    {"id": "influencer-wrong-feature", "hook": "Influencer ürünü övüyor ama yanlış özelliği övüyor: trafik geldi, kafa da geldi.",
     "impact": "Yanlış kullanıcı dolar; churn ve support artar. Doğru vaadi netleştirirsen MRR toparlar."},
    {"id": "payment-meme", "hook": "Ödeme sayfası meme oldu: 'Kredi kartım bile vazgeçti' diye paylaşım dönüyor.",
     "impact": "Conversion düşer; düzeltirsen ters viral + MRR sıçraması olur."},
    {"id": "kedi-filter-ddos", "hook": "Kedi filtresi trendi: herkes ekranı kediye çevirip OCR’ı kırıyor; trafik DDOS gibi.",
     "impact": "Infra tavan, support 'kedi dili' ticket’ı; stabiliteye oynamazsan kasa yanar."},
    {"id": "twitter-misread", "hook": "X seni yanlış anladı: ürün 'komplo' thread’ine düştü, herkes 'kanıt' istiyor.",
     "impact": "İtibar düşer, support patlar. Doğru karşı hamleyle itibar geri gelir, talep bile artabilir."},
    {"id": "viral-wrong-country", "hook": "Viral oldun ama yanlış ülkede: trafik Peru’dan, ödeme ekranın Türkiye IBAN istiyor.",
     "impact": "Support yükü + ödeme hatası. Lokalizasyonla MRR açılır; yoksa churn artar."},
    {"id": "procurement-portal", "hook": "Procurement portalı cehennemi: 9 farklı portala davetlisin; her biri şifre ve form istiyor.",
     "impact": "Zaman yer, cash yanar. Bitirirsen tek anlaşmayla MRR patlar."},
    {"id": "hot-take-backfire", "hook": "Eski tweet’in gündem: 'Onboarding gereksiz' demişsin; onboarding’in 6 adım çıkıyor.",
     "impact": "İtibar sarsılır. Yalınlaştırırsan kazanırsın; inat edersen churn büyür."},
]

REALIST_THEMES = [
    "onboarding sürtünmesi", "netlik/vaat belirsizliği", "pricing kararsızlığı",
    "performans/altyapı darboğazı", "support yükü", "kanal verimsizliği", "kullanıcı beklentisi kayması"
]

TURKEY_THEMES = [
    "kur/enflasyon sunucu maliyeti", "tahsilat gecikmesi (30-60 gün)", "KDV/stopaj sürprizi",
    "e-fatura/e-arşiv zorunluluğu", "platform komisyonu artışı", "asgari ücret/yan hak baskısı",
    "kurumsal 'fatura kesemezsen olmaz' şartı"
]


# -----------------------------
# Prompts
# -----------------------------
def mode_instructions(mode: str) -> str:
    if mode == "Realist":
        return ("Gerçekçi, dengeli ve profesyonel bir simülasyon anlatıcısısın. "
                "Mantıklı trade-off ver, abartma, net sebep-sonuç kur.")
    if mode == "Hard":
        return ("Zorlayıcı bir finansal denetçi gibisin. "
                "Her kararın bedeli var. Kolay çıkış yok ama adil ol.")
    if mode == "Spartan":
        return ("Acımasız ayı piyasası gibi davran. Engeller sert, maliyet yüksek. "
                "Hayatta kalma testi. Şans düşük.")
    if mode == "Extreme":
        return ("Kaos teorisi anlatıcısısın. Mantık ikinci planda; paylaşmalık absürtlük üret. "
                "Absürt olayların %80'i sosyal medya/platform/influencer/kurumsal saçmalık/kullanıcı davranışı kaynaklı olsun. "
                "%15 sürreal ama metaforik (abartılmış gerçek). %5 nadir sci-fi cameo. "
                "Kural: Ne kadar saçma olursa olsun sonuç mutlaka startup metriklerine bağlanır (kasa, MRR, kayıp oranı, itibar, support, altyapı). "
                "Tekrar eden cümlelerden kaçın. Sahne gibi yaz.")
    if mode == "Türkiye":
        return ("Türkiye pazarına benzeyen gerçekçi bir anlatıcı ol. "
                "Kur/enflasyon, tahsilat gecikmesi, KDV/stopaj, e-fatura, platform komisyonu, kurumsal fatura şartı gibi dinamikleri kat. "
                "Karikatür yok; günlük hayat gibi.")
    return "Dengeli bir anlatıcı ol."

def build_turn_prompt(
    idea: str,
    character: Character,
    metrics: Metrics,
    mode: str,
    month: int,
    season_len: int,
    hook: str,
    last_style_avoid: str,
) -> str:
    # Strong length targets (quality guardrails)
    # - teaser: 1 cümle, 12-22 kelime
    # - situation: 90-140 kelime (tek paragraf, hikayesel)
    # - crisis: 90-140 kelime (tek paragraf, net ve somut, metriklerle)
    # - options: 80-120 kelime (tek paragraf, 2-3 adım + tradeoff)

    return f"""
Sen metin tabanlı girişim RPG oyun motorusun.
{mode_instructions(mode)}

KARAKTER:
- Ad: {character.name}
- Arketip: {character.archetype}
- Ton: {character.tone}
- Risk: {character.risk_appetite}

FİKİR:
{idea}

METRİKLER:
Ay {month}/{season_len}
Kasa {metrics.cash:.0f}, MRR {metrics.mrr:.0f}, KayıpOranı {metrics.churn:.3f}, İtibar {metrics.reputation:.0f}/100,
Support {metrics.support_load:.0f}/100, Altyapı {metrics.infra_load:.0f}/100, AylıkGider {metrics.burn:.0f}

HOOK (buna yaslan, ama birebir kopyalama):
{hook}

TEKRAR YASAĞI (buna benzeme):
{last_style_avoid}

SADECE JSON ÇIKTI VER (markdown yok, açıklama yok).
ŞEMA:
{{
 "teaser": "1 cümle, 12-22 kelime. Soğuk açılış gibi, paylaşmalık. (Ay/ürün adı geçebilir)",
 "situation": "Tek paragraf, 90-140 kelime. Hikayesel sahne; oyuncunun fikrini yorumla; ekip/ kullanıcı davranışı detayı olsun.",
 "crisis": "Tek paragraf, 90-140 kelime. Çok net kriz: ne oldu, neden oldu, bugün ne acıtıyor. En az 2 metrik sayıyla bağla.",
 "option_a_title": "A başlığı: 3-6 kelime, vurucu",
 "option_a_body": "Tek paragraf, 80-120 kelime. 2-3 adım çözüm + tradeoff. En az 1 metrik etkisini ima et.",
 "option_b_title": "B başlığı: 3-6 kelime, vurucu",
 "option_b_body": "Tek paragraf, 80-120 kelime. 2-3 adım çözüm + tradeoff. En az 1 metrik etkisini ima et."
}}

KURALLAR:
- Situation ve Crisis aynı cümleleri tekrar etmesin.
- Extreme modda komiklik yüksek olsun (ama metrik bağlı).
- Seçenekler "tek cümle" olamaz. Minimum kaliteyi koru.
""".strip()


def pick_hook(mode: str, month: int) -> Tuple[str, Optional[str]]:
    r = random.Random(st.session_state.rng_seed + month * 1337)
    if mode == "Extreme":
        used = st.session_state.used_extreme_events
        remaining = [e for e in EXTREME_EVENTS if e["id"] not in used]
        if not remaining:
            used.clear()
            remaining = EXTREME_EVENTS[:]
        ev = r.choice(remaining)
        used.append(ev["id"])
        return (f"{ev['hook']} Etki: {ev['impact']}", ev["id"])

    if mode == "Türkiye":
        theme = r.choice(TURKEY_THEMES)
        return (f"TEMA: {theme}", None)

    theme = r.choice(REALIST_THEMES)
    return (f"TEMA: {theme}", None)


# -----------------------------
# Local fallback (still quality)
# -----------------------------
def local_fallback_turn(month: int, mode: str, idea: str, metrics: Metrics, hook: str, event_id: Optional[str]) -> TurnContent:
    # A decent, non-generic fallback if LLM fails completely.
    # Still follows length targets.
    r = random.Random(st.session_state.rng_seed + month * 4242)

    teaser = "Bu ay tek bir yanlış cümle, her şeyi komediye çevirip metriklerini tokatlayabilir."
    if mode == "Extreme":
        teaser = r.choice([
            "Bir anda herkes senin ürünü yanlış şey için kullanıyor — ve internet bunu şova çeviriyor.",
            "Bugün ürünün değil, algoritma seni yönetiyor: yanlış anlaşılma trend oluyor.",
            "Bir kurumsal tablo, seni ‘startup’ değil ‘Excel eklentisi’ sanıp sahiplendi.",
        ])

    # Situation
    situation = (
        f"Ay {month}. {idea[:80].strip()}… diye başladın ama sahne kayıyor. "
        "Bir yanda ekip ‘hız’ diye tempo tutuyor, diğer yanda kullanıcıların gözleri cam gibi: "
        "ürün güzel ama ‘ne işe yarıyor’ cümlesi havada kalıyor. "
        f"{hook.split('Etki:')[0].strip()} derken senin asıl derdin şu: "
        "insanlar seni konuşuyor ama aynı şeyi anlamıyor. Her mesajın bir bedeli var; "
        "doğru mesajı bulamazsan büyüme değil, gürültü satın alıyorsun."
    )
    # Crisis
    crisis = (
        f"Bu ay kriz net: kasa {fmt_try(metrics.cash)} iken aylık gider {fmt_try(metrics.burn)}; "
        f"MRR {fmt_try(metrics.mrr)} ve kayıp oranı %{metrics.churn*100:.1f}. "
        "Kullanıcıların yarısı ‘harika’ diyor, yarısı ‘bu kesin komplo’ diye ticket açıyor; "
        "support yükün artmaya başladı ve bu artış altyapıyı da sürüklüyor. "
        "Eğer bugün net bir vaade kilitlemezsen hem itibarın çalkalanacak hem de yanlış kitle yüzünden kayıp oranı yükselip MRR’ı zehirleyecek."
    )
    # Options
    option_a_title = "Tek vaat, tek sahne"
    option_a_body = (
        "Ürünü tek bir ana vaade indir: ilk 60 saniyede tek ‘Aha!’ anı yarat. "
        "Onboarding’i 3 adıma düşür, geri kalan özellikleri gizle ve sadece o ana vaadi ölç. "
        "Support’u azaltmak için tek bir sabit cevap şablonu + mini rehber hazırla. "
        "Trade-off: Kısa vadede bazı kullanıcılar ‘özellik yok’ diye ayrılır; ama doğru kitle kalır, kayıp oranı düşerken MRR daha temiz büyür."
    )

    option_b_title = "Kaosu yönetecek filtre"
    option_b_body = (
        "Gürültüyü ürünün içine filtrele: kullanıcıyı girişte iki yola ayır (anlık kullanım / öğrenme modu). "
        "Yanlış beklentiyi azaltmak için ödeme ekranına net ‘bu ne değildir’ satırı ekle. "
        "Altyapı/sunucu stresini azaltmak için ağır işleri sıraya al ve limit koy. "
        "Trade-off: Büyüme daha yavaş görünür; ama itibar toparlanır, support/altyapı yükü düşer ve kasa daha uzun dayanır."
    )

    return TurnContent(
        month=month,
        teaser=teaser,
        situation=situation,
        crisis=crisis,
        option_a_title=option_a_title,
        option_a_body=option_a_body,
        option_b_title=option_b_title,
        option_b_body=option_b_body,
        event_id=event_id,
    )


# -----------------------------
# State management
# -----------------------------
def ensure_state():
    if "initialized" in st.session_state:
        return

    st.session_state.initialized = True
    st.session_state.character = asdict(Character())
    st.session_state.mode = "Extreme"
    st.session_state.season_len = 12
    st.session_state.metrics = asdict(Metrics())
    st.session_state.idea = ""
    st.session_state.game_started = False
    st.session_state.month = 1

    # Chat log
    st.session_state.chat: List[Dict[str, str]] = []

    # Turn state locks
    st.session_state.pending_turn: Optional[Dict[str, Any]] = None
    st.session_state.generated_months = set()  # months posted
    st.session_state.resolved_months = set()   # months applied

    # For variety
    st.session_state.rng_seed = random.randint(1, 10_000_000)
    st.session_state.used_extreme_events = []

    st.session_state.gemini_model = init_gemini()


def chat_add(role: str, content: str):
    st.session_state.chat.append({"role": role, "content": content})

def render_chat():
    for msg in st.session_state.chat:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])


# -----------------------------
# Turn generation (robust)
# -----------------------------
def generate_turn():
    if not st.session_state.game_started:
        return

    month = st.session_state.month
    if month in st.session_state.resolved_months:
        return

    # If we already have pending for this month, do not regenerate
    pending = st.session_state.pending_turn
    if pending and pending.get("month") == month:
        return

    mode = st.session_state.mode
    idea = st.session_state.idea.strip()
    character = Character(**st.session_state.character)
    metrics = Metrics(**st.session_state.metrics)

    hook, event_id = pick_hook(mode, month)

    # Avoid repeating style: give last 2 assistant messages as "avoid"
    last_avoid = ""
    for m in reversed(st.session_state.chat[-6:]):
        if m["role"] == "assistant":
            last_avoid += m["content"][:200].replace("\n", " ") + "\n"

    prompt = build_turn_prompt(
        idea=idea,
        character=character,
        metrics=metrics,
        mode=mode,
        month=month,
        season_len=st.session_state.season_len,
        hook=hook,
        last_style_avoid=last_avoid.strip() or "Yok",
    )

    # 1) First attempt
    raw = llm_call(prompt, temperature=0.95 if mode == "Extreme" else 0.85, max_tokens=900)
    data = extract_json(raw)

    # 2) Repair attempt if parse failed
    if data is None and raw:
        repair_prompt = f"""
Aşağıdaki metni ŞEMAYA UYGUN TEK BİR JSON objesine dönüştür.
SADECE JSON ver, başka hiçbir şey yazma.

ŞEMA:
{{
 "teaser": "...",
 "situation": "...",
 "crisis": "...",
 "option_a_title": "...",
 "option_a_body": "...",
 "option_b_title": "...",
 "option_b_body": "..."
}}

METİN:
{raw}
""".strip()
        raw2 = llm_call(repair_prompt, temperature=0.2, max_tokens=700)
        data = extract_json(raw2)

    # 3) Local fallback if still none
    if data is None:
        turn = local_fallback_turn(month, mode, idea, metrics, hook, event_id)
    else:
        # Validate and fill
        def g(k: str, default: str) -> str:
            v = str(data.get(k, "")).strip()
            return v if v else default

        turn = TurnContent(
            month=month,
            teaser=g("teaser", "Bu ay tek bir yanlış hamle, metriklerini yumruklar."),
            situation=g("situation", "Bu ay sahne kayıyor: kullanıcılar farklı şeyler anlıyor."),
            crisis=g("crisis", "Kriz net: belirsizlik büyüyor; kasa yanıyor ve kayıp oranı artma riski taşıyor."),
            option_a_title=g("option_a_title", "A Planı"),
            option_a_body=g("option_a_body", "Net bir hamle yap. Vaadi daralt, onboarding’i kısalt, ölç."),
            option_b_title=g("option_b_title", "B Planı"),
            option_b_body=g("option_b_body", "Hasarı azalt. Support/altyapı yükünü indir, sonra büyümeyi dene."),
            event_id=event_id,
        )

    st.session_state.pending_turn = asdict(turn)

    # Post to chat once per month
    if month not in st.session_state.generated_months:
        # Cold open teaser first (user asked "başlangıçta da kriz ver")
        chat_add("assistant", f"🎬 **Soğuk Açılış (Ay {month})**\n\n{turn.teaser}")
        chat_add("assistant", f"🧠 **Durum Analizi**\n\n{turn.situation}")
        chat_add("assistant", f"⚠️ **Kriz**\n\n{turn.crisis}")
        st.session_state.generated_months.add(month)


# -----------------------------
# Apply choices
# -----------------------------
def apply_choice(choice: str):
    pending = st.session_state.pending_turn
    if not pending:
        return

    month = pending["month"]
    if month in st.session_state.resolved_months:
        return

    mode = st.session_state.mode
    metrics = Metrics(**st.session_state.metrics)

    r = random.Random(st.session_state.rng_seed + month * (9991 if choice == "A" else 9992))

    # Mode scales
    if mode == "Realist":
        scale, vol = 1.0, 0.7
    elif mode == "Hard":
        scale, vol = 1.1, 0.95
    elif mode == "Spartan":
        scale, vol = 1.25, 1.1
    elif mode == "Türkiye":
        scale, vol = 1.05, 0.95
    else:  # Extreme
        scale, vol = 1.0, 1.35

    bold = 1.0 if choice == "A" else 0.75
    defend = 1.0 if choice == "B" else 0.8

    # Deltas
    mrr_delta = (r.uniform(-0.02, 0.14) * (metrics.mrr + 1) + r.uniform(200, 2500) * bold) * scale
    churn_delta = (r.uniform(-0.02, 0.04) * vol) * (0.9 if defend > 0.95 else 1.05)
    rep_delta = r.uniform(-6, 10) * scale
    support_delta = r.uniform(-10, 18) * vol
    infra_delta = r.uniform(-8, 16) * vol

    # Turkey dynamics
    if mode == "Türkiye":
        fx = r.uniform(0.03, 0.12)
        metrics.monthly_server *= (1.0 + fx)
        metrics.monthly_salary *= (1.0 + r.uniform(0.02, 0.08))
        if r.random() < 0.35:
            # Collections delay: cash impact delayed
            mrr_delta *= 0.75
            rep_delta -= 1.5

    # Spartan brutality
    if mode == "Spartan":
        churn_delta += r.uniform(0.01, 0.03)
        rep_delta -= r.uniform(1, 5)
        mrr_delta *= 0.9

    # Extreme chaos
    if mode == "Extreme":
        chaos = r.uniform(0.8, 1.7)
        support_delta *= chaos
        infra_delta *= chaos
        if r.random() < 0.28:  # viral pop
            mrr_delta += r.uniform(800, 7000)
            rep_delta += r.uniform(6, 18)
        if r.random() < 0.22:  # backlash
            churn_delta += r.uniform(0.01, 0.07)
            rep_delta -= r.uniform(6, 16)

    metrics.mrr = max(0, metrics.mrr + mrr_delta)
    metrics.churn = clamp(metrics.churn + churn_delta, 0.0, 0.35)
    metrics.reputation = clamp(metrics.reputation + rep_delta, 0.0, 100.0)
    metrics.support_load = clamp(metrics.support_load + support_delta, 0.0, 100.0)
    metrics.infra_load = clamp(metrics.infra_load + infra_delta, 0.0, 100.0)

    # Cash update with overload penalties
    overload = 0.0
    if metrics.support_load > 80:
        overload += (metrics.support_load - 80) * 450
    if metrics.infra_load > 80:
        overload += (metrics.infra_load - 80) * 650
    if mode == "Extreme":
        overload *= 1.35

    metrics.cash = metrics.cash + metrics.mrr - metrics.burn - overload

    st.session_state.metrics = asdict(metrics)
    st.session_state.resolved_months.add(month)

    # Log as chat
    title = pending["option_a_title"] if choice == "A" else pending["option_b_title"]
    chat_add("user", f"Seçimim: **{choice}** — {title}")

    chat_add(
        "assistant",
        "✅ Seçimin işlendi.\n\n"
        f"• Kasa: {fmt_try(metrics.cash)}\n"
        f"• MRR: {fmt_try(metrics.mrr)}\n"
        f"• Kayıp Oranı: %{metrics.churn*100:.1f}\n"
        f"• İtibar: {metrics.reputation:.0f}/100\n"
        f"• Support: {metrics.support_load:.0f}/100\n"
        f"• Altyapı: {metrics.infra_load:.0f}/100"
    )

    # Advance month
    if st.session_state.month < st.session_state.season_len:
        st.session_state.month += 1
        st.session_state.pending_turn = None
    else:
        chat_add("assistant", "🏁 Sezon bitti. Yeni sezon için Reset’e basabilirsin.")
        st.session_state.pending_turn = None


# -----------------------------
# UI
# -----------------------------
def sidebar_ui():
    c = st.session_state.character
    st.sidebar.markdown(f"## {c['name']}")
    # Mode selection ABOVE season length (as you requested)
    st.session_state.mode = st.sidebar.selectbox("Mod", MODES, index=MODES.index(st.session_state.mode))

    st.session_state.season_len = st.sidebar.slider("Sezon uzunluğu (ay)", 3, 36, int(st.session_state.season_len))
    st.sidebar.caption(f"Ay: **{st.session_state.month}/{st.session_state.season_len}**")
    st.sidebar.progress(st.session_state.month / max(1, st.session_state.season_len))

    # Starting cash (can be changed before start; after start, still adjustable if you want)
    start_cash = st.sidebar.slider("Başlangıç kasası", 50_000, 5_000_000, int(st.session_state.metrics["cash"]), step=50_000)
    st.session_state.metrics["cash"] = float(start_cash)

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
    st.sidebar.write(f"Kayıp Oranı: **%{m.churn*100:.1f}**")

    st.sidebar.markdown("---")
    if st.sidebar.button("🔄 Reset (Yeni Sezon)"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()


def top_right_character_panel():
    # Put character customization on TOP RIGHT as requested
    colL, colR = st.columns([6, 2])
    with colL:
        st.markdown(f"# {APP_TITLE}")
        st.caption(APP_SUB)
    with colR:
        with st.expander("🧩 Karakter", expanded=False):
            c = st.session_state.character
            c["name"] = st.text_input("Ad", value=c.get("name", "İsimsiz Girişimci"))
            c["archetype"] = st.selectbox("Arketip", ["Genel", "Growth", "Product", "Sales", "Engineer", "Ops"],
                                          index=["Genel","Growth","Product","Sales","Engineer","Ops"].index(c.get("archetype","Genel")))
            c["tone"] = st.selectbox("Ton", ["Sert", "Komik", "Dramatik", "Kuru"],
                                     index=["Sert","Komik","Dramatik","Kuru"].index(c.get("tone","Sert")))
            c["risk_appetite"] = st.selectbox("Risk", ["Düşük", "Dengeli", "Yüksek"],
                                              index=["Düşük","Dengeli","Yüksek"].index(c.get("risk_appetite","Dengeli")))
            st.session_state.character = c


def setup_screen():
    top_right_character_panel()

    ok, msg = model_ready()
    if ok:
        st.success(msg)
    else:
        st.error(msg)
        st.caption("Not: Model yoksa da oyun çalışır; ama kalite için Gemini önerilir.")

    st.markdown("---")
    st.info("Oyuna başlamak için girişim fikrini yaz.")

    st.session_state.idea = st.text_area("Girişim fikrin ne?", height=150, value=st.session_state.idea)

    if st.button("🚀 Oyunu Başlat", type="primary"):
        if not st.session_state.idea.strip():
            st.warning("Önce girişim fikrini yaz.")
            return

        st.session_state.gemini_model = init_gemini()
        st.session_state.game_started = True
        st.session_state.month = 1
        st.session_state.pending_turn = None
        st.session_state.generated_months = set()
        st.session_state.resolved_months = set()
        st.session_state.chat = []
        st.session_state.used_extreme_events = []

        chat_add("assistant", f"Tamam **{st.session_state.character['name']}**. Mod: **{st.session_state.mode}**. Ay 1’e giriyoruz.")
        chat_add("assistant", "Kural: Önce soğuk açılış, sonra durum analizi, sonra net kriz, sonra A/B.")
        st.rerun()


def gameplay_screen():
    top_right_character_panel()

    # Generate current month content (once)
    generate_turn()

    # Render chat
    render_chat()

    # Show choices INSIDE chat flow (not as a separate page section)
    pending = st.session_state.pending_turn
    if pending:
        with st.chat_message("assistant"):
            st.write("🧭 **Şimdi seçim zamanı.** A mı B mi?")
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

    # Optional free chat notes (kept in chat style)
    note = st.chat_input("Not yazabilirsin (opsiyonel). Oyun ilerlemesi A/B ile olur.")
    if note:
        chat_add("user", note)
        st.rerun()


def main():
    ensure_state()
    sidebar_ui()

    if not st.session_state.game_started:
        setup_screen()
    else:
        gameplay_screen()


if __name__ == "__main__":
    main()
