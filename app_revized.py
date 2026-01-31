import html
import os
import re
import json
import random
import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

# =========================================================
# Startup Survivor RPG (single-file Streamlit app)
# - Modlar: Realist / Hard / Spartan / Extreme / Türkiye
# - Akış: Durum Analizi -> Kriz -> A/B (veya serbest hamle)
# - Tekrar bug'ı: aynı ay paketi bir kez üretilir ve cache'lenir
# - Extreme: absürt olay havuzu + tekrar engeli
# - Gerçek vaka (esinlenme): opsiyonel sezon
# =========================================================

# -------------------------
# Page
# -------------------------
st.set_page_config(
    page_title="Startup Survivor RPG",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -------------------------
# Minimal CSS (card + chat look)
# -------------------------
_CSS = """
<style>
:root {
  --card-bg: rgba(255,255,255,0.03);
  --card-border: rgba(255,255,255,0.08);
  --muted: rgba(255,255,255,0.65);
}
.block-container { padding-top: 1.25rem; }
.small-muted { color: var(--muted); font-size: 0.9rem; }

.choice-wrap {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 16px;
  padding: 18px 18px;
  height: 100%;
}
.choice-title {
  font-weight: 800;
  font-size: 1.35rem;
  margin-bottom: 8px;
}
.choice-body {
  color: rgba(255,255,255,0.85);
  font-size: 0.98rem;
  line-height: 1.45;
}
.choice-steps {
  margin: 10px 0 0 0;
  padding-left: 18px;
  color: rgba(255,255,255,0.82);
}
.choice-steps li { margin: 6px 0; }

.badge {
  display: inline-block;
  padding: 4px 9px;
  border-radius: 999px;
  border: 1px solid var(--card-border);
  background: rgba(0,0,0,0.18);
  font-size: 0.85rem;
  color: rgba(255,255,255,0.78);
}

.hr {
  height: 1px;
  background: rgba(255,255,255,0.08);
  margin: 18px 0;
}

.metric-box {
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 14px;
  padding: 12px 14px;
}

.chat-header {
  font-size: 2.2rem;
  font-weight: 900;
  margin: 0.2rem 0 0.35rem 0;
}
</style>
"""

st.markdown(_CSS, unsafe_allow_html=True)

# -------------------------
# Data
# -------------------------

MODS: Dict[str, Dict[str, Any]] = {
    "Gerçekçi": {
        "tagline": "Dengeli, profesyonel simülasyon. Mantıklı kararlar ödüllenir.",
        "tone": "dengeli, gerçekçi, profesyonel",
        "absurdity": 0.05,
        "severity_mul": 1.0,
        "volatility": 1.0,
    },
    "Zor": {
        "tagline": "Her seçimin bedeli var. Kolay çıkış yok.",
        "tone": "zorlu, finansal denetçi, trade-off vurgulu",
        "absurdity": 0.07,
        "severity_mul": 1.25,
        "volatility": 1.1,
    },
    "Spartan": {
        "tagline": "Acımasız ayı piyasası. Hata affetmez.",
        "tone": "acımasız, soğukkanlı, felaket yönetimi",
        "absurdity": 0.08,
        "severity_mul": 1.5,
        "volatility": 1.2,
    },
    "Extreme": {
        "tagline": "Kaos ve absürt. Paylaşmalık olaylar. Sonuç metriklere çarpar.",
        "tone": "komik, absürt, internet kültürü, hızlı ve keskin",
        "absurdity": 1.0,
        "severity_mul": 1.15,
        "volatility": 1.35,
    },
    "Türkiye": {
        "tagline": "Türkiye pazar dinamikleri: kur, enflasyon, vergi, bürokrasi, tahsilat.",
        "tone": "Türkiye gerçekleri, pratik, bürokrasi/ekonomi detaylı",
        "absurdity": 0.12,
        "severity_mul": 1.15,
        "volatility": 1.15,
    },
}

# Extreme olay tohumu havuzu (tekrar engeli için id+metin)
EXTREME_EVENTS: List[Dict[str, str]] = [
    {"id": "ex01", "seed": "Bir influencer senin ürünü överken yanlış özelliği övüyor: 'Bunu açınca telefonum ısındı, demek ki çok güçlü!'"},
    {"id": "ex02", "seed": "Bir 'kurumsal dönüşüm' danışmanı LinkedIn'de ürünü Excel'e çevirmeyi öğreten bir thread paylaşıyor. Thread viral."},
    {"id": "ex03", "seed": "Ürünün adı bir anda 'kötü kelime filtreleri'ne takılıyor ve platformlar reklamlarını otomatik reddetmeye başlıyor."},
    {"id": "ex04", "seed": "Bir TikTok trendi: insanlar uygulamana 'tek kelime' yazıp tepki videosu çekiyor. 48 saatte 200k yeni kullanıcı."},
    {"id": "ex05", "seed": "Bir kurumsal müşteri, satın alma komitesi için 17 kolonluk 'istek listesi' Excel'i yolluyor. 3 departman 3 farklı Excel."},
    {"id": "ex06", "seed": "Bir YouTuber ürün demosunu canlı yayında ters kullanıyor ve 'bu böyle çalışmalı' diye standardı belirliyor."},
    {"id": "ex07", "seed": "Ürünün UI'ındaki bir ikon, yanlışlıkla bir politik sembole benzetiliyor; yorumlar 'bu bir mesaj mı?' diye ikiye bölünüyor."},
    {"id": "ex08", "seed": "Bir meme sayfası 'Startup'ların en büyük yalanı' diye seni etiketliyor: caption 'AI var ama aslında ...'"},
    {"id": "ex09", "seed": "App Store yorumlarında aynı cümle patlıyor: 'Abi çok iyi ama bu ne?'"},
    {"id": "ex10", "seed": "Bir platform algoritması yanlışlıkla seni 'eğitim uygulaması' yerine 'oyun' kategorisine koyuyor; bambaşka kitle doluşuyor."},
    {"id": "ex11", "seed": "Bir kurumsal müşteri 'SLA var mı?' diye soruyor. Sen 'var' diyorsun. Onlar 'peki SLA'nın SLA'sı?' diye geri dönüyor."},
    {"id": "ex12", "seed": "Bir rakip senin adını 'yanlış yazıp' trend başlatıyor; yanlış yazım daha çok aratılıyor."},
    {"id": "ex13", "seed": "Ürün, bir Discord sunucusunda 'mucize hack' diye paylaşılıyor; insanlar senin hiç düşünmediğin şekilde kullanıyor."},
    {"id": "ex14", "seed": "Bir VC partneri DM atıyor: 'Ürün beni duygulandırdı.' Hangi özelliğin duygulandırdığı meçhul."},
    {"id": "ex15", "seed": "Bir kullanıcı 'bu kesin komplo' diye ticket açıp sonra üye olup kayboluyor. Ticket'ın altında 90 kişi 'same' yazıyor."},
    {"id": "ex16", "seed": "Bir kurumsal müşteri satış demo kaydını AI ile kesip biçiyor; senin ağzından hiç söylemediğin cümleler dolaşıyor."},
    {"id": "ex17", "seed": "Bir Reddit başlığı: 'Bu uygulama beni daha iyi insan yaptı' — altına 'ben de denedim, beni işten attırdı' yorumları."},
    {"id": "ex18", "seed": "Bir podcaster seni 'gizli devlet projesi' diye anıyor; şaka ama dinleyiciler ciddiye alıyor."},
    {"id": "ex19", "seed": "Ürünün onboarding'inde geçen bir kelime yeni bir argo oluyor. İnsanlar ekran görüntüsü alıp kullanıyor."},
    {"id": "ex20", "seed": "Bir kurumsal müşteri 'AI güzel ama bizde süreç Excel' diyerek ekibini senin ürün yerine Excel'e eğitmeye başlıyor."},
    {"id": "ex21", "seed": "Bir medya kuruluşu seni yanlış sektörle röportaja çağırıyor; sen de 'evet' deyince hikâye garipleşiyor."},
    {"id": "ex22", "seed": "App'in bir bug'ı, kullanıcıların yanlışlıkla birbirinin ekranını 'görüyormuş gibi' hissetmesine sebep oluyor (aslında sadece UI glitch)."},
    {"id": "ex23", "seed": "Bir kedi videosu hesabı ürünü 'kedi altyazısı' yapmak için kullanıyor; beklenmedik B2C patlaması."},
    {"id": "ex24", "seed": "Bir e-ticaret influencer'ı 'bu uygulama ile müşteriye cevap veriyorum' diye paylaşıyor; support trafiğin katlanıyor."},
    {"id": "ex25", "seed": "Bir kurumsal IT ekibi 'güvenlik' diyerek her şeyi VPN arkasına alıyor; ürünün çalıştığı şeyler çalışmıyor."},
    {"id": "ex26", "seed": "Bir forumda senin ürünün için 'korsan patch' yazmışlar: kullanıcılar yanlış sürümü kuruyor."},
    {"id": "ex27", "seed": "Bir otomasyon aracı seni 'spam' diye sınıflıyor; onboarding e-postaları gitmiyor, kimse nedenini anlamıyor."},
    {"id": "ex28", "seed": "Bir kullanıcı ekran görüntüsü paylaşmış: UI'da 1 piksel kayık bir çizgi. 'Bu bir işaret' diye viral."},
    {"id": "ex29", "seed": "Bir kurumsal müşteri, ürünün adını kendi iç jargonuna çeviriyor; sonra herkes o ismi kullanıp seni bulamıyor."},
    {"id": "ex30", "seed": "Bir 'kurumsal saçmalık' anı: satın alma ekibi 3 ay sözleşme görüşürken, asıl kullanıcılar ücretsizle zaten kullanıyor."},
    {"id": "ex31", "seed": "Bir konferansta sahneye çağrılıyorsun ama slaytın yerine yanlışlıkla loglar yansıyor. İnsanlar 'wow şeffaflık' diyor."},
    {"id": "ex32", "seed": "Kullanıcılar ürünün en basit özelliğini 'ritüel' haline getiriyor. Herkes aynı sırayla tıklıyor."},
    {"id": "ex33", "seed": "Bir platform 'çocuklara uygun değil' etiketi yapıştırıyor. Sebep: onboarding metnindeki masum bir kelime."},
    {"id": "ex34", "seed": "Bir kamu kurumu 'biz de kullanacağız' diyip PDF istiyor. Sonra PDF'yi WhatsApp'tan dağıtıyorlar."},
    {"id": "ex35", "seed": "Bir rakip senin ürününü 'AI değil' diye taşlıyor; ama seni konuşarak daha çok kullanıcı gönderiyor."},
    {"id": "ex36", "seed": "Bir kullanıcı 'Sadece bunu istiyorum' diyerek tek bir buton istiyor. 10 bin kişi aynı buton için imza kampanyası."},
    {"id": "ex37", "seed": "Bir podcast'te 'Startup'ların en büyük yanlışı: her şeyi seçenek yapmak' diyip seni örnek veriyor."},
    {"id": "ex38", "seed": "Bir API sağlayıcısı fiyatını artırıyor ve bunu 'şeffaflık' diye kutluyor. Senin maliyet grafiğin ağlıyor."},
    {"id": "ex39", "seed": "Bir kullanıcı kitlesi ürününü 'alternatif terapi' diye kullanmaya başlıyor. PR yangını çıkmadan önce yön lazım."},
    {"id": "ex40", "seed": "Bir bot ordusu yanlışlıkla seni 'bedava kupon' hedefi sanıyor; signup patlıyor ama kalite yok."},
]

# Türkiye modu: daha yerel ama abartısız olay tohumları
TR_EVENTS: List[Dict[str, str]] = [
    {"id": "tr01", "seed": "Kur artışı bir gecede sunucu maliyetini zıplatıyor; fiyatı güncellersen kullanıcı kızıyor, güncellemezsen kasa eriyor."},
    {"id": "tr02", "seed": "Bir müşterin 'fatura kesemiyorsak alamayız' diyor; e-fatura/e-arşiv süreci beklediğinden daha yorucu."},
    {"id": "tr03", "seed": "Tahsilat gecikiyor: 'Önümüzdeki hafta muhasebe kapatıyor' cümlesi bu ayın mottosu oluyor."},
    {"id": "tr04", "seed": "Reklam maliyetleri artıyor, organik büyüme ise dalgalı: aynı içerik bir gün 200, ertesi gün 20 kişi getiriyor."},
    {"id": "tr05", "seed": "KDV/stopaj konuşmaları uzuyor: müşteri fiyatı değil, kalemleri tartışıyor."},
    {"id": "tr06", "seed": "Personel maliyetleri beklenmedik kalemler çıkarıyor; bütçe planı ay ortasında deliniyor."},
    {"id": "tr07", "seed": "B2B tarafında satın alma süreçleri uzuyor: demo var, niyet var ama 'imza süreci' bitmiyor."},
    {"id": "tr08", "seed": "Bir kamu kurumundan ilgi geliyor ama şartnameler dili ve süreçleri ürünü eğip büküyor."},
]

# "Gerçek" vaka sezonları (kamuya açık vakalardan esinlenme; oyunlaştırılmış)
REAL_CASES: Dict[str, Dict[str, Any]] = {
    "Serbest (Rastgele)": {
        "desc": "Her ay farklı olaylar. Mod seçimine göre ton değişir.",
        "beats": [],
    },
    "Ölçek Patlaması (Esinlenme)": {
        "desc": "Bir anda gelen talep + altyapı yükü + yanlış kitle. (Viral büyüme vakalarından esinlenme)",
        "beats": [
            {"seed": "Beklenmedik viral dalga geliyor; onboarding yanlış kitleyi içeri alıyor.", "a": "odak", "b": "filtre", "severity": 3},
            {"seed": "Altyapı geceleri çöküyor; support birikiyor; sosyal medya öfke.", "a": "altyapi", "b": "pr", "severity": 4},
            {"seed": "İçeride 'büyüme mi kalite mi' kavgası; ekip ikiye bölünüyor.", "a": "odak", "b": "ikili_kulvar", "severity": 3},
            {"seed": "Yanlış kullanım biçimi trend oluyor; itibar iki uca ayrılıyor.", "a": "rehber", "b": "kisit", "severity": 3},
        ],
    },
    "Uyumluluk ve Süreç Krizi (Esinlenme)": {
        "desc": "Hızlı büyüme sonrası süreç/uyumluluk açıkları ve denetim baskısı. (Uyumluluk krizlerinden esinlenme)",
        "beats": [
            {"seed": "B2B müşteriler ""denetim"" ve ""log"" ister; süreçler eksik yakalanır.", "a": "uyumluluk", "b": "ertelemek", "severity": 4},
            {"seed": "Basit bir kontrol listesi çok büyür; operasyon kitlenir.", "a": "odak", "b": "delegasyon", "severity": 3},
            {"seed": "İçeriden bir hata sosyal medyaya sızar; güven krizi.", "a": "pr", "b": "teknik", "severity": 4},
        ],
    },
    "Fiyatlandırma Yanlışı (Esinlenme)": {
        "desc": "Yanlış paket/yanlış fiyat; churn ve MRR şoku. (Yanlış fiyatlandırma/pivot vakalarından esinlenme)",
        "beats": [
            {"seed": "Ücretsiz kitle büyüdü ama ödemeye geçmiyor; herkes farklı değer görüyor.", "a": "odak", "b": "fiyat", "severity": 3},
            {"seed": "Kurumsal bir müşteri indirim ister; diğerleri duyarsa yangın.", "a": "kurumsal", "b": "selfserve", "severity": 3},
            {"seed": "Fiyat değişince sosyal medya ""ihanet"" der; ödeme altyapısı da aksar.", "a": "pr", "b": "teknik", "severity": 4},
        ],
    },
}


# -------------------------
# Helpers
# -------------------------

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _pct(v: float) -> str:
    return f"%{v:.1f}"


def _tl(v: float) -> str:
    # 1.000.000 formatı
    s = f"{int(round(v)):,}".replace(",", ".")
    return f"{s} ₺"


def _stable_hash(text: str) -> int:
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return int(h[:8], 16)


def _extract_json(text: str) -> Optional[dict]:
    """Gemini bazen JSON'u markdown içinde döndürebilir; ilk JSON objesini çek."""
    if not text:
        return None
    # doğrudan dene
    try:
        return json.loads(text)
    except Exception:
        pass

    # ilk { ... } bloğunu bul
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


# -------------------------
# Gemini (optional)
# -------------------------

def get_gemini_key() -> Optional[str]:
    # 1) environment
    k = os.getenv("GEMINI_API_KEY")
    if k:
        return k.strip()

    # 2) secrets (string or list)
    try:
        if "GEMINI_API_KEY" in st.secrets:
            v = st.secrets["GEMINI_API_KEY"]
            if isinstance(v, list) and v:
                # list ise ilkini al
                return str(v[0]).strip()
            if isinstance(v, str):
                return v.strip()
        if "GEMINI_API_KEYS" in st.secrets:
            v = st.secrets["GEMINI_API_KEYS"]
            if isinstance(v, list) and v:
                return str(v[0]).strip()
            if isinstance(v, str) and v.strip():
                return v.strip()
    except Exception:
        pass

    return None


@st.cache_resource(show_spinner=False)
def get_gemini_model(api_key: str):
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    # Flash genelde hızlı ve yeterli
    return genai.GenerativeModel("gemini-1.5-flash")


def llm_json(prompt: str, temperature: float = 0.7, max_output_tokens: int = 900) -> Optional[dict]:
    api_key = get_gemini_key()
    if not api_key:
        return None

    try:
        model = get_gemini_model(api_key)
        # response_mime_type her ortamda desteklenmeyebilir; yine de prompt'a JSON şartı koyuyoruz.
        resp = model.generate_content(
            prompt,
            generation_config={
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
            },
        )
        txt = getattr(resp, "text", "")
        return _extract_json(txt)
    except Exception:
        return None


# -------------------------
# Game state
# -------------------------

@dataclass
class Metrics:
    cash: float
    mrr: float
    reputation: float
    support_load: float
    infra_load: float
    churn_pct: float


def default_metrics(start_cash: float) -> Metrics:
    return Metrics(
        cash=float(start_cash),
        mrr=0.0,
        reputation=50.0,
        support_load=20.0,
        infra_load=20.0,
        churn_pct=5.0,
    )


def init_state() -> None:
    ss = st.session_state
    ss.setdefault("game_started", False)
    ss.setdefault("seed", 0)
    ss.setdefault("messages", [])  # chat log
    ss.setdefault("month", 1)
    ss.setdefault("season_len", 12)
    ss.setdefault("mode", "Extreme")
    ss.setdefault("case", "Serbest (Rastgele)")
    ss.setdefault("idea", "")
    ss.setdefault("player_name", "İsimsiz Girişimci")
    ss.setdefault("metrics", default_metrics(1_000_000))
    ss.setdefault("monthly_expenses", {"Maşlar": 50_000, "Sunucu": 6_100, "Pazarlama": 5_300})
    ss.setdefault("phase", "setup")  # setup | awaiting_action | done
    ss.setdefault("current_bundle", None)  # current month content
    ss.setdefault("used_event_ids", set())
    ss.setdefault("recent_event_ids", [])
    ss.setdefault("decision_history", [])  # list of dicts

    # character customization
    ss.setdefault("persona", {
        "sektor": "Genel",
        "hedef_kitle": "Genel kullanıcı",
        "strateji": "Dengeli",
        "tarz": "Net, kısa, vurucu",
    })


def reset_game() -> None:
    ss = st.session_state
    keep = {
        "mode": ss.get("mode", "Extreme"),
        "season_len": ss.get("season_len", 12),
        "case": ss.get("case", "Serbest (Rastgele)"),
        "player_name": ss.get("player_name", "İsimsiz Girişimci"),
        "persona": ss.get("persona", {}),
    }
    for k in list(ss.keys()):
        del ss[k]
    init_state()
    ss.update(keep)


init_state()


# -------------------------
# Scenario generation
# -------------------------

ARCHETYPES = [
    "odak", "filtre", "ikili_kulvar", "altyapi", "pr", "fiyat", "kurumsal", "selfserve",
    "rehber", "kisit", "uyumluluk", "delegasyon", "teknik", "ertelemek"
]


def pick_event_seed(mode: str) -> Tuple[str, str]:
    """Return (event_id, seed_text)."""
    ss = st.session_state
    rng = random.Random(ss["seed"] + ss["month"] * 7919)

    if mode == "Extreme":
        pool = EXTREME_EVENTS
    elif mode == "Türkiye":
        pool = TR_EVENTS
    else:
        # diğer modlarda aynı havuzun daha sakin subset'i
        pool = EXTREME_EVENTS[:12]

    used = ss["used_event_ids"]
    recent = set(ss["recent_event_ids"][-6:])

    candidates = [e for e in pool if e["id"] not in used and e["id"] not in recent]
    if not candidates:
        # hepsi kullanıldıysa, sadece recent filtresi uygula
        candidates = [e for e in pool if e["id"] not in recent] or pool

    chosen = rng.choice(candidates)
    return chosen["id"], chosen["seed"]


def case_beat(month: int, case_name: str) -> Optional[dict]:
    case = REAL_CASES.get(case_name)
    if not case:
        return None
    beats = case.get("beats", [])
    if not beats:
        return None
    idx = month - 1
    if idx < 0 or idx >= len(beats):
        return None
    return beats[idx]


def build_month_prompt(mode: str, month: int, season_len: int, idea: str, metrics: Metrics, persona: dict,
                       case_name: str, event_seed: str, beat: Optional[dict], last_decision: Optional[dict]) -> str:
    mod = MODS[mode]

    # Durum analizi yönlendirmesi: Ay1 fikir; sonraki aylar geçmiş seçimler.
    if month == 1:
        durum_focus = "Bu ay DURUM ANALİZİ kısmında girişim fikrini analiz et: değer önerisi, kimin problemi, nerede kayıyor, hangi yanlış anlaşılma riski var. Daha uzun ve detaylı bir paragraf olsun."
    else:
        prev = last_decision or {}
        prev_summary = prev.get("outcome_summary", "(önceki ay özeti yok)")
        prev_choice = prev.get("action", "")
        durum_focus = (
            "Bu ay DURUM ANALİZİ, girişim fikrini tekrar anlatmak yerine **geçen ay yapılan hamlenin** etkisini analiz et: "
            f"\n- Geçen ay hamle: {prev_choice}"
            f"\n- Geçen ay sonuç özeti: {prev_summary}"
            "\nBunu 1-2 paragraf net ve anlaşılır şekilde yaz."
        )

    beat_line = "" if not beat else f"Bu ayın vaka tohumu (esinlenme): {beat['seed']}"

    # Seçeneklerde sonuç/metric söyleme yok.
    # Kriz net, somut, anlaşılır; MRR/kasa sayılarını kriz metninin içine yazma.
    # Extreme ise absürt seed'i mutlaka kullan.

    return f"""
Sen bir "Startup Survivor RPG" oyun yöneticisisin. Türkçe yaz.

MOD: {mode}
Mod tonu: {mod['tone']}
Kural: Yazdığın her şey oyun içi metin olarak kullanılacak. Jargon az; net; akıcı.

Oyuncu/persona:
- İsim: {st.session_state['player_name']}
- Sektör: {persona.get('sektor')}
- Hedef kitle: {persona.get('hedef_kitle')}
- Strateji tarzı: {persona.get('strateji')}
- Yazım tarzı tercihi: {persona.get('tarz')}

Mevcut metrikler (kriz metnine SAYI koyma, sadece arka plan):
- Kasa: {int(metrics.cash)}
- MRR: {int(metrics.mrr)}
- Kayıp oranı: {metrics.churn_pct:.1f}%
- İtibar: {metrics.reputation:.0f}/100
- Support yükü: {metrics.support_load:.0f}/100
- Altyapı yükü: {metrics.infra_load:.0f}/100

    Sezon: Ay {month}/{season_len}
    Girişim fikri (ham metin):
    <<<GIRISIM_FIKRI>>>
    {idea}
    <<<BITIS>>>

{durum_focus}

Kriz yazım kuralı:
- KRİZ kısmı 4-7 cümle olsun.
- Olay somut, okunur, anlaşılır olsun (kim, ne yaptı, niye sorun, hangi gerilime bağlanıyor).
- Krizde metrik sayıları (kasa/MRR) yazma.
- Mod Extreme ise absürt/komik bir internet/kurumsal saçmalık olayı mutlaka olsun.

Bu ay olay tohumu:
- {event_seed}
{beat_line}

Seçenek kuralı:
- Sadece A ve B seçeneklerini sun.
- Seçenek açıklamasında **sonuç/etki tahmini yazma** ("support artar" / "MRR düşer" gibi cümleler yasak).
- Seçenekler 3-5 maddelik kısa bir plan gibi yazılsın.

ÇIKTIYI SADECE JSON olarak ver (başka hiçbir şey yazma).
Şema:
{{
  "durum_analizi": "...",
  "kriz": "...",
  "secenekler": {{
    "A": {{"baslik": "...", "adimlar": ["...", "...", "..."]}},
    "B": {{"baslik": "...", "adimlar": ["...", "...", "..."]}}
  }},
  "meta": {{
    "archetypeA": "{random.choice(ARCHETYPES)}",
    "archetypeB": "{random.choice(ARCHETYPES)}",
    "severity": {beat['severity'] if beat else 3}
  }}
}}
""".strip()


def build_resolution_prompt(mode: str, month: int, bundle: dict, action_text: str, metrics_before: Metrics,
                            metrics_after: Metrics, persona: dict) -> str:
    mod = MODS[mode]

    # Sonuç metninde sayıları kullanabiliriz ama kısa ve okunur tut.
    return f"""
Sen oyun yöneticisisin. Türkçe yaz.
MOD: {mode} (ton: {mod['tone']})

Ay {month} hamlesi:
	<<<HAMLE>>>
	{action_text}
	<<<BITIS>>>

Bu ayın krizi:
	<<<KRIZ>>>
	{bundle.get('kriz','')}
	<<<BITIS>>>

İstenen:
- 1 kısa paragraf: hamlenin nasıl uygulandığı (sahne, ekip, kullanıcı davranışı) ve komik/gerilimli detay.
- 1 kısa paragraf: ortaya çıkan sonuçlar (kullanıcı algısı, support, altyapı, itibar, gelir dinamiği).
- En sona 1 satırlık "Özet:" cümlesi koy (tek cümle, çok net).

Metrikler (bunları bu sefer kullanabilirsin):
- Önce: kasa {int(metrics_before.cash)}, MRR {int(metrics_before.mrr)}, kayıp {metrics_before.churn_pct:.1f}%, itibar {metrics_before.reputation:.0f}, support {metrics_before.support_load:.0f}, altyapı {metrics_before.infra_load:.0f}
- Sonra: kasa {int(metrics_after.cash)}, MRR {int(metrics_after.mrr)}, kayıp {metrics_after.churn_pct:.1f}%, itibar {metrics_after.reputation:.0f}, support {metrics_after.support_load:.0f}, altyapı {metrics_after.infra_load:.0f}

Sadece düz metin yaz. Başlık koyma.
""".strip()


def generate_month_bundle() -> dict:
    ss = st.session_state
    mode = ss["mode"]
    month = ss["month"]

    # Case beat varsa onu kullan
    beat = case_beat(month, ss["case"])

    # event seed
    event_id, event_seed = pick_event_seed(mode)

    last_decision = ss["decision_history"][-1] if ss["decision_history"] else None

    prompt = build_month_prompt(
        mode=mode,
        month=month,
        season_len=ss["season_len"],
        idea=ss["idea"],
        metrics=ss["metrics"],
        persona=ss["persona"],
        case_name=ss["case"],
        event_seed=event_seed,
        beat=beat,
        last_decision=last_decision,
    )

    j = llm_json(prompt, temperature=0.8 if mode == "Extreme" else 0.7, max_output_tokens=1100)

    if not j:
        # Fallback: basit ama çalışır
        # Not: kullanıcı gerçek LLM ile oynadığında kalite artar.
        j = {
            "durum_analizi": (
                "Bu ay sahne kaygan: değer önerin 'anlık ihtiyaç' yakalıyor ama herkes farklı şey sanıyor. "
                "Net bir cümle ve tek bir ilk başarı anı üretmezsen, büyüme değil gürültü toplayacaksın."
            ) if month == 1 else (
                "Geçen ayın hamlesi kısa vadede nefes aldırdı ama yan etkileri var: ekipte öncelik algısı kaydı, "
                "kullanıcılar da senin söylediğin şey yerine anladığı şeye tutundu. Bu ay, o yanlış anlama ile yüzleşeceksin."
            ),
            "kriz": (
                f"{event_seed} Bu ay, ürününün ne olduğu konusunda iki farklı hikâye aynı anda yayılıyor. "
                "Biri seni büyütüyor, diğeri seni yanlış kitleye boğuyor. "
                "Ekip 'hepsini yapalım' ile 'tek şeye kilitlenelim' arasında geriliyor. "
                "Bir karar vermezsen, support ve altyapı üst üste binip seni yavaşlatacak."
            ),
            "secenekler": {
                "A": {"baslik": "Tek vaat protokolü", "adimlar": [
                    "Tek cümlelik değer önerisini yaz ve ekipte kilitle.",
                    "Onboarding'i 3 ekrana indir; ilk 60 saniyede tek başarı anı.",
                    "Kurumsal istekleri 1 sayfalık kapsam notuna bağla.",
                    "SSS + 6 hazır cevapla support'ı düzle."
                ]},
                "B": {"baslik": "Çift kulvar planı", "adimlar": [
                    "Kullanımı iki kulvara ayır: hızlı akış / derin akış.",
                    "İlk ekranda tek soru sor ve akışı ona göre aç.",
                    "Kurumsala şablon bir paket hazırla; özel istekleri sıraya al.",
                    "Sosyal taraftaki yanlış kullanıma küçük rehberler ekle."
                ]},
            },
            "meta": {"archetypeA": "odak", "archetypeB": "ikili_kulvar", "severity": 3},
        }

    # normalize
    j.setdefault("meta", {})
    j["meta"].setdefault("severity", 3)
    j["meta"].setdefault("archetypeA", "odak")
    j["meta"].setdefault("archetypeB", "filtre")

    # track event usage (to prevent repeats)
    ss["used_event_ids"].add(event_id)
    ss["recent_event_ids"].append(event_id)

    # attach ids
    j["meta"]["event_id"] = event_id

    return j


# -------------------------
# Simulation / Impact
# -------------------------

# Archetype -> metric deltas (bias). Values are multipliers; later scaled by severity & mode.
ARCH_IMPACT: Dict[str, Dict[str, float]] = {
    # cash: + means improves cash (less burn / more), mrr: + means grows
    # churn: negative means churn goes down
    # loads: negative means load decreases
    "odak": {"mrr": 0.35, "churn": -0.35, "support": -0.2, "infra": -0.15, "rep": 0.2, "cash": 0.1},
    "filtre": {"mrr": 0.15, "churn": -0.45, "support": -0.35, "infra": -0.25, "rep": 0.25, "cash": 0.12},
    "ikili_kulvar": {"mrr": 0.28, "churn": -0.2, "support": 0.05, "infra": 0.08, "rep": 0.12, "cash": -0.05},
    "altyapi": {"mrr": 0.05, "churn": -0.25, "support": -0.25, "infra": -0.6, "rep": 0.18, "cash": -0.18},
    "pr": {"mrr": 0.12, "churn": -0.12, "support": 0.05, "infra": 0.0, "rep": 0.45, "cash": -0.08},
    "fiyat": {"mrr": 0.5, "churn": 0.15, "support": 0.1, "infra": 0.05, "rep": -0.1, "cash": 0.2},
    "kurumsal": {"mrr": 0.6, "churn": 0.05, "support": 0.18, "infra": 0.12, "rep": 0.05, "cash": 0.25},
    "selfserve": {"mrr": 0.25, "churn": -0.15, "support": -0.15, "infra": 0.05, "rep": 0.05, "cash": 0.08},
    "rehber": {"mrr": 0.12, "churn": -0.22, "support": -0.18, "infra": -0.05, "rep": 0.2, "cash": 0.05},
    "kisit": {"mrr": -0.05, "churn": -0.18, "support": -0.25, "infra": -0.1, "rep": -0.05, "cash": 0.12},
    "uyumluluk": {"mrr": 0.2, "churn": -0.05, "support": 0.05, "infra": 0.05, "rep": 0.35, "cash": -0.18},
    "delegasyon": {"mrr": 0.1, "churn": -0.05, "support": -0.1, "infra": -0.05, "rep": 0.05, "cash": 0.02},
    "teknik": {"mrr": 0.05, "churn": -0.15, "support": -0.15, "infra": -0.3, "rep": 0.15, "cash": -0.12},
    "ertelemek": {"mrr": 0.05, "churn": 0.2, "support": 0.2, "infra": 0.12, "rep": -0.2, "cash": 0.1},
}


def apply_monthly_burn(metrics: Metrics, expenses: dict) -> None:
    burn = float(expenses.get("Maşlar", 0) + expenses.get("Sunucu", 0) + expenses.get("Pazarlama", 0))
    # gelir = MRR
    metrics.cash = max(0.0, metrics.cash - burn + metrics.mrr)


def simulate_choice(bundle: dict, choice: str, free_text_action: Optional[str] = None) -> Tuple[Metrics, str, str]:
    """Return (metrics_after, action_text, archetype_used)."""
    ss = st.session_state
    mode = ss["mode"]
    mod = MODS[mode]
    severity = float(bundle.get("meta", {}).get("severity", 3))

    # choose archetype
    if choice == "A":
        archetype = bundle.get("meta", {}).get("archetypeA", "odak")
        action_text = f"A) {bundle['secenekler']['A'].get('baslik','A Planı')}"
    elif choice == "B":
        archetype = bundle.get("meta", {}).get("archetypeB", "filtre")
        action_text = f"B) {bundle['secenekler']['B'].get('baslik','B Planı')}"
    else:
        # serbest hamle: LLM yoksa odak varsay
        archetype = "odak"
        action_text = free_text_action or "(Serbest hamle)"

    base = ARCH_IMPACT.get(archetype, ARCH_IMPACT["odak"])

    # RNG: volatility
    rng = random.Random(ss["seed"] + ss["month"] * 104729 + _stable_hash(action_text) % 10000)
    noise = lambda s: (rng.random() * 2 - 1) * s

    # scale
    sev_scale = (0.6 + 0.25 * severity) * mod["severity_mul"]
    vol = mod["volatility"]

    before: Metrics = ss["metrics"]
    after = Metrics(**before.__dict__)

    # apply deltas
    after.mrr = max(0.0, after.mrr + (2000 * sev_scale) * base["mrr"] + noise(500 * vol))
    after.churn_pct = _clamp(after.churn_pct + (8 * sev_scale) * base["churn"] + noise(1.2 * vol), 0.5, 35.0)
    after.reputation = _clamp(after.reputation + (18 * sev_scale) * base["rep"] + noise(2.5 * vol), 0.0, 100.0)
    after.support_load = _clamp(after.support_load + (22 * sev_scale) * base["support"] + noise(3.5 * vol), 0.0, 100.0)
    after.infra_load = _clamp(after.infra_load + (22 * sev_scale) * base["infra"] + noise(3.5 * vol), 0.0, 100.0)

    # cash impact: primarily via burn/revenue, but allow small bonus/penalty
    after.cash = max(0.0, after.cash + (120000 * sev_scale) * base["cash"] + noise(20000 * vol))

    # monthly burn at end of month
    apply_monthly_burn(after, ss["monthly_expenses"])

    return after, action_text, archetype


# -------------------------
# UI rendering
# -------------------------


def sidebar_ui() -> None:
    ss = st.session_state

    st.sidebar.markdown(f"### {ss['player_name']}")

    # Mod select above calendar
    ss["mode"] = st.sidebar.selectbox(
        "Mod",
        options=list(MODS.keys()),
        index=list(MODS.keys()).index(ss["mode"]) if ss["mode"] in MODS else 3,
        help="Mod, olayların tonunu ve zorluk/kaos dengesini değiştirir.",
    )
    st.sidebar.caption(MODS[ss["mode"]]["tagline"])

    ss["case"] = st.sidebar.selectbox(
        "Vaka sezonu (opsiyonel)",
        options=list(REAL_CASES.keys()),
        index=list(REAL_CASES.keys()).index(ss["case"]) if ss["case"] in REAL_CASES else 0,
        help="Kamuya açık vakalardan esinlenilmiş sezonlar. Detaylar oyunlaştırılmıştır.",
    )
    st.sidebar.caption(REAL_CASES[ss["case"]]["desc"])

    ss["season_len"] = int(st.sidebar.slider("Sezon uzunluğu (ay)", 6, 24, int(ss["season_len"])))

    st.sidebar.markdown(f"<div class='small-muted'>Ay: {ss['month']}/{ss['season_len']}</div>", unsafe_allow_html=True)
    st.sidebar.progress(min(1.0, ss["month"] / max(1, ss["season_len"])))

    start_cash = int(st.sidebar.slider("Başlangıç kasası", 50_000, 3_000_000, int(ss["metrics"].cash) if not ss["game_started"] else int(ss["metrics"].cash), step=50_000))
    if not ss["game_started"]:
        ss["metrics"] = default_metrics(start_cash)

    st.sidebar.markdown("---")
    st.sidebar.markdown("### Finansal Durum")
    st.sidebar.markdown(f"**Kasa**\n\n{_tl(ss['metrics'].cash)}")
    st.sidebar.markdown(f"**MRR**\n\n{_tl(ss['metrics'].mrr)}")

    with st.sidebar.expander("Aylık Gider Detayı", expanded=True):
        exp = ss["monthly_expenses"]
        st.markdown(f"- Maaşlar: {_tl(exp.get('Maşlar', 0))}")
        st.markdown(f"- Sunucu: {_tl(exp.get('Sunucu', 0))}")
        st.markdown(f"- Pazarlama: {_tl(exp.get('Pazarlama', 0))}")
        st.markdown(f"**TOPLAM:** {_tl(sum(exp.values()))}")

    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**İtibar:** {ss['metrics'].reputation:.0f}/100")
    st.sidebar.markdown(f"**Support yükü:** {ss['metrics'].support_load:.0f}/100")
    st.sidebar.markdown(f"**Altyapı yükü:** {ss['metrics'].infra_load:.0f}/100")
    st.sidebar.markdown(f"**Kayıp oranı:** {_pct(ss['metrics'].churn_pct)}")

    st.sidebar.markdown("---")

    # Key diagnostics
    api_key = get_gemini_key()
    if api_key:
        st.sidebar.success("Gemini anahtarı görüldü. Model çağrıları çalışmalı.")
    else:
        st.sidebar.warning("GEMINI_API_KEY bulunamadı. (İstersen LLM olmadan da çalışır ama kalite düşer.)")

    cols = st.sidebar.columns(2)
    if cols[0].button("Yeni Oyun", use_container_width=True):
        reset_game()
        st.rerun()
    if cols[1].button("Sıfırla", use_container_width=True, help="Sezonu ve chat'i sıfırlar."):
        reset_game()
        st.rerun()


def topbar_persona_ui() -> None:
    ss = st.session_state

    # header row with persona expander on right
    left, right = st.columns([0.72, 0.28])
    with left:
        st.markdown("<div class='chat-header'>Startup Survivor RPG</div>", unsafe_allow_html=True)
        st.caption("Sohbet akışı korunur. Durum Analizi → Kriz → A/B (veya serbest hamle).")

    with right:
        with st.expander("🛠️ Karakterini ve ayarlarını özelleştir", expanded=False):
            ss["player_name"] = st.text_input("Karakter adı", ss["player_name"], max_chars=24)
            p = ss["persona"]
            p["sektor"] = st.selectbox("Sektör", ["Genel", "B2C", "B2B", "SaaS", "Eğitim", "Oyun", "Fintech"], index=["Genel", "B2C", "B2B", "SaaS", "Eğitim", "Oyun", "Fintech"].index(p.get("sektor", "Genel")))
            p["hedef_kitle"] = st.text_input("Hedef kitle", p.get("hedef_kitle", "Genel kullanıcı"))
            p["strateji"] = st.selectbox("Oyun tarzı", ["Dengeli", "Agresif büyüme", "Maliyet kıs", "Kurumsal", "Topluluk"], index=["Dengeli", "Agresif büyüme", "Maliyet kıs", "Kurumsal", "Topluluk"].index(p.get("strateji", "Dengeli")))
            p["tarz"] = st.selectbox("Anlatım tarzı", ["Net, kısa, vurucu", "Daha hikâye gibi", "Daha teknik", "Daha komik"], index=["Net, kısa, vurucu", "Daha hikâye gibi", "Daha teknik", "Daha komik"].index(p.get("tarz", "Net, kısa, vurucu")))
            ss["persona"] = p


def add_assistant(text: str) -> None:
    st.session_state["messages"].append({"role": "assistant", "content": text})


def add_user(text: str) -> None:
    st.session_state["messages"].append({"role": "user", "content": text})


def render_chat() -> None:
    for m in st.session_state["messages"]:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])  # markdown allowed


