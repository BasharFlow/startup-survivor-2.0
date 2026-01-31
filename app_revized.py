# app.py — Startup Survivor RPG (single-file)
# Requested changes implemented:
# - Options: ONLY actions/plan steps. NO "if you choose this, MRR/support/cash..." hints.
# - Crisis: more explanatory, NO numeric metric dump in the crisis text (sidebar already shows).
# - Situation analysis logic:
#   - Month 1: deep idea analysis
#   - Month 2+: deep analysis of last month's choice + observed outcomes (qualitative summary)
# - Keep UI as-is (no extra layout changes beyond previous version)

from __future__ import annotations

import os
import json
import random
import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, Tuple, List

import streamlit as st

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

def llm_call(prompt: str, temperature: float = 0.9, max_tokens: int = 900) -> str:
    model = st.session_state.get("gemini_model")
    if model is None:
        return ""
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
        lines = s.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
            return "\n".join(lines[1:-1]).strip()
    return s

def extract_json(s: str) -> Optional[Dict[str, Any]]:
    if not s:
        return None
    s = strip_code_fences(s).strip()
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
     "impact": "Scope patlar; talepler saçma bir hıza çıkar; ekip, ürünü değil tabloyu savunur."},
    {"id": "influencer-wrong-feature", "hook": "Influencer ürünü övüyor ama yanlış özelliği övüyor: trafik geldi, kafa da geldi.",
     "impact": "Yanlış beklenti yüzünden her şey ters anlaşılır; ekip bir anda PR ekibine döner."},
    {"id": "payment-meme", "hook": "Ödeme sayfası meme oldu: 'Kredi kartım bile vazgeçti' diye paylaşım dönüyor.",
     "impact": "Checkout bir sahneye dönüşür; insanlar satın almak yerine ekran görüntüsü toplar."},
    {"id": "kedi-filter-ddos", "hook": "Kedi filtresi trendi: herkes ekranı kediye çevirip OCR’ı kırıyor; trafik DDOS gibi.",
     "impact": "Ürün ‘kedi dili’yle sınanır; destek hattı kedi emojisiyle dolar."},
    {"id": "twitter-misread", "hook": "X seni yanlış anladı: ürün 'komplo' thread’ine düştü, herkes 'kanıt' istiyor.",
     "impact": "Gerçeklik değil anlatı kazanır; sen de anlatını geri almak zorundasın."},
    {"id": "viral-wrong-country", "hook": "Viral oldun ama yanlış ülkede: trafik Peru’dan, ödeme ekranın Türkiye IBAN istiyor.",
     "impact": "Talep var ama akış ters; insanlar ‘bu bir şaka mı’ diye bağırır."},
    {"id": "procurement-portal", "hook": "Procurement portalı cehennemi: 9 farklı portala davetlisin; her biri form ister.",
     "impact": "İnsan değil süreç kazanır; ekip, feature değil form iterasyonuna girer."},
    {"id": "hot-take-backfire", "hook": "Eski tweet’in gündem: 'Onboarding gereksiz' demişsin; onboarding’in 6 adım çıktı.",
     "impact": "İnternet seni kendi sözünle döver; sen ya sahiplenirsin ya da kaybolursun."},
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
# Prompting
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
                "Kural: Ne kadar saçma olursa olsun sonuç mutlaka startup metriklerine bağlanır "
                "(ama metinde SAYI yazma; sadece nitel anlat). Tekrar eden cümlelerden kaçın. Sahne gibi yaz.")
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
    last_outcome_summary: str,
) -> str:
    """
    Key user request:
    - Options MUST NOT reveal consequences. No 'artar/azalır/düşer/yükselir' re metrics.
    - Crisis must be explanatory but MUST NOT contain numeric metric dump.
    - Situation: month 1 = analyze idea; month>1 = analyze last choice + what happened.
    """

    situation_instruction = (
        "Ay 1 ise: girişim fikrini detaylı analiz et (vaat, hedef kitle, kullanım anı, risk, ilk darboğaz)."
        if month == 1 else
        "Ay 2+ ise: geçen ayki seçimi ve gözlenen etkilerini analiz et; bu ayın psikolojisine/operasyonuna etkisini anlat."
    )

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

