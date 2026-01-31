# Startup Survivor RPG - Single-file Streamlit App
# - Fixes: st.escape AttributeError, duplicate month outputs, chat-style flow
# - Modes: Realist / Hard / Spartan / Extreme / Türkiye
# - Seasons: Free / Real-life inspired arcs
# - Options show only "what you'll do" (no outcome spoilers)
# - Crisis text: narrative, no metric clutter
# - Analysis: Month1 idea analysis; later months analyze previous choice effects

import os
import json
import random
import re
import html
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

# -----------------------------
# Page + Style
# -----------------------------
st.set_page_config(page_title="Startup Survivor RPG", page_icon="🧠", layout="wide")

CSS = """
<style>
/* Layout tightening */
.block-container { padding-top: 1.2rem; padding-bottom: 2.2rem; max-width: 1200px; }

/* Chat bubbles a bit denser */
.stChatMessage { margin-bottom: 0.65rem; }

/* Option cards */
.choice-wrap {
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 14px;
  padding: 16px 16px 14px 16px;
  background: rgba(255,255,255,0.03);
  height: 100%;
}
.choice-title {
  font-size: 1.6rem;
  font-weight: 800;
  margin: 0 0 10px 0;
}
.choice-steps {
  margin: 0;
  padding-left: 1.1rem;
  line-height: 1.55;
  color: rgba(255,255,255,0.88);
}
.choice-steps li { margin-bottom: 0.35rem; }
.choice-btn-row { margin-top: 12px; }

/* Subtle section headers */
.small-hdr { color: rgba(255,255,255,0.72); font-size: 0.95rem; margin-top: 0.6rem; }

/* Sidebar stats */
.statbox {
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 14px;
  padding: 14px;
  background: rgba(255,255,255,0.03);
}
.statbig { font-size: 2.2rem; font-weight: 900; margin: 0.2rem 0 0.4rem 0; }
.muted { color: rgba(255,255,255,0.6); }

/* Remove default list padding for our html UL in options */
ul.choice-steps { margin-top: 0.2rem; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# -----------------------------
# Gemini (optional)
# -----------------------------
def _get_api_keys() -> List[str]:
    keys: List[str] = []
    # Streamlit secrets (TOML)
    try:
        if "GEMINI_API_KEY" in st.secrets:
            v = st.secrets["GEMINI_API_KEY"]
            if isinstance(v, list):
                keys += [str(x).strip() for x in v if str(x).strip()]
            elif isinstance(v, str):
                keys += [k.strip() for k in v.split(",") if k.strip()]
    except Exception:
        pass

    # Env fallback
    env = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
    if env.strip():
        keys += [k.strip() for k in env.split(",") if k.strip()]

    # Dedup keep order
    seen = set()
    out = []
    for k in keys:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out

@st.cache_resource(show_spinner=False)
def _get_gemini_client():
    # Import lazily; if not installed, we run with fallback generator
    try:
        import google.generativeai as genai  # type: ignore
    except Exception:
        return None
    return genai

def gemini_generate(prompt: str, temperature: float = 0.9, model_name: str = "gemini-1.5-flash") -> Optional[str]:
    genai = _get_gemini_client()
    keys = _get_api_keys()
    if genai is None or not keys:
        return None

    # rotate key to avoid limits
    idx = st.session_state.get("_key_idx", 0) % len(keys)
    st.session_state["_key_idx"] = idx + 1
    key = keys[idx]

    try:
        genai.configure(api_key=key)
        model = genai.GenerativeModel(model_name)
        resp = model.generate_content(
            prompt,
            generation_config={
                "temperature": temperature,
                "top_p": 0.95,
                "top_k": 40,
                "max_output_tokens": 800,
            },
        )
        text = getattr(resp, "text", None)
        if text:
            return text.strip()
        return None
    except Exception:
        return None

# -----------------------------
# Game Data
# -----------------------------
MODS = {
    "Gerçekçi": {
        "desc": "Dengeli, rasyonel, gerçekçi piyasa baskısı. Mantıklı kararlar istikrarlı ödüllenir.",
        "tone": "dengeli, profesyonel, net",
        "volatility": 0.45,
        "punish": 0.75,
        "absurdity": 0.05,
        "turkey": False,
    },
    "Zor": {
        "desc": "Kaynak kısıtlı, her seçimin bedeli var. Kolay çıkış yok.",
        "tone": "sert, gerçekçi, tavizsiz",
        "volatility": 0.65,
        "punish": 1.0,
        "absurdity": 0.10,
        "turkey": False,
    },
    "Spartan": {
        "desc": "Acımasız. Hukuki/teknik/finansal engeller yoğun. Hayatta kalma testi.",
        "tone": "acımasız, baskıcı, keskin",
        "volatility": 0.85,
        "punish": 1.25,
        "absurdity": 0.12,
        "turkey": False,
    },
    "Extreme": {
        "desc": "Kaos ve absürt. Paylaşmalık olaylar. Mantık ikinci planda, sonuç metriklere çarpar.",
        "tone": "komik, absürt, hızlı tempo, meme’lik",
        "volatility": 1.15,
        "punish": 0.95,
        "absurdity": 0.92,  # very high
        "turkey": False,
    },
    "Türkiye": {
        "desc": "Türkiye şartları: kur/enflasyon, tahsilat, vergi/SGK, bürokrasi, 'son dakika' sürprizleri.",
        "tone": "Türkiye gerçekliği, pratik, yerel detaylı",
        "volatility": 0.9,
        "punish": 1.05,
        "absurdity": 0.20,
        "turkey": True,
    },
}

# “Gerçek vakalar” -> isim vermeden, esinli (daha güvenli/kolay)
REAL_SEASONS = {
    "Serbest (Rastgele)": [],
    "Gerçek Vakalar (Esinli) — Hiper Büyüme": [
        {
            "id": "hypergrowth_quality",
            "title": "Hızlı büyüme, kalite çöküşü",
            "blurb": "Bir anda patlayan talep; altyapı, support ve itibar aynı anda geriliyor.",
        },
        {
            "id": "viral_misuse",
            "title": "Viral oldu ama yanlış anlaşıldı",
            "blurb": "Ürün sosyal medyada başka amaçla kullanılınca PR ve churn tırmanıyor.",
        },
    ],
    "Gerçek Vakalar (Esinli) — Güven & İtibar": [
        {
            "id": "trust_crisis",
            "title": "Güven krizi / şüphe dalgası",
            "blurb": "Komplo anlatıları, yanlış bilgiler ve panik; satıştan önce güveni tamir etmelisin.",
        },
        {
            "id": "enterprise_scope",
            "title": "Kurumsal scope patlaması",
            "blurb": "‘Bizde süreç Excel’ diyen müşteri, ürününü şekilsizleştiriyor.",
        },
    ],
    "Gerçek Vakalar (Esinli) — Regülasyon": [
        {
            "id": "compliance_wave",
            "title": "Uyumluluk dalgası",
            "blurb": "Bir düzenleme/uyumluluk talebi işini bir gecede değiştiriyor.",
        },
    ],
}

# Extreme event seed bank (no repeats until exhausted)
EXTREME_SEEDS = [
    {"id": "ex_01", "hook": "Bir influencer ürününü överken yanlış özelliği övüyor; herkes o ‘olmayan’ şeyi istiyor.", "cat": "social"},
    {"id": "ex_02", "hook": "Ürün demosu bir anda ‘terapi’ TikTok’unda trend oluyor; kullanıcılar onboarding’i seans sanıyor.", "cat": "social"},
    {"id": "ex_03", "hook": "Bir meme sayfası uygulamanın adını yanlış yazıyor; yanlış isim App Store’da trend oluyor.", "cat": "social"},
    {"id": "ex_04", "hook": "Kurumsal müşteri ‘AI güzel ama bizde süreç Excel’ diyerek ürününü Excel’e dönüştürmeye kalkıyor.", "cat": "corp"},
    {"id": "ex_05", "hook": "Kullanıcılar ürünün bir butonunu ‘kader butonu’ sanıp ritüel yapıyor; support’a dua yazıyorlar.", "cat": "surreal"},
    {"id": "ex_06", "hook": "Bir rakip, senin onboarding ekranını ‘challenge’ yapıyor; herkes 3 saniyede çıkıyor.", "cat": "social"},
    {"id": "ex_07", "hook": "Ürün logosu yanlışlıkla bir futbol tribün sloganına benziyor; maç günü trafik patlıyor.", "cat": "social"},
    {"id": "ex_08", "hook": "Ürün ekran görüntüsü ‘dolandırıcılık uyarısı’ diye paylaşılıyor; itibar bir gecede dalgalanıyor.", "cat": "social"},
    {"id": "ex_09", "hook": "Bir podcast’te adın geçiyor ama sunucu ürününü ‘yeni bir din’ sanıyor.", "cat": "social"},
    {"id": "ex_10", "hook": "Bir kurumsal ekip ‘17 kolonluk istek listesi’ atıyor: ‘Bunu yarına yetiştirir misiniz?’", "cat": "corp"},
    {"id": "ex_11", "hook": "Kullanıcılar ürünün içinde ‘gizli mesaj’ arıyor; her bug ‘kanıt’ oluyor.", "cat": "surreal"},
    {"id": "ex_12", "hook": "Bir ödeme sağlayıcısı ‘risk’ deyip ödemeleri askıya alıyor; herkes bedava kullanıyor.", "cat": "corp"},
    {"id": "ex_13", "hook": "Bir AI hesabı seni ‘dünya kurtaran uygulama’ diye etiketliyor; yanlış beklenti tsunami.", "cat": "social"},
    {"id": "ex_14", "hook": "Ürünün ismi bir şehirdeki meşhur tostçuyla çakışıyor; yorumlar tost üzerinden geliyor.", "cat": "social"},
    {"id": "ex_15", "hook": "Bir kullanıcı 1 yıldız veriyor: ‘Çok iyi ama beni duygulandırdı.’ Herkes aynı yorumu kopyalıyor.", "cat": "social"},
    {"id": "ex_16", "hook": "Sunucuların ‘bakım’ bildirimi bir anda ‘müzik festivali lineup’ı sanılıyor.", "cat": "social"},
    {"id": "ex_17", "hook": "Bir Slack emoji’si ürünün resmi ‘roadmap’i sanılıyor; kurumsallar plan diye yapışıyor.", "cat": "corp"},
    {"id": "ex_18", "hook": "Ürünün ‘beta’ etiketi, kullanıcılar tarafından ‘bedava ömür boyu’ sanılıyor.", "cat": "social"},
    {"id": "ex_19", "hook": "Bir viral video, ürününü ‘ekran okuma’ yerine ‘ekran falı’ diye anlatıyor.", "cat": "surreal"},
    {"id": "ex_20", "hook": "Bir büyüme danışmanı ‘tek vaat tek sahne’ diye bağırıyor; ekip ikiye bölünüyor.", "cat": "corp"},
]

TURKEY_SEEDS = [
    {"id": "tr_01", "hook": "Kur artışı yüzünden yabancı servis faturası iki katına yaklaşıyor; herkes ‘iptal edelim’ diyor."},
    {"id": "tr_02", "hook": "Tahsilat 45 güne kayıyor; nakit akışı ‘sanki varmış gibi’ görünüyor ama kasaya girmiyor."},
    {"id": "tr_03", "hook": "Bir müşteri ‘fatura kesmeden alamayız’ diyor; e-fatura/e-arşiv süreci haftanı yiyor."},
    {"id": "tr_04", "hook": "SGK/yan haklar kalemi beklenmedik büyüyor; maaş aynı ama toplam yük artıyor."},
    {"id": "tr_05", "hook": "KVKK soruları artıyor: ‘veri nerede, nasıl saklanıyor?’ Satışın önüne duvar oluyor."},
]

GENERIC_SEEDS = [
    {"id": "g_01", "hook": "Ürünü duyanlar merak ediyor ama herkes farklı şey anlıyor; mesaj tek bir cümleye sığmıyor."},
    {"id": "g_02", "hook": "İlk kullanıcılar geliyor; biri bayılıyor, biri ‘ne aldım ben?’ diye çıkıyor."},
    {"id": "g_03", "hook": "Kurumsal taraftan küçük bir fırsat var ama scope genişlerse ürün odağı kayabilir."},
    {"id": "g_04", "hook": "Altyapı küçükken sorun yok, ama bir tık büyümede gecikmeler başlıyor."},
]

# -----------------------------
# Helpers
# -----------------------------
def money(n: float) -> str:
    try:
        return f"{int(round(n)):,}".replace(",", ".") + " ₺"
    except Exception:
        return f"{n} ₺"

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def add_message_once(msg_id: str, role: str, content: str):
    if "msg_ids" not in st.session_state:
        st.session_state.msg_ids = set()
    if msg_id in st.session_state.msg_ids:
        return
    st.session_state.msg_ids.add(msg_id)
    st.session_state.chat.append({"id": msg_id, "role": role, "content": content})

def render_steps_html(steps: List[str]) -> str:
    safe = [html.escape(str(s)) for s in (steps or [])]
    items = "".join(f"<li>{s}</li>" for s in safe)
    return f"<ul class='choice-steps'>{items}</ul>"

def pick_seed(mode_name: str) -> Dict[str, Any]:
    mode = MODS[mode_name]
    used = st.session_state.get("used_seed_ids", set())
    if mode_name == "Extreme":
        pool = EXTREME_SEEDS
    elif mode.get("turkey"):
        pool = TURKEY_SEEDS
    else:
        pool = GENERIC_SEEDS

    # Try non-used first
    candidates = [s for s in pool if s["id"] not in used]
    if not candidates:
        # reset if exhausted (but keep last few? simple reset)
        used = set()
        st.session_state.used_seed_ids = used
        candidates = pool[:]
    seed = random.choice(candidates)
    used.add(seed["id"])
    st.session_state.used_seed_ids = used
    return seed

def choose_season_scenario(season_name: str) -> Dict[str, Any]:
    if season_name == "Serbest (Rastgele)":
        # pick from all other seasons combined for variety
        all_s = []
        for k, v in REAL_SEASONS.items():
            if v:
                all_s.extend(v)
        if not all_s:
            return {"id": "free", "title": "Serbest", "blurb": "Rastgele olaylar."}
        return random.choice(all_s)
    pool = REAL_SEASONS.get(season_name, [])
    if not pool:
        return {"id": "free", "title": "Serbest", "blurb": "Rastgele olaylar."}
    return random.choice(pool)

def qualitative_runway(cash: float, burn: float) -> str:
    if burn <= 0:
        return "kasan şimdilik yanmıyor"
    m = cash / burn
    if m < 1.2:
        return "kasanın ucu görünüyor (1 ay civarı)"
    if m < 3:
        return "2–3 aylık nefes var"
    if m < 6:
        return "birkaç aylık manevra alanın var"
    return "rahat sayılabilecek bir runway var"

# -----------------------------
# Content generation (LLM + fallback)
# -----------------------------
def build_prompt_analysis(game: Dict[str, Any], seed: Dict[str, Any]) -> str:
    mode = game["mode"]
    m = game["month"]
    idea = game["idea"]
    scenario = game["scenario"]
    last = game.get("last_choice_summary", "")

    rules = []
    rules.append("Türkçe yaz.")
    rules.append("1 paragraf, 110-170 kelime. Hikayesel ama anlaşılır.")
    rules.append("Liste/numara yok.")
    rules.append("Kasa/MRR gibi sayıları burada dökme; sadece durumun anlamını anlat.")
    if mode == "Extreme":
        rules.append("Extreme mod: cümleler meme’lik, komik ve absürt olabilir ama startup gerçeğine bağlanmalı.")
    if game["mode"] == "Türkiye":
        rules.append("Türkiye modu: yerel iş yapma gerçekliği (tahsilat, kur, e-fatura, KVKK, SGK) gibi detaylar hissedilsin.")

    if m == 1:
        ctx = f"Kurucu fikri: {idea}\nSezon teması: {scenario['title']} — {scenario.get('blurb','')}\nSeed: {seed['hook']}"
        task = "Ay 1 durum analizi: fikrin vaadini, yanlış anlaşılma riskini, ilk değer önerisini ve ilk dar boğazı anlat."
    else:
        ctx = f"Önceki seçim özeti: {last}\nSezon teması: {scenario['title']} — {scenario.get('blurb','')}\nBu ayın kıvılcımı: {seed['hook']}"
        task = "Ay durum analizi: önceki seçimin etkisini (ekip odağı, ürün mesajı, kullanıcı beklentisi) üzerinden yorumla. Bu ay neden kritik?"

    return f"""
