import streamlit as st
import google.generativeai as genai
import json
import random
import time
from typing import Any, Dict, List, Optional, Tuple

# ============================================================
# Startup Survivor RPG (Gemini) - Tek Dosya (REVIZE v4)
# - Extreme: daha komik, daha kaotik, daha özgün
# - Durum analizi daha uzun/detaylı (tek paragraf)
# - "Öneri/çıkarım" tamamen kaldırıldı
# - Sıralama: Durum Analizi -> Kriz -> Seçenekler
# - A/B: tek paragraf, orta uzunluk (korundu)
# ============================================================

st.set_page_config(page_title="Startup Survivor RPG", page_icon="💀", layout="wide")

# ------------------------------
# MOD PROFİLLERİ (REVIZE)
# ------------------------------
MODE_COLORS = {
    "Gerçekçi": "#2ECC71",
    "Zor": "#F1C40F",
    "Türkiye Simülasyonu": "#1ABC9C",
    "Spartan": "#E74C3C",
    "Extreme": "#9B59B6",
}

MODE_PROFILES = {
    "Gerçekçi": {"chance_prob": 0.18, "shock_mult": 1.00, "turkey": False, "tone": "realistic", "temp": 0.90},
    "Zor": {"chance_prob": 0.28, "shock_mult": 1.25, "turkey": False, "tone": "hard", "temp": 0.86},
    "Spartan": {"chance_prob": 0.30, "shock_mult": 1.45, "turkey": False, "tone": "hardcore", "temp": 0.84},
    "Türkiye Simülasyonu": {"chance_prob": 0.26, "shock_mult": 1.15, "turkey": True, "tone": "turkey", "temp": 0.88},
    # Extreme: Kaos yüksek + daha yaratıcı + daha komik
    "Extreme": {"chance_prob": 0.70, "shock_mult": 2.40, "turkey": False, "tone": "extreme", "temp": 1.18},
}

LIMITS = {
    "TEAM_MIN": 0,
    "TEAM_MAX": 100,
    "MOT_MIN": 0,
    "MOT_MAX": 100,
    "MARKETING_MIN": 0,
    "MARKETING_MAX": 250_000,
    "PRICE_MIN": 0,
    "PRICE_MAX": 2_000,
}

