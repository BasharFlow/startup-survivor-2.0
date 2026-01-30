# app.py
import os
import json
import random
import hashlib
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Tuple, Optional

import streamlit as st
import google.generativeai as genai


# =========================
# CONFIG
# =========================
APP_TITLE = "Startup Survivor RPG"
MODEL_NAME = "gemini-2.5-flash"  # sende çalışıyorsa bunu bırak
API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

if API_KEY:
    genai.configure(api_key=API_KEY)


# =========================
# HELPERS
# =========================
def money(n: float) -> str:
    try:
        n = float(n)
    except Exception:
        n = 0.0
    return f"{int(round(n)):,}".replace(",", ".") + " ₺"


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def sha(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()[:12]


def pick_weighted(items: List[Tuple[Any, float]], rng: random.Random):
    total = sum(w for _, w in items)
    r = rng.random() * total
    upto = 0.0
    for item, w in items:
        upto += w
        if upto >= r:
            return item
    return items[-1][0]


def safe_model():
    return genai.GenerativeModel(MODEL_NAME)


def llm_json(prompt: str, temperature: float = 0.85, max_output_tokens: int = 1400) -> Dict[str, Any]:
    model = safe_model()
    resp = model.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        ),
    )
    text = (resp.text or "").strip()

    # strip code fences if any
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1].strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()

    try:
        return json.loads(text)
    except Exception:
        # try best-effort extraction
        l = text.find("{")
        r = text.rfind("}")
        if l != -1 and r != -1 and r > l:
            try:
                return json.loads(text[l : r + 1])
            except Exception:
                pass
    return {"_error": "json_parse_failed", "_raw": text}


# =========================
# GAME STATE
# =========================
@dataclass
class Metrics:
    cash: float
    mrr: float
    churn: float          # 0..1
    reputation: float     # 0..100
    support_load: float   # 0..100
    infra: float          # 0..100

    team: float           # 0..100 (ekip gücü)
    motivation: float     # 0..100 (motivasyon)

    def cost_breakdown(self) -> Dict[str, float]:
        # Screenshots'taki ruh: Maaş + Sunucu + Pazarlama + "gizli" yükler
        salaries = 50_000
        server = 500 + (100 - self.infra) * 120 + (self.support_load * 40)
        marketing = 5_000 + max(0, (60 - self.reputation)) * 60
        misc = 0  # istersek sonra eklenebilir
        return {
            "Maaşlar": salaries,
            "Sunucu": server,
            "Pazarlama": marketing,
            "Diğer": misc
        }

    @property
    def burn(self) -> float:
        b = self.cost_breakdown()
        return float(sum(b.values()))

    def apply_deltas(self, d: Dict[str, float]):
        self.cash += float(d.get("cash", 0))
        self.mrr = max(0.0, self.mrr + float(d.get("mrr", 0)))
        self.churn = clamp(self.churn + float(d.get("churn", 0)), 0.0, 0.95)
        self.reputation = clamp(self.reputation + float(d.get("reputation", 0)), 0.0, 100.0)
        self.support_load = clamp(self.support_load + float(d.get("support_load", 0)), 0.0, 100.0)
        self.infra = clamp(self.infra + float(d.get("infra", 0)), 0.0, 100.0)
        self.team = clamp(self.team + float(d.get("team", 0)), 0.0, 100.0)
        self.motivation = clamp(self.motivation + float(d.get("motivation", 0)), 0.0, 100.0)

    def month_tick(self):
        self.cash += self.mrr - self.burn
        # aşırı negatifte kilitlenmesin diye
        self.cash = max(-10_000_000, self.cash)


def default_character():
    return {
        "name": "İsimsiz Girişimci",
        "avatar": "🧑‍💻",
        "background": "Genelci",
        "trait": "Hızlı Öğrenen",
        "risk": "Dengeli",  # Dengeli / Agresif / Temkinli
    }