METRİKLER (BUNLARI METİNDE SAYI OLARAK YAZMA; SADECE NİTEL ANLAT):
Ay {month}/{season_len}
Kasa {metrics.cash:.0f}, MRR {metrics.mrr:.0f}, KayıpOranı {metrics.churn:.3f}, İtibar {metrics.reputation:.0f}/100,
Support {metrics.support_load:.0f}/100, Altyapı {metrics.infra_load:.0f}/100, AylıkGider {metrics.burn:.0f}

GEÇEN AY ÖZET (Ay 2+ için):
{last_outcome_summary}

HOOK (buna yaslan, ama birebir kopyalama):
{hook}

TEKRAR YASAĞI (buna benzeme):
{last_style_avoid}

SADECE JSON ÇIKTI VER (markdown yok, açıklama yok).
ŞEMA:
{{
 "teaser": "1 cümle, 12-22 kelime. Soğuk açılış gibi, paylaşmalık.",
 "situation": "Tek paragraf, 110-170 kelime. {situation_instruction} Teknik/ürün/insan detayı olsun.",
 "crisis": "Tek paragraf, 110-170 kelime. Çok net kriz: ne oldu, neden oldu, bugün ne acıtıyor. SAYI YAZMA. "
          "Kriz anlaşılır ve somut olsun; 1-2 somut belirti/örnek ekle (ticket türü, satış konuşması, viral olay, procurement talebi vb.).",
 "option_a_title": "A başlığı: 3-6 kelime, vurucu",
 "option_a_body": "Tek paragraf, 70-110 kelime. SADECE hamle planı: 3-5 adım. "
                  "METRİKLERİ ve SONUÇLARI ASLA söyleme. 'artar/azalır/düşer/yükselir' gibi çıktı cümleleri yok. "
                  "Ama aksiyonlar net olsun (ne yapacağız?).",
 "option_b_title": "B başlığı: 3-6 kelime, vurucu",
 "option_b_body": "Tek paragraf, 70-110 kelime. SADECE hamle planı: 3-5 adım. "
                  "METRİKLERİ ve SONUÇLARI ASLA söyleme. ÇIKTI TAHMİNİ yok."
}}