# ------------------------------
# CSS
# ------------------------------
def apply_custom_css(selected_mode: str) -> None:
    color = MODE_COLORS.get(selected_mode, "#2ECC71")
    st.markdown(
        f"""
        <style>
        .stApp {{ font-family: 'Inter', sans-serif; }}
        [data-testid="stSidebar"] {{
            min-width: 300px; max-width: 350px;
            background-color: #0e1117; border-right: 1px solid #333;
        }}
        .hero-container {{ text-align: center; padding: 18px 0 0 0; }}
        .hero-title {{
            font-size: 2.6rem; font-weight: 800;
            background: -webkit-linear-gradient(45deg, {color}, #ffffff);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            margin: 0;
        }}
        .hero-subtitle {{ font-size: 1.05rem; color: #bbb; font-weight: 300; margin-top: 6px; }}

        .crisis-box {{
            border:1px solid #2b2f36;
            background:#0b0f14;
            padding: 10px 12px;
            border-radius: 12px;
            margin: 10px 0 12px 0;
            color:#ddd;
        }}

        .analysis-box {{
            border:1px solid #22262d;
            background:#0d1219;
            padding: 10px 12px;
            border-radius: 12px;
            margin: 6px 0 8px 0;
            color:#ddd;
        }}

        .expense-row {{ display: flex; justify-content: space-between; font-size: 0.9rem; color: #ccc; margin-bottom: 5px; }}
        .expense-label {{ font-weight: bold; }}
        .expense-val {{ color: #e74c3c; }}
        .total-expense {{ border-top: 1px solid #444; margin-top: 5px; padding-top: 5px; font-weight: bold; color: #e74c3c; }}
        .chip {{
            display:inline-block; padding:4px 10px; border-radius:999px;
            border:1px solid #333; margin-right:6px; margin-bottom:6px; font-size:0.85rem; color:#ddd;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

# ------------------------------
# HELPERS
# ------------------------------
def clean_json(text: str) -> str:
    text = (text or "").replace("```json", "").replace("```", "").strip()
    s = text.find("{")
    e = text.rfind("}") + 1
    if s != -1 and e != 0:
        return text[s:e]
    return text

def format_currency(amount: int) -> str:
    try:
        return f"{int(amount):,} ₺".replace(",", ".")
    except Exception:
        return f"{amount} ₺"

def clamp_int(x: Any, lo: int, hi: int, default: int) -> int:
    try:
        v = int(round(float(x)))
    except Exception:
        v = default
    return max(lo, min(hi, v))

def clamp_float(x: Any, lo: float, hi: float, default: float) -> float:
    try:
        v = float(x)
    except Exception:
        v = default
    return max(lo, min(hi, v))

def clamp_core_stats(stats: Dict[str, Any]) -> None:
    stats["team"] = clamp_int(stats.get("team", 50), LIMITS["TEAM_MIN"], LIMITS["TEAM_MAX"], 50)
    stats["motivation"] = clamp_int(stats.get("motivation", 50), LIMITS["MOT_MIN"], LIMITS["MOT_MAX"], 50)
    stats["marketing_cost"] = clamp_int(stats.get("marketing_cost", 5000), LIMITS["MARKETING_MIN"], LIMITS["MARKETING_MAX"], 5000)
    stats["debt"] = max(0, clamp_int(stats.get("debt", 0), 0, 10_000_000, 0))
    stats["money"] = clamp_int(stats.get("money", 0), -10_000_000_000, 10_000_000_000, 0)
    stats["price"] = clamp_int(stats.get("price", 99), LIMITS["PRICE_MIN"], LIMITS["PRICE_MAX"], 99)

def skill_multiplier(v0_10: int, base: float = 0.03) -> float:
    v = clamp_int(v0_10, 0, 10, 5)
    return 1.0 + (v - 5) * base

def detect_intent(user_text: str) -> str:
    t = (user_text or "").lower()
    if any(k in t for k in ["reklam", "pazarlama", "kampanya", "influencer", "ads", "seo", "growth"]):
        return "growth"
    if any(k in t for k in ["abonelik", "premium", "fiyat", "ücret", "monet", "paywall", "gelir"]):
        return "monetize"
    if any(k in t for k in ["bug", "hata", "refactor", "optimiz", "onboarding", "ux", "performans", "özellik", "feature", "mvp"]):
        return "product"
    if any(k in t for k in ["işe al", "hire", "ekip", "developer", "satış", "sales", "support", "müşteri desteği"]):
        return "team_ops"
    if any(k in t for k in ["yatırım", "investor", "melek", "fon", "pitch", "demo"]):
        return "fundraise"
    return "general"

def build_character_desc(player: Dict[str, Any]) -> str:
    stats = player.get("stats", {}) or {}
    traits = player.get("custom_traits", []) or []
    traits_txt = ""
    for t in traits:
        traits_txt += f"- {t.get('title','')}: {t.get('desc','')}\n"

    s = (
        f"Oyuncu adı: {player.get('name','İsimsiz Girişimci')}\n"
        f"Cinsiyet: {player.get('gender','Belirtmek İstemiyorum')}\n"
        f"Yetenekler (0-10): Yazılım={stats.get('coding',5)}, Pazarlama={stats.get('marketing',5)}, Network={stats.get('network',5)}, Disiplin={stats.get('discipline',5)}, Karizma={stats.get('charisma',5)}\n"
    )
    if traits_txt.strip():
        s += f"Özel özellikler:\n{traits_txt}\n"
    return s

# ------------------------------
# EKONOMİ / GİDER
# ------------------------------
def calculate_expenses(stats: Dict[str, Any], month: int, mode: str) -> Tuple[int, int, int, int]:
    salary = int(stats.get("team", 50) * 1000)
    server = int((month ** 2) * 500)
    marketing = int(stats.get("marketing_cost", 5000))

    if MODE_PROFILES.get(mode, {}).get("turkey"):
        inflation = 1.0 + min(0.03 * month, 0.45)
        salary = int(salary * inflation)
        server = int(server * (1.0 + min(0.02 * month, 0.35)))

    total = salary + server + marketing
    return salary, server, marketing, total

# ------------------------------
# ŞANS KARTLARI
# ------------------------------
BASE_CARDS = [
    {"title": "📜 KVKK Cezası", "desc": "Küçük bir veri açığı yüzünden ceza yedin.", "effect": "money", "val": -15_000},
    {"title": "🧪 Kritik Bug", "desc": "Uygulama çöktü, kullanıcılar şikayetçi.", "effect": "motivation", "val": -10},
    {"title": "👋 Kıdemli Geliştirici Ayrıldı", "desc": "Senior geliştirici gitti, hız düştü.", "effect": "team", "val": -8},
    {"title": "🚀 Viral Paylaşım", "desc": "Bir paylaşım patladı, yeni kullanıcılar geldi.", "effect": "money", "val": 20_000},
]

TURKEY_CARDS = [
    {"title": "💱 Kur Şoku", "desc": "Kurlar arttı, bazı servis maliyetleri yükseldi.", "effect": "money", "val": -22_000},
    {"title": "🧾 Beklenmedik Tebligat", "desc": "Bir evrak işi uzadı, küçük ceza çıktı.", "effect": "money", "val": -18_000},
    {"title": "🏦 POS Kesintisi", "desc": "Ödeme sağlayıcısı kesintiyi artırdı.", "effect": "money", "val": -10_000},
]

# Extreme: komik+farklı+kaotik ama "çözüm ihtimali olan" gerçek probleme bağlanan kartlar
EXTREME_CARDS = [
    {"title": "🎭 Ürün Yanlış Anlaşıldı", "desc": "Kullanıcılar uygulamayı 'dil öğrenme' değil 'altyazı büyüsü' sandı. Beklenti çarpıştı.", "effect": "motivation", "val": -16},
    {"title": "📦 Sunucu Şiir Yazıyor", "desc": "Loglar kafayı yedi, performans düştü. Sunucu resmen 'duygusal'.", "effect": "money", "val": -28_000},
    {"title": "🎪 Trend Oldun (Yanlış Sebeple)", "desc": "Bir meme oldun. Trafik geldi ama doğru kitle mi, kimse emin değil.", "effect": "money", "val": 30_000},
    {"title": "🧿 Nazar Değdi", "desc": "Ödeme sayfası tam kritik anda bozdu. Aynı anda herkes 'bende de' diyor.", "effect": "money", "val": -24_000},
    {"title": "🕵️ Rakip Ayna Modu", "desc": "Rakip seninle aynı anda aynı fikri duyurdu. Tesadüf mü, evren mi?", "effect": "motivation", "val": -14},
    {"title": "🧃 Limonata Stratejisi", "desc": "Ekip, nakit açığını kapatmak için bir günlük 'limonata & demo' etkinliği öneriyor.", "effect": "motivation", "val": 22},
]

def trigger_chance_card(mode: str) -> Optional[Dict[str, Any]]:
    p = MODE_PROFILES.get(mode, MODE_PROFILES["Gerçekçi"])
    if random.random() >= float(p["chance_prob"]):
        return None
    cards = list(BASE_CARDS)
    if p.get("turkey"):
        cards.extend(TURKEY_CARDS)
    if mode == "Extreme":
        cards.extend(EXTREME_CARDS)
    return random.choice(cards) if cards else None

def apply_chance_card(stats: Dict[str, Any], card: Dict[str, Any], mode: str) -> str:
    if not card:
        return ""

    shock = float(MODE_PROFILES.get(mode, MODE_PROFILES["Gerçekçi"]).get("shock_mult", 1.0))
    effect = card.get("effect")
    raw_val = int(card.get("val", 0))
    val = int(round(raw_val * shock))

    if effect == "money":
        abs_cash = max(1, int(abs(stats.get("money", 0))))
        cap_ratio = 0.55 if mode != "Extreme" else 1.20
        cap = max(15_000, int(abs_cash * cap_ratio))
        val = max(-cap, min(cap, val))
        stats["money"] = int(stats.get("money", 0) + val)
    elif effect == "team":
        cap = 25 if mode != "Extreme" else 45
        val = max(-cap, min(cap, val))
        stats["team"] = int(stats.get("team", 50) + val)
    elif effect == "motivation":
        cap = 30 if mode != "Extreme" else 60
        val = max(-cap, min(cap, val))
        stats["motivation"] = int(stats.get("motivation", 50) + val)

    return f"\n\n🃏 **ŞANS KARTI:** {card.get('title','')}\n_{card.get('desc','')}_"

# ------------------------------
# EXTREME "ABSÜRT TETİKLEYİCİ" (HER TUR)
# ------------------------------
EXTREME_TRIGGERS = [
    "Bir kullanıcı destek talebine sadece ‘abi çok iyi ama ne bu?’ yazıp kayboldu; ekip bunu üç farklı şekilde yorumladı.",
    "Bir yatırımcı DM’den ‘bu ürün beni duygulandırdı’ dedi ama hangi özelliğin duygulandırdığı meçhul.",
    "Uygulama ekran görüntüsü WhatsApp gruplarında dolaşıyor; herkes farklı bir amaç uyduruyor.",
    "Ürünü anlatırken herkes aynı kelimeyi farklı anlıyor: 'anlık çeviri' mi, 'anlık mucize' mi, kimse emin değil.",
    "Bug raporu yerine bir kullanıcı ‘benim telefonda ürün küstü’ yazdı. Teknik açıklaması yok, sonuç gerçek.",
    "Bir influencer ürünü överken yanlış özelliği övdü; trafik geldi ama kullanıcıların kafası da geldi."
]

def get_extreme_trigger(mode: str) -> str:
    if mode != "Extreme":
        return ""
    return random.choice(EXTREME_TRIGGERS)

# ------------------------------
# KPI / GELİR (SaaS)
# ------------------------------
def simulate_saas_kpis(stats: Dict[str, Any], player: Dict[str, Any], mode: str, intent: str) -> Dict[str, Any]:
    pstats = player.get("stats", {}) or {}
    marketing_skill = skill_multiplier(pstats.get("marketing", 5))
    coding_skill = skill_multiplier(pstats.get("coding", 5))
    discipline_skill = skill_multiplier(pstats.get("discipline", 5))

    users_total = clamp_int(stats.get("users_total", 2000), 0, 50_000_000, 2000)
    active_users = clamp_int(stats.get("active_users", 500), 0, 50_000_000, 500)
    price = clamp_int(stats.get("price", 99), LIMITS["PRICE_MIN"], LIMITS["PRICE_MAX"], 99)

    retention = clamp_float(stats.get("retention", 0.78), 0.20, 0.98, 0.78)
    churn = clamp_float(stats.get("churn", 0.10), 0.01, 0.60, 0.10)
    activation = clamp_float(stats.get("activation", 0.35), 0.05, 0.90, 0.35)
    conversion = clamp_float(stats.get("conversion", 0.04), 0.001, 0.40, 0.04)

    if intent == "growth":
        activation = clamp_float(activation + 0.02 * marketing_skill, 0.05, 0.90, activation)
        churn = clamp_float(churn + (0.020 if mode == "Extreme" else 0.01), 0.01, 0.60, churn)
    elif intent == "product":
        retention = clamp_float(retention + 0.03 * coding_skill, 0.20, 0.98, retention)
        churn = clamp_float(churn - 0.01, 0.01, 0.60, churn)
    elif intent == "monetize":
        conversion = clamp_float(conversion + 0.01 * discipline_skill, 0.001, 0.40, conversion)
    elif intent == "team_ops":
        churn = clamp_float(churn - 0.005, 0.01, 0.60, churn)

    base_cac = clamp_int(stats.get("cac", 35), 5, 500, 35)
    if mode == "Zor":
        base_cac = int(base_cac * 1.15)
    elif mode == "Spartan":
        base_cac = int(base_cac * 1.25)
    elif mode == "Türkiye Simülasyonu":
        base_cac = int(base_cac * 1.10)
    elif mode == "Extreme":
        base_cac = int(base_cac * random.choice([0.4, 0.7, 1.0, 1.8, 2.8]))

    cac = max(5, int(base_cac / max(0.75, marketing_skill)))
    marketing_spend = clamp_int(stats.get("marketing_cost", 5000), LIMITS["MARKETING_MIN"], LIMITS["MARKETING_MAX"], 5000)

    new_users = int(marketing_spend / max(1, cac))
    if mode == "Extreme":
        new_users = int(new_users * random.choice([0.12, 0.45, 1.0, 2.2, 3.6]))

    new_active = int(new_users * activation)
    active_users = max(0, int(active_users * (1.0 - churn)) + new_active)
    users_total = max(users_total, users_total + new_users)

    paid_users = int(active_users * conversion)
    mrr = int(paid_users * price)

    stats["users_total"] = users_total
    stats["active_users"] = active_users
    stats["paid_users"] = paid_users
    stats["mrr"] = mrr
    stats["price"] = price
    stats["retention"] = retention
    stats["churn"] = churn
    stats["activation"] = activation
    stats["conversion"] = conversion
    stats["cac"] = cac

    return {
        "new_users": new_users,
        "new_active": new_active,
        "paid_users": paid_users,
        "mrr": mrr,
        "cac": cac,
        "retention": retention,
        "churn": churn,
        "activation": activation,
        "conversion": conversion,
    }

# ------------------------------
# KRİZ TESPİTİ (DETAYLI + EXTREME GAG)
# ------------------------------
def detect_crisis(stats: Dict[str, Any], expenses_total: int, mode: str) -> Dict[str, Any]:
    money = int(stats.get("money", 0))
    mrr = int(stats.get("mrr", 0))
    churn = float(stats.get("churn", 0.10))
    activation = float(stats.get("activation", 0.35))
    conversion = float(stats.get("conversion", 0.04))
    motivation = int(stats.get("motivation", 50))
    team = int(stats.get("team", 50))

    burn = max(0, expenses_total - mrr)
    runway_months = 999
    if burn > 0:
        runway_months = max(0, money // burn)

    issues = []
    if burn > 0 and runway_months <= 3:
        issues.append(("RUNWAY", f"Kasa hızlı eriyor; bu hızla yaklaşık {runway_months} ayın var."))
    if churn >= 0.14:
        issues.append(("CHURN", "Kullanıcılar hızlı bırakıyor; ürünü deniyorlar ama tutunmuyorlar."))
    if activation <= 0.22:
        issues.append(("ACTIVATION", "İlk deneyim zayıf; gelen kullanıcılar 'tamam' deyip ilerleyemiyor."))
    if conversion <= 0.02 and stats.get("active_users", 0) > 300:
        issues.append(("CONVERSION", "Aktif kullanıcı var ama ödeme yok; değer algısı net değil ya da plan/fiyat uyuşmuyor."))
    if motivation <= 25:
        issues.append(("MORALE", "Ekip morali düşmüş; küçük sorunlar büyümeden durdurulmalı."))
    if team <= 15:
        issues.append(("CAPACITY", "Ekip kapasitesi düşük; birikme, kullanıcı kaybını tetikleyebilir."))

    if not issues:
        issues.append(("BALANCE", "Şimdilik dengedesin; ama küçük bir yanlış hamle bu dengeyi hızla bozabilir."))

    primary_code, primary_text = issues[0]

    base = (
        f"Bu ay masada net bir gerilim var: {primary_text} "
        f"Giderin {format_currency(expenses_total)}, MRR'ın {format_currency(mrr)}, kasan {format_currency(money)}."
    )
    if burn > 0:
        base += f" Net yanma yaklaşık {format_currency(burn)}; bu da 'yanlış ayda yanlış karar' riskini büyütüyor."
    else:
        base += " Şu an yanma yok gibi görünse de, bu rahatlık ölçüm koymadan savrulmaya davetiye çıkarır."

    if mode == "Extreme":
        gag = random.choice([
            "Toplantıda biri ‘bunu tek kelimeyle anlat’ dedi; herkes farklı bir kelime söyledi ve kavga çıktı.",
            "Bir kullanıcı ürünü açıp ‘bu kesin komplo’ yazdı; sonra üye olup kayboldu.",
            "Ekip, problemi çözmek yerine önce logların ‘neden duygusal’ olduğunu tartıştı.",
            "Kullanıcıların bir kısmı ürünü harika buluyor ama ‘ne işe yarıyor’ sorusunda birleşiyor."
        ])
        crisis_detail = f"{base} {gag}"
    elif mode == "Türkiye Simülasyonu":
        crisis_detail = f"{base} Üstüne bir de piyasa ritmi ve maliyet dalgalanması kararlarını daha temkinli yapmanı istiyor."
    elif mode == "Spartan":
        crisis_detail = f"{base} Bu modda hataların faturası sert kesilir; tek hedefle ilerlemek zorundasın."
    elif mode == "Zor":
        crisis_detail = f"{base} Burada tolerans düşük; küçük bir gecikme bile kullanıcı kaybına dönüşebilir."
    else:
        crisis_detail = f"{base} Bu ayın işi: krizi tek bir köke indirip, tek hamleyle öğrenmek."

    crisis_line = f"KRİZ: {primary_text} (Gider {format_currency(expenses_total)} | MRR {format_currency(mrr)} | Kasa {format_currency(money)})"

    return {
        "primary_code": primary_code,
        "primary_text": primary_text,
        "crisis_line": crisis_line,
        "crisis_detail": crisis_detail,
        "runway_months": int(runway_months),
        "burn": int(burn),
        "all": issues,
    }

# ------------------------------
# GEMINI
# ------------------------------
def configure_gemini() -> Optional[List[str]]:
    keys = st.secrets.get("GOOGLE_API_KEYS", None)
    if not keys:
        # Tek key kullananlar için
        k = st.secrets.get("GOOGLE_API_KEY", None)
        if k:
            return [k]
        return None
    if isinstance(keys, str):
        keys = [keys]
    return [k for k in keys if k and isinstance(k, str)]

def build_model_candidates() -> List[str]:
    pinned = st.secrets.get("GEMINI_MODEL", None)
    if pinned and isinstance(pinned, str) and pinned.strip():
        return [pinned.strip()]
    return [
        "gemini-2.5-flash",
        "models/gemini-2.5-flash",
        "gemini-2.0-flash",
        "models/gemini-2.0-flash",
        "gemini-1.5-flash",
        "models/gemini-1.5-flash",
    ]

def call_gemini(prompt: str, history: List[Dict[str, Any]], mode: str) -> Optional[str]:
    keys = configure_gemini()
    if not keys:
        st.warning("AI anahtarı bulunamadı. Offline anlatıcıyla devam ediyorum.")
        return None

    models = build_model_candidates()
    last_err = None
    temp = float(MODE_PROFILES.get(mode, MODE_PROFILES["Gerçekçi"]).get("temp", 0.90))

    for key in keys:
        try:
            genai.configure(api_key=key)
        except Exception as e:
            last_err = e
            continue

        for mname in models:
            try:
                model = genai.GenerativeModel(mname)
                resp = model.generate_content(
                    history + [{"role": "user", "parts": [prompt]}],
                    generation_config={"temperature": temp, "max_output_tokens": 1900},
                )
                if resp and getattr(resp, "text", None):
                    return resp.text
            except Exception as e:
                last_err = e
                if "429" in str(e) or "quota" in str(e).lower():
                    time.sleep(0.8)
                continue

    if last_err:
        st.warning("AI isteği başarısız oldu. Offline anlatıcıyla devam ediyorum.\n\n" f"Hata: {last_err}")
    return None

# ------------------------------
# AI PAYLOAD DOĞRULAMA
# - ÖNERİ/ÇIKARIM YOK (tamamen kaldırıldı)
# ------------------------------
def validate_ai_payload(resp: Any) -> Dict[str, Any]:
    if not isinstance(resp, dict):
        return {
            "analysis": "AI cevabı okunamadı. Lütfen tekrar dene.",
            "crisis_detail": "",
            "choices": [],
        }

    # eski sürümle uyum: text/analysis ikisini de kabul et
    analysis = resp.get("analysis", resp.get("text", ""))
    crisis_detail = resp.get("crisis_detail", "")
    choices = resp.get("choices", [])

    if not isinstance(analysis, str):
        analysis = str(analysis)
    if not isinstance(crisis_detail, str):
        crisis_detail = str(crisis_detail)

    norm_choices = []
    if isinstance(choices, list):
        for c in choices[:2]:
            if isinstance(c, dict):
                cid = (str(c.get("id", "")).strip() or "A")[:2]
                title = str(c.get("title", "")).strip()
                paragraph = str(c.get("paragraph", "")).strip()
                if title and paragraph:
                    norm_choices.append({"id": cid, "title": title, "paragraph": paragraph})

    return {"analysis": analysis.strip(), "crisis_detail": crisis_detail.strip(), "choices": norm_choices}

# ------------------------------
# PROMPTLER (REVIZE)
# - Analiz daha uzun/detaylı (tek paragraf)
# - Extreme daha komik + daha özgün
# - Sıralama: Durum Analizi -> Kriz -> A/B
# ------------------------------
def build_intro_prompt(mode: str, idea_full: str, char_desc: str, stats: Dict[str, Any]) -> str:
    tone = MODE_PROFILES.get(mode, MODE_PROFILES["Gerçekçi"])["tone"]
    idea_short = " ".join((idea_full or "").strip().split()[:8]) or "Startup"
    extreme_trigger = get_extreme_trigger(mode)

    extreme_rules = ""
    if mode == "Extreme":
        extreme_rules = f"""
EXTREME RUHU:
- Olaylar komik, beklenmedik, tuhaf ve hızlı değişen biçimde akmalı.
- "Mantıklı ders anlatımı" yapma; sahne ve diyalogla anlat.
- Her tur en az 1 absürt tetikleyici kullan.
- Kriz gerçek bir probleme bağlanmalı (netlik/akış/ödeme/performans/yanma vb.).
- Seçenekler çılgın olabilir ama ikisi de teoride krizi çözebilir.

ABSÜRT TETİKLEYİCİ (kullan):
{extreme_trigger}
""".strip()

    return f"""
ROLÜN: Startup simülasyonu anlatıcısı + hikâye anlatıcısı.
MOD: {mode} (ton: {tone})

{extreme_rules}

GÖREV:
- Ay 1 için "Durum Analizi" yaz: tek paragraf, daha uzun ve detaylı olsun (yaklaşık 10-14 cümle).
- Bu paragraf fikir hakkında netlik, hedef kitle, değer vaadi, risk, yanlış anlaşılma ihtimali gibi detaylara girsin.
- Fikri kopyalayıp tekrar etme; yorumla, sahne kur.
- Sonra "Kriz" yaz (3-6 cümle, detaylı, sayılarla bağla: gider/mrr/kasa/yanma).
- A/B seçenekleri tek paragraf, orta uzunluk; madde kullanma.

FİKİR:
Kısa ad: {idea_short}
Detay: {idea_full}

KARAKTER:
{char_desc}

BAŞLANGIÇ:
Kasa: {int(stats.get("money",0))} TL
Ekip: {int(stats.get("team",50))}/100
Motivasyon: {int(stats.get("motivation",50))}/100
Aylık pazarlama: {int(stats.get("marketing_cost",5000))} TL
Fiyat: {int(stats.get("price",99))} TL

SADECE JSON:
{{
  "analysis": "Durum Analizi (tek paragraf, 10-14 cümle; hikâyesel, detaylı)",
  "crisis_detail": "⚠️ KRİZ (3-6 cümle; detaylı; sayılarla bağla; Extreme ise komik/kaotik ekle)",
  "choices": [
    {{
      "id":"A",
      "title":"(kısa başlık)",
      "paragraph":"(tek paragraf; orta uzunluk) Krizi çözmeye yönelik yöntem + neden işe yarar."
    }},
    {{
      "id":"B",
      "title":"(kısa başlık)",
      "paragraph":"(tek paragraf; orta uzunluk) Alternatif çözüm + neden işe yarar."
    }}
  ]
}}
""".strip()

def build_turn_prompt(
    *,
    mode: str,
    month: int,
    user_move: str,
    crisis: Dict[str, Any],
    stats: Dict[str, Any],
    expenses_total: int,
    chance_text: str,
    char_desc: str,
    idea_short: str,
    idea_full: str,
    extreme_trigger: str,
) -> str:
    tone = MODE_PROFILES.get(mode, MODE_PROFILES["Gerçekçi"])["tone"]

    extreme_rules = ""
    if mode == "Extreme":
        extreme_rules = f"""
EXTREME RUHU:
- Her tur komik ve tuhaf bir kırılma olmalı (ama problem gerçek).
- "Ders anlatır gibi" yazma; sahne + küçük diyalog + absürt detayla ak.
- A/B seçenekleri delice olabilir ama ikisi de teoride krizi çözebilir.
- Seçeneklerde çok terim kullanma; basit konuş.

ABSÜRT TETİKLEYİCİ (mutlaka kullan):
{extreme_trigger}
""".strip()

    return f"""
ROLÜN: Startup simülasyonu anlatıcısı + kriz çözdüren oyun yöneticisi.
MOD: {mode} (ton: {tone})
AY: {month}

{extreme_rules}

KURALLAR:
- Önce Durum Analizi yaz (tek paragraf, 10-14 cümle). Kullanıcının hamlesini yorumla ve fikre bağla.
- Sonra Kriz yaz (3-6 cümle, detaylı, sayılarla bağlı).
- A/B seçenekleri tek paragraf, orta uzunluk; madde yok.
- Terim kullanacaksan çok basit anlat.

KARAKTER:
{char_desc}

GİRİŞİM:
Kısa ad: {idea_short}
Detay: {idea_full}

DURUM:
- Kasa: {int(stats.get("money",0))} TL
- Gider: {int(expenses_total)} TL
- MRR: {int(stats.get("mrr",0))} TL
- Aktif: {int(stats.get("active_users",0))}
- Ödeyen: {int(stats.get("paid_users",0))}
- Churn: {round(float(stats.get("churn",0))*100,1)}%
{chance_text}

PYTHON KRİZ TESPİTİ:
{crisis["crisis_detail"]}

Oyuncunun hamlesi:
{user_move}

SADECE JSON:
{{
  "analysis":"Durum Analizi (tek paragraf, 10-14 cümle; hikâyesel; kullanıcı hamlesini yorumla)",
  "crisis_detail":"⚠️ KRİZ (3-6 cümle, detaylı, sayılarla bağlı; Extreme ise komik/kaotik ekle)",
  "choices":[
    {{"id":"A","title":"(kısa başlık)","paragraph":"(tek paragraf; orta uzunluk) Krizi çözmeye yönelik yöntem + neden işe yarar."}},
    {{"id":"B","title":"(kısa başlık)","paragraph":"(tek paragraf; orta uzunluk) Alternatif çözüm + neden işe yarar."}}
  ]
}}
""".strip()

# ------------------------------
# OFFLINE FALLBACK (ÖNERİ YOK, EXTREME KOMİK)
# ------------------------------
def offline_payload(mode: str, month: int, idea_short: str, crisis: Dict[str, Any], extreme_trigger: str) -> Dict[str, Any]:
    if mode == "Extreme":
        analysis = (
            f"Ay {month} — {idea_short} yine sahnede ama sahne dediğin şey düz değil; yer yer kayıyor. "
            f"{extreme_trigger} Bu tuhaflık komik görünse de altındaki gerçek problem net: insanlar ürünü duyuyor ama tam olarak ‘ne’yi aldığını anlamadan uzaklaşıyor. "
            "Sen hamleni yapınca ekip ikiye bölünüyor: bir taraf ‘şimdi büyüme zamanı’ diye tempo tutuyor, diğer taraf ‘önce anlaşılır olalım’ diye fren basıyor. "
            "Asıl mesele hız değil; hangi cümleyle var olduğunu söyleyebildiğin. Çünkü kullanıcı kafası karışınca ürünün iyi olması yetmiyor—iyi olduğunu kimse fark etmiyor."
        )
        a = "Krizden çıkışı ‘komik ama işe yarayan’ bir teste bağla: ürünü tek bir ana vaade indir ve bir günlüğüne her şeyi o vaadin etrafına kilitle. Bir mini açılış ekranı koyup kullanıcıya iki seçenek sun: ‘anında çeviri’ mi ‘öğrenme modu’ mu; üçüncü seçenek yok. Bu, hem yanlış beklentiyi temizler hem de en çok hangi vaat çalışıyor onu görmeni sağlar; kısa vadede bazı kişileri kaybedersin ama doğru kitleyi bulursun."
        b = "Kaosu ‘daha az seçenek, daha çok netlik’ ile düzelt: onboarding’i üç adımda bitir ve ilk 60 saniyede tek bir başarı anı yarat (ör. bir kelimeyi yakalayıp çevirmek). Ardından fiyat/plan konuşmasını ertele; önce değer kanıtı ver. Böylece kriz ‘her şey çok iddialı ama belirsiz’ olmaktan çıkar, kullanıcı zihninde ‘tamam bu iş görüyor’ noktasına iner."
    else:
        analysis = (
            f"Ay {month} — {idea_short} hızla ilerlemek istiyor ama yolun ortasında küçük bir belirsizlik büyüyerek önüne çıkıyor. "
            "Hamlen, iyi niyetli olsa da kullanıcı tarafında ‘tam olarak neyi çözüyor’ sorusunu netleştirmeden büyümeye zorlarsa geri tepme riski var. "
            "Bu ayın kilidi: fikri bir hedef kitleye ve tek bir ana vaade indirip, bunu ilk deneyimde kanıtlamak. "
            "Bunu yapınca hem kullanıcı davranışlarını daha doğru okuyacaksın hem de hangi yatırımın gerçekten işe yaradığını göreceksin."
        )
        a = "Krizden çıkmak için vaadi netleştir ve ilk deneyimi sadeleştir: kullanıcı daha ilk dakikada değer görsün. Net bir hedef kitle seçip mesajı ona göre kurarsan, yanlış kullanıcıların yarattığı gürültü azalır ve doğru metrikleri okumaya başlarsın."
        b = "Alternatif çözüm: ürünü ölçülebilir bir akışa bağla ve tek bir metrik seç (ör. aktivasyon). Bu metrik yükselmeden büyüme denemeleri yapma; böylece bütçeyi ‘ne işe yaradığını bildiğin’ yere yatırırsın."

    return {
        "analysis": analysis,
        "crisis_detail": crisis["crisis_detail"],
        "choices": [
            {"id": "A", "title": "A Planı", "paragraph": a},
            {"id": "B", "title": "B Planı", "paragraph": b},
        ],
    }

# ------------------------------
# AYARLAR PANELİ (SAĞ ÜST)
# ------------------------------
def render_settings_panel(game_started: bool) -> None:
    lock = bool(game_started)

    st.session_state.setup_name = st.text_input("Adın", st.session_state.setup_name)
    st.session_state.setup_gender = st.selectbox(
        "Cinsiyet", ["Belirtmek İstemiyorum", "Erkek", "Kadın"],
        index=["Belirtmek İstemiyorum", "Erkek", "Kadın"].index(st.session_state.setup_gender)
        if st.session_state.setup_gender in ["Belirtmek İstemiyorum", "Erkek", "Kadın"] else 0,
    )

    if game_started and isinstance(st.session_state.get("player"), dict):
        st.session_state.player["name"] = st.session_state.setup_name
        st.session_state.player["gender"] = st.session_state.setup_gender

    st.divider()
    st.write("🧠 **Yetenek (0-10)**")
    c1, c2 = st.columns(2)
    with c1:
        st.session_state.setup_skill_coding = st.slider("💻 Yazılım", 0, 10, st.session_state.setup_skill_coding, disabled=lock)
        st.session_state.setup_skill_marketing = st.slider("📢 Pazarlama", 0, 10, st.session_state.setup_skill_marketing, disabled=lock)
        st.session_state.setup_skill_network = st.slider("🤝 Network", 0, 10, st.session_state.setup_skill_network, disabled=lock)
    with c2:
        st.session_state.setup_skill_discipline = st.slider("⏱️ Disiplin", 0, 10, st.session_state.setup_skill_discipline, disabled=lock)
        st.session_state.setup_skill_charisma = st.slider("✨ Karizma", 0, 10, st.session_state.setup_skill_charisma, disabled=lock)

    st.divider()
    st.write("💳 **SaaS Varsayımları**")
    k1, k2, k3 = st.columns(3)
    with k1:
        st.session_state.setup_price = st.number_input("Aylık fiyat (TL)", LIMITS["PRICE_MIN"], LIMITS["PRICE_MAX"], int(st.session_state.setup_price), step=10, disabled=lock)
    with k2:
        st.session_state.setup_conversion = st.slider("Ödeyen oranı", 0.001, 0.20, float(st.session_state.setup_conversion), step=0.001, disabled=lock)
    with k3:
        st.session_state.setup_churn = st.slider("Aylık bırakma (churn)", 0.01, 0.40, float(st.session_state.setup_churn), step=0.01, disabled=lock)

    st.divider()
    st.write("💰 **Başlangıç Finans**")
    f1, f2 = st.columns(2)
    with f1:
        st.session_state.setup_start_money = st.number_input("Kasa (TL)", 1000, 5_000_000, int(st.session_state.setup_start_money), step=10_000, disabled=lock)
    with f2:
        st.session_state.setup_start_loan = st.number_input("Kredi (TL)", 0, 1_000_000, int(st.session_state.setup_start_loan), step=10_000, disabled=lock)

    st.divider()
    st.write("✨ **Özel Özellikler**")
    t1, t2, t3 = st.columns([2, 2, 1])
    with t1:
        title = st.text_input("Özellik", placeholder="Örn: Gece Kuşu", disabled=lock, key="trait_title")
    with t2:
        desc = st.text_input("Açıklama", placeholder="Geceleri verim artar", disabled=lock, key="trait_desc")
    with t3:
        if st.button("Ekle", disabled=lock):
            if (title or "").strip():
                st.session_state.custom_traits_list.append({"title": title.strip(), "desc": (desc or "").strip()})

    if st.session_state.custom_traits_list:
        for t in st.session_state.custom_traits_list:
            st.caption(f"🔸 **{t.get('title','')}**: {t.get('desc','')}")

# ------------------------------
# TUR İŞLEME
# ------------------------------
def run_turn(user_move: str) -> Dict[str, Any]:
    mode = st.session_state.selected_mode
    stats = st.session_state.stats
    player = st.session_state.player
    month = int(st.session_state.month)

    # gider düş
    salary, server, marketing, total_exp = calculate_expenses(stats, month, mode)
    stats["money"] = int(stats.get("money", 0) - total_exp)
    st.session_state.expenses = {"salary": salary, "server": server, "marketing": marketing, "total": total_exp}

    # intent
    intent = detect_intent(user_move)

    # KPI -> MRR -> kasa
    simulate_saas_kpis(stats, player, mode, intent)
    stats["money"] = int(stats.get("money", 0) + int(stats.get("mrr", 0)))
    clamp_core_stats(stats)

    # şans kartı
    card = trigger_chance_card(mode)
    st.session_state.last_chance_card = card
    chance_text = ""
    if card:
        chance_text = apply_chance_card(stats, card, mode)
        clamp_core_stats(stats)

    # kriz (detaylı)
    crisis = detect_crisis(stats, total_exp, mode)

    # Extreme tetikleyici (her tur)
    extreme_trigger = get_extreme_trigger(mode)

    # AI prompt
    char_desc = build_character_desc(player)
    idea_full = st.session_state.startup_idea
    idea_short = " ".join((idea_full or "").strip().split()[:8]) or "Startup"

    prompt = build_turn_prompt(
        mode=mode,
        month=month,
        user_move=user_move,
        crisis=crisis,
        stats=stats,
        expenses_total=total_exp,
        chance_text=chance_text,
        char_desc=char_desc,
        idea_short=idea_short,
        idea_full=idea_full,
        extreme_trigger=extreme_trigger,
    )

    raw = call_gemini(prompt, st.session_state.model_history, mode)
    data = None
    if raw:
        try:
            data = json.loads(clean_json(raw))
        except Exception:
            data = None

    if data is None:
        data = offline_payload(mode, month, idea_short, crisis, extreme_trigger)

    ai = validate_ai_payload(data)

    # UI history: sohbet akışında kaybolmasın
    st.session_state.ui_history.append(
        {
            "role": "assistant",
            "analysis": ai.get("analysis", ""),
            "crisis_detail": ai.get("crisis_detail", crisis["crisis_detail"]),
        }
    )

    # model history (kısa)
    st.session_state.model_history.append({"role": "user", "parts": [user_move]})
    st.session_state.model_history.append({"role": "model", "parts": [ai.get("analysis", "")]})

    # seçenekleri sakla
    st.session_state.last_choices = ai.get("choices", []) or []

    # game over
    if stats.get("money", 0) < 0 or stats.get("team", 0) <= 0 or stats.get("motivation", 0) <= 0:
        st.session_state.game_over = True
        if stats.get("money", 0) < 0:
            st.session_state.game_over_reason = "Kasa negatife düştü. Runway bitti."
        elif stats.get("team", 0) <= 0:
            st.session_state.game_over_reason = "Ekip dağıldı."
        else:
            st.session_state.game_over_reason = "Motivasyon sıfırlandı."

    # ay artır
    st.session_state.month = month + 1
    return ai

# ------------------------------
# HEADER + AYARLAR
# ------------------------------
def render_header(game_started: bool):
    left, right = st.columns([0.82, 0.18], vertical_alignment="center")
    with left:
        st.markdown(
            '<div class="hero-container">'
            '<h1 class="hero-title">Startup Survivor RPG</h1>'
            '<div class="hero-subtitle">Gemini Destekli Girişimcilik Simülasyonu (Web SaaS odaklı)</div>'
            "</div>",
            unsafe_allow_html=True,
        )
    with right:
        if hasattr(st, "popover"):
            with st.popover("⚙️ Ayarlar", use_container_width=True):
                render_settings_panel(game_started=game_started)
        else:
            with st.expander("⚙️ Ayarlar", expanded=False):
                render_settings_panel(game_started=game_started)

# ------------------------------
# SESSION INIT
# ------------------------------
def init_state():
    if "game_started" not in st.session_state:
        st.session_state.game_started = False
    if "game_over" not in st.session_state:
        st.session_state.game_over = False
    if "game_over_reason" not in st.session_state:
        st.session_state.game_over_reason = ""

    if "ui_history" not in st.session_state:
        st.session_state.ui_history = []
    if "model_history" not in st.session_state:
        st.session_state.model_history = []

    if "stats" not in st.session_state:
        st.session_state.stats = {}
    if "expenses" not in st.session_state:
        st.session_state.expenses = {"salary": 0, "server": 0, "marketing": 0, "total": 0}

    if "player" not in st.session_state:
        st.session_state.player = {}
    if "month" not in st.session_state:
        st.session_state.month = 1

    if "selected_mode" not in st.session_state:
        st.session_state.selected_mode = "Gerçekçi"

    if "last_chance_card" not in st.session_state:
        st.session_state.last_chance_card = None
    if "last_choices" not in st.session_state:
        st.session_state.last_choices = []
    if "pending_move" not in st.session_state:
        st.session_state.pending_move = None

    if "custom_traits_list" not in st.session_state:
        st.session_state.custom_traits_list = []
    if "startup_idea" not in st.session_state:
        st.session_state.startup_idea = ""

    st.session_state.setdefault("setup_name", "İsimsiz Girişimci")
    st.session_state.setdefault("setup_gender", "Belirtmek İstemiyorum")
    st.session_state.setdefault("setup_start_money", 100_000)
    st.session_state.setdefault("setup_start_loan", 0)
    st.session_state.setdefault("setup_skill_coding", 5)
    st.session_state.setdefault("setup_skill_marketing", 5)
    st.session_state.setdefault("setup_skill_network", 5)
    st.session_state.setdefault("setup_skill_discipline", 5)
    st.session_state.setdefault("setup_skill_charisma", 5)
    st.session_state.setdefault("setup_price", 99)
    st.session_state.setdefault("setup_conversion", 0.04)
    st.session_state.setdefault("setup_churn", 0.10)

init_state()
apply_custom_css(st.session_state.selected_mode)

# ============================================================
# LOBBY
# ============================================================
if not st.session_state.game_started:
    with st.sidebar:
        st.header(f"👤 {st.session_state.setup_name}")
        mode_list = ["Gerçekçi", "Türkiye Simülasyonu", "Zor", "Extreme", "Spartan"]
        cur = st.session_state.get("selected_mode", "Gerçekçi")
        st.session_state.selected_mode = st.selectbox(
            "🎮 Mod",
            mode_list,
            index=mode_list.index(cur) if cur in mode_list else 0,
            key="mode_select_lobby",
        )
        st.divider()
        st.caption("Ayarlar: sağ üstte ⚙️")

    render_header(game_started=False)
    st.info("👇 Oyuna başlamak için iş fikrini yaz ve Enter'a bas.")
    startup_idea = st.chat_input("Girişim fikrin ne? (Örn: Üniversiteliler için proje yönetimi SaaS...)")

    if startup_idea:
        st.session_state.player = {
            "name": st.session_state.setup_name,
            "gender": st.session_state.setup_gender,
            "stats": {
                "coding": st.session_state.setup_skill_coding,
                "marketing": st.session_state.setup_skill_marketing,
                "network": st.session_state.setup_skill_network,
                "discipline": st.session_state.setup_skill_discipline,
                "charisma": st.session_state.setup_skill_charisma,
            },
            "custom_traits": st.session_state.custom_traits_list,
        }

        start_money = int(st.session_state.setup_start_money)
        start_loan = int(st.session_state.setup_start_loan)

        st.session_state.stats = {
            "money": int(start_money + start_loan),
            "team": 50,
            "motivation": 50,
            "debt": int(start_loan),
            "marketing_cost": 5000,
            "users_total": 2000,
            "active_users": 500,
            "paid_users": 20,
            "mrr": 0,
            "price": int(st.session_state.setup_price),
            "retention": 0.78,
            "churn": float(st.session_state.setup_churn),
            "activation": 0.35,
            "conversion": float(st.session_state.setup_conversion),
            "cac": 35,
        }
        clamp_core_stats(st.session_state.stats)

        st.session_state.expenses = {"salary": 0, "server": 0, "marketing": 0, "total": 0}
        st.session_state.month = 1  # Ay 1
        st.session_state.game_started = True
        st.session_state.game_over = False
        st.session_state.game_over_reason = ""
        st.session_state.ui_history = []
        st.session_state.model_history = []
        st.session_state.last_choices = []
        st.session_state.pending_move = None
        st.session_state.startup_idea = startup_idea

        # chat: user fikri
        st.session_state.ui_history.append({"role": "user", "text": startup_idea})

        mode = st.session_state.selected_mode
        char_desc = build_character_desc(st.session_state.player)

        # kriz üretimi için örnek gider
        _, _, _, total_exp = calculate_expenses(st.session_state.stats, 1, mode)
        crisis = detect_crisis(st.session_state.stats, total_exp, mode)

        intro_prompt = build_intro_prompt(mode, startup_idea, char_desc, st.session_state.stats)
        raw = call_gemini(intro_prompt, [], mode)
        data = None
        if raw:
            try:
                data = json.loads(clean_json(raw))
            except Exception:
                data = None

        extreme_trigger = get_extreme_trigger(mode)
        if data is None:
            idea_short = " ".join(startup_idea.split()[:8])
            data = offline_payload(mode, 1, idea_short, crisis, extreme_trigger)

        intro = validate_ai_payload(data)

        st.session_state.ui_history.append(
            {
                "role": "assistant",
                "analysis": intro.get("analysis", ""),
                "crisis_detail": intro.get("crisis_detail", crisis["crisis_detail"]),
            }
        )
        st.session_state.last_choices = intro.get("choices", []) or []
        st.session_state.model_history.append({"role": "user", "parts": [f"Startup fikrim: {startup_idea}"]})
        st.session_state.model_history.append({"role": "model", "parts": [intro.get("analysis", "")]})

        st.rerun()

# ============================================================
# GAME OVER
# ============================================================
elif st.session_state.game_over:
    render_header(game_started=True)
    st.error("💀 GAME OVER")
    st.write(st.session_state.game_over_reason or "Oyun bitti.")
    if st.button("Tekrar dene"):
        st.session_state.clear()
        st.rerun()

# ============================================================
# GAME
# ============================================================
else:
    render_header(game_started=True)

    # SIDEBAR
    with st.sidebar:
        st.header(f"👤 {st.session_state.player.get('name','İsimsiz Girişimci')}")

        mode_list = ["Gerçekçi", "Türkiye Simülasyonu", "Zor", "Extreme", "Spartan"]
        cur_mode = st.session_state.get("selected_mode", "Gerçekçi")
        st.session_state.selected_mode = st.selectbox(
            "🎮 Mod",
            mode_list,
            index=mode_list.index(cur_mode) if cur_mode in mode_list else 0,
            key="mode_select_game",
        )

        st.progress(min(st.session_state.month / 12.0, 1.0), text=f"🗓️ Ay: {st.session_state.month}/12")
        st.divider()

        with st.expander("💡 Girişim fikrim", expanded=False):
            st.write(st.session_state.startup_idea)

        st.subheader("📊 Finansal Durum")
        st.metric("💵 Kasa", format_currency(int(st.session_state.stats.get("money", 0))))
        if int(st.session_state.stats.get("debt", 0)) > 0:
            st.warning(f"🏦 Kredi Borcu: {format_currency(int(st.session_state.stats['debt']))}")

        with st.expander("🔻 Aylık Gider Detayı", expanded=True):
            exp = st.session_state.expenses
            st.markdown(
                f"""
                <div class='expense-row'><span class='expense-label'>Maaşlar:</span><span class='expense-val'>-{format_currency(exp['salary'])}</span></div>
                <div class='expense-row'><span class='expense-label'>Sunucu:</span><span class='expense-val'>-{format_currency(exp['server'])}</span></div>
                <div class='expense-row'><span class='expense-label'>Pazarlama:</span><span class='expense-val'>-{format_currency(exp['marketing'])}</span></div>
                <div class='expense-row total-expense'><span class='expense-label'>TOPLAM:</span><span>-{format_currency(exp['total'])}</span></div>
                """,
                unsafe_allow_html=True,
            )

        st.divider()
        st.write(f"👥 Ekip: %{st.session_state.stats.get('team', 0)}")
        st.progress(int(st.session_state.stats.get("team", 0)) / 100.0)
        st.write(f"🔥 Motivasyon: %{st.session_state.stats.get('motivation', 0)}")
        st.progress(int(st.session_state.stats.get("motivation", 0)) / 100.0)

        st.divider()
        st.subheader("📈 SaaS KPI")
        st.metric("👤 Toplam Kullanıcı", f"{int(st.session_state.stats.get('users_total', 0)):,}".replace(",", "."))
        st.metric("✅ Aktif", f"{int(st.session_state.stats.get('active_users', 0)):,}".replace(",", "."))
        st.metric("💳 Ödeyen", f"{int(st.session_state.stats.get('paid_users', 0)):,}".replace(",", "."))
        st.metric("🔁 MRR", format_currency(int(st.session_state.stats.get("mrr", 0))))
        st.caption(
            f"CAC: {int(st.session_state.stats.get('cac', 0))} TL | "
            f"Churn: {round(float(st.session_state.stats.get('churn',0))*100,1)}% | "
            f"Ödeyen oranı: {round(float(st.session_state.stats.get('conversion',0))*100,2)}%"
        )

        if st.session_state.player.get("custom_traits"):
            with st.expander("✨ Özelliklerin", expanded=False):
                for t in st.session_state.player["custom_traits"]:
                    st.markdown(
                        f"<div class='chip'><b>{t.get('title','')}</b> — {t.get('desc','')}</div>",
                        unsafe_allow_html=True,
                    )

        if st.session_state.last_chance_card:
            st.info(f"🃏 Son Kart: {st.session_state.last_chance_card.get('title','')}")

    # CHAT (Sıralama: Durum Analizi -> Kriz)
    for msg in st.session_state.ui_history:
        role = msg.get("role", "assistant")
        with st.chat_message("user" if role == "user" else "assistant"):
            if role == "user":
                st.write(msg.get("text", ""))
            else:
                analysis = (msg.get("analysis") or "").strip()
                crisis_detail = (msg.get("crisis_detail") or "").strip()

                # 1) Durum analizi (üstte)
                if analysis:
                    st.markdown(
                        f"<div class='analysis-box'><b>🧠 DURUM ANALİZİ</b><br/><br/>{analysis}</div>",
                        unsafe_allow_html=True
                    )

                # 2) Kriz (altta)
                if crisis_detail:
                    st.markdown(
                        f"<div class='crisis-box'><b>⚠️ KRİZ</b><br/><br/>{crisis_detail}</div>",
                        unsafe_allow_html=True
                    )

    # 12 ay bitti mi?
    if st.session_state.month > 12:
        st.success("🎉 12 ayı tamamladın — hayatta kaldın (şimdilik).")
        if st.button("Yeni kariyer / yeniden başla"):
            st.session_state.clear()
            st.rerun()
    else:
        # Seçenek kartları (A/B paragraf)
        choices = st.session_state.last_choices or []
        if choices:
            st.caption("👇 Durumu gördün. Şimdi krize karşı bir çözüm seç (A/B) veya alttan serbest yaz.")
            cols = st.columns(len(choices))
            for idx, ch in enumerate(choices):
                cid = (ch.get("id") or "A").strip()
                title = (ch.get("title") or "").strip()
                paragraph = (ch.get("paragraph") or "").strip()

                with cols[idx]:
                    st.markdown(f"### {cid}) {title}")
                    st.write(paragraph)

                    if st.button(f"✅ {cid} seç", key=f"choice_{st.session_state.month}_{idx}", use_container_width=True):
                        st.session_state.pending_move = f"{cid}) {title}\n\n{paragraph}"
                        st.rerun()

        user_move = st.session_state.pending_move or st.chat_input("Hamleni yap... (krizi çözmeye odaklan)")
        if user_move:
            st.session_state.pending_move = None
            st.session_state.ui_history.append({"role": "user", "text": user_move})

            with st.spinner("Tur işleniyor..."):
                run_turn(user_move)

            st.rerun()