def init_state():
    if "game" not in st.session_state:
        st.session_state.game = {
            "started": False,
            "idea": "",
            "mode": "Extreme",
            "month": 1,
            "months_total": 12,
            "rng_seed": 12345,
            "chat": [],  # [{"role":"user/assistant","content":"..."}]
            "last_turn": None,

            # anti-repeat
            "recent_fingerprints": [],     # title_fingerprint
            "recent_event_ids": [],        # event_id
            "recent_families": [],         # last families
            "recent_text_hashes": [],      # durum+kriz hash

            "character": default_character(),
            "settings": {
                "show_suggestions": False,  # "Öneri" kısmını şimdilik kapalı tutuyoruz
            },

            "metrics": Metrics(
                cash=1_000_000,
                mrr=0.0,
                churn=0.12,
                reputation=55.0,
                support_load=35.0,
                infra=65.0,
                team=50.0,
                motivation=50.0,
            ),
        }


# =========================
# MODES
# =========================
MODE_DESCRIPTIONS = {
    "Realist": "Dengeli ve profesyonel simülasyon. Mantıklı kararlar ödüllendirilir.",
    "Hard": "Kıt kaynak, ağır bedeller. Her seçenek trade-off içerir.",
    "Spartan": "Acımasız ayı piyasası. Engeller maksimum, hata affetmez.",
    "Extreme": "Kaos ve absürt. Paylaşmalık olaylar. Mantık ikinci planda; sonuç metriklere çarpar.",
    "Türkiye": "Türkiye gerçekliği: kur/enflasyon/ödeme/vergiler/bürokrasi/tedarik/işgücü.",
}

EXTREME_FAMILIES = [
    ("social_platform", 0.50),
    ("surreal_metaphor", 0.30),
    ("scifi_cameo", 0.20),
]