Sen bir startup RPG anlatıcısısın. Ton: {MODS[mode]['tone']}.
Kurallar:
- {"; ".join(rules)}

Bağlam:
{ctx}

Görev:
{task}
""".strip()

def build_prompt_crisis(game: Dict[str, Any], seed: Dict[str, Any]) -> str:
    mode = game["mode"]
    cash = game["metrics"]["cash"]
    burn = game["metrics"]["burn"]
    runway = qualitative_runway(cash, burn)

    rules = []
    rules.append("Türkçe yaz.")
    rules.append("2-4 paragraf. Kriz net, somut, anlaşılır olsun.")
    rules.append("Kasa/MRR sayısı yazma; sadece baskıyı ve sonucu anlat.")
    rules.append("Kriz, startup metriklerine dolaylı bağlansın: itibar, kayıp oranı, support yükü, altyapı yükü, MRR.")
    rules.append("Okuyan ekran görüntüsü almak istesin: 1 cümle ‘alıntılanabilir’ punchline olsun.")
    if mode == "Extreme":
        rules.append("Extreme mod: olayın %80’i sosyal medya/platform/influencer/kurumsal saçmalık/kullanıcı davranışı kaynaklı absürtlük olsun. Mantık şart değil; komiklik ve özgünlük şart.")
        rules.append("Ama sonuç gerçek: support/altyapı/itibar/kayıp oranı etkilenir.")
    if game["mode"] == "Türkiye":
        rules.append("Türkiye modu: tahsilat/kur/vergi/uyumluluk gibi yerel baskı hissedilsin (dayı faktörü yok).")

    scenario = game["scenario"]

    return f"""
