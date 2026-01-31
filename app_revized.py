import os
import json
import random
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional, Tuple

import streamlit as st

# -------------------------
# Optional Gemini import
# -------------------------
HAS_GEMINI = True
try:
    import google.generativeai as genai
except Exception:
    HAS_GEMINI = False


# =========================
# CONFIG / THEME
# =========================
st.set_page_config(
    page_title="Startup Survivor RPG",
    page_icon="🧠",
    layout="wide",
)

st.markdown(
    """
    <style>
      .small-muted { opacity: 0.70; font-size: 0.92rem; }
      .card { border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; padding: 14px 14px 12px 14px; background: rgba(255,255,255,0.02); }
      .tag { display:inline-block; padding: 3px 10px; border-radius:999px; border:1px solid rgba(255,255,255,0.10); font-size: 0.85rem; opacity:0.85;}
      .hr { height: 1px; background: rgba(255,255,255,0.08); margin: 14px 0; }
      .kpi { font-size: 1.8rem; font-weight: 750; }
      .kpi2 { font-size: 1.2rem; font-weight: 650; opacity:0.92; }
      .warn { background: rgba(255,193,7,0.10); border: 1px solid rgba(255,193,7,0.25); padding: 10px 12px; border-radius: 12px; }
      .danger { background: rgba(255,0,0,0.08); border: 1px solid rgba(255,0,0,0.20); padding: 10px 12px; border-radius: 12px; }
      .good { background: rgba(0,200,0,0.07); border: 1px solid rgba(0,200,0,0.16); padding: 10px 12px; border-radius: 12px; }
    </style>
    """,
    unsafe_allow_html=True,
)


# =========================
# DATA MODELS
# =========================
@dataclass
class Character:
    name: str = "İsimsiz Girişimci"
    persona: str = "Pragmatik"
    background: str = "Tek başına"
    risk_style: str = "Dengeli"
    product_type: str = "SaaS"
    tone: str = "Sohbet"


@dataclass
class GameState:
    started: bool = False
    mode: str = "Realist"
    season_length: int = 12
    month: int = 1

    cash: int = 1_000_000
    mrr: int = 0

    churn: float = 0.10  # monthly churn ratio
    reputation: int = 50  # 0-100
    support_load: int = 20  # 0-100
    infra_load: int = 20  # 0-100

    # Costs
    payroll: int = 50_000
    server: int = 6_100
    marketing: int = 5_300

    # Meta / history
    idea: str = ""
    last_crisis_id: Optional[str] = None
    used_extreme_ids: List[str] = None
    last_turn: Dict[str, Any] = None


# =========================
# MODES
# =========================
MODES = {
    "Realist": {
        "label": "Gerçekçi (Realist)",
        "desc": "Dengeli, profesyonel simülasyon. Mantıklı kararlar ödüllenir; sonuçlar gerçek dünyaya yakın akar.",
    },
    "Hard": {
        "label": "Zor (Hard)",
        "desc": "Kaynak kısıtlı, bedeller ağır. Her seçeneğin mutlaka trade-off’u var; bedelsiz çıkış yok.",
    },
    "Spartan": {
        "label": "Spartan",
        "desc": "Acımasız ayı piyasası: hukuki/teknik/finansal engel yüksek, şans düşük. Hayatta kalma testi.",
    },
    "Extreme": {
        "label": "Extreme",
        "desc": "Kaos ve paylaşmalık absürtlük. Mantık ikinci planda; her saçmalık metriklere çarpar.",
    },
    "Turkey": {
        "label": "Türkiye Simülasyonu",
        "desc": "Türkiye’nin ekonomik/bürokratik gerçekleri: kur/enflasyon/vergiler/işgücü ve sürpriz gündemler.",
    },
}