def start_game_flow() -> None:
    ss = st.session_state
    ss["seed"] = random.randint(1, 10_000_000)
    ss["game_started"] = True
    ss["phase"] = "awaiting_action"
    ss["month"] = 1
    ss["messages"] = []
    ss["decision_history"] = []
    ss["used_event_ids"] = set()
    ss["recent_event_ids"] = []
    ss["current_bundle"] = None

    add_assistant(f"Tamam **{ss['player_name']}**. Ay 1'den başlıyoruz. Mod: **{ss['mode']}**.")

    # generate month bundle once
    bundle = generate_month_bundle()
    ss["current_bundle"] = bundle

    add_assistant(f"🧠 **Durum Analizi (Ay {ss['month']})**\n\n{bundle['durum_analizi']}")
    add_assistant(f"⚠️ **Kriz**\n\n{bundle['kriz']}")
    add_assistant("👉 Şimdi seçim zamanı. A mı B mi? (İstersen serbest hamleni de yazabilirsin.)")


def finish_game() -> None:
    ss = st.session_state
    ss["phase"] = "done"
    add_assistant("Sezon bitti. İstersen Yeni Oyun'a basıp farklı mod/vaka ile tekrar başlayabilirsin.")


def advance_to_next_month() -> None:
    ss = st.session_state
    ss["month"] += 1
    ss["current_bundle"] = None
    if ss["month"] > ss["season_len"]:
        finish_game()
        return

    # generate next month bundle
    bundle = generate_month_bundle()
    ss["current_bundle"] = bundle

    add_assistant(f"🧠 **Durum Analizi (Ay {ss['month']})**\n\n{bundle['durum_analizi']}")
    add_assistant(f"⚠️ **Kriz**\n\n{bundle['kriz']}")
    add_assistant("👉 Şimdi seçim zamanı. A mı B mi? (İstersen serbest hamleni de yazabilirsin.)")