KURALLAR:
- Options'larda metrik adı geçmesin (kasa/MRR/kayıp oranı/itibar/support/altyapı).
- Options'larda sonuç fiilleri geçmesin: artar, azalır, düşer, yükselir, toparlar, patlar, dayanır.
- Crisis içinde SAYI/para yazma.
- Extreme modda olay komik/absürt ama anlaşılır sahne olsun.
""".strip()


# -----------------------------
# Hook picker
# -----------------------------
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
# Text sanitizers (hard enforcement)
# -----------------------------
FORBIDDEN_METRIC_WORDS = [
    "kasa", "mrr", "kayıp", "kayıp oranı", "churn", "itibar", "support", "altyapı", "masraf", "gider"
]
FORBIDDEN_RESULT_VERBS = [
    "artar", "azalır", "düşer", "yükselir", "toparlar", "patlar", "dayanır", "zehirler", "kurtarır"
]

def remove_sentences_with_forbidden(text: str) -> str:
    """Remove sentences that look like consequence spoilers (metric words + result verbs) or 'Trade-off' lines."""
    if not text:
        return text
    t = text.replace("Trade-off", "").replace("trade-off", "")
    # sentence split (simple)
    parts = re.split(r"(?<=[\.\!\?])\s+", t)
    kept = []
    for s in parts:
        s_l = s.lower()
        if "trade" in s_l:
            continue
        if any(w in s_l for w in FORBIDDEN_METRIC_WORDS) and any(v in s_l for v in FORBIDDEN_RESULT_VERBS):
            continue
        # also remove explicit "sonuç" spoilers
        if "sonuç" in s_l and any(w in s_l for w in FORBIDDEN_METRIC_WORDS):
            continue
        kept.append(s)
    out = " ".join(kept).strip()
    # compact whitespace
    out = re.sub(r"\s+", " ", out).strip()
    return out

def strip_numbers_in_crisis(text: str) -> str:
    """Remove numeric dumps in crisis (money/percent) while keeping narrative."""
    if not text:
        return text
    t = text
    t = t.replace("₺", "")
    t = re.sub(r"\b\d[\d\.\,]*\b", "", t)  # remove numbers
    t = re.sub(r"\s+", " ", t).strip()
    return t


# -----------------------------
# Local fallback (quality, no spoilers)
# -----------------------------
def local_fallback_turn(
    month: int,
    mode: str,
    idea: str,
    metrics: Metrics,
    hook: str,
    event_id: Optional[str],
    last_outcome_summary: str,
) -> TurnContent:
    r = random.Random(st.session_state.rng_seed + month * 4242)

    teaser = r.choice([
        "Bu ay sahne gerçek değil: yanlış anlaşılma trend, panik de plan gibi satılıyor.",
        "Bir tuşla herkes seni başka bir ürün sanabilir — ve buna göre davranabilir.",
        "Bugün ürünü değil, anlatıyı yönetiyorsun; yoksa anlatı seni yönetir.",
    ]) if mode == "Extreme" else "Bu ay küçük bir kıvılcım, büyük bir yangına dönüşebilir."

    if month == 1:
        situation = (
            "Ay 1. Fikrin güçlü bir ‘anlık ihtiyaç’ yakalıyor ama sahne kaygan: insanlar ürünü duyunca farklı şey hayal ediyor. "
            "Değer önermesi tek cümleye sığmıyor; bu da ilk temas anında sürtünme yaratıyor. "
            "Ürünün kullanım anı netleşmezse, ekip özellik üretirken kullanıcı ‘ben ne satın aldım’ diye bakakalır. "
            f"{hook.split('Etki:')[0].strip()} gibi bir durum da olunca, mesajın tonu bir anda kontrolünden çıkabilir."
        )
    else:
        situation = (
            f"Ay {month}. Geçen ayki hamlenin yankısı sürüyor: {last_outcome_summary}. "
            "Ekip bu ay ikiye bölünmüş gibi: bir taraf ‘daha çok şey ekleyelim’ derken diğer taraf ‘daha net anlatalım’ diyor. "
            "Kullanıcı tarafında ise aynı davranış tekrar ediyor: bir grup ürünü kendi ihtiyacına göre büküyor, bir grup ‘bu ne’ diye soruyor. "
            "Bu ay, geçen ayın yan etkileri ile bugünün gündemi üst üste binmiş durumda."
        )

    crisis = (
        "Kriz net ve somut: bir kurumsal müşteri toplantıda ürünü övüyor ama cümleyi şu yerden vuruyor: "
        "‘Biz bunu kendi sürecimize uydururuz.’ Ardından farklı ekiplerden birbirini çürüten talepler geliyor; "
        "bir yandan demo isterken diğer yandan ‘rapor’ diye bağırıyorlar. Aynı anda sosyal tarafta bir paylaşım, "
        "ürünün amacını bambaşka yere çekiyor ve destek hattı ‘bu böyle mi çalışmalı’ sorularıyla doluyor. "
        "Bu ay kararın, ya sahneyi tek bir şeye kilitleyecek ya da herkesin seni farklı bir şeye çevirmesine izin verecek."
    )

    # Options: only steps, no outcomes
    option_a_title = "Tek vaat protokolü"
    option_a_body = (
        "1) Ürünün ‘tek cümle’ tanımını yaz ve ekiple aynı cümlede anlaş. "
        "2) İlk deneyimi 3 ekrana indir: giriş → tek görev → tek çıktı. "
        "3) Kurumsal talepleri ‘1 sayfalık kapsam’ dokümanına çevir; imzasız hiçbir şey açma. "
        "4) Destek için tek bir kısa SSS sayfası ve 6 hazır cevap oluştur. "
        "5) Haftalık tek metin: ‘Bu ay neyi yapmıyoruz?’"
    )

    option_b_title = "Çift kulvar planı"
    option_b_body = (
        "1) Ürünü iki kulvara ayır: hızlı kullanım akışı ve derin kullanım akışı. "
        "2) İlk ekranda kullanıcıya tek soru sor: ‘Hız mı, kontrol mü?’ ve akışı ona göre aç. "
        "3) Kurumsal müşteriye ‘şablon rapor’ paketini hazırla; özel istekleri sonraya sırala. "
        "4) Platform/sosyal tarafta dolaşan yanlış anlatıya karşı tek bir kısa açıklama metni yayınla. "
        "5) Altyapı tarafında yoğun işleri sıraya alacak bir limit kuralı koy."
    )

    # enforce no spoilers in fallback too
    option_a_body = remove_sentences_with_forbidden(option_a_body)
    option_b_body = remove_sentences_with_forbidden(option_b_body)

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

    st.session_state.chat: List[Dict[str, str]] = []

    st.session_state.pending_turn: Optional[Dict[str, Any]] = None
    st.session_state.generated_months = set()
    st.session_state.resolved_months = set()

    # New: store per-month outcome summaries to use in situation analysis
    st.session_state.turn_history: List[Dict[str, Any]] = []

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
# Outcome summarizer (qualitative)
# -----------------------------
def qualitative_delta(before: Metrics, after: Metrics) -> str:
    def dir_word(d: float) -> str:
        if abs(d) < 0.5:
            return "hemen hemen aynı"
        return "yükseldi" if d > 0 else "azaldı"

    cash_d = (after.cash - before.cash) / max(1.0, abs(before.cash)) * 100.0
    mrr_d = (after.mrr - before.mrr) / max(1.0, abs(before.mrr) + 1.0) * 100.0
    churn_d = (after.churn - before.churn) * 100.0
    rep_d = after.reputation - before.reputation
    sup_d = after.support_load - before.support_load
    inf_d = after.infra_load - before.infra_load

    # Keep it narrative; no exact numbers
    bits = []
    bits.append(f"kasa {dir_word(cash_d)}")
    bits.append(f"MRR {dir_word(mrr_d)}")
    bits.append("kayıp oranı " + ("yükseldi" if churn_d > 0.2 else "azaldı" if churn_d < -0.2 else "çok değişmedi"))
    bits.append("itibar " + ("toparlandı" if rep_d > 3 else "sarsıldı" if rep_d < -3 else "stabil kaldı"))
    bits.append("destek hattı " + ("kalabalıklaştı" if sup_d > 5 else "rahatladı" if sup_d < -5 else "benzer kaldı"))
    bits.append("altyapı " + ("gerildi" if inf_d > 5 else "sakinleşti" if inf_d < -5 else "benzer kaldı"))
    return ", ".join(bits) + "."


# -----------------------------
# Turn generation (robust)
# -----------------------------
def generate_turn():
    if not st.session_state.game_started:
        return

    month = st.session_state.month
    if month in st.session_state.resolved_months:
        return

    pending = st.session_state.pending_turn
    if pending and pending.get("month") == month:
        return

    mode = st.session_state.mode
    idea = st.session_state.idea.strip()
    character = Character(**st.session_state.character)
    metrics = Metrics(**st.session_state.metrics)

    hook, event_id = pick_hook(mode, month)

    # Avoid repeating style: last 2 assistant msgs
    last_avoid = ""
    for m in reversed(st.session_state.chat[-6:]):
        if m["role"] == "assistant":
            last_avoid += m["content"][:220].replace("\n", " ") + "\n"

    # Last outcome summary for month 2+
    if month > 1 and st.session_state.turn_history:
        last_outcome_summary = st.session_state.turn_history[-1]["summary"]
    else:
        last_outcome_summary = "Ay 1: henüz seçim yok."

    prompt = build_turn_prompt(
        idea=idea,
        character=character,
        metrics=metrics,
        mode=mode,
        month=month,
        season_len=st.session_state.season_len,
        hook=hook,
        last_style_avoid=last_avoid.strip() or "Yok",
        last_outcome_summary=last_outcome_summary,
    )

    raw = llm_call(prompt, temperature=0.95 if mode == "Extreme" else 0.85, max_tokens=950)
    data = extract_json(raw)

    # Repair attempt if parse failed
    if data is None and raw:
        repair_prompt = f"""