# =========================
# EXTREME EVENT DECK
# (Repeat-proof + metric-bound)
# =========================
def build_extreme_deck() -> List[Dict[str, Any]]:
    """
    Extreme: Komik + absürt + paylaşmalık.
    Kural: Ne kadar saçma olursa olsun, sonuç metriklere bağlanır.
    """
    deck = [
        {
            "id": "ex_02",
            "title": "Kurumsal LinkedIn Tiyatro Gecesi",
            "type": "platform_absurd",
            "story": (
                "Bir kurumsal hesap, ürününü ‘Türkiye’nin en duygusal çeviri motoru’ diye övüyor. "
                "Sorun şu: Övdüğü özellik sende yok. Ama post viral; herkes o özelliği arayıp bulamayınca "
                "support’a saldırıyor. ‘Nerede o duygu modu?!’"
            ),
            "crisis": (
                "Trafik patlıyor ama yanlış beklenti daha hızlı patlıyor. Support kuyruğu kabarıyor, "
                "itibar ikiye bölünüyor: bir kitle aşırı seviyor, bir kitle ‘kandırıldım’ modunda. "
                "Sunucu nefes alamıyor; churn kapıda."
            ),
            "options": {
                "A": {
                    "title": "‘Evet o bendim’ Güncellemesi (Uydur ve Çak)",
                    "text": (
                        "Bir gecede ‘duygu modu’ diye bir buton koyup arka planda aynı işlevi başka isimle sun. "
                        "Kısa vadede itibar toparlar, talep akar; ama teknik borç ve support yükü sürpriz şekilde büyür."
                    ),
                    "effects": {"reputation": +8, "support_load": +18, "infra_load": +15, "mrr": +1200, "cash": -15000, "churn": -0.01},
                },
                "B": {
                    "title": "Gerçekleri Mizahla Çevir (Kibar ‘Yok Öyle Bir Şey’)",
                    "text": (
                        "Viral postu yakalayıp mizahi bir ‘o özellik yok ama daha iyisi var’ hikâyesine çevir. "
                        "Beklentiyi sıfırla, onboarding’i tek cümle vaat etrafında yeniden kur. Daha az büyüme, "
                        "daha az kaos; churn kontrol altına girer."
                    ),
                    "effects": {"reputation": +4, "support_load": -10, "infra_load": -6, "mrr": +450, "cash": -4000, "churn": -0.03},
                },
            },
        },
        {
            "id": "ex_10",
            "title": "Influencer ‘Yanlış Özelliği’ Övüyor",
            "type": "platform_absurd",
            "story": (
                "Bir influencer ürünü anlatırken yanlış özelliği övüyor: ‘Ekranı saniyede 120 kere tarıyor’ diyor. "
                "Senin ürün 10 kere tarıyor. Ama video o kadar komik ki herkes ‘120 tarama’ diye geliyor."
            ),
            "crisis": (
                "Trafik kaliteli değil, meraklı. Sunucu yükleniyor, support ‘120 nerede’ diye yanıyor. "
                "MRR potansiyeli var ama churn da var: yanlış beklenti = hızlı vazgeçiş."
            ),
            "options": {
                "A": {
                    "title": "‘120’yi Sahne Şovu Yap (Gerçek Değil, Deneyim)",
                    "text": (
                        "Gerçekte 120 tarama yapmadan, ekrana ‘hız hissi’ veren demo modu ekle: "
                        "kullanıcı ilk 30 saniyede ‘vay be’ desin. Sonra gerçek performansa indir. "
                        "MRR artar ama infra ve destek yükü yükselir."
                    ),
                    "effects": {"reputation": +6, "support_load": +12, "infra_load": +20, "mrr": +1400, "cash": -18000, "churn": +0.01},
                },
                "B": {
                    "title": "‘120 Efsanesi’ni Bitir (Net Düzeltme + Tek Vaat)",
                    "text": (
                        "Influencer’la kısa bir düzeltme videosu: ‘120 değil; ama doğru yerde hızlı’ diye netleştir. "
                        "Onboarding’e tek vaat: ‘yazıyı bul, çevir, öğren’. Talep bir miktar düşer ama kalan kitle doğru olur."
                    ),
                    "effects": {"reputation": +3, "support_load": -6, "infra_load": -4, "mrr": +650, "cash": -3000, "churn": -0.04},
                },
            },
        },
        # --- Daha fazla extreme olay (kısa ama özgün) ---
        {
            "id": "ex_20",
            "title": "‘Kedi Dil Paketi’ Skandalı",
            "type": "platform_absurd",
            "story": "Bir kullanıcı ‘kedim miyavladı, uygulama Japonca çevirdi’ diye video atıyor. Herkes deniyor.",
            "crisis": "Support’a ‘kedim konuşmuyor’ şikayetleri yağıyor. İtibar komik ama hassas. Trafik artıyor, altyapı inliyor.",
            "options": {
                "A": {"title": "Kedi Modu: Resmi Olmayan Resmi", "text": "Kedi modu diye Easter egg ekranı koy; aslında mikrofon filtresi + eğlence. Paylaşım artar, infra/support artar.", "effects": {"reputation": +7, "support_load": +14, "infra_load": +18, "mrr": +800, "cash": -12000, "churn": +0.00}},
                "B": {"title": "Şakayı Ürüne Bağla", "text": "‘Kedi değil, sesi yakalama’ anlatımıyla ürünü netleştir. Paylaşım azalır ama churn düşer, support toparlar.", "effects": {"reputation": +3, "support_load": -8, "infra_load": -5, "mrr": +500, "cash": -2500, "churn": -0.02}},
            },
        },
        {
            "id": "ex_25",
            "title": "Kurumsal Satınalma ‘Excel İster’",
            "type": "corporate_absurd",
            "story": "Bir kurumsal müşteri ‘AI güzel ama bizde süreç Excel’ diyerek senin ürünü Excel’e çevirmeye çalışıyor.",
            "crisis": "3 farklı departman 17 kolonluk istek listesi yollar. Scope patlar; itibar ‘kurumsal hazır’ beklentisine döner.",
            "options": {
                "A": {"title": "Excel’e İbadet Et", "text": "Tek bir ‘kurumsal rapor export’ ile istekleri yatıştır. Kısa vadede MRR artar; ürün odağı bulanır.", "effects": {"reputation": +4, "support_load": +10, "infra_load": +6, "mrr": +1600, "cash": -22000, "churn": +0.01}},
                "B": {"title": "Excel’i Kapıda Bırak", "text": "‘Biz ürünüz’ diyerek 2 kritik rapor seç, kalanını reddet. MRR daha az ama odak korunur, churn düşer.", "effects": {"reputation": +2, "support_load": -3, "infra_load": -2, "mrr": +700, "cash": -6000, "churn": -0.02}},
            },
        },
        {
            "id": "ex_33",
            "title": "Rakip Senin UI’ını Meme Yapıyor",
            "type": "platform_absurd",
            "story": "Rakip senin butonları tiye alıp meme yapıyor; meme öyle komik ki senin marka büyüyor.",
            "crisis": "Trafik artar ama ‘meme ürünü’ algısı oluşur. İtibar iki uçta: ya efsane ya rezil.",
            "options": {
                "A": {"title": "Meme’i Sahiplen", "text": "Resmi hesapla devamını getir, meme’i onboarding’e bağla. Viral büyür ama infra/support fırlar.", "effects": {"reputation": +9, "support_load": +16, "infra_load": +14, "mrr": +1000, "cash": -9000, "churn": +0.00}},
                "B": {"title": "Sessizce Ciddileş", "text": "Meme’i büyütmeden, ürünü tek vaatle netleştir. Viral azalır ama churn düşer, itibar stabilize olur.", "effects": {"reputation": +3, "support_load": -6, "infra_load": -3, "mrr": +550, "cash": -3500, "churn": -0.03}},
            },
        },
    ]
    return deck