# Daha büyük havuz = tekrar azalır.
# Event ID'ler "EXT-XXX" şeklinde; tekrar kilidi bu ID üzerinden çalışır.
EXTREME_POOL: Dict[str, List[Dict[str, str]]] = {
    "social_platform": [
        {"id": "EXT-002", "seed": "Bir influencer seni överken ürünü 'yanlış' tanımlıyor: herkes yanlış beklentiyle akın ediyor. Support DM'leri 'bu niye böyle değil??' diye yanıyor."},
        {"id": "EXT-003", "seed": "Platform algoritması seni yanlış kategoriye atıyor: insanlar ürünü 'ilişki testi' sanıp giriyor. Conversion artıyor ama churn da artıyor."},
        {"id": "EXT-004", "seed": "App store yorumlarında tek emoji trendi başlıyor. Rating dalgalanıyor; herkes aynı emojiyi spamliyor. Support yükü 'emoji çevirisi' talebine dönüyor."},
        {"id": "EXT-005", "seed": "Bir meme sayfası ekran görüntünü 'startup'ın en komik bug’ı' diye paylaşıyor. Trafik patlıyor; itibar ve support aynı anda kavga ediyor."},
        {"id": "EXT-010", "seed": "Bir kurumsal LinkedIn postu seni 'Case Study' diye paylaşıyor ama metnin yarısı otomatik çeviriyle komikleşmiş. CEO'lar geliyor, kullanıcılar gülüyor, altyapı ağlıyor."},
        {"id": "EXT-012", "seed": "Kullanıcılar challenge başlatıyor: ürünü en saçma yerde kullanıp ekran görüntüsü alma yarışı. Paylaşım artıyor ama support ve sunucu maliyeti fırlıyor."},
        {"id": "EXT-013", "seed": "Bir ünlü yanlışlıkla aboneliğe basıp story atıyor: 'Bu ne ya?' — tam da viral oluyor. MRR artıyor ama churn dalgası geliyor."},
        {"id": "EXT-014", "seed": "Rakip senin ekran görüntünü 'bizde yok' diye paylaşıyor. Herkes sende olmayan özelliği isterken sen 'ben onu hiç demedim' diye açıklama yazıyorsun."},
        {"id": "EXT-017", "seed": "Bir podcast sunucusu ürün adını yanlış okuyup yeni bir jargon uyduruyor. İnsanlar seni o kelimeyle arıyor; inbound artıyor ama kimse ne aldığını bilmiyor."},
        {"id": "EXT-018", "seed": "Bir spam bot ordusu ürününü 'en romantik çeviri' diye dolduruyor. Abone sayısı artıyor ama chargeback kokusu var. Support 'aşk mektupları' ile doluyor."},
        {"id": "EXT-020", "seed": "Bir marka senin adını yanlışlıkla kampanyaya koyuyor. Support'a 'indirim kodu çalışmıyor' yağmuru başlıyor, itibarın müşteri hizmetleri tonuna bağlı kalıyor."},
        {"id": "EXT-025", "seed": "Kullanıcılar ürünü ters kullanınca daha komik buluyor. Gerçek kullanım düşüyor ama sosyal paylaşım patlıyor. Ürün 'meme makinesi'ne dönüşüyor."},
        {"id": "EXT-026", "seed": "TikTok’ta trend: 'Bu uygulama beni yargıladı' — herkes senin kriz cümlelerini ekran görüntüsü alıp paylaşıyor. Senin metinlerin viral; metriklerin panik."},
        {"id": "EXT-027", "seed": "Bir topluluk seni 'asla yapma' listesine koyuyor; ters psikolojiyle herkes denemeye geliyor. Conversion artıyor ama churn dalga dalga."},
        {"id": "EXT-028", "seed": "Bir ürün avı (product hunt) sayfasında seni yanlış etiketliyorlar: 'Steam oyun çeviri hilesi'. Yeni kitle geliyor; ödeme itirazları başlıyor."},
        {"id": "EXT-033", "seed": "Bir kurumsal müşteri demo isterken yanlış linki tüm şirkete atıyor. 800 kişi aynı anda deniyor; support load bir anda 'kurumsal panik' seviyesine çıkıyor."},
        {"id": "EXT-034", "seed": "Instagram keşfeti seni 'manifestasyon' etiketinde gösteriyor. Kullanıcılar uygulamayı başarı ritüeli sanıyor; ürün yerine umut satın alıyorlar."},
        {"id": "EXT-035", "seed": "Bir 'AI detoks' influencer'ı seni 'en bağımlılık yapan ürün' diye suçluyor. Topluluk ikiye bölünüyor; itibarın tartışma performansına bağlı."},
        {"id": "EXT-037", "seed": "X’te biri 'bu uygulama benim ekranı dinliyor' diye komplo yazıyor. Herkes test ediyor. Trafik patlıyor; churn ve support da patlıyor."},
    ],
    "surreal_metaphor": [
        {"id": "EXT-S01", "seed": "Metrikler konuşmaya başlıyor: churn sana 'ben gidiyorum' diye DM atıyor, support 'ben bittim' diye ağlıyor. Ekip bunu ciddiye alıyor gibi davranıyor."},
        {"id": "EXT-S02", "seed": "Roadmap’teki post-it’ler gece kendi kendine yer değiştiriyor. Sabah herkes başka şeye çalışmış; 'bu da çevik' diyerek devam ediyorlar."},
        {"id": "EXT-S03", "seed": "Ürün kullanıcıların dilini değil 'niyetini' çeviriyor. Yanlış anlaşılmalar romantik/komik kriz çıkarıyor; support yeni bir edebiyat kulübü gibi."},
        {"id": "EXT-S04", "seed": "Her demo sırasında sunucu sadece en kritik anda 'naz yapıyor'. Sanki bilinçli. İtibar: 'kader mi test mi?' tartışmasına dönüyor."},
    ],
    "scifi_cameo": [
        {"id": "EXT-X01", "seed": "Bir AR filtresi hatası yüzünden ürünün uzaylı meme’ine dönüşüyor. Talep patlıyor, altyapı çöküyor, itibar 'efsane mi rezalet mi?' arası."},
        {"id": "EXT-X02", "seed": "Botlar seni 'en iyi çevirmen' ilan ediyor ve topluca abone oluyor. MRR artıyor ama support 'botlarla konuşma terapisi'ne dönüyor."},
    ],
}

TURKEY_SEEDS = [
    "Kur bir haftada zıplıyor; yabancı servis maliyetin TL’de bir anda şişiyor.",
    "Ödeme sağlayıcısı 'risk' bahanesiyle ekstra doğrulama istiyor; dönüşüm düşüyor.",
    "KDV/masraf/komisyon kalemleri tahmin edilenden yüksek geliyor; nakit akışı sıkışıyor.",
    "Enflasyon dalgası: maaş beklentisi güncelleniyor; ekip motivasyonu pazarlığa dönüyor.",
    "Reklam maliyetleri dalgalanıyor; CAC bozuluyor, büyüme yavaşlıyor.",
    "B2B satışta 'bir üstten onay' döngüsü uzuyor; satış döngüsü şişiyor.",
]