Sen bir startup RPG anlatıcısısın. Ton: {MODS[mode]['tone']}.
Kurallar:
- {"; ".join(rules)}

Sezon teması: {scenario['title']} — {scenario.get('blurb','')}
Bu ayın kıvılcımı: {seed['hook']}
Runway hissi: {runway}

Görev:
Ay {game['month']} için krizi yaz. Kriz bir şeyleri KIRILMA NOKTASINA getirsin ve karar zorunlu olsun.
""".strip()

def build_prompt_options(game: Dict[str, Any], seed: Dict[str, Any]) -> str:
    mode = game["mode"]
    rules = []
    rules.append("Türkçe yaz.")
    rules.append("Sadece JSON üret. Açıklama, başlık, markdown yok.")
    rules.append("JSON şema: {\"A\":{\"title\":str,\"steps\":[str,...]},\"B\":{\"title\":str,\"steps\":[str,...]}}")
    rules.append("Her seçenek 3-5 adım içersin. Adımlar ‘ne yapacağını’ söylesin, SONUÇ söylemesin.")
    rules.append("Trade-off / ‘support artar’ / ‘MRR düşer’ gibi spoiler yazma.")
    if mode == "Extreme":
        rules.append("Extreme: başlıklar komik/absürt olabilir ama uygulanabilir aksiyonlar içersin.")
    if game["mode"] == "Türkiye":
        rules.append("Türkiye: adımlar yerel pratiklerle uyumlu olsun (e-fatura, tahsilat, KVKK, kur riski vb.).")

    scenario = game["scenario"]
    last = game.get("last_choice_summary", "")

    return f"""