# =========================
# HELPERS
# =========================
def tl(n: int) -> str:
    return f"{n:,}".replace(",", ".") + " ₺"


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def clamp_int(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def safe_pick(seq: List[Any], rng: random.Random) -> Any:
    return seq[rng.randrange(0, len(seq))]


def get_api_key() -> Optional[str]:
    """
    Streamlit Cloud: st.secrets
    Local: env var
    Supports:
      - GEMINI_API_KEY as string
      - GEMINI_API_KEY as list (first non-empty)
      - GEMINI_API_KEYS as list
      - GOOGLE_API_KEY fallback
    """
    # 1) secrets
    if hasattr(st, "secrets"):
        # Preferred single
        if "GEMINI_API_KEY" in st.secrets:
            val = st.secrets["GEMINI_API_KEY"]
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, (list, tuple)):
                for x in val:
                    if isinstance(x, str) and x.strip():
                        return x.strip()

        # Multi key pool
        if "GEMINI_API_KEYS" in st.secrets:
            val = st.secrets["GEMINI_API_KEYS"]
            if isinstance(val, (list, tuple)):
                for x in val:
                    if isinstance(x, str) and x.strip():
                        return x.strip()

        # Fallback
        if "GOOGLE_API_KEY" in st.secrets:
            val = st.secrets["GOOGLE_API_KEY"]
            if isinstance(val, str) and val.strip():
                return val.strip()

    # 2) env
    for k in ["GEMINI_API_KEY", "GOOGLE_API_KEY"]:
        val = os.getenv(k)
        if val and val.strip():
            return val.strip()

    return None


def ensure_rng() -> random.Random:
    # Repeatleri azaltmak için: mode+month+idea hash ile seed
    gs: GameState = st.session_state["game"]
    seed_base = f"{gs.mode}|{gs.month}|{gs.idea[:80]}"
    seed = abs(hash(seed_base)) % (2**32)
    return random.Random(seed)