def mode_style(mode: str) -> str:
    if mode == "Realist":
        return "Ton: profesyonel, dengeli, gerçekçi. Absürt mizah yok."
    if mode == "Hard":
        return "Ton: ciddi ve zorlayıcı. Her seçeneğin bedeli var, kolay çıkış yok."
    if mode == "Spartan":
        return "Ton: acımasız ayı piyasası. Engeller maksimum, şans minimum."
    if mode == "Türkiye":
        return "Ton: Türkiye gerçekliği. Kur/enflasyon/ödeme/vergiler/tedarik/işgücü gibi dinamikler."
    return (
        "Ton: KAOTİK, komik, paylaşmalık, özgün. Danışman/öğüt veren dil YASAK. "
        "Olaylar absürt olacak ama sonuçlar metriklere bağlanacak."
    )


# =========================
# ANTI-REPEAT: EVENT CHOICE
# =========================
def choose_event_seed(state: Dict[str, Any], rng: random.Random) -> Tuple[Optional[str], str, Optional[str]]:
    mode = state["mode"]
    if mode == "Extreme":
        # aile seç
        last_families = state["recent_families"][-2:]
        family = pick_weighted(EXTREME_FAMILIES, rng)

        # mümkünse son 2 aileyi tekrar etme
        tries = 0
        while family in last_families and tries < 4:
            family = pick_weighted(EXTREME_FAMILIES, rng)
            tries += 1

        pool = EXTREME_POOL[family]
        recent_ids = set(state["recent_event_ids"][-8:])  # son 8 olayı tekrar etme
        candidates = [e for e in pool if e["id"] not in recent_ids]
        if not candidates:
            candidates = pool[:]  # havuz tükendiyse serbest bırak

        chosen = rng.choice(candidates)
        return chosen["seed"], family, chosen["id"]

    if mode == "Türkiye":
        return rng.choice(TURKEY_SEEDS), "turkiye", "TR-" + str(rng.randint(100, 999))

    return None, mode.lower(), None