Kurallar:
- {"; ".join(rules)}

Bağlam:
Sezon: {scenario['title']} — {scenario.get('blurb','')}
Ay: {game['month']}
Önceki seçim: {last}
Kıvılcım: {seed['hook']}

Görev:
Bu krize cevap olacak iki seçenek üret (A ve B). Sonuç söylemeden plan adımlarını yaz.
""".strip()

def parse_options_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    # find JSON object
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    raw = m.group(0)
    try:
        data = json.loads(raw)
        if "A" in data and "B" in data:
            return data
        return None
    except Exception:
        return None

def fallback_options(game: Dict[str, Any]) -> Dict[str, Any]:
    mode = game["mode"]
    if mode == "Extreme":
        return {
            "A": {"title": "Tek vaat protokolü", "steps": ["Tek cümlelik vaat yaz ve her yere yapıştır.", "Onboarding’i 3 ekrana indir: giriş → tek görev → tek çıktı.", "SSS sayfasını tek soruya indir ve 6 hazır cevap ekle.", "Kurumsal istekleri tek sayfalık kapsama notuna bağla."]},
            "B": {"title": "Çift kulvar planı", "steps": ["Ürünü iki akışa ayır: hızlı kullanım / derin kullanım.", "İlk ekranda tek soru sor ve akışı ona göre aç.", "Kurumsala ‘şablon rapor’ paketi çıkar; özel istekleri sıraya al.", "Support taleplerini tek formda topla ve etiketle."]},
        }
    if mode == "Türkiye":
        return {
            "A": {"title": "Tahsilat + kur kalkanı", "steps": ["Fiyatı TL’ye sabitle ve kur riski kalemini ayrı yaz.", "Tahsilatı kısaltacak teklif çıkar: peşin/3 aylık paket.", "E-fatura/e-arşiv sürecini 1 akışta netleştir.", "KVKK metnini sadeleştir ve tek sayfa onay akışı yap."]},
            "B": {"title": "Maliyet budama sprinti", "steps": ["Yabancı servisleri listele ve 48 saatte gereksizleri kapat.", "En pahalı kalemi alternatifle değiştir (aynı işi gören).", "Sunucu/altyapıda limit ve cache ayarlarını sıkılaştır.", "Satış tarafında tek hedef müşteri profiline odaklan."]},
        }
    return {
        "A": {"title": "Tek mesaj, tek sahne", "steps": ["Değer önerisini tek cümleye indir.", "Onboarding’i tek başarı anına bağla.", "En kritik hatayı kapat ve bir demo videosu çek.", "Support için 10 hazır cevap oluştur."]},
        "B": {"title": "Kontrollü büyüme filtresi", "steps": ["Kullanıcı girişini ikiye ayır: hızlı/derin.", "Yanlış kullanım alanlarını uyarı metniyle kapat.", "Kurumsal talepleri şablonla sınırla.", "Geri bildirimleri tek kanalda topla."]},
    }

def fallback_text_analysis(game: Dict[str, Any], seed: Dict[str, Any]) -> str:
    m = game["month"]
    if m == 1:
        return (
            f"Ay 1: Fikrin dikkat çekiyor ama sahne kaygan: insanlar duyunca farklı şey hayal ediyor. "
            f"Bu tip ürünlerde asıl risk ‘ürün kötü’ olması değil, ‘ne olduğu’ netleşmeden büyümeye zorlanması. "
            f"Birileri seni övüyor, birileri yanlış kitleye çekiyor; bu ikisi aynı anda olunca ilk temas sürtünmeye dönüyor. "
            f"Bugün netleştirmezsen yarın her yeni özellik ‘yanlış beklentiye hizmet eden’ bir süs olur."
        )
    else:
        last = game.get("last_choice_summary", "Geçen ay bir karar verdin.")
        return (
            f"Ay {m}: Geçen ayın seçimi hâlâ odada. {last} Bu karar, ekibin refleksini belirledi: "
            f"ya netlik için kesip attın ya da iki kulvarla kontrol etmeye çalıştın. "
            f"Şimdi kıvılcım yeniden çakıyor: {seed['hook']} Eğer bu ay mesajın direksiyonunu bırakırsan, "
            f"ürün değil söylenti büyür; söylenti büyürse support ve itibar aynı anda yıpranır."
        )

def fallback_text_crisis(game: Dict[str, Any], seed: Dict[str, Any]) -> str:
    mode = game["mode"]
    punch = "Bugün karar vermezsen, yarın ‘karar’ seni verir."
    if mode == "Extreme":
        punch = "Ürün değil, yanlış anlaşılma büyüyor — ve o her zaman senden hızlı koşar."
    if mode == "Türkiye":
        punch = "Türkiye’de en pahalı şey belirsizlik: hem kur oynar, hem müşteri."

    return (
        f"{seed['hook']}\n\n"
        f"Bir yandan ekip ‘hepsini yapalım’ diye gaza geliyor, diğer yandan kullanıcılar aynı ekranı bambaşka amaçla kullanıyor. "
        f"Kriz şu: tek bir hikâyeye kilitlemezsen herkes seni kendi hikâyesine çeviriyor. "
        f"Bu da itibarın tonunu bozuyor, support yükünü şişiriyor ve altyapıyı ‘bir anda’ yavaşlatıyor.\n\n"
        f"{punch}"
    )

def generate_month_packet(game: Dict[str, Any]) -> Dict[str, Any]:
    seed = pick_seed(game["mode"])

    # 1) analysis
    p = build_prompt_analysis(game, seed)
    analysis = gemini_generate(p, temperature=0.9)
    if not analysis:
        analysis = fallback_text_analysis(game, seed)

    # 2) crisis
    p = build_prompt_crisis(game, seed)
    crisis = gemini_generate(p, temperature=0.95 if game["mode"] == "Extreme" else 0.85)
    if not crisis:
        crisis = fallback_text_crisis(game, seed)

    # 3) options (JSON)
    p = build_prompt_options(game, seed)
    opt_raw = gemini_generate(p, temperature=0.9)
    opts = parse_options_json(opt_raw or "") if opt_raw else None
    if not opts:
        opts = fallback_options(game)

    # normalize
    for k in ["A", "B"]:
        opts[k]["title"] = str(opts[k].get("title", "")).strip()[:80]
        steps = opts[k].get("steps", [])
        if not isinstance(steps, list):
            steps = [str(steps)]
        opts[k]["steps"] = [str(s).strip()[:140] for s in steps if str(s).strip()][:5]

    return {
        "seed": seed,
        "analysis": analysis.strip(),
        "crisis": crisis.strip(),
        "options": opts,
    }

# -----------------------------
# Metrics engine (simple + mod-sensitive)
# -----------------------------
def init_metrics(start_cash: float) -> Dict[str, Any]:
    # expenses are monthly; you can edit defaults
    expenses = {"Maşlar": 50000, "Sunucu": 6100, "Pazarlama": 5300}
    burn = sum(expenses.values())
    return {
        "cash": float(start_cash),
        "mrr": 0.0,
        "itibar": 50.0,         # 0-100
        "support": 20.0,        # 0-100
        "altyapi": 20.0,        # 0-100
        "kayip_orani": 5.0,     # percent 0-30
        "expenses": expenses,
        "burn": float(burn),
    }

def apply_choice(game: Dict[str, Any], choice: str, free_text: str = "") -> Tuple[str, Dict[str, float]]:
    """Returns (outcome_narrative, delta_metrics)"""
    mode = MODS[game["mode"]]
    vol = mode["volatility"]
    punish = mode["punish"]
    absurd = mode["absurdity"]

    # Base deltas
    r = random.random()
    wild = (absurd > 0.6)

    # Create a bias: A tends toward "focus", B tends toward "filter/structure"
    if choice == "A":
        d_itibar = random.uniform(-3, 8) * (1.0 if not wild else 1.2)
        d_support = random.uniform(-8, 4) * (1.0 if not wild else 1.3)
        d_altyapi = random.uniform(-6, 6) * (1.0 if not wild else 1.4)
        d_kayip = random.uniform(-2.2, 1.5) * (1.0 if not wild else 1.3)
        d_mrr = random.uniform(-120, 520) * (1.0 if not wild else 1.6)
    else:
        d_itibar = random.uniform(-2, 10) * (1.0 if not wild else 1.25)
        d_support = random.uniform(-10, 2) * (1.0 if not wild else 1.35)
        d_altyapi = random.uniform(-10, 2) * (1.0 if not wild else 1.35)
        d_kayip = random.uniform(-2.8, 1.2) * (1.0 if not wild else 1.25)
        d_mrr = random.uniform(-80, 420) * (1.0 if not wild else 1.4)

    # Harder modes punish more volatility
    # punish > 1 increases negatives, reduces positives slightly
    def skew(x: float) -> float:
        if x >= 0:
            return x * (1.0 - (punish - 1.0) * 0.25)
        return x * punish

    d_itibar = skew(d_itibar) * vol
    d_support = skew(d_support) * vol
    d_altyapi = skew(d_altyapi) * vol
    d_kayip = skew(d_kayip) * vol
    d_mrr = skew(d_mrr) * vol

    # Cash changes: burn happens + random incident cost
    burn = game["metrics"]["burn"]
    incident_cost = random.uniform(0.15, 0.55) * burn * (1.0 + absurd * 0.6)
    d_cash = -(burn + incident_cost) + max(0, d_mrr) * random.uniform(0.1, 0.35)

    # Clamp and apply
    m = game["metrics"]
    before = m.copy()

    m["mrr"] = max(0.0, m["mrr"] + d_mrr)
    m["cash"] = max(0.0, m["cash"] + d_cash)
    m["itibar"] = clamp(m["itibar"] + d_itibar, 0, 100)
    m["support"] = clamp(m["support"] + d_support, 0, 100)
    m["altyapi"] = clamp(m["altyapi"] + d_altyapi, 0, 100)
    m["kayip_orani"] = clamp(m["kayip_orani"] + d_kayip, 0, 30)

    # Outcome narrative (LLM optional but keep short)
    month = game["month"]
    seed = game["current_packet"]["seed"]["hook"]
    title = game["current_packet"]["options"][choice]["title"]

    # Lightweight prompt for outcome
    outcome_prompt = f"""