def resolve_action(choice: str, free_text: Optional[str] = None) -> None:
    ss = st.session_state
    bundle = ss["current_bundle"]
    if not bundle:
        return

    before = ss["metrics"]
    after, action_text, archetype = simulate_choice(bundle, choice=choice, free_text_action=free_text)

    # Log user choice
    if choice in ("A", "B"):
        add_user(f"Seçim: **{choice}** — {action_text}")
    else:
        add_user(f"Hamle: {free_text}")

    # Generate narrative outcome
    outcome_txt = None
    prompt = build_resolution_prompt(
        mode=ss["mode"],
        month=ss["month"],
        bundle=bundle,
        action_text=free_text if choice not in ("A", "B") else action_text,
        metrics_before=before,
        metrics_after=after,
        persona=ss["persona"],
    )
    # LLM metin
    api_key = get_gemini_key()
    if api_key:
        try:
            model = get_gemini_model(api_key)
            resp = model.generate_content(
                prompt,
                generation_config={"temperature": 0.8 if ss["mode"] == "Extreme" else 0.65, "max_output_tokens": 650},
            )
            outcome_txt = getattr(resp, "text", "")
        except Exception:
            outcome_txt = None

    if not outcome_txt:
        # Fallback
        outcome_txt = (
            "Hamleni uyguladın. Ekip önce itiraz etti, sonra bir şeyler yerine oturdu. "
            "Kullanıcıların bir kısmı rahatladı; bir kısmı ise alışkanlıklarını değiştirmeye direndi.\n\n"
            "Özet: Bu ay sahne biraz netleşti ama yeni bir yan etki bıraktı."
        )

    add_assistant(outcome_txt.strip())

    # Update metrics and store decision history
    ss["metrics"] = after
    ss["decision_history"].append({
        "month": ss["month"],
        "choice": choice,
        "action": free_text if choice not in ("A", "B") else action_text,
        "archetype": archetype,
        "event_id": bundle.get("meta", {}).get("event_id"),
        "outcome_summary": (outcome_txt.strip().split("Özet:")[-1].strip() if "Özet:" in outcome_txt else outcome_txt.strip()[:120]),
    })

    # Move forward
    advance_to_next_month()