# =========================
# PROMPT BUILDER
# =========================
def build_prompt(state: Dict[str, Any], event_seed: Optional[str], event_family: str, event_id: Optional[str], free_action: str) -> str:
    m: Metrics = state["metrics"]
    c = state["character"]
    mode = state["mode"]
    month = state["month"]

    # son mesajlardan kompakt bağlam
    last_msgs = state["chat"][-6:]
    ctx_lines = []
    for msg in last_msgs:
        role = msg.get("role", "assistant")
        content = (msg.get("content", "") or "").strip()
        if len(content) > 360:
            content = content[:360] + "…"
        ctx_lines.append(f"{role.upper()}: {content}")
    ctx = "\n".join(ctx_lines) if ctx_lines else "(yok)"

    banned_fps = state["recent_fingerprints"][-6:]
    banned_hashes = state["recent_text_hashes"][-6:]
    banned_ids = state["recent_event_ids"][-8:]

    # tekrar eden klişeleri açıkça yasaklayalım
    forbidden_phrases = [
        "sahne dediğin şey düz değil",
        "yer kayıyor",
        "perde arkasında",
        "sahnede ama",
        "masada net bir gerilim var: Şimdilik dengesin",
    ]

    seed_block = ""
    if event_seed:
        seed_block = f"BU TUR OLAY TOHUMU (mutlaka kullan): {event_seed}\nOlay ailesi: {event_family}\nOlay ID: {event_id}\n"
    else:
        seed_block = "BU TUR OLAY TOHUMU: (serbest)\n"

    return f"""
Sen bir "Startup Survivor RPG" tur motorusun. Çıktıyı SADECE geçerli JSON ver.

MOD: {mode}
{mode_style(mode)}

KARAKTER:
- İsim: {c.get("name")}
- Avatar: {c.get("avatar")}
- Arka plan: {c.get("background")}
- Özellik: {c.get("trait")}
- Risk yaklaşımı: {c.get("risk")}

GİRİŞİM FİKRİ:
{state["idea"]}

MEVCUT METRİKLER (Ay {month}):
- Kasa: {money(m.cash)}
- MRR: {money(m.mrr)}
- Churn: {round(m.churn*100,1)}%
- İtibar: {round(m.reputation,1)}/100
- Support yükü: {round(m.support_load,1)}/100
- Altyapı: {round(m.infra,1)}/100
- Ekip: {round(m.team,1)}/100
- Motivasyon: {round(m.motivation,1)}/100
- Aylık gider (burn): {money(m.burn)}

SOHBET BAĞLAMI (son mesajlar):
{ctx}

KULLANICININ SERBEST HAMLESİ (varsa): {free_action or "(yok)"}

{seed_block}

TEKRAR YASAĞI:
- Bu fingerprint'leri tekrar etme: {banned_fps}
- Bu event ID'leri tekrar etme: {banned_ids}
- Bu metin hash'lerine yakın şeyleri tekrar etme: {banned_hashes}
- Şu klişe ifadeleri KULLANMA: {forbidden_phrases}

İSTENEN AKIŞ (sırayı bozma):
1) "durum_analizi": 1 paragraf. Hikayesel. Chat gibi. Danışman/öğüt dili YASAK.
   - Fikri yorumla ama ders verme. Benzetmeler özgün olsun.
2) "kriz": 2-4 cümle. Detaylı: ne oldu + neden oldu + metrik etkisi.
   - En az 3 metrik adı geçsin (kasa/mrr/churn/itibar/support/altiyapi/ekip/motivasyon).
3) "secenekler": A ve B:
   - Başlık + 1 paragraf (ne çok kısa ne çok uzun). "Plan + risk/bedel".
   - Seçenekler krize gerçek çözüm denesin (Extreme'de çözüm 'garip' olabilir ama yine metriklere bağlanır).
4) "deltalar": A ve B için yaklaşık etkiler:
   cash, mrr, churn, reputation, support_load, infra, team, motivation

ÖZEL KURALLAR:
- Extreme modda: paylaşılası absürt olay. Normal/kurumsal metin yazma.
- Türkiye modda: kur/enflasyon/ödeme/vergiler vb. gerçeklik.
- Spartan modda: acımasız, kurtuluş zor.
- Her modda: tekrar eden kalıplardan kaçın.

JSON ŞEMASI:
{{
  "event_id": "string",
  "event_family": "string",
  "title_fingerprint": "string",
  "durum_analizi": "string",
  "kriz": {{
    "baslik": "string",
    "metin": "string"
  }},
  "secenekler": {{
    "A": {{ "baslik": "string", "metin": "string" }},
    "B": {{ "baslik": "string", "metin": "string" }}
  }},
  "deltalar": {{
    "A": {{ "cash": number, "mrr": number, "churn": number, "reputation": number, "support_load": number, "infra": number, "team": number, "motivation": number }},
    "B": {{ "cash": number, "mrr": number, "churn": number, "reputation": number, "support_load": number, "infra": number, "team": number, "motivation": number }}
  }}
}}
""".strip()


def validate_turn(out: Dict[str, Any]) -> bool:
    needed = ["event_id", "event_family", "title_fingerprint", "durum_analizi", "kriz", "secenekler", "deltalar"]
    for k in needed:
        if k not in out:
            return False
    if not isinstance(out["kriz"], dict) or "baslik" not in out["kriz"] or "metin" not in out["kriz"]:
        return False
    if not isinstance(out["secenekler"], dict) or "A" not in out["secenekler"] or "B" not in out["secenekler"]:
        return False
    if not isinstance(out["deltalar"], dict) or "A" not in out["deltalar"] or "B" not in out["deltalar"]:
        return False
    return True