Aşağıdaki metni TEK BİR JSON objesine dönüştür.
SADECE JSON ver.

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
        raw2 = llm_call(repair_prompt, temperature=0.2, max_tokens=750)
        data = extract_json(raw2)

    if data is None:
        turn = local_fallback_turn(month, mode, idea, metrics, hook, event_id, last_outcome_summary)
    else:
        def g(k: str, default: str) -> str:
            v = str(data.get(k, "")).strip()
            return v if v else default

        turn = TurnContent(
            month=month,
            teaser=g("teaser", "Bu ay sahne kayıyor; küçük bir yanlış anlaşılma büyük bir yangına dönüşebilir."),
            situation=g("situation", "Bu ay durum analizi: sahne kayıyor, ekip/ürün/mesaj arasında boşluk var."),
            crisis=g("crisis", "Kriz net: bugün olan şeyin sebebi ve acısı açık; karar gecikirse hasar büyür."),
            option_a_title=g("option_a_title", "A Planı"),
            option_a_body=g("option_a_body", "Net bir hamle planı: 3-5 adım."),
            option_b_title=g("option_b_title", "B Planı"),
            option_b_body=g("option_b_body", "Alternatif hamle planı: 3-5 adım."),
            event_id=event_id,
        )

        # HARD ENFORCEMENT:
        turn.option_a_body = remove_sentences_with_forbidden(turn.option_a_body)
        turn.option_b_body = remove_sentences_with_forbidden(turn.option_b_body)
        turn.crisis = strip_numbers_in_crisis(turn.crisis)

    st.session_state.pending_turn = asdict(turn)

    # Post to chat once per month
    if month not in st.session_state.generated_months:
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
    before = Metrics(**st.session_state.metrics)
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
        if r.random() < 0.28:
            mrr_delta += r.uniform(800, 7000)
            rep_delta += r.uniform(6, 18)
        if r.random() < 0.22:
            churn_delta += r.uniform(0.01, 0.07)
            rep_delta -= r.uniform(6, 16)

    metrics.mrr = max(0, metrics.mrr + mrr_delta)
    metrics.churn = clamp(metrics.churn + churn_delta, 0.0, 0.35)
    metrics.reputation = clamp(metrics.reputation + rep_delta, 0.0, 100.0)
    metrics.support_load = clamp(metrics.support_load + support_delta, 0.0, 100.0)
    metrics.infra_load = clamp(metrics.infra_load + infra_delta, 0.0, 100.0)

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

    title = pending["option_a_title"] if choice == "A" else pending["option_b_title"]
    chat_add("user", f"Seçimim: **{choice}** — {title}")

    # Save qualitative outcome summary for next month situation analysis
    summary = qualitative_delta(before, metrics)
    st.session_state.turn_history.append({
        "month": month,
        "choice": choice,
        "title": title,
        "summary": f"Ay {month} seçimi ({choice} — {title}) sonrası: {summary}"
    })

    # Reveal consequences AFTER choice (this is the point of the game)
    chat_add(
        "assistant",
        "✅ Seçimin işlendi. Sonuçları görüyorsun:\n\n"
        f"• Kasa: {fmt_try(metrics.cash)}\n"
        f"• MRR: {fmt_try(metrics.mrr)}\n"
        f"• Kayıp Oranı: %{metrics.churn*100:.1f}\n"
        f"• İtibar: {metrics.reputation:.0f}/100\n"
        f"• Support: {metrics.support_load:.0f}/100\n"
        f"• Altyapı: {metrics.infra_load:.0f}/100"
    )

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
    st.session_state.mode = st.sidebar.selectbox("Mod", MODES, index=MODES.index(st.session_state.mode))

    st.session_state.season_len = st.sidebar.slider("Sezon uzunluğu (ay)", 3, 36, int(st.session_state.season_len))
    st.sidebar.caption(f"Ay: **{st.session_state.month}/{st.session_state.season_len}**")
    st.sidebar.progress(st.session_state.month / max(1, st.session_state.season_len))

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
        st.caption("Model yoksa da oyun çalışır; ama kalite için Gemini önerilir.")

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
        st.session_state.turn_history = []

        chat_add("assistant", f"Tamam **{st.session_state.character['name']}**. Mod: **{st.session_state.mode}**. Ay 1’e giriyoruz.")
        chat_add("assistant", "Kural: Önce soğuk açılış, sonra durum analizi, sonra net kriz, sonra A/B.")
        st.rerun()


def gameplay_screen():
    top_right_character_panel()

    generate_turn()
    render_chat()

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