Türkçe yaz. 2 paragraf.
Paragraf 1: Ay {month} sonucu: seçilen plan "{title}" uygulandı. Olay kıvılcımı: {seed}. 80-130 kelime.
Paragraf 2: tek cümle punchline (alıntılanabilir). (Extreme ise komik ve paylaşmalık olsun.)
Sayı dökme yok.
Not: Kullanıcı şunu da yazdı: {free_text}
Mod tonu: {MODS[game["mode"]]["tone"]}
"""
    out = gemini_generate(outcome_prompt, temperature=0.95 if game["mode"] == "Extreme" else 0.75)
    if not out:
        if game["mode"] == "Extreme":
            out = (
                f"Ay {month}: '{title}' ile sahneyi tek bir şeye kilitlemeye çalıştın ama internet yine kendi senaryosunu yazdı. "
                f"{seed} Ekip bir yandan toparlanırken, kullanıcılar ‘bu bir özellik mi yoksa işaret mi?’ diye birbirini gaza getirdi. "
                f"Sen toparlamaya çalıştıkça olay daha paylaşılır hâle geldi; paylaşılır oldukça support yağdı.\n\n"
                f"Punchline: ‘Ürün değil, yanlış anlaşılma büyüyor — ve o hep senden hızlı koşuyor.’"
            )
        else:
            out = (
                f"Ay {month}: '{title}' ile krizi bir çerçeveye aldın. {seed} Bu hamle, ekibi daha net bir ritme soktu ama "
                f"herkesin aynı şeyi anlaması zaman aldı. İyi haber: gürültü azaldı. Kötü haber: bazı beklentileri kapatırken "
                f"bazı fırsatları da kapatmış oldun.\n\n"
                f"Punchline: ‘Netlik bazen büyüme değil, hayatta kalma aracıdır.’"
            )

    deltas = {
        "cash": m["cash"] - before["cash"],
        "mrr": m["mrr"] - before["mrr"],
        "itibar": m["itibar"] - before["itibar"],
        "support": m["support"] - before["support"],
        "altyapi": m["altyapi"] - before["altyapi"],
        "kayip_orani": m["kayip_orani"] - before["kayip_orani"],
    }
    return out.strip(), deltas

# -----------------------------
# Session State
# -----------------------------
def reset_game():
    for k in list(st.session_state.keys()):
        del st.session_state[k]

def ensure_state():
    if "chat" not in st.session_state:
        st.session_state.chat = []
    if "game_started" not in st.session_state:
        st.session_state.game_started = False
    if "month" not in st.session_state:
        st.session_state.month = 1
    if "season_len" not in st.session_state:
        st.session_state.season_len = 12
    if "mode" not in st.session_state:
        st.session_state.mode = "Extreme"
    if "season_name" not in st.session_state:
        st.session_state.season_name = "Serbest (Rastgele)"
    if "scenario" not in st.session_state:
        st.session_state.scenario = choose_season_scenario(st.session_state.season_name)
    if "idea" not in st.session_state:
        st.session_state.idea = ""
    if "player_name" not in st.session_state:
        st.session_state.player_name = "İsimsiz Girişimci"
    if "metrics" not in st.session_state:
        st.session_state.metrics = init_metrics(1_000_000)
    if "current_packet" not in st.session_state:
        st.session_state.current_packet = None
    if "choice_done" not in st.session_state:
        st.session_state.choice_done = False
    if "last_choice_summary" not in st.session_state:
        st.session_state.last_choice_summary = ""
    if "used_seed_ids" not in st.session_state:
        st.session_state.used_seed_ids = set()
    if "msg_ids" not in st.session_state:
        st.session_state.msg_ids = set()

ensure_state()

# -----------------------------
# Sidebar
# -----------------------------
with st.sidebar:
    st.markdown("### " + st.session_state.player_name)

    st.session_state.mode = st.selectbox(
        "Mod",
        list(MODS.keys()),
        index=list(MODS.keys()).index(st.session_state.mode),
        help="Mod tonu ve olayların sertliği buna göre değişir.",
    )
    st.caption(MODS[st.session_state.mode]["desc"])

    st.session_state.season_name = st.selectbox(
        "Vaka sezonu (opsiyonel)",
        list(REAL_SEASONS.keys()),
        index=list(REAL_SEASONS.keys()).index(st.session_state.season_name),
        help="Gerçek hayattan esinli sezonlar: isim vermeden, mekanik olarak benzer krizler.",
    )

    # only allow changing scenario before game start
    if not st.session_state.game_started:
        st.session_state.scenario = choose_season_scenario(st.session_state.season_name)
    st.caption(f"Sezon: **{st.session_state.scenario['title']}**")

    st.session_state.season_len = st.slider("Sezon uzunluğu (ay)", 6, 24, int(st.session_state.season_len))

    st.markdown(f"**Ay:** {st.session_state.month}/{st.session_state.season_len}")
    st.progress(min(1.0, st.session_state.month / max(1, st.session_state.season_len)))

    if not st.session_state.game_started:
        start_cash = st.slider("Başlangıç kasası", 50_000, 5_000_000, int(st.session_state.metrics["cash"]), step=50_000)
        if float(start_cash) != float(st.session_state.metrics["cash"]):
            st.session_state.metrics = init_metrics(float(start_cash))

    st.markdown("---")

    # Financial/metrics panel
    m = st.session_state.metrics
    st.markdown("### Finansal Durum")
    st.markdown(f"<div class='statbig'>{money(m['cash'])}</div><div class='muted'>Kasa</div>", unsafe_allow_html=True)
    st.markdown(f"**MRR:** {money(m['mrr'])}")

    with st.expander("Aylık Gider Detayı"):
        exp = m["expenses"]
        total = sum(exp.values())
        for k, v in exp.items():
            st.write(f"- **{k}:** {money(v)}")
        st.write(f"**TOPLAM:** {money(total)}")

    st.markdown("---")
    st.write(f"**İtibar:** {int(round(m['itibar']))}/100")
    st.write(f"**Support yükü:** {int(round(m['support']))}/100")
    st.write(f"**Altyapı yükü:** {int(round(m['altyapi']))}/100")
    st.write(f"**Kayıp Oranı:** %{m['kayip_orani']:.1f}")

    st.markdown("---")
    if st.button("Oyunu sıfırla", use_container_width=True):
        reset_game()
        st.rerun()

# -----------------------------
# Main
# -----------------------------
st.title("Startup Survivor RPG")
st.caption("Sohbet akışı korunur. Ay 1’den başlar: Durum Analizi → Kriz → A/B seçimi. (Gerçek vakalar esinlidir.)")

# API key status (non-leaking)
keys = _get_api_keys()
if keys:
    st.success("Gemini anahtarı görüldü. Model çağrıları çalışmalı.", icon="✅")
else:
    st.warning("Gemini anahtarı bulunamadı. Model yoksa bile oyun fallback içerikle çalışır.", icon="⚠️")

# -----------------------------
# Start screen
# -----------------------------
if not st.session_state.game_started:
    st.markdown("#### Oyuna başlamak için girişim fikrini yaz.")
    st.session_state.player_name = st.text_input("Karakter adı", st.session_state.player_name)

    idea = st.text_area("Girişim fikrin ne?", st.session_state.idea, height=120)
    st.session_state.idea = idea.strip()

    if st.button("Oyunu Başlat", type="primary"):
        if not st.session_state.idea:
            st.error("Bir girişim fikri yazmalısın.")
        else:
            st.session_state.game_started = True
            st.session_state.month = 1
            st.session_state.choice_done = False
            st.session_state.chat = []
            st.session_state.msg_ids = set()
            st.session_state.used_seed_ids = set()
            st.session_state.last_choice_summary = ""

            # intro message once
            add_message_once("intro-1", "assistant",
                             f"Tamam **{st.session_state.player_name}**. Ay 1’den başlıyoruz. Mod: **{st.session_state.mode}**.\n\n"
                             f"Sezon: **{st.session_state.scenario['title']}** (esinli).")
            st.rerun()

    st.stop()

# -----------------------------
# Month packet generation (idempotent)
# -----------------------------
def ensure_current_packet():
    if st.session_state.current_packet is None:
        game = {
            "mode": st.session_state.mode,
            "month": st.session_state.month,
            "idea": st.session_state.idea,
            "scenario": st.session_state.scenario,
            "metrics": st.session_state.metrics,
            "last_choice_summary": st.session_state.last_choice_summary,
        }
        st.session_state.current_packet = generate_month_packet(game)

        # Add to chat only once via IDs
        add_message_once(f"m{st.session_state.month}-analysis", "assistant",
                         f"🧠 **Durum Analizi (Ay {st.session_state.month})**\n\n{st.session_state.current_packet['analysis']}")
        add_message_once(f"m{st.session_state.month}-crisis", "assistant",
                         f"⚠️ **Kriz**\n\n{st.session_state.current_packet['crisis']}")
        add_message_once(f"m{st.session_state.month}-prompt", "assistant",
                         "👉 Şimdi seçim zamanı. **A mı B mi?** (İstersen aşağıdan serbest not da yazabilirsin.)")

ensure_current_packet()

# -----------------------------
# Render chat
# -----------------------------
for msg in st.session_state.chat:
    with st.chat_message(msg["role"], avatar="🧠" if msg["role"] == "assistant" else "🧍"):
        st.markdown(msg["content"])

# -----------------------------
# Choice UI (only if not chosen)
# -----------------------------
packet = st.session_state.current_packet
opts = packet["options"]

# Free note (optional) - chat-like
free_note = st.chat_input("İstersen kısa bir not yaz (opsiyonel). Seçim yine A/B ile ilerler.")
if free_note:
    add_message_once(f"m{st.session_state.month}-note", "user", free_note.strip())
    st.session_state["_pending_note"] = free_note.strip()
    st.rerun()

pending_note = st.session_state.get("_pending_note", "")

if not st.session_state.choice_done:
    c1, c2 = st.columns(2, gap="large")

    def choice_card(col, letter: str):
        title = opts[letter]["title"]
        steps = opts[letter]["steps"]
        with col:
            st.markdown("<div class='choice-wrap'>", unsafe_allow_html=True)
            st.markdown(f"<div class='choice-title'>{letter}) {html.escape(title)}</div>", unsafe_allow_html=True)

            # Steps list (no spoilers, just actions)
            st.markdown(render_steps_html(steps), unsafe_allow_html=True)

            st.markdown("<div class='choice-btn-row'>", unsafe_allow_html=True)
            if st.button(f"{letter} seç", key=f"choose_{letter}_m{st.session_state.month}", use_container_width=True):
                # Process once
                st.session_state.choice_done = True
                add_message_once(f"m{st.session_state.month}-choice", "user", f"Seçim: **{letter}** — {title}")

                # Apply consequences + narrative outcome
                game = {
                    "mode": st.session_state.mode,
                    "month": st.session_state.month,
                    "idea": st.session_state.idea,
                    "scenario": st.session_state.scenario,
                    "metrics": st.session_state.metrics,
                    "last_choice_summary": st.session_state.last_choice_summary,
                    "current_packet": st.session_state.current_packet,
                }
                outcome_text, deltas = apply_choice(game, letter, free_text=pending_note)

                # Update last_choice_summary for next month analysis
                st.session_state.last_choice_summary = f"Ay {st.session_state.month} seçimin: {letter}) {title}."

                # Outcome message
                add_message_once(f"m{st.session_state.month}-outcome", "assistant", f"✅ **Sonuç**\n\n{outcome_text}")

                # Metrics summary (brief, not in crisis)
                m = st.session_state.metrics
                delta_line = (
                    f"📌 **Güncel durum:** Kasa {money(m['cash'])}, MRR {money(m['mrr'])}, "
                    f"İtibar {int(round(m['itibar']))}/100, Kayıp Oranı %{m['kayip_orani']:.1f}, "
                    f"Support {int(round(m['support']))}/100, Altyapı {int(round(m['altyapi']))}/100."
                )
                add_message_once(f"m{st.session_state.month}-metrics", "assistant", delta_line)

                # clear pending note after using
                st.session_state["_pending_note"] = ""

                st.rerun()
            st.markdown("</div></div>", unsafe_allow_html=True)

    choice_card(c1, "A")
    choice_card(c2, "B")

else:
    # Next month button
    if st.session_state.month >= st.session_state.season_len:
        st.info("Sezon bitti. İstersen oyunu sıfırlayıp yeni bir sezon başlatabilirsin.")
    else:
        if st.button("Sonraki Ay →", type="primary"):
            st.session_state.month += 1
            st.session_state.choice_done = False
            st.session_state.current_packet = None
            st.rerun()