def generate_turn(state: Dict[str, Any], free_action: str = "") -> Dict[str, Any]:
    rng = random.Random(state["rng_seed"] + state["month"] * 911)

    seed, family, eid = choose_event_seed(state, rng)
    prompt = build_prompt(state, seed, family, eid, free_action)

    temp = 0.95 if state["mode"] == "Extreme" else 0.75
    out = llm_json(prompt, temperature=temp, max_output_tokens=1500)

    # retry once if bad or repeats
    def is_repeat(o: Dict[str, Any]) -> bool:
        fp = (o.get("title_fingerprint") or "").strip()
        event_id = (o.get("event_id") or "").strip()
        h = sha((o.get("durum_analizi", "") + "||" + o.get("kriz", {}).get("metin", "")))
        if fp and fp in state["recent_fingerprints"][-6:]:
            return True
        if event_id and event_id in state["recent_event_ids"][-8:]:
            return True
        if h and h in state["recent_text_hashes"][-6:]:
            return True
        return False

    if (not validate_turn(out)) or out.get("_error") or is_repeat(out):
        # farklı bir seed zorla
        rng2 = random.Random(state["rng_seed"] + state["month"] * 911 + 777)
        seed2, fam2, eid2 = choose_event_seed(state, rng2)
        prompt2 = build_prompt(state, seed2, fam2, eid2, free_action)
        out2 = llm_json(prompt2, temperature=min(1.0, temp + 0.1), max_output_tokens=1600)
        if validate_turn(out2) and (not out2.get("_error")):
            out = out2

    if not validate_turn(out):
        # fallback
        out = {
            "event_id": eid or f"FALL-{state['month']}",
            "event_family": family,
            "title_fingerprint": f"fallback-{state['month']}",
            "durum_analizi": "Bu tur anlatıcı boğazına bir şey kaçırdı. Ama oyun devam ediyor: bu ay kararın yine de bir şeyleri değiştirecek.",
            "kriz": {"baslik": "Motor Krizi", "metin": "Model düzgün JSON üretmedi. Bu ay iki basit yoldan birini seçerek devam edelim (metrikler yine etkilenir)."},
            "secenekler": {
                "A": {"baslik": "Kaosu Temizle", "metin": "Bu ay sadece yangın söndür: destek yükünü azaltacak hızlı bir bakım turu at, sunucuyu stabilize et. Büyüme yavaşlar ama çöküş riski düşer."},
                "B": {"baslik": "İleri Atla", "metin": "Görmezden gel ve pazarlamayı zorla: belki MRR kazanırsın ama support ve itibarın test edilir; yanlış kitle churn’ü şişirebilir."},
            },
            "deltalar": {
                "A": {"cash": -8000, "mrr": 500, "churn": -0.01, "reputation": 2, "support_load": -8, "infra": 6, "team": 1, "motivation": -1},
                "B": {"cash": -5000, "mrr": 2000, "churn": 0.03, "reputation": -3, "support_load": 10, "infra": -4, "team": -1, "motivation": -2},
            },
        }

    # anti-repeat kayıtları
    fp = out.get("title_fingerprint", "")
    eid_out = out.get("event_id", "")
    fam_out = out.get("event_family", family)
    h = sha((out.get("durum_analizi", "") + "||" + out.get("kriz", {}).get("metin", "")))

    if fp:
        state["recent_fingerprints"].append(fp)
        state["recent_fingerprints"] = state["recent_fingerprints"][-10:]
    if eid_out:
        state["recent_event_ids"].append(eid_out)
        state["recent_event_ids"] = state["recent_event_ids"][-12:]
    if fam_out:
        state["recent_families"].append(fam_out)
        state["recent_families"] = state["recent_families"][-10:]
    if h:
        state["recent_text_hashes"].append(h)
        state["recent_text_hashes"] = state["recent_text_hashes"][-10:]

    return out


def apply_choice(state: Dict[str, Any], choice: str, out: Dict[str, Any]):
    m: Metrics = state["metrics"]
    deltas = out.get("deltalar", {}).get(choice, {})
    m.apply_deltas(deltas)
    m.month_tick()
    state["month"] += 1


# =========================
# UI HELPERS
# =========================
def bubble(role: str, content: str):
    if role == "user":
        st.markdown(
            f"<div style='padding:12px;border-radius:14px;background:#1f2937;margin:8px 0'>"
            f"<b>🧑 Sen</b><br>{content}</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<div style='padding:12px;border-radius:14px;background:#111827;margin:8px 0'>"
            f"<b>🤖 Oyun</b><br>{content}</div>",
            unsafe_allow_html=True,
        )