# -------------------------
# Main
# -------------------------

sidebar_ui()

topbar_persona_ui()

ss = st.session_state

# Setup screen
if not ss["game_started"]:
    st.markdown("<div class='hr'></div>", unsafe_allow_html=True)

    st.info("Oyuna başlamak için girişim fikrini yaz ve 'Oyunu Başlat'a bas.")

    ss["idea"] = st.text_area(
        "Girişim fikrin ne?",
        value=ss.get("idea", ""),
        height=140,
        placeholder="Örn: ...",
    )

    cols = st.columns([0.22, 0.78])
    with cols[0]:
        start_clicked = st.button("🚀 Oyunu Başlat", use_container_width=True)
    with cols[1]:
        st.caption("Not: GEMINI_API_KEY yoksa oyun yine açılır ama içerik daha şablon olur. Streamlit Cloud'da Secrets'a ekle.")

    if start_clicked:
        if not ss["idea"].strip():
            st.error("Önce girişim fikrini yaz.")
        else:
            start_game_flow()
            st.rerun()

else:
    # In-game
    render_chat()

    if ss["phase"] == "awaiting_action" and ss.get("current_bundle"):
        bundle = ss["current_bundle"]

        # Choice UI
        st.markdown("<div class='hr'></div>", unsafe_allow_html=True)

        colA, colB = st.columns(2)

        a = bundle["secenekler"]["A"]
        b = bundle["secenekler"]["B"]

        with colA:
            st.markdown("<div class='choice-wrap'>", unsafe_allow_html=True)
            st.markdown(f"<div class='choice-title'>A) {a.get('baslik','A Planı')}</div>", unsafe_allow_html=True)
            steps = a.get("adimlar", [])
            if steps:
                st.markdown(
    "<ul class='choice-steps'>"
    + "".join([f"<li>{html.escape(str(s))}</li>" for s in (steps or [])])
    + "</ul>",
    unsafe_allow_html=True
)

            st.markdown("</div>", unsafe_allow_html=True)
            if st.button("A seç", key=f"chooseA_{ss['month']}", use_container_width=True):
                resolve_action("A")
                st.rerun()

        with colB:
            st.markdown("<div class='choice-wrap'>", unsafe_allow_html=True)
            st.markdown(f"<div class='choice-title'>B) {b.get('baslik','B Planı')}</div>", unsafe_allow_html=True)
            steps = b.get("adimlar", [])
            if steps:
                st.markdown("<ul class='choice-steps'>" + "".join([f"<li>{st.escape(s)}</li>" for s in steps]) + "</ul>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
            if st.button("B seç", key=f"chooseB_{ss['month']}", use_container_width=True):
                resolve_action("B")
                st.rerun()

        # Optional free-text action
        user_text = st.chat_input("İstersen serbest hamleni yaz (opsiyonel).")
        if user_text:
            resolve_action("FREE", free_text=user_text.strip())
            st.rerun()

    elif ss["phase"] == "done":
        st.success("Sezon tamamlandı.")

# Footer tip about secrets formatting (only if missing)
if not get_gemini_key():
    with st.expander("GEMINI_API_KEY nasıl eklenir?", expanded=False):
        st.markdown(
            """
Streamlit Cloud → App → **Settings → Secrets** alanına şunu ekle:

```toml
GEMINI_API_KEY = "BURAYA_TEKNOKEŞ"
```

Birden fazla anahtar kullanacaksan:

```toml
GEMINI_API_KEYS = ["KEY1", "KEY2"]
```

> Not: Ekran görüntüsünde anahtar(lar) görünmüş; güvenlik için yenileyip (rotate) yeniden oluşturmanı öneririm.
            """.strip()
        )