# =========================
# GEMINI (LLM) LAYER
# =========================
def gemini_text(prompt: str, temperature: float = 0.7) -> str:
    if not HAS_GEMINI:
        raise RuntimeError("Gemini kütüphanesi yok: requirements'a google-generativeai ekleyin.")
    api_key = get_api_key()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY bulunamadı.")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    resp = model.generate_content(
        prompt,
        generation_config={
            "temperature": temperature,
            "max_output_tokens": 900,
        },
    )
    return (resp.text or "").strip()


def try_json(s: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(s)
    except Exception:
        return None


def extract_json_from_text(txt: str) -> Optional[Dict[str, Any]]:
    """
    Model bazen JSON'u metinle sarar. İlk { ... } bloğunu çek.
    """
    start = txt.find("{")
    end = txt.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    chunk = txt[start : end + 1]
    return try_json(chunk)


# =========================
# TURN GENERATION
# =========================
def mode_params(mode: str) -> Dict[str, Any]:
    if mode == "Realist":
        return {"temp": 0.55, "volatility": 0.9, "shock": 0.9}
    if mode == "Hard":
        return {"temp": 0.6, "volatility": 1.1, "shock": 1.15}
    if mode == "Spartan":
        return {"temp": 0.65, "volatility": 1.35, "shock": 1.35}
    if mode == "Turkey":
        return {"temp": 0.6, "volatility": 1.2, "shock": 1.25}
    if mode == "Extreme":
        return {"temp": 0.9, "volatility": 1.8, "shock": 1.7}
    return {"temp": 0.6, "volatility": 1.0, "shock": 1.0}


def generate_extreme_turn(gs: GameState) -> Dict[str, Any]:
    rng = ensure_rng()
    deck = build_extreme_deck()

    if gs.used_extreme_ids is None:
        gs.used_extreme_ids = []

    # Repeat-proof pick: prefer unused
    unused = [e for e in deck if e["id"] not in gs.used_extreme_ids]
    if not unused:
        gs.used_extreme_ids = []
        unused = deck[:]

    event = safe_pick(unused, rng)
    gs.used_extreme_ids.append(event["id"])

    # Build “durum analizi” (daha hikayesel + her ay varyasyon)
    # Extreme modda bile: önce durum analizi, sonra kriz.
    analysis = (
        f"Ay {gs.month} — {gs.idea[:80].strip() or 'Bu startup'} sahnede ama sahne dediğin kaygan. "
        f"Bugün ekip, bir yandan ‘büyüme mi, yoksa hayatta kalma mı’ diye tartışırken; "
        f"öte yandan internet seni bir şakaya dönüştürmeye kararlı. "
        f"Sen karar vermeden evren karar veriyor gibi: küçük bir kıvılcım, büyük bir yangın."
    )

    crisis = (
        f"{event['story']}\n\n"
        f"{event['crisis']}\n\n"
        f"Şu an tablo: kasa {tl(gs.cash)}, MRR {tl(gs.mrr)}, churn %{int(gs.churn*100)}, "
        f"support yükü {gs.support_load}/100, altyapı yükü {gs.infra_load}/100, itibar {gs.reputation}/100."
    )

    turn = {
        "crisis_id": event["id"],
        "analysis_title": "💬 DURUM ANALİZİ",
        "analysis": analysis,
        "crisis_title": "⚠️ KRİZ",
        "crisis": crisis,
        "options": {
            "A": {
                "title": f"A) {event['options']['A']['title']}",
                "text": event["options"]["A"]["text"],
                "effects": event["options"]["A"]["effects"],
            },
            "B": {
                "title": f"B) {event['options']['B']['title']}",
                "text": event["options"]["B"]["text"],
                "effects": event["options"]["B"]["effects"],
            },
        },
    }
    return turn


def generate_turkey_turn_llm(gs: GameState) -> Dict[str, Any]:
    p = mode_params(gs.mode)
    prompt = f"""
Sen bir girişim simülasyonu anlatıcısısın. Dil: Türkçe. Tarz: sohbet gibi, hikayesel ama net.
Mod: TÜRKİYE SİMÜLASYONU. Dayı faktörü YOK. Karikatür değil; gerçekçi TR dinamikleri:
- kur/enflasyon sürprizleri
- stopaj/KDV/BSMV gibi vergi ve tahsilat sancıları
- iş gücü maliyetleri, asgari ücret etkisi
- ödeme alma/chargeback, bankacılık süreçleri
- “gündem şoku”: bir gecede değişen algı/kurallar

KURAL: Her olay mutlaka metriklere bağlanır: cash, MRR, churn, itibar, support, altyapı.

Şu an durum:
Ay: {gs.month}/{gs.season_length}
Kasa: {gs.cash}
MRR: {gs.mrr}
Churn: {gs.churn}
İtibar: {gs.reputation}
Support yükü: {gs.support_load}
Altyapı yükü: {gs.infra_load}
Gider: maaş {gs.payroll}, sunucu {gs.server}, pazarlama {gs.marketing}
Girişim fikri: {gs.idea}

ÇIKTI FORMATIN: SADECE JSON.
Şema:
{{
  "analysis_title": "💬 DURUM ANALİZİ",
  "analysis": "Ay {gs.month} ... (hikayesel, 6-10 cümle)",
  "crisis_title": "⚠️ KRİZ",
  "crisis": "Detaylı kriz: 6-10 cümle, TR şartlarına benzesin, metrikleri an.",
  "options": {{
     "A": {{"title":"A) ...","text":"tek paragraf (orta uzunluk), çözüm mantığı net","effects":{{"cash":-10000,"mrr":+800,"churn":-0.02,"reputation":+4,"support_load":-5,"infra_load":+3}}}},
     "B": {{"title":"B) ...","text":"tek paragraf (orta uzunluk), çözüm mantığı net","effects":{{...}}}}
  }}
}}
Notlar:
- effects sayıları küçük/orta olsun; cash etkisi TL bazlı (negatif/pozitif), churn -0.08..+0.08 arası.
"""
    txt = gemini_text(prompt, temperature=p["temp"])
    data = extract_json_from_text(txt) or try_json(txt)
    if not data:
        # fallback minimal
        return {
            "analysis_title": "💬 DURUM ANALİZİ",
            "analysis": f"Ay {gs.month} — Türkiye’de her şey aynı anda olur: hem büyüme hayali hem tahsilat gerçeği.",
            "crisis_title": "⚠️ KRİZ",
            "crisis": "Kriz üretimi sırasında JSON parse edilemedi. Lütfen tekrar dene.",
            "options": {
                "A": {"title": "A) Yeniden dene", "text": "Tekrar üret.", "effects": {"cash": 0, "mrr": 0, "churn": 0.0, "reputation": 0, "support_load": 0, "infra_load": 0}},
                "B": {"title": "B) Yeniden dene", "text": "Tekrar üret.", "effects": {"cash": 0, "mrr": 0, "churn": 0.0, "reputation": 0, "support_load": 0, "infra_load": 0}},
            },
        }
    data["crisis_id"] = f"tr_{gs.month}_{abs(hash(gs.idea))%9999}"
    return data


def generate_standard_turn_llm(gs: GameState) -> Dict[str, Any]:
    p = mode_params(gs.mode)

    mode_instructions = {
        "Realist": "Dengeli ve profesyonel. Mantıklı kararları ödüllendir. Dünya gerçekçi.",
        "Hard": "Finans denetçisi gibi zorlayıcı. Her seçenek bir bedel içerir; kolay kaçış yok.",
        "Spartan": "Acımasız ayı piyasası. Engeller yüksek, hata affetmez. Şans faktörü düşük.",
    }.get(gs.mode, "Dengeli.")

    prompt = f"""
Sen bir girişim simülasyonu anlatıcısısın. Dil: Türkçe. Tarz: sohbet gibi, hikayesel ama net.
Mod: {gs.mode}. {mode_instructions}

KURAL: Çıktı mutlaka metriklere bağlanır: cash, MRR, churn, itibar, support, altyapı.
Yapı: önce DURUM ANALİZİ (6-9 cümle), sonra KRİZ (6-9 cümle, detaylı), sonra A/B seçenekleri.
A/B: Başlık kısa; açıklama tek paragraf (ne kısa ne roman). Çözüm yolu anlatılsın.

Şu an durum:
Ay: {gs.month}/{gs.season_length}
Kasa: {gs.cash}
MRR: {gs.mrr}
Churn: {gs.churn}
İtibar: {gs.reputation}
Support yükü: {gs.support_load}
Altyapı yükü: {gs.infra_load}
Gider: maaş {gs.payroll}, sunucu {gs.server}, pazarlama {gs.marketing}
Girişim fikri: {gs.idea}

ÇIKTI FORMATIN: SADECE JSON.
Şema:
{{
  "analysis_title": "💬 DURUM ANALİZİ",
  "analysis": "Ay {gs.month} ...",
  "crisis_title": "⚠️ KRİZ",
  "crisis": "...",
  "options": {{
     "A": {{"title":"A) ...","text":"...","effects":{{"cash":-10000,"mrr":+800,"churn":-0.02,"reputation":+4,"support_load":-5,"infra_load":+3}}}},
     "B": {{"title":"B) ...","text":"...","effects":{{...}}}}
  }}
}}
Notlar:
- effects: cash TL bazlı; churn -0.06..+0.06.
"""
    txt = gemini_text(prompt, temperature=p["temp"])
    data = extract_json_from_text(txt) or try_json(txt)
    if not data:
        return {
            "analysis_title": "💬 DURUM ANALİZİ",
            "analysis": f"Ay {gs.month} — Bu tur üretimde bir şeyler ters gitti (JSON parse edilemedi).",
            "crisis_title": "⚠️ KRİZ",
            "crisis": "Lütfen tekrar dene.",
            "options": {
                "A": {"title": "A) Yeniden dene", "text": "Tekrar üret.", "effects": {"cash": 0, "mrr": 0, "churn": 0.0, "reputation": 0, "support_load": 0, "infra_load": 0}},
                "B": {"title": "B) Yeniden dene", "text": "Tekrar üret.", "effects": {"cash": 0, "mrr": 0, "churn": 0.0, "reputation": 0, "support_load": 0, "infra_load": 0}},
            },
        }
    data["crisis_id"] = f"std_{gs.mode}_{gs.month}_{abs(hash(gs.idea))%9999}"
    return data


def generate_turn(gs: GameState) -> Dict[str, Any]:
    # Extreme deck-first: LLM'e bırakınca tekrar + “normalleşme” riski artıyor.
    if gs.mode == "Extreme":
        return generate_extreme_turn(gs)

    # Turkey uses LLM but with TR constraints
    if gs.mode == "Turkey":
        return generate_turkey_turn_llm(gs)

    # Others
    return generate_standard_turn_llm(gs)


# =========================
# SIMULATION / APPLY EFFECTS
# =========================
def monthly_baseline(gs: GameState) -> None:
    """
    Ay sonu baz etkiler:
    - giderler düşer
    - mrr gelir olarak eklenir
    - churn mrr azaltır
    """
    burn = gs.payroll + gs.server + gs.marketing
    gs.cash -= burn
    gs.cash += gs.mrr

    # churn mrr
    churn_loss = int(gs.mrr * gs.churn)
    gs.mrr = max(0, gs.mrr - churn_loss)

    # soft drift
    gs.support_load = clamp_int(gs.support_load + 2, 0, 100)
    gs.infra_load = clamp_int(gs.infra_load + 2, 0, 100)

    # bankruptcy guard
    if gs.cash < 0:
        gs.cash = gs.cash  # negative allowed (dramatic), but we can clamp later if desired


def apply_effects(gs: GameState, eff: Dict[str, Any]) -> None:
    gs.cash += int(eff.get("cash", 0))
    gs.mrr = max(0, gs.mrr + int(eff.get("mrr", 0)))

    gs.churn = clamp(gs.churn + float(eff.get("churn", 0.0)), 0.01, 0.60)
    gs.reputation = clamp_int(gs.reputation + int(eff.get("reputation", 0)), 0, 100)
    gs.support_load = clamp_int(gs.support_load + int(eff.get("support_load", 0)), 0, 100)
    gs.infra_load = clamp_int(gs.infra_load + int(eff.get("infra_load", 0)), 0, 100)


def push_message(role: str, content: str) -> None:
    st.session_state["messages"].append({"role": role, "content": content})


def render_stat_sidebar(gs: GameState, ch: Character) -> None:
    st.sidebar.markdown(f"### {ch.name}")
    st.sidebar.markdown(f"<div class='small-muted'>Mod: <b>{MODES[gs.mode]['label']}</b></div>", unsafe_allow_html=True)
    st.sidebar.markdown(f"<div class='small-muted'>Ay: <b>{gs.month}/{gs.season_length}</b></div>", unsafe_allow_html=True)
    st.sidebar.progress(min(gs.month / max(gs.season_length, 1), 1.0))

    st.sidebar.markdown("### Finansal Durum")
    st.sidebar.markdown(f"<div class='kpi'>{tl(gs.cash)}</div><div class='small-muted'>Kasa</div>", unsafe_allow_html=True)
    st.sidebar.markdown(f"<div class='kpi2'>{tl(gs.mrr)}</div><div class='small-muted'>MRR</div>", unsafe_allow_html=True)

    st.sidebar.markdown("<div class='hr'></div>", unsafe_allow_html=True)

    st.sidebar.markdown("#### Aylık Gider Detayı")
    st.sidebar.markdown(
        f"""
        <div class="card">
          <div> Maaşlar: <b>{tl(gs.payroll)}</b></div>
          <div> Sunucu: <b>{tl(gs.server)}</b></div>
          <div> Pazarlama: <b>{tl(gs.marketing)}</b></div>
          <div class="hr"></div>
          <div><b>TOPLAM:</b> {tl(gs.payroll + gs.server + gs.marketing)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.sidebar.markdown("<div class='hr'></div>", unsafe_allow_html=True)
    st.sidebar.markdown(f"**İtibar:** {gs.reputation}/100")
    st.sidebar.markdown(f"**Support:** {gs.support_load}/100")
    st.sidebar.markdown(f"**Altyapı:** {gs.infra_load}/100")
    st.sidebar.markdown(f"**Churn:** %{int(gs.churn*100)}")


# =========================
# SESSION INIT
# =========================
if "character" not in st.session_state:
    st.session_state["character"] = Character()

if "game" not in st.session_state:
    st.session_state["game"] = GameState(used_extreme_ids=[], last_turn={})

if "messages" not in st.session_state:
    st.session_state["messages"] = []

if "awaiting_choice" not in st.session_state:
    st.session_state["awaiting_choice"] = False

if "current_turn" not in st.session_state:
    st.session_state["current_turn"] = None


# =========================
# HEADER
# =========================
gs: GameState = st.session_state["game"]
ch: Character = st.session_state["character"]

st.title("Startup Survivor RPG")
st.caption("Sohbet akışı korunur. Ay 1’den başlar. Sıra: Durum Analizi → Kriz → A/B seçimi.")

# Sidebar stats
render_stat_sidebar(gs, ch)


# =========================
# SETTINGS / CHARACTER
# =========================
with st.expander("🛠️ Karakterini ve Ayarları Özelleştir (Tıkla)", expanded=not gs.started):
    c1, c2, c3 = st.columns([1.2, 1, 1])

    with c1:
        ch.name = st.text_input("Karakter adı", value=ch.name)
        ch.persona = st.selectbox("Persona", ["Pragmatik", "Hırslı", "Analitik", "Kaos Sever", "Minimalist"], index=["Pragmatik","Hırslı","Analitik","Kaos Sever","Minimalist"].index(ch.persona) if ch.persona in ["Pragmatik","Hırslı","Analitik","Kaos Sever","Minimalist"] else 0)
        ch.background = st.selectbox("Arka plan", ["Tek başına", "2 kişilik ekip", "Küçük ekip", "Ajans/partner"], index=0)

    with c2:
        mode_keys = list(MODES.keys())
        gs.mode = st.selectbox("Mod", mode_keys, index=mode_keys.index(gs.mode))
        st.markdown(f"<div class='small-muted'>{MODES[gs.mode]['desc']}</div>", unsafe_allow_html=True)

        gs.season_length = st.slider("Sezon uzunluğu (ay)", min_value=6, max_value=24, value=int(gs.season_length), step=1)

    with c3:
        gs.cash = st.slider("Başlangıç kasası", min_value=50_000, max_value=2_000_000, value=int(gs.cash), step=10_000)
        ch.risk_style = st.selectbox("Risk tarzı", ["Dengeli", "Agresif", "Temkinli"], index=["Dengeli","Agresif","Temkinli"].index(ch.risk_style) if ch.risk_style in ["Dengeli","Agresif","Temkinli"] else 0)
        ch.product_type = st.selectbox("Ürün tipi", ["SaaS", "Mobil", "B2B", "B2C", "Marketplace"], index=0)

    st.session_state["character"] = ch
    st.session_state["game"] = gs

st.markdown("<div class='hr'></div>", unsafe_allow_html=True)


# =========================
# API KEY STATUS
# =========================
api_key = get_api_key()
if not api_key:
    st.markdown(
        "<div class='danger'><b>GEMINI_API_KEY bulunamadı.</b> Streamlit Cloud → App settings → Secrets içine "
        "<code>GEMINI_API_KEY = \"...\"</code> şeklinde ekle. (Liste olarak eklediysen yeni kod yine de okur.)</div>",
        unsafe_allow_html=True,
    )
else:
    st.markdown("<div class='good'>✅ Gemini anahtarı görüldü. Model çağrıları çalışmalı.</div>", unsafe_allow_html=True)


# =========================
# IDEA INPUT / START
# =========================
if not gs.started:
    st.info("Oyuna başlamak için girişim fikrini yaz ve **Oyunu Başlat**’a bas.")
    gs.idea = st.text_area("Girişim fikrin ne?", value=gs.idea, height=140, placeholder="Örn: Ekrandaki yabancı yazıları anlık çeviren bir uygulama...")

    start = st.button("🚀 Oyunu Başlat", type="primary", use_container_width=True)

    if start:
        # Start game at Month 1 (NOT skipping)
        gs.started = True
        gs.month = 1
        gs.mrr = 0
        gs.reputation = 50
        gs.support_load = 20
        gs.infra_load = 20
        gs.churn = 0.10
        gs.used_extreme_ids = []
        st.session_state["messages"] = []
        st.session_state["awaiting_choice"] = False
        st.session_state["current_turn"] = None

        push_message("assistant", f"Tamam {ch.name}. Ay 1’den başlıyoruz. Mod: **{MODES[gs.mode]['label']}**.")
        push_message("assistant", "Önce durumu okuyacağız, sonra kriz gelecek, sonra A/B seçeceksin.")
        st.session_state["game"] = gs
        st.rerun()

    st.stop()


# =========================
# CHAT HISTORY RENDER
# =========================
for m in st.session_state["messages"]:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])


# =========================
# TURN UI
# =========================
def render_turn(turn: Dict[str, Any]) -> None:
    # Turn blocks: DURUM -> KRİZ -> A/B
    with st.chat_message("assistant"):
        st.markdown(f"### {turn.get('analysis_title','💬 DURUM ANALİZİ')}")
        st.markdown(turn.get("analysis", ""))

        st.markdown(f"### {turn.get('crisis_title','⚠️ KRİZ')}")
        st.markdown(turn.get("crisis", ""))

        st.markdown("<div class='hr'></div>", unsafe_allow_html=True)
        st.markdown("👇 Şimdi krize karşı bir çözüm seç (A/B).")

        colA, colB = st.columns(2)

        optA = turn["options"]["A"]
        optB = turn["options"]["B"]

        with colA:
            st.markdown(f"#### {optA['title']}")
            st.markdown(optA["text"])
            if st.button("A seç", key=f"pickA_{gs.month}", use_container_width=True):
                handle_choice("A")

        with colB:
            st.markdown(f"#### {optB['title']}")
            st.markdown(optB["text"])
            if st.button("B seç", key=f"pickB_{gs.month}", use_container_width=True):
                handle_choice("B")


def handle_choice(which: str) -> None:
    gs: GameState = st.session_state["game"]
    turn = st.session_state["current_turn"]
    if not turn:
        return

    opt = turn["options"][which]
    push_message("user", f"{which} seçtim: {opt['title']}")

    # Apply option effects immediately
    apply_effects(gs, opt.get("effects", {}))

    # Then apply baseline month end
    monthly_baseline(gs)

    # Month advances
    gs.month += 1
    st.session_state["game"] = gs

    # Add short recap message
    recap = (
        f"✅ Seçimin işlendi. Yeni durum: kasa **{tl(gs.cash)}**, MRR **{tl(gs.mrr)}**, "
        f"itibar **{gs.reputation}/100**, churn **%{int(gs.churn*100)}**, "
        f"support **{gs.support_load}/100**, altyapı **{gs.infra_load}/100**."
    )
    push_message("assistant", recap)

    # Clear and continue
    st.session_state["awaiting_choice"] = False
    st.session_state["current_turn"] = None

    if gs.month > gs.season_length:
        push_message("assistant", "🏁 Sezon bitti. İstersen ayarları değiştirip yeniden başlayabilirsin.")
    st.rerun()


# =========================
# GENERATE NEXT TURN
# =========================
if gs.month <= gs.season_length and st.session_state["current_turn"] is None:
    # Generate fresh turn
    try:
        turn = generate_turn(gs)
    except Exception as e:
        # If Gemini key not working, give actionable error
        push_message("assistant", f"⚠️ Tur üretirken hata: `{e}`")
        push_message("assistant", "Secrets formatını kontrol et: `GEMINI_API_KEY = \"...\"` (tek satır) en garanti yol.")
        st.session_state["current_turn"] = None
        st.rerun()

    st.session_state["current_turn"] = turn
    st.session_state["awaiting_choice"] = True

# Render current turn if awaiting
if st.session_state["awaiting_choice"] and st.session_state["current_turn"] is not None:
    render_turn(st.session_state["current_turn"])


# =========================
# FREEFORM CHAT INPUT (optional flavor)
# =========================
# Kullanıcı isterse serbest bir şey yazsın diye; ama seçim A/B ana akış.
if gs.month <= gs.season_length:
    user_free = st.chat_input("İstersen bir not yaz (opsiyonel). Seçim yine A/B ile ilerler.")
    if user_free:
        push_message("user", user_free)
        push_message("assistant", "Notunu aldım. Bu turda ana ilerleme A/B seçimiyle.")
        st.rerun()