def render_sidebar(state: Dict[str, Any]):
    c = state["character"]
    m: Metrics = state["metrics"]

    st.sidebar.markdown(f"## {c.get('avatar','🧑‍💻')} {c.get('name','İsimsiz Girişimci')}")
    st.sidebar.caption(f"Mod: **{state['mode']}**")

    st.sidebar.markdown(f"**Ay:** {state['month']}/{state['months_total']}")
    st.sidebar.progress(min(1.0, state["month"] / max(1, state["months_total"])))

    st.sidebar.markdown("---")
    with st.sidebar.expander("💡 Girişim fikrim", expanded=False):
        st.write(state["idea"] or "—")

    st.sidebar.markdown("### 📊 Finansal Durum")
    st.sidebar.metric("Kasa", money(m.cash))
    st.sidebar.metric("MRR", money(m.mrr))

    with st.sidebar.expander("Aylık Gider Detayı", expanded=True):
        b = m.cost_breakdown()
        st.write(f"**Maaşlar:** {money(b['Maaşlar'])}")
        st.write(f"**Sunucu:** {money(b['Sunucu'])}")
        st.write(f"**Pazarlama:** {money(b['Pazarlama'])}")
        if b.get("Diğer", 0) != 0:
            st.write(f"**Diğer:** {money(b['Diğer'])}")
        st.markdown(f"**TOPLAM:** {money(m.burn)}")

    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**İtibar:** {int(m.reputation)}/100")
    st.sidebar.progress(m.reputation / 100.0)

    st.sidebar.markdown(f"**Support:** {int(m.support_load)}/100")
    st.sidebar.progress(m.support_load / 100.0)

    st.sidebar.markdown(f"**Altyapı:** {int(m.infra)}/100")
    st.sidebar.progress(m.infra / 100.0)

    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**Ekip:** {int(m.team)}/100")
    st.sidebar.progress(m.team / 100.0)

    st.sidebar.markdown(f"**Motivasyon:** {int(m.motivation)}/100")
    st.sidebar.progress(m.motivation / 100.0)

    st.sidebar.markdown("---")
    if st.sidebar.button("🔄 Oyunu Sıfırla"):
        st.session_state.pop("game", None)
        init_state()
        st.rerun()


def render_customization(state: Dict[str, Any]):
    with st.expander("🛠️ Karakterini ve Ayarları Özelleştir (Tıkla)", expanded=False):
        c = state["character"]
        col1, col2, col3 = st.columns(3)

        with col1:
            c["name"] = st.text_input("Karakter adı", value=c.get("name", "İsimsiz Girişimci"))
            c["avatar"] = st.selectbox("Avatar", ["🧑‍💻", "🧠", "🧑‍🚀", "🦾", "🧑‍🎤", "🧑‍🔧", "🧑‍🍳"], index=0)
        with col2:
            c["background"] = st.selectbox("Arka plan", ["Genelci", "Teknik", "Satışçı", "Ürüncü", "Büyüme", "Operasyon"], index=0)
            c["trait"] = st.selectbox("Özellik", ["Hızlı Öğrenen", "Soğukkanlı", "İnatçı", "Pragmatik", "Yaratıcı", "Paranoyak (iyi anlamda)"], index=0)
        with col3:
            c["risk"] = st.selectbox("Risk yaklaşımı", ["Dengeli", "Agresif", "Temkinli"], index=0)

        st.markdown("---")
        s1, s2, s3 = st.columns(3)

        with s1:
            state["mode"] = st.selectbox("Mod", ["Realist", "Hard", "Spartan", "Extreme", "Türkiye"],
                                         index=["Realist", "Hard", "Spartan", "Extreme", "Türkiye"].index(state["mode"]))
            st.caption(MODE_DESCRIPTIONS[state["mode"]])

        with s2:
            state["months_total"] = st.slider("Sezon uzunluğu (ay)", 6, 24, int(state["months_total"]), step=1)

        with s3:
            start_cash = st.select_slider("Başlangıç kasası", options=[250_000, 500_000, 1_000_000, 2_000_000], value=1_000_000)
            # sadece oyun başlamadıysa etkilesin; başladıysa "mahvetmesin"
            if not state["started"]:
                state["metrics"].cash = float(start_cash)

        st.markdown("---")
        state["settings"]["show_suggestions"] = st.toggle("Öneri panelini göster (şimdilik kapalı önerilir)", value=state["settings"]["show_suggestions"])


