import streamlit as st
import google.generativeai as genai
import json
import random
import time
from typing import Any, Dict, List, Optional, Tuple

# ============================================================
# Startup Survivor RPG (Gemini) - Tek Dosya
# Web SaaS odaklı simülasyon + oyun modları
# ============================================================

st.set_page_config(page_title="Startup Survivor RPG", page_icon="💀", layout="wide")

# ------------------------------
# MOD PROFİLLERİ
# ------------------------------
MODE_COLORS = {
    "Gerçekçi": "#2ECC71",
    "Zor": "#F1C40F",
    "Türkiye Simülasyonu": "#1ABC9C",
    "Spartan": "#E74C3C",
    "Extreme": "#9B59B6",
}

MODE_PROFILES = {
    "Gerçekçi": {"chance_prob": 0.20, "shock_mult": 1.0, "turkey": False, "tone": "realistic"},
    "Zor": {"chance_prob": 0.30, "shock_mult": 1.25, "turkey": False, "tone": "hard"},
    "Spartan": {"chance_prob": 0.25, "shock_mult": 1.45, "turkey": False, "tone": "hardcore"},
    "Türkiye Simülasyonu": {"chance_prob": 0.28, "shock_mult": 1.15, "turkey": True, "tone": "turkey"},
    "Extreme": {"chance_prob": 0.45, "shock_mult": 2.20, "turkey": False, "tone": "extreme"},
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

EXTREME_CARDS = [
    {"title": "🐙 Rakip Ahtapot", "desc": "Rakip her kanala aynı anda saldırdı. Kaos!", "effect": "motivation", "val": -18},
    {"title": "🦄 Unicorn Havası", "desc": "Ekip 'unicorn olacağız' diye gazlandı.", "effect": "motivation", "val": 25},
    {"title": "🎩 Yatırımcı Şapkası", "desc": "Şapkadan term-sheet çıktı ama şartlar tuhaf.", "effect": "money", "val": 35_000},
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

def apply_chance_card(stats: Dict[str, Any], card: Dict[str, Any], mode: str) -> Tuple[str, Dict[str, Any]]:
    if not card:
        return "", {}

    shock = float(MODE_PROFILES.get(mode, MODE_PROFILES["Gerçekçi"]).get("shock_mult", 1.0))
    effect = card.get("effect")
    raw_val = int(card.get("val", 0))
    val = int(round(raw_val * shock))

    # Uçları kırp (Extreme biraz daha geniş)
    if effect == "money":
        abs_cash = max(1, int(abs(stats.get("money", 0))))
        cap_ratio = 0.50 if mode != "Extreme" else 1.25
        cap = max(15_000, int(abs_cash * cap_ratio))
        val = max(-cap, min(cap, val))
        stats["money"] = int(stats.get("money", 0) + val)

    elif effect == "team":
        cap = 25 if mode != "Extreme" else 40
        val = max(-cap, min(cap, val))
        stats["team"] = int(stats.get("team", 50) + val)

    elif effect == "motivation":
        cap = 30 if mode != "Extreme" else 55
        val = max(-cap, min(cap, val))
        stats["motivation"] = int(stats.get("motivation", 50) + val)

    text = f"\n\n🃏 **ŞANS KARTI:** {card.get('title','')}\n_{card.get('desc','')}_"
    return text, {"effect": effect, "val": val}

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

    # Intent -> metriklere küçük dokunuş (kural tabanlı)
    if intent == "growth":
        activation = clamp_float(activation + 0.02 * marketing_skill, 0.05, 0.90, activation)
        churn = clamp_float(churn + 0.01, 0.01, 0.60, churn)  # agresif büyüme bazen kaliteyi zorlar
    elif intent == "product":
        retention = clamp_float(retention + 0.03 * coding_skill, 0.20, 0.98, retention)
        churn = clamp_float(churn - 0.01, 0.01, 0.60, churn)
    elif intent == "monetize":
        conversion = clamp_float(conversion + 0.01 * discipline_skill, 0.001, 0.40, conversion)
    elif intent == "team_ops":
        churn = clamp_float(churn - 0.005, 0.01, 0.60, churn)

    # CAC
    base_cac = clamp_int(stats.get("cac", 35), 5, 500, 35)
    if mode == "Zor":
        base_cac = int(base_cac * 1.15)
    elif mode == "Spartan":
        base_cac = int(base_cac * 1.25)
    elif mode == "Türkiye Simülasyonu":
        base_cac = int(base_cac * 1.10)
    elif mode == "Extreme":
        base_cac = int(base_cac * random.choice([0.6, 0.8, 1.0, 1.5, 2.0]))

    cac = max(5, int(base_cac / max(0.75, marketing_skill)))
    marketing_spend = clamp_int(stats.get("marketing_cost", 5000), LIMITS["MARKETING_MIN"], LIMITS["MARKETING_MAX"], 5000)

    new_users = int(marketing_spend / max(1, cac))
    if mode == "Extreme":
        new_users = int(new_users * random.choice([0.2, 0.6, 1.0, 1.7, 3.0]))

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
# KRİZ TESPİTİ (Seçenekleri kriz odaklı yaptırmak için)
# ------------------------------
def detect_crisis(stats: Dict[str, Any], expenses_total: int) -> Dict[str, Any]:
    money = int(stats.get("money", 0))
    mrr = int(stats.get("mrr", 0))
    churn = float(stats.get("churn", 0.10))
    activation = float(stats.get("activation", 0.35))
    conversion = float(stats.get("conversion", 0.04))
    motivation = int(stats.get("motivation", 50))
    team = int(stats.get("team", 50))

    burn = max(0, expenses_total - mrr)  # aylık net yanma
    runway_months = 999
    if burn > 0:
        runway_months = max(0, money // burn)

    issues = []
    if burn > 0 and runway_months <= 3:
        issues.append(("RUNWAY", "Kasa hızlı eriyor (runway çok kısa)."))
    if churn >= 0.14:
        issues.append(("CHURN", "Kullanıcılar hızlı bırakıyor (churn yüksek)."))
    if activation <= 0.22:
        issues.append(("ACTIVATION", "Yeni gelenler ürünü yeterince kullanmıyor (aktivasyon düşük)."))
    if conversion <= 0.02 and stats.get("active_users", 0) > 300:
        issues.append(("CONVERSION", "Aktif kullanıcı var ama ödeyen az (ödeme dönüşümü düşük)."))
    if motivation <= 25:
        issues.append(("MORALE", "Ekip morali düşüyor (motivasyon kritik)."))
    if team <= 15:
        issues.append(("CAPACITY", "Ekip çok küçük, yetişememe riski var."))

    if not issues:
        issues.append(("BALANCE", "Şimdilik dengedesin; bir sonraki sıçrama için doğru hamle önemli."))

    # birincil kriz = ilk eleman (öncelik sırası yukarıdaki sıraya göre)
    primary_code, primary_text = issues[0]
    return {
        "primary_code": primary_code,
        "primary_text": primary_text,
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
        st.error("st.secrets içinde GOOGLE_API_KEYS bulunamadı.")
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

def call_gemini(prompt: str, history: List[Dict[str, Any]]) -> Optional[str]:
    keys = configure_gemini()
    if not keys:
        return None

    models = build_model_candidates()
    last_err = None

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
                    generation_config={"temperature": 0.85, "max_output_tokens": 2048},
                )
                if resp and getattr(resp, "text", None):
                    return resp.text
            except Exception as e:
                last_err = e
                if "429" in str(e) or "quota" in str(e).lower():
                    time.sleep(0.8)
                continue

    if last_err:
        st.warning(
            "AI isteği başarısız oldu (quota/model/ağ). Offline anlatıcıyla devam ediyorum.\n\n"
            f"Hata: {last_err}"
        )
    return None

# ------------------------------
# AI PAYLOAD DOĞRULAMA
# ------------------------------
def validate_ai_payload(resp: Any) -> Dict[str, Any]:
    if not isinstance(resp, dict):
        return {"text": "AI cevabı okunamadı. Lütfen tekrar dene.", "insights": [], "choices": [], "next": {}}

    text = resp.get("text", "")
    insights = resp.get("insights", [])
    choices = resp.get("choices", [])
    nxt = resp.get("next", {})

    if not isinstance(text, str):
        text = str(text)
    if not isinstance(insights, list):
        insights = []
    insights = [str(x) for x in insights][:6]

    norm_choices = []
    if isinstance(choices, list):
        for c in choices[:2]:
            if isinstance(c, dict):
                cid = (str(c.get("id", "")).strip() or "A")[:2]
                title = str(c.get("title", "")).strip()
                desc = str(c.get("desc", "")).strip()
                steps = c.get("steps", [])
                if not isinstance(steps, list):
                    steps = []
                steps = [str(s).strip() for s in steps][:4]
                if title or desc:
                    norm_choices.append({"id": cid, "title": title, "desc": desc, "steps": steps})
    choices = norm_choices

    if not isinstance(nxt, dict):
        nxt = {}
    normalized_next = {
        "marketing_cost": nxt.get("marketing_cost", None),
        "team_delta": nxt.get("team_delta", 0),
        "motivation_delta": nxt.get("motivation_delta", 0),
    }

    return {"text": text, "insights": insights, "choices": choices, "next": normalized_next}

def offline_intro_payload(mode: str, idea_short: str) -> Dict[str, Any]:
    # başlangıçta Ay 1 için "karar sorusu" (hesap yok)
    if mode == "Extreme":
        text = f"Ay 1: {idea_short} sahneye çıkıyor. Evren saçmalamak için hazır. İlk hamlen ne?"
        choices = [
            {
                "id": "A",
                "title": "Deli Cesaretiyle Lansman",
                "desc": "Hızlı bir demo yayınla, insanlardan geri bildirim topla. Risk: ortalık bug dolabilir.",
                "steps": ["Mini demo hazırla", "10 kişiye test ettir", "En çok şikayeti not al"],
            },
            {
                "id": "B",
                "title": "Kaos Öncesi Emniyet Kemeri",
                "desc": "En kritik hataları önle, sonra büyü. Risk: büyüme yavaşlar ama sağlam başlarsın.",
                "steps": ["En kritik akışı seç", "Çökme riskini azalt", "Basit onboarding ekle"],
            },
        ]
    else:
        text = f"Ay 1: {idea_short} için ilk ay başladı. İlk hamlen ne olacak?"
        choices = [
            {
                "id": "A",
                "title": "Hızlı Lansman + Geri Bildirim",
                "desc": "Basit bir sürüm çıkarıp gerçek kullanıcıdan öğren. Risk: eksikler görünür.",
                "steps": ["MVP'yi daralt", "10–20 test kullanıcısı bul", "En büyük sorunu seç"],
            },
            {
                "id": "B",
                "title": "Ürünü Sağlamlaştır",
                "desc": "Önce deneyimi ve temel kaliteyi iyileştir. Risk: büyüme biraz gecikir.",
                "steps": ["Onboarding'i iyileştir", "Hata/performansı düzelt", "Kısa yol haritası çıkar"],
            },
        ]
    return {"text": text, "insights": ["Hedef seç: ya öğrenme ya kalite.", "İlk ayda en büyük kazanım: doğru problemi bulmak.", "Küçük, ölçülebilir bir hedef koy."], "choices": choices, "next": {}}

def offline_turn_payload(mode: str, month: int, crisis: Dict[str, Any], stats: Dict[str, Any], expenses_total: int) -> Dict[str, Any]:
    ctext = crisis["primary_text"]
    text = (
        f"Ay {month}: {ctext}\n\n"
        f"Bu ay gider: {format_currency(expenses_total)} | MRR: {format_currency(int(stats.get('mrr',0)))} | "
        f"Kasa: {format_currency(int(stats.get('money',0)))}"
    )
    if mode == "Extreme":
        choices = [
            {"id": "A", "title": "Sorunu Çözen Saçmalık (Ama Mantıklı)", "desc": "Absürt bir kampanya ile geri dönüş al. Risk: itibar sallanır.", "steps": ["Komik ama net mesaj", "Küçük deneme", "Sonuca göre büyüt"]},
            {"id": "B", "title": "Daha Az Saçmalık, Daha Çok Çözüm", "desc": "Kök sebebi düzelt. Risk: hemen büyüme bekleme.", "steps": ["Kök sebebi seç", "1 kritik düzeltme", "Ölç ve doğrula"]},
        ]
    else:
        choices = [
            {"id": "A", "title": "Hızlı İyileştirme", "desc": "Kriz kaynağını hızlı yamala ve ölç. Risk: geçici çözüm olabilir.", "steps": ["En büyük sorun", "Hızlı düzelt", "Ölçüm ekle"]},
            {"id": "B", "title": "Kalıcı Çözüm", "desc": "Kriz kökünü çözmek için ürün ve süreç kur. Risk: zaman alır.", "steps": ["Kök analiz", "Kalıcı değişim", "Takip metriği"]},
        ]
    return {"text": text, "insights": ["Krizi bir metrikle tarif et.", "Bir hamle = bir hedef.", "Ölçmezsen öğrenemezsin."], "choices": choices, "next": {}}

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
# AI: KRİZ-ODAKLI SEÇENEK ÜRET (Terimsiz, çözüm odaklı)
# ------------------------------
def build_choices_prompt(
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
) -> str:
    tone = MODE_PROFILES.get(mode, MODE_PROFILES["Gerçekçi"])["tone"]

    # Jargon azaltma kuralı: terim kullanırsa parantezle açıklasın
    # Seçenekler kriz çözsün: "ne yapacaksın + nasıl + beklenen etki"
    # Extreme: absürt ama işe yarayabilir
    return f"""
ROLÜN: Startup simülasyonu anlatıcısı + kriz koçu.
MOD: {mode} (ton: {tone})
AY: {month}

KURAL-1: "text" içinde fikri BİREBİR uzun uzun tekrar etme. Sadece kısa ad ile referans ver: {idea_short}
KURAL-2: Çok teknik/iş terimi kullanma. Mecbur kalırsan parantez içinde basitçe açıkla.
KURAL-3: Bu turdaki seçenekler MUTLAKA şu anki krizi çözmeye çalışmalı. "Süs" seçenek olmasın.
KURAL-4: Extreme modda seçenekler absürt olabilir ama yine de sorunu çözme ihtimali olmalı (komik ama işe yarayabilir).
KURAL-5: Diğer modlarda seçenekler gerçek hayatta uygulanabilir, mantıklı olmalı.

{char_desc}

GİRİŞİM (özet):
Kısa ad: {idea_short}
Detay: {idea_full}

BU TUR RAPORU (Python hesapladı, değiştirme):
- Kasa: {int(stats.get("money",0))} TL
- Gider: {int(expenses_total)} TL
- MRR (aylık gelir): {int(stats.get("mrr",0))} TL
- Aktif kullanıcı: {int(stats.get("active_users",0))}
- Ödeyen: {int(stats.get("paid_users",0))}
- Churn (bırakma): {round(float(stats.get("churn",0))*100,1)}%
{chance_text}

KRİZ:
- Ana kriz: {crisis["primary_text"]}
- Runway (ay): {crisis["runway_months"]}
- Aylık net yanma (yaklaşık): {crisis["burn"]} TL

Oyuncunun hamlesi:
{user_move}

İSTENEN ÇIKTI:
- "text": Bu ay ne oldu? Krizi hikaye gibi anlat ama kısa ve net.
- "insights": 3 madde: (1) Krizin gerçek hayatta karşılığı, (2) kısa vadede yapılacak, (3) dikkat edilecek risk
- "choices": 2 seçenek:
    A) Krize hızlı çözüm (hızlı etkili ama riskli olabilir)
    B) Krize kalıcı çözüm (daha yavaş ama sağlam)
  Her choice şunları içersin:
    - title: kısa başlık
    - desc: 2-3 cümlelik açıklama (krizi nasıl çözer?)
    - steps: 3 maddelik mini plan (kısa, anlaşılır)
- "next": küçük öneriler:
    - marketing_cost: (opsiyonel) yeni pazarlama bütçesi öner
    - team_delta: -5..+5
    - motivation_delta: -5..+5

SADECE JSON DÖN:
{{
  "text": "...",
  "insights": ["...", "...", "..."],
  "choices": [
    {{"id":"A","title":"...","desc":"...","steps":["...","...","..."]}},
    {{"id":"B","title":"...","desc":"...","steps":["...","...","..."]}}
  ],
  "next": {{"marketing_cost": null, "team_delta": 0, "motivation_delta": 0}}
}}
""".strip()

# ------------------------------
# TUR İŞLEME (Ay 1, Ay 2 ...)
# ------------------------------
def run_turn(user_move: str) -> Dict[str, Any]:
    mode = st.session_state.selected_mode
    stats = st.session_state.stats
    player = st.session_state.player
    month = int(st.session_state.month)

    # 1) Giderleri düş
    salary, server, marketing, total_exp = calculate_expenses(stats, month, mode)
    stats["money"] = int(stats.get("money", 0) - total_exp)
    st.session_state.expenses = {"salary": salary, "server": server, "marketing": marketing, "total": total_exp}

    # 2) Hamle niyetini çıkar (KPI simüle ederken kullanacağız)
    intent = detect_intent(user_move)

    # 3) KPI simülasyonu -> MRR hesapla (gelir ekle)
    kpi_summary = simulate_saas_kpis(stats, player, mode, intent)
    stats["money"] = int(stats.get("money", 0) + int(stats.get("mrr", 0)))

    clamp_core_stats(stats)

    # 4) Şans kartı
    card = trigger_chance_card(mode)
    st.session_state.last_chance_card = card
    chance_text = ""
    if card:
        chance_text, _ = apply_chance_card(stats, card, mode)
        clamp_core_stats(stats)

    # 5) Kriz tespit et (Seçenekleri kriz odaklı yaptıracağız)
    crisis = detect_crisis(stats, total_exp)

    # 6) AI prompt
    char_desc = build_character_desc(player)
    idea_full = st.session_state.startup_idea
    idea_short = " ".join((idea_full or "").strip().split()[:6]) or "Startup"

    prompt = build_choices_prompt(
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
    )

    # AI call
    raw = call_gemini(prompt, st.session_state.model_history)
    data = None
    if raw:
        try:
            data = json.loads(clean_json(raw))
        except Exception:
            data = None

    if data is None:
        data = offline_turn_payload(mode, month, crisis, stats, total_exp)

    ai = validate_ai_payload(data)

    # Next önerileri: kontrollü uygula (küçük)
    nxt = ai.get("next", {}) or {}
    if isinstance(nxt, dict):
        nm = nxt.get("marketing_cost", None)
        if nm is not None:
            stats["marketing_cost"] = clamp_int(nm, LIMITS["MARKETING_MIN"], LIMITS["MARKETING_MAX"], stats.get("marketing_cost", 5000))
        td = clamp_int(nxt.get("team_delta", 0), -5, 5, 0)
        md = clamp_int(nxt.get("motivation_delta", 0), -5, 5, 0)
        stats["team"] = int(stats.get("team", 50) + td)
        stats["motivation"] = int(stats.get("motivation", 50) + md)
        clamp_core_stats(stats)

    # Game over (Python)
    if stats.get("money", 0) < 0 or stats.get("team", 0) <= 0 or stats.get("motivation", 0) <= 0:
        st.session_state.game_over = True
        if stats.get("money", 0) < 0:
            st.session_state.game_over_reason = "Kasa negatife düştü. Runway bitti."
        elif stats.get("team", 0) <= 0:
            st.session_state.game_over_reason = "Ekip dağıldı."
        else:
            st.session_state.game_over_reason = "Motivasyon sıfırlandı."

    # UI history: AI mesajını ekle
    st.session_state.ui_history.append({
        "role": "assistant",
        "text": ai.get("text", ""),
        "insights": ai.get("insights", []),
    })

    # Model history (temiz metin)
    st.session_state.model_history.append({"role": "user", "parts": [user_move]})
    st.session_state.model_history.append({"role": "model", "parts": [ai.get("text", "")]})

    # Seçenekleri sakla
    st.session_state.last_choices = ai.get("choices", []) or []

    # Ayı artır (Ay 1 oynandı -> Ay 2)
    st.session_state.month = month + 1

    return ai

# ------------------------------
# INTRO MESAJI (Ay 1 başlamadan önce)
# ------------------------------
def generate_intro_message() -> None:
    mode = st.session_state.selected_mode
    idea_full = st.session_state.startup_idea
    idea_short = " ".join((idea_full or "").strip().split()[:6]) or "Startup"
    payload = offline_intro_payload(mode, idea_short)

    # AI ile intro da üretilebilir; ama güvenli olsun diye offline veriyoruz.
    # İstersen burayı AI'a da çevirebilirsin.
    st.session_state.ui_history.append({
        "role": "assistant",
        "text": payload["text"],
        "insights": payload["insights"],
    })
    st.session_state.last_choices = payload["choices"]

# ------------------------------
# SESSION STATE INIT
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

    # Setup (lobby)
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

# ------------------------------
# UI: HEADER + SETTINGS BUTTON
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
# LOBBY
# ------------------------------
if not st.session_state.game_started:
    # Sidebar: mod seçimi (oyuna başlamadan)
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
        # Player
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

        # Stats
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

        # State reset
        st.session_state.expenses = {"salary": 0, "server": 0, "marketing": 0, "total": 0}
        st.session_state.month = 1  # ✅ Ay 1'den başla
        st.session_state.game_started = True
        st.session_state.game_over = False
        st.session_state.game_over_reason = ""
        st.session_state.ui_history = []
        st.session_state.model_history = []
        st.session_state.last_choices = []
        st.session_state.pending_move = None
        st.session_state.startup_idea = startup_idea

        # Chat: kullanıcının fikrini 1 kere "user mesajı" olarak ekle
        st.session_state.ui_history.append({"role": "user", "text": startup_idea})

        # Model history: sadece bağlam
        st.session_state.model_history.append({"role": "user", "parts": [f"Startup fikrim: {startup_idea}"]})

        # ✅ Ay 1 başlamadan intro mesajı üret (ay atlamadan)
        generate_intro_message()

        st.rerun()

# ------------------------------
# GAME OVER
# ------------------------------
elif st.session_state.game_over:
    render_header(game_started=True)
    st.error("💀 GAME OVER")
    st.write(st.session_state.game_over_reason or "Oyun bitti.")
    if st.button("Tekrar dene"):
        st.session_state.clear()
        st.rerun()

# ------------------------------
# GAME
# ------------------------------
else:
    render_header(game_started=True)

    # SIDEBAR
    with st.sidebar:
        st.header(f"👤 {st.session_state.player.get('name','İsimsiz Girişimci')}")

        # ✅ Mod seçimi: Ay göstergesinin üstünde
        mode_list = ["Gerçekçi", "Türkiye Simülasyonu", "Zor", "Extreme", "Spartan"]
        cur_mode = st.session_state.get("selected_mode", "Gerçekçi")
        st.session_state.selected_mode = st.selectbox(
            "🎮 Mod",
            mode_list,
            index=mode_list.index(cur_mode) if cur_mode in mode_list else 0,
            key="mode_select_game",
        )

        # Ay göstergesi (oynanacak ay)
        st.progress(min(st.session_state.month / 12.0, 1.0), text=f"🗓️ Ay: {st.session_state.month}/12")
        st.divider()

        # Fikir: chat’te de var ama burada da “kısa erişim”
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

    # CHAT (mesajlaşma gibi: user + assistant hepsi kalır)
    for msg in st.session_state.ui_history:
        role = msg.get("role", "assistant")
        with st.chat_message("user" if role == "user" else "assistant"):
            st.write(msg.get("text", ""))
            if role != "user":
                ins = msg.get("insights", []) or []
                if ins:
                    with st.expander("🧠 Bu turdan çıkarım / öneri", expanded=False):
                        for i in ins:
                            st.write(f"- {i}")

    # 12 ay bitti mi?
    if st.session_state.month > 12:
        st.success("🎉 12 ayı tamamladın — hayatta kaldın (şimdilik).")
        if st.button("Yeni kariyer / yeniden başla"):
            st.session_state.clear()
            st.rerun()
    else:
        # Seçenek kartları (kriz çözüm odaklı ve daha uzun)
        choices = st.session_state.last_choices or []
        if choices:
            st.caption("👇 Bu ayın krizine karşı bir çözüm seç (A/B) veya alttan serbest yaz.")
            cols = st.columns(len(choices))
            for idx, ch in enumerate(choices):
                cid = (ch.get("id") or "A").strip()
                title = (ch.get("title") or "").strip()
                desc = (ch.get("desc") or "").strip()
                steps = ch.get("steps", []) or []
                with cols[idx]:
                    st.markdown(f"### {cid}) {title}")
                    if desc:
                        st.write(desc)
                    if steps:
                        st.write("**Mini plan:**")
                        for s in steps[:3]:
                            st.write(f"- {s}")
                    if st.button(f"✅ {cid} seç", key=f"choice_{st.session_state.month}_{idx}", use_container_width=True):
                        # buton mantığını koru: tıklayınca mesaj olarak hamle yazdır
                        st.session_state.pending_move = f"{cid}) {title}\n{desc}\n" + "\n".join([f"- {s}" for s in steps[:3]])
                        st.rerun()

        # Kullanıcı hamlesi (pending varsa onu kullan)
        user_move = st.session_state.pending_move or st.chat_input("Hamleni yaz... (Kriz çözümüne odaklan: 'şunu düzelt', 'şunu dene' gibi)")
        if user_move:
            st.session_state.pending_move = None

            # chat'e user mesajı ekle
            st.session_state.ui_history.append({"role": "user", "text": user_move})

            with st.spinner("Tur işleniyor..."):
                run_turn(user_move)

            st.rerun()