# =========================
# MAIN RENDER
# =========================
def render_turn_cards(out: Dict[str, Any]) -> Tuple[bool, bool]:
    st.markdown("### 🧠 DURUM ANALİZİ")
    st.markdown(out["durum_analizi"])

    st.markdown("### ⚠️ KRİZ")
    st.markdown(f"**{out['kriz']['baslik']}** — {out['kriz']['metin']}")

    st.markdown("### 🎯 Çözüm seç (A/B)")
    colA, colB = st.columns(2)

    with colA:
        st.markdown(f"#### A) {out['secenekler']['A']['baslik']}")
        st.write(out["secenekler"]["A"]["metin"])
        a = st.button("✅ A seç", use_container_width=True)

    with colB:
        st.markdown(f"#### B) {out['secenekler']['B']['baslik']}")
        st.write(out["secenekler"]["B"]["metin"])
        b = st.button("✅ B seç", use_container_width=True)

    return a, b


def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    init_state()
    state = st.session_state.game

    render_sidebar(state)

    st.markdown(f"# {APP_TITLE}")
    st.caption("Sohbet akışı korunur. Ay 1’den başlar. Durum Analizi → Kriz → A/B seçimi.")

    render_customization(state)

    st.markdown("---")

    # sohbet geçmişi
    for msg in state["chat"]:
        bubble(msg["role"], msg["content"])

    # start screen
    if not state["started"]:
        st.info("Oyuna başlamak için girişim fikrini yaz.")
        idea = st.text_area("Girişim fikrin ne?", placeholder="Örn: Flow Lens... ekran üstü çeviri, altyazı üretimi, offline çalışma vb.", height=110)
        if st.button("🚀 Oyunu Başlat", type="primary"):
            if not API_KEY:
                st.error("GEMINI_API_KEY bulunamadı. Ortam değişkeni olarak eklemeden model çalışmaz.")
                st.stop()

            if not idea.strip():
                st.warning("Fikri yazmadan oyun başlayamaz.")
                st.stop()

            state["idea"] = idea.strip()
            state["started"] = True
            state["month"] = 1
            state["rng_seed"] = abs(hash(state["idea"] + state["character"].get("name", ""))) % (10**7)

            # chat'e fikri bas
            state["chat"].append({"role": "user", "content": state["idea"]})

            out = generate_turn(state, free_action="")
            state["last_turn"] = out

            assistant_msg = (
                f"**DURUM ANALİZİ:** {out['durum_analizi']}\n\n"
                f"**KRİZ — {out['kriz']['baslik']}:** {out['kriz']['metin']}\n\n"
                f"**A) {out['secenekler']['A']['baslik']}:** {out['secenekler']['A']['metin']}\n\n"
                f"**B) {out['secenekler']['B']['baslik']}:** {out['secenekler']['B']['metin']}"
            )
            state["chat"].append({"role": "assistant", "content": assistant_msg})
            st.rerun()
        return

    # ensure last turn
    if not state.get("last_turn"):
        state["last_turn"] = generate_turn(state, free_action="")

    out = state["last_turn"]

    free_action = st.text_input("İstersen serbest hamle yaz (opsiyonel)", placeholder="Örn: onboarding'i 3 adıma indir, fiyatı test et, altyapıyı stabil yap...")

    a_clicked, b_clicked = render_turn_cards(out)

    if a_clicked or b_clicked:
        choice = "A" if a_clicked else "B"
        chosen_title = out["secenekler"][choice]["baslik"]

        # user msg
        u = f"{choice} seçtim: {chosen_title}"
        if free_action.strip():
            u += f" | Serbest hamle: {free_action.strip()}"
        state["chat"].append({"role": "user", "content": u})

        # apply deltas + month tick
        apply_choice(state, choice, out)

        # finish?
        if state["month"] > state["months_total"]:
            state["chat"].append({"role": "assistant", "content": "🏁 Sezon bitti! İstersen sol menüden sıfırla ve tekrar başla."})
            state["last_turn"] = None
            st.rerun()

        # next turn
        next_out = generate_turn(state, free_action=free_action.strip())
        state["last_turn"] = next_out

        assistant_msg = (
            f"**DURUM ANALİZİ:** {next_out['durum_analizi']}\n\n"
            f"**KRİZ — {next_out['kriz']['baslik']}:** {next_out['kriz']['metin']}\n\n"
            f"**A) {next_out['secenekler']['A']['baslik']}:** {next_out['secenekler']['A']['metin']}\n\n"
            f"**B) {next_out['secenekler']['B']['baslik']}:** {next_out['secenekler']['B']['metin']}"
        )
        state["chat"].append({"role": "assistant", "content": assistant_msg})
        st.rerun()


if __name__ == "__main__":
    main()
