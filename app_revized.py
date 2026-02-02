# app.py
# Startup Survivor RPG — tek dosya Streamlit uygulaması
# (kopyala/yapıştır çalıştır)

from __future__ import annotations

import json
import os
import random
import re
import textwrap
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

# Optional dependency: google-generativeai
try:
    import google.generativeai as genai  # type: ignore
    from google.api_core import exceptions as gexc  # type: ignore
except Exception:  # pragma: no cover
    genai = None  # type: ignore
    gexc = None  # type: ignore


# =========================
# Config / Constants
# =========================

APP_TITLE = "Startup Survivor RPG"
APP_SUBTITLE = "Sohbet akışı korunur. Ay 1'den başlar. Durum Analizi → Kriz → A/B seçimi."

DEFAULT_MODEL_CANDIDATES = [
    # Yeni/klasik isimler — NotFound olursa sırayla deneriz
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-pro",
    "models/gemini-1.5-flash",
    "models/gemini-1.5-pro",
    "models/gemini-pro",
]

MODES = {
    "Normal": {
        "desc": "Dengeli. İyi kararlar ödüllenir, kötü kararlar acıtır.",
        "temperature": 0.7,
        "spice": "net, gerçekçi, ölçülü dramatik",
        "extreme": False,
    },
    "Hard": {
        "desc": "Hata affetmez. Küçük yanlışlar büyük fatura çıkarır.",
        "temperature": 0.85,
        "spice": "daha sert, daha riskli, daha az tolerans",
        "extreme": False,
    },
    "Spartan": {
        "desc": "Kaynak kıt. Her karar bir şeyden vazgeçirir.",
        "temperature": 0.75,
        "spice": "minimal, tavizsiz, kaynak kısıtlı",
        "extreme": False,
    },
    "Extreme": {
        "desc": "Kaos ve absürt. Paylaşmalık olaylar. Mantık ikinci planda; sonuç metriklere çarpar.",
        "temperature": 1.0,
        "spice": "absürt, kaotik, kara mizah ama anlaşılır",
        "extreme": True,
    },
    "Türkiye Simülasyonu": {
        "desc": "Bürokrasi, dalgalı ekonomi, 'dayı faktörü' ve yerel sürprizler.",
        "temperature": 0.85,
        "spice": "Türkiye bağlamı, yerel gerçeklik, bürokrasi ve piyasa dalgası",
        "extreme": False,
    },
}

# Gerçek hayattan esinli vaka sezonları (dramatize / eğitim amaçlı).
# İster istemez basitleştirilmiştir; bire bir tarihsel döküm değil, "oyunlaştırılmış" versiyon.
CASE_PRESETS = {
    "Serbest (Rastgele)": {
        "seed": None,
        "brief": "Kendi fikrine göre rastgele olaylar.",
        "tags": [],
    },
    "WeWork (IPO Krizi)": {
        "seed": 2019,
        "brief": "Aşırı büyüme, yönetişim sorunu, IPO çöküşü sonrası güven ve nakit sıkıntısı.",
        "tags": ["governance", "burn", "brand"],
    },
    "FTX (Şok Çöküş)": {
        "seed": 2022,
        "brief": "Hızlı büyüme, güven krizleri, bilanço söylentileri ve ani likidite şoku.",
        "tags": ["trust", "liquidity", "risk"],
    },
    "Quibi (Yanlış Ürün/Dağıtım)": {
        "seed": 2020,
        "brief": "Ürün-habit uyumsuzluğu, pahalı içerik, düşük tutunma ve keskin pivot baskısı.",
        "tags": ["product", "retention", "pivot"],
    },
    "B2B Enterprise Scope Patlaması": {
        "seed": 404,
        "brief": "Kurumsal müşteri her şeyi ister; rapor/Excel talepleri ürünü yutar.",
        "tags": ["enterprise", "scope", "support"],
    },
}

# Metrik aralıkları
CLAMP = {
    "reputation": (0, 100),
    "support_load": (0, 100),
    "infra_load": (0, 100),
    "dayi_factor": (0, 100),
    "churn_pct": (0.0, 25.0),
}

# Üretim minimum uzunluklar (yetersiz kısa cevapları otomatik uzattırır)
MIN_LEN_ANALYSIS = 500   # karakter
MIN_LEN_CRISIS = 550
MIN_LEN_OUTCOME = 450


# =========================
# Helpers
# =========================

def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

def money_fmt(v: int) -> str:
    # TR biçim: 1.234.567 ₺
    s = f"{v:,}".replace(",", ".")
    return f"{s} ₺"

def pct_fmt(v: float) -> str:
    return f"%{v:.1f}"

def stable_hash(s: str) -> int:
    # Python hash rastgelelenir; deterministik olsun diye basit
    h = 2166136261
    for ch in s:
        h ^= ord(ch)
        h *= 16777619
        h &= 0xFFFFFFFF
    return int(h)

def now_ms() -> int:
    return int(time.time() * 1000)

def safe_json_extract(text: str) -> Optional[dict]:
    """
    Modelden gelen metinde JSON arar.
    - ```json ... ``` bloğu
    - veya ilk {...} dengeli blok
    """
    if not text:
        return None

    # fenced
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.S | re.I)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass

    # first balanced object (naive)
    start = text.find("{")
    if start != -1:
        # en son }'yi bulup dene; gerekirse küçülterek dene
        for end in range(len(text) - 1, start, -1):
            if text[end] != "}":
                continue
            snippet = text[start : end + 1]
            try:
                return json.loads(snippet)
            except Exception:
                continue

    return None


# =========================
# Gemini wrapper (robust)
# =========================

@dataclass
class GeminiClient:
    model_name: str
    model: Any

def _get_secret_any(key: str) -> Any:
    # streamlit secrets: st.secrets.get() bazen yoksa KeyError atar
    try:
        return st.secrets.get(key)  # type: ignore
    except Exception:
        return None

def get_gemini_api_key() -> Optional[str]:
    # 1) env
    k = os.getenv("GEMINI_API_KEY")
    if k:
        return k.strip()

    # 2) streamlit secrets
    k2 = _get_secret_any("GEMINI_API_KEY")
    if not k2:
        return None

    # Kullanıcı bazen liste olarak giriyor (TOML). Destekle:
    if isinstance(k2, list) and k2:
        return str(k2[0]).strip()
    return str(k2).strip()

def init_gemini_client() -> Tuple[Optional[GeminiClient], Optional[str]]:
    """
    Dönüş: (client, error_message)
    - NotFound/InvalidArgument durumlarında farklı model isimlerini dener.
    """
    if genai is None:
        return None, "google-generativeai paketi bulunamadı. requirements.txt'e ekleyin: google-generativeai"

    api_key = get_gemini_api_key()
    if not api_key:
        return None, "GEMINI_API_KEY bulunamadı. Streamlit Secrets veya ortam değişkeni olarak ekleyin."

    try:
        genai.configure(api_key=api_key)
    except Exception as e:
        return None, f"Gemini yapılandırılamadı: {e}"

    preferred = os.getenv("GEMINI_MODEL") or _get_secret_any("GEMINI_MODEL")
    candidates: List[str] = []
    if preferred:
        candidates.append(str(preferred).strip())

    candidates.extend(DEFAULT_MODEL_CANDIDATES)

    # Tekilleştir
    seen = set()
    uniq: List[str] = []
    for c in candidates:
        if not c or c in seen:
            continue
        seen.add(c)
        uniq.append(c)

    last_err = None
    for name in uniq:
        try:
            model = genai.GenerativeModel(name)
            # tiny ping to validate name (NotFound burada patlar)
            _ = model.generate_content(
                "ping",
                generation_config={"max_output_tokens": 8, "temperature": 0.0},
            )
            return GeminiClient(model_name=name, model=model), None
        except Exception as e:
            last_err = e
            continue

    return None, f"Gemini model bulunamadı / erişilemedi. Denenen modeller: {', '.join(uniq)}. Hata: {last_err}"

def gemini_generate(
    client: GeminiClient,
    prompt: str,
    temperature: float = 0.8,
    max_output_tokens: int = 1300,
) -> str:
    """
    NotFound gibi durumlarda yeni model fallback denemek için üst seviyede try/except yapılır.
    """
    resp = client.model.generate_content(
        prompt,
        generation_config={
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
        },
    )
    # bazı sürümlerde resp.text yok; resp.candidates[0].content.parts...
    txt = getattr(resp, "text", None)
    if txt:
        return str(txt)

    try:
        parts = resp.candidates[0].content.parts  # type: ignore
        return "".join(getattr(p, "text", "") for p in parts)
    except Exception:
        return str(resp)


# =========================
# Prompt builders
# =========================

def build_system_context(state: dict) -> str:
    mode = state["mode"]
    preset = state["case_preset"]
    startup = state.get("startup_idea", "")
    name = state.get("player_name", "İsimsiz Girişimci")

    metrics = state["metrics"]
    turkey = (mode == "Türkiye Simülasyonu")

    # Geçmiş seçim özeti
    history_lines = []
    for h in state.get("choice_history", [])[-6:]:
        history_lines.append(f"- Ay {h['month']}: {h['choice']} — {h['title']}")
    history = "\n".join(history_lines) if history_lines else "- (Henüz seçim yok.)"

    preset_brief = CASE_PRESETS.get(preset, CASE_PRESETS["Serbest (Rastgele)"])["brief"]

    # Mode ton ve kurallar
    tone = MODES[mode]["spice"]
    extra_tr = ""
    if turkey:
        extra_tr = (
            "\nTürkiye simülasyonu kuralları:\n"
            "- Olaylar Türkiye bağlamında geçer (bürokrasi, kur farkı, vergiler, tedarik, tahsilat gecikmesi, 'dayı faktörü').\n"
            "- 'Dayı Faktörü' (0-100) doğru ilişki/bağlantı yönetimini temsil eder; bazen hızlandırır bazen risk yaratır.\n"
        )

    # Metrikleri modele bağlam olarak veririz ama metinde TEKRAR yazdırmayız (kullanıcı istemiyor)
    metrics_ctx = (
        f"Kasa: {metrics['cash']} TL, MRR: {metrics['mrr']} TL, "
        f"Kayıp Oranı (churn): {metrics['churn_pct']}%, "
        f"İtibar: {metrics['reputation']}/100, Destek yükü: {metrics['support_load']}/100, "
        f"Altyapı yükü: {metrics['infra_load']}/100"
        + (f", Dayı Faktörü: {metrics['dayi_factor']}/100" if turkey else "")
    )

    return textwrap.dedent(
        f"""
        Sen bir startup simülasyonu anlatıcısısın. Dil: Türkçe.
        Oyuncu: {name}
        Mod: {mode} ({tone})
        Vaka sezonağı: {preset} — {preset_brief}

        Kurallar:
        - "Durum Analizi" bölümünü her ay üret.
          * Ay 1: oyuncunun girişim fikrini güçlü/zayıf yönleriyle derin analiz et (pazar, farklılaşma, riskler, ilk 30 gün).
          * Ay 2+: bir önceki ay seçiminin sonuçlarını ve biriken ikinci-order etkileri analiz et (takım, ürün, satış, PR, operasyon).
        - "Kriz" bölümü: net, sahneli, anlaşılır, somut bir kriz anlat.
          * 2-4 paragraf olsun; neden şimdi patladı, kimler baskı yapıyor, oyuncu neyi kaybedebilir?
          * Metrikleri/numaraları metinde sayma (kullanıcı istemiyor). Metrikler sadece arka plan.
        - Sonra A/B seçenekleri üret:
          * Her seçenek: başlık + 3-6 maddelik "ne yaparsın" planı.
          * Seçenek metninde "bunu seçersen MRR artar/support düşer" gibi spoiler sonuç yazma.
          * Seçenekler benzer uzunlukta olsun.
        - Extreme moddaysan: olaylar daha absürt/kaotik/komik ama HALA anlaşılır ve kararın bedeli ağır.
        - Her ay yeni bir olay olsun; aynı krizi tekrar etme.

        Oyuncunun girişim fikri:
        {startup}

        Son seçimlerin özeti:
        {history}

        Arka plan metrikleri (metinde tekrar yazma, sadece bağlam): {metrics_ctx}
        {extra_tr}
        """
    ).strip()

def month_bundle_prompt(state: dict, month: int) -> str:
    ctx = build_system_context(state)
    mode = state["mode"]
    preset = state["case_preset"]
    # Gerçek vaka taglerini prompta ekleyelim
    tags = CASE_PRESETS.get(preset, CASE_PRESETS["Serbest (Rastgele)"]).get("tags", [])
    tag_line = ", ".join(tags) if tags else ""

    return textwrap.dedent(
        f"""
        {ctx}

        Şimdi Ay {month} içeriğini ÜRET ve SADECE aşağıdaki JSON'u döndür (başka metin ekleme):

        {{
          "month": {month},
          "analysis": "string",
          "crisis": "string",
          "options": {{
            "A": {{"title":"string","steps":["..."]}},
            "B": {{"title":"string","steps":["..."]}}
          }},
          "case_reference": "string (opsiyonel, 1 cümle; gerçek hayattan esin varsa imalı şekilde)"
        }}

        Ek koşullar:
        - analysis en az {MIN_LEN_ANALYSIS} karakter, crisis en az {MIN_LEN_CRISIS} karakter olsun.
        - steps maddeleri kısa ama net olsun (1 cümle).
        - {mode=} {tag_line=}
        """
    ).strip()

def outcome_prompt(state: dict, month: int, chosen: str, free_action: str = "") -> str:
    ctx = build_system_context(state)
    mode = state["mode"]
    turkey = (mode == "Türkiye Simülasyonu")

    extra_metrics = ""
    if turkey:
        extra_metrics = ', "dayi_factor_delta": -10'

    # Seçim başlığı ve adımlar
    bundle = state["current_bundle"]
    opt = bundle["options"][chosen]
    title = opt["title"]
    steps = opt["steps"]

    free_line = ""
    if free_action.strip():
        free_line = f'\nOyuncunun ekstra hamlesi (not): "{free_action.strip()}"\n'

    return textwrap.dedent(
        f"""
        {ctx}

        Ay {month} için oyuncu seçimi: {chosen}) {title}
        Plan maddeleri:
        {chr(10).join([f"- {s}" for s in steps])}
        {free_line}

        Şimdi bu seçimin AY SONU SONUÇLARINI yaz ve SADECE aşağıdaki JSON'u döndür (başka metin ekleme):

        {{
          "outcome": "string (en az {MIN_LEN_OUTCOME} karakter, 2-4 paragraf; somut sonuçlar + 1 tane sürpriz yan etki)",
          "deltas": {{
            "cash_delta": -50000,
            "mrr_delta": 1000,
            "reputation_delta": 5,
            "churn_pct_delta": -0.4,
            "support_load_delta": -3,
            "infra_load_delta": 2{extra_metrics}
          }},
          "headline": "string (kısa başlık)"
        }}

        Kurallar:
        - outcome metninde yine metrik/numara sayma; sadece etkileri hikaye içinde anlat.
        - Extreme moddaysan absürt detay ekle ama sonucu ciddiye al.
        - Kasa/MRR gibi rakamlar UI'da zaten var; metinde spoiler sayma.
        """
    ).strip()


# =========================
# Offline fallback content (no API)
# =========================

def offline_bundle(state: dict, month: int) -> dict:
    rnd = random.Random(state["seed"] + month * 101)
    idea = state.get("startup_idea", "bir uygulama")
    base = f"Ay {month}. {idea} etrafında işler karışıyor."
    analysis = (
        f"{base}\n\n"
        "Durum Analizi: Şu an en büyük risk 'netlik'. Kullanıcılar seni duyuyor ama aynı şeyi anlamıyor. "
        "Bu ay tek bir cümlelik değer önermesini kilitlemezsen ürün iyi olsa bile anlaşılmayacak.\n\n"
        "Ayrıca ekip içinde hız/kalite gerilimi büyüyor: bir taraf 'büyüme zamanı' diye tempo tutuyor, "
        "diğer taraf 'önce anlaşılır olalım' diye fren basıyor."
    )
    crisis = (
        "Kriz: Bir kurumsal müşteri demo sonrası 'Biz bunu kendi sürecimize uydururuz' deyip ürünü Excel'e çevirmeye kalkıyor. "
        "Aynı anda sosyal medyada bir paylaşım ürününü bambaşka bir amaçla konumlandırıyor ve destek hattın 'bu böyle mi çalışmalı?' "
        "sorularıyla doluyor. Bu ay bir karar vermezsen, herkes seni kendi hikayesine çevirip ürün algını paramparça edecek."
    )

    optA = {
        "title": "Tek cümle protokolü",
        "steps": [
            "Tek cümlelik değer önermesini yaz ve ekipte kilitle.",
            "Onboarding'i 3 ekrana indir; ilk dakikada tek başarı anı.",
            "Kurumsal istekleri 1 sayfalık 'kapsam notu'na bağla.",
            "SSS + hazır cevaplarla destek hattını düzene sok.",
        ],
    }
    optB = {
        "title": "Çift kulvar planı",
        "steps": [
            "Ürünü iki akışa ayır: hızlı kullanım / derin kullanım.",
            "Girişte tek soru sor ve akışı ona göre aç.",
            "Kurumsala şablon rapor paketini hazırla; özel istekleri sıraya al.",
            "Ürün anlatımını iki persona için netleştir.",
        ],
    }
    # küçük varyasyon
    if rnd.random() < 0.5:
        optA["steps"].append("Web sitesini tek vaat etrafında yeniden yaz.")
        optB["steps"].append("Toplulukta dolaşan yanlış kullanım örneklerini düzelt.")

    return {
        "month": month,
        "analysis": analysis,
        "crisis": crisis,
        "options": {"A": optA, "B": optB},
        "case_reference": "Offline demo (API yok).",
    }

def offline_outcome(state: dict, month: int, chosen: str) -> dict:
    rnd = random.Random(state["seed"] + month * 999 + (1 if chosen == "A" else 2))
    if chosen == "A":
        headline = "Netlik geldi, gürültü azaldı"
        outcome = (
            "Bir haftada herkesin diline aynı cümleyi yerleştirdin. Demo'larda farklı ekipler farklı şeyler istemeye çalışsa da "
            "sen aynı yere dönüp 'bizim ürün şunu yapar' diye çerçeveledin. Destek hattındaki sorular azaldı çünkü artık insanlar "
            "ne aldığını daha iyi anlıyor.\n\n"
            "Sürpriz: Netlik bazı yanlış kitleyi ürküttü; sosyalde 'eskisi kadar gizemli değil' diye tuhaf bir eleştiri çıktı ama "
            "bu gürültü seni aslında temizledi."
        )
        deltas = {
            "cash_delta": -45000,
            "mrr_delta": 1200,
            "reputation_delta": 6,
            "churn_pct_delta": -0.6,
            "support_load_delta": -6,
            "infra_load_delta": 1,
        }
    else:
        headline = "İki kulvar açıldı, kontrol zorlaştı"
        outcome = (
            "Hızlı kullanıcılar 'hemen iş görsün' akışını sevdi, derin kullanıcılar da kontrol modunda vakit geçirmeye başladı. "
            "Bu sayede ürün tek bir kalıba sıkışmadı; farklı segmentlerden geri bildirim topladın.\n\n"
            "Sürpriz: İki akış, ekip içinde iki ayrı ürün gibi algılandı ve roadmap toplantıları uzadı. Doğru yönetişim koymazsan "
            "bir sonraki ay 'iki ürün, iki kriz' yaşayabilirsin."
        )
        deltas = {
            "cash_delta": -60000,
            "mrr_delta": 900,
            "reputation_delta": 3,
            "churn_pct_delta": -0.2,
            "support_load_delta": -2,
            "infra_load_delta": 4,
        }

    # small randomness
    deltas["reputation_delta"] += rnd.choice([0, 1, -1])
    return {"headline": headline, "outcome": outcome, "deltas": deltas}


# =========================
# Game state
# =========================

def default_metrics(mode: str, starting_cash: int) -> dict:
    base = {
        "cash": int(starting_cash),
        "mrr": 0,
        "churn_pct": 5.0,
        "reputation": 50,
        "support_load": 20,
        "infra_load": 20,
        "dayi_factor": 35 if mode == "Türkiye Simülasyonu" else 0,
    }
    # Mod ayarı
    if mode == "Hard":
        base["churn_pct"] = 6.0
        base["support_load"] = 25
        base["infra_load"] = 25
        base["reputation"] = 45
    if mode == "Spartan":
        base["cash"] = int(starting_cash * 0.7)
        base["support_load"] = 30
        base["infra_load"] = 30
    if mode == "Extreme":
        base["churn_pct"] = 7.5
    return base

def init_state() -> dict:
    seed = int(time.time()) ^ random.randint(0, 999999)
    return {
        "seed": seed,
        "phase": "setup",  # setup | playing | finished
        "month": 1,
        "season_len": 12,
        "mode": "Normal",
        "case_preset": "Serbest (Rastgele)",
        "player_name": "İsimsiz Girişimci",
        "startup_idea": "",
        "metrics": default_metrics("Normal", 1_000_000),
        "monthly_spend": {"Salaries": 50000, "Servers": 6100, "Marketing": 5300},
        "messages": [],  # chat history: list[{role, content}]
        "choice_history": [],  # list[{month, choice, title}]
        "current_bundle": None,
        "bundle_posted": False,
        "gemini_model_used": None,
    }


# =========================
# Month generation & progression (no duplicates)
# =========================

def ensure_bundle(state: dict) -> None:
    """Generate month bundle if missing. Does NOT append to chat. (append is separate & guarded)"""
    if state["current_bundle"] is not None:
        return

    month = state["month"]

    # deterministic per month + preset
    preset_seed = CASE_PRESETS.get(state["case_preset"], CASE_PRESETS["Serbest (Rastgele)"])["seed"]
    base_seed = state["seed"]
    if preset_seed is not None:
        base_seed = stable_hash(f"{preset_seed}-{state['seed']}-{state.get('startup_idea','')}")
    random.seed(base_seed + month * 10007)

    client, err = st.session_state.get("_gemini_client"), st.session_state.get("_gemini_err")
    if client is None and err is None:
        client, err = init_gemini_client()
        st.session_state["_gemini_client"] = client
        st.session_state["_gemini_err"] = err

    if client is None:
        # Offline fallback
        state["current_bundle"] = offline_bundle(state, month)
        state["bundle_posted"] = False
        return

    # Build prompt, call model, parse JSON, retry once if too short
    prompt = month_bundle_prompt(state, month)
    temperature = MODES[state["mode"]]["temperature"]

    def _try(prompt_text: str) -> Optional[dict]:
        try:
            raw = gemini_generate(client, prompt_text, temperature=temperature, max_output_tokens=1700)
            data = safe_json_extract(raw)
            return data
        except Exception as e:
            # If NotFound, reset client for next time
            if gexc and isinstance(e, gexc.NotFound):
                st.session_state["_gemini_client"] = None
                st.session_state["_gemini_err"] = None
            raise

    try:
        data = _try(prompt)
        if not data:
            # second attempt: explicitly ask for JSON only
            data = _try(prompt + "\n\nSADECE JSON döndür. Açıklama ekleme.")
        if not data:
            raise RuntimeError("Model JSON üretmedi.")

        # validate & normalize
        data.setdefault("month", month)
        if "options" not in data or "A" not in data["options"] or "B" not in data["options"]:
            raise RuntimeError("JSON formatı beklenen yapıda değil (options/A/B).")

        # length guard
        if len(str(data.get("analysis", ""))) < MIN_LEN_ANALYSIS or len(str(data.get("crisis", ""))) < MIN_LEN_CRISIS:
            # retry once: force longer
            data2 = _try(prompt + f"\n\nNot: analysis>={MIN_LEN_ANALYSIS} ve crisis>={MIN_LEN_CRISIS} olacak şekilde daha uzun yaz.")
            if data2:
                data = data2

        state["current_bundle"] = data
        state["bundle_posted"] = False
        state["gemini_model_used"] = client.model_name

    except Exception as e:
        # UI'da kırmızı stack yerine anlaşılır hata
        state["current_bundle"] = offline_bundle(state, month)
        state["bundle_posted"] = False
        st.warning(f"Model çağrısı başarısız oldu; offline moda düştüm. (Hata: {e})")

def post_bundle_to_chat(state: dict) -> None:
    """Append analysis + crisis once per month (guarded by bundle_posted)."""
    if state["current_bundle"] is None or state["bundle_posted"]:
        return

    b = state["current_bundle"]
    m = b.get("month", state["month"])
    analysis = str(b.get("analysis", "")).strip()
    crisis = str(b.get("crisis", "")).strip()
    case_ref = str(b.get("case_reference", "")).strip()

    # Chat messages (assistant)
    state["messages"].append({"role": "assistant", "content": f"🧠 **Durum Analizi (Ay {m})**\n\n{analysis}"})
    state["messages"].append({"role": "assistant", "content": f"⚠️ **Kriz**\n\n{crisis}"})
    if case_ref:
        state["messages"].append({"role": "assistant", "content": f"🗂️ _Vaka notu:_ {case_ref}"})

    state["messages"].append(
        {"role": "assistant", "content": "👉 **Şimdi seçim zamanı. A mı B mi?** (İstersen aşağıya kısa bir not da ekleyebilirsin.)"}
    )
    state["bundle_posted"] = True

def apply_deltas(state: dict, deltas: dict) -> None:
    m = state["metrics"]

    m["cash"] = int(m["cash"] + int(deltas.get("cash_delta", 0)))
    m["mrr"] = int(max(0, m["mrr"] + int(deltas.get("mrr_delta", 0))))

    m["reputation"] = int(clamp(m["reputation"] + int(deltas.get("reputation_delta", 0)), *CLAMP["reputation"]))
    m["support_load"] = int(clamp(m["support_load"] + int(deltas.get("support_load_delta", 0)), *CLAMP["support_load"]))
    m["infra_load"] = int(clamp(m["infra_load"] + int(deltas.get("infra_load_delta", 0)), *CLAMP["infra_load"]))
    m["churn_pct"] = float(clamp(m["churn_pct"] + float(deltas.get("churn_pct_delta", 0.0)), *CLAMP["churn_pct"]))

    if state["mode"] == "Türkiye Simülasyonu":
        m["dayi_factor"] = int(clamp(m["dayi_factor"] + int(deltas.get("dayi_factor_delta", 0)), *CLAMP["dayi_factor"]))

    # burn (aylık gider)
    burn = sum(int(v) for v in state["monthly_spend"].values())
    m["cash"] = int(m["cash"] - burn)

def resolve_choice(state: dict, chosen: str, free_action: str = "") -> None:
    bundle = state["current_bundle"]
    month = state["month"]

    title = bundle["options"][chosen]["title"]
    state["choice_history"].append({"month": month, "choice": chosen, "title": title})

    # user message
    user_line = f"{chosen}) {title}"
    if free_action.strip():
        user_line += f"\n\n_Not:_ {free_action.strip()}"
    state["messages"].append({"role": "user", "content": user_line})

    # outcome via model
    client = st.session_state.get("_gemini_client")
    err = st.session_state.get("_gemini_err")

    if client is None:
        out = offline_outcome(state, month, chosen)
        state["messages"].append({"role": "assistant", "content": f"✅ **{out['headline']}**\n\n{out['outcome']}"})
        apply_deltas(state, out["deltas"])
    else:
        temperature = MODES[state["mode"]]["temperature"]
        prompt = outcome_prompt(state, month, chosen, free_action=free_action)

        def _try(prompt_text: str) -> Optional[dict]:
            raw = gemini_generate(client, prompt_text, temperature=temperature, max_output_tokens=1400)
            return safe_json_extract(raw)

        try:
            data = _try(prompt)
            if not data:
                data = _try(prompt + "\n\nSADECE JSON döndür.")
            if not data:
                raise RuntimeError("Model outcome JSON üretmedi.")

            if len(str(data.get("outcome", ""))) < MIN_LEN_OUTCOME:
                data2 = _try(prompt + f"\n\nNot: outcome>={MIN_LEN_OUTCOME} olacak şekilde daha uzun yaz.")
                if data2:
                    data = data2

            headline = str(data.get("headline", "Seçim işlendi")).strip()
            outcome_txt = str(data.get("outcome", "")).strip()
            deltas = data.get("deltas", {}) if isinstance(data.get("deltas"), dict) else {}

            state["messages"].append({"role": "assistant", "content": f"✅ **{headline}**\n\n{outcome_txt}"})
            apply_deltas(state, deltas)

        except Exception as e:
            # NotFound gibi durumlarda kullanıcıya çözüm yolu göster
            if gexc and isinstance(e, gexc.NotFound):
                st.error(
                    "Gemini model NotFound hatası: Model adı/erişimi yanlış görünüyor.\n\n"
                    "Çözüm: Streamlit Secrets içine `GEMINI_MODEL=\"gemini-1.5-flash\"` (veya pro) ekle, "
                    "ya da ortam değişkeni olarak ayarla. Sonra app'i yeniden başlat."
                )
                # client'ı sıfırla ki fallback denesin
                st.session_state["_gemini_client"] = None
                st.session_state["_gemini_err"] = None

            state["messages"].append(
                {"role": "assistant", "content": f"⚠️ Model tarafında hata oldu; offline sonuç ürettim. (Hata: {e})"}
            )
            out = offline_outcome(state, month, chosen)
            state["messages"].append({"role": "assistant", "content": f"✅ **{out['headline']}**\n\n{out['outcome']}"})
            apply_deltas(state, out["deltas"])

    # next month
    state["month"] += 1
    state["current_bundle"] = None
    state["bundle_posted"] = False

    if state["month"] > state["season_len"]:
        state["phase"] = "finished"
        state["messages"].append({"role": "assistant", "content": "🏁 Sezon bitti. İstersen oyunu sıfırlayıp yeni vaka seçebilirsin."})


# =========================
# UI
# =========================

def inject_css() -> None:
    st.markdown(
        """
        <style>
          .big-title { font-size: 46px; font-weight: 800; margin: 0 0 6px 0; }
          .subtitle { opacity: .75; margin-bottom: 16px; }

          /* Choice cards */
          .choice-card {
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 16px;
            padding: 18px 18px 14px 18px;
            background: rgba(255,255,255,0.02);
            min-height: 260px;
          }
          .choice-title { font-size: 22px; font-weight: 800; margin-bottom: 10px; }
          .choice-steps { opacity: .9; }
          .choice-steps li { margin-bottom: 6px; }

          /* Sidebar small labels */
          .metric-label { opacity: .7; font-size: 12px; }
          .metric-value { font-size: 26px; font-weight: 800; margin-top: -4px; }
        </style>
        """,
        unsafe_allow_html=True,
    )

def sidebar(state: dict) -> None:
    with st.sidebar:
        st.markdown(f"### {state['player_name']}")
        mode = st.selectbox("Mod", list(MODES.keys()), index=list(MODES.keys()).index(state["mode"]))
        state["mode"] = mode

        st.caption(MODES[mode]["desc"])

        preset = st.selectbox("Vaka sezonu (opsiyonel)", list(CASE_PRESETS.keys()), index=list(CASE_PRESETS.keys()).index(state["case_preset"]))
        state["case_preset"] = preset
        st.caption(CASE_PRESETS[preset]["brief"])

        season_len = st.slider("Sezon uzunluğu (ay)", min_value=6, max_value=24, value=int(state["season_len"]), step=1)
        state["season_len"] = season_len

        st.caption(f"Ay: {min(state['month'], state['season_len'])}/{state['season_len']}")

        starting_cash = st.slider("Başlangıç kasası", min_value=100_000, max_value=2_000_000, value=int(state["metrics"]["cash"]) if state["phase"] == "setup" else int(state["metrics"]["cash"]), step=50_000)
        if state["phase"] == "setup":
            # setup aşamasında başlangıç kasası metriklerini ayarlasın
            state["metrics"] = default_metrics(state["mode"], starting_cash)

        st.markdown("---")
        st.markdown("### Finansal Durum")

        m = state["metrics"]
        st.markdown(f"<div class='metric-label'>Kasa</div><div class='metric-value'>{money_fmt(int(m['cash']))}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-label'>MRR</div><div class='metric-value'>{money_fmt(int(m['mrr']))}</div>", unsafe_allow_html=True)

        with st.expander("Aylık Gider Detayı"):
            sp = state["monthly_spend"]
            st.write(f"• Maaşlar: {money_fmt(int(sp['Salaries']))}")
            st.write(f"• Sunucu: {money_fmt(int(sp['Servers']))}")
            st.write(f"• Pazarlama: {money_fmt(int(sp['Marketing']))}")
            st.write(f"**TOPLAM:** {money_fmt(int(sum(sp.values())))}")

        st.markdown("---")
        st.markdown(f"**İtibar:** {m['reputation']}/100")
        st.markdown(f"**Destek yükü:** {m['support_load']}/100")
        st.markdown(f"**Altyapı yükü:** {m['infra_load']}/100")
        st.markdown(f"**Kayıp oranı:** {pct_fmt(m['churn_pct'])}")

        if state["mode"] == "Türkiye Simülasyonu":
            st.markdown(f"**Dayı faktörü:** {m['dayi_factor']}/100")

        st.markdown("---")
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("Oyunu sıfırla", use_container_width=True):
                st.session_state["game_state"] = init_state()
                st.rerun()
        with col_b:
            if st.button("Sohbeti temizle", use_container_width=True):
                state["messages"] = []
                st.rerun()


def top_bar(state: dict) -> None:
    left, right = st.columns([8, 4], vertical_alignment="top")
    with left:
        st.markdown(f"<div class='big-title'>{APP_TITLE}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='subtitle'>{APP_SUBTITLE}</div>", unsafe_allow_html=True)
    with right:
        with st.expander("🛠️ Karakterini ve ayarlarını özelleştir", expanded=False):
            state["player_name"] = st.text_input("Karakter adı", value=state["player_name"])
            # Bu alanlar oyun mekaniği değil; rol hissi için
            st.text_input("Rol (opsiyonel)", value=st.session_state.get("role", "Kurucu"))
            st.text_input("Ekip stili (opsiyonel)", value=st.session_state.get("team_style", "Küçük ama hızlı"))

def render_chat(state: dict) -> None:
    for msg in state["messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

def render_setup(state: dict) -> None:
    st.info("Oyuna başlamak için girişim fikrini yaz. Sonra Ay 1 başlar (Durum Analizi → Kriz → A/B).")
    idea = st.text_area("Girişim fikrin ne?", value=state.get("startup_idea", ""), height=120, placeholder="Örn: Anlık çeviri yapan bir uygulama...")
    state["startup_idea"] = idea

    # API durumu
    client = st.session_state.get("_gemini_client")
    err = st.session_state.get("_gemini_err")
    if client is None and err is None:
        client, err = init_gemini_client()
        st.session_state["_gemini_client"] = client
        st.session_state["_gemini_err"] = err

    if client:
        st.success(f"✅ Gemini anahtarı görüldü. Model çağrıları çalışmalı. (Model: {client.model_name})")
    else:
        st.warning(f"⚠️ Gemini kapalı: {err}\n\nİstersen offline demo ile devam edebilirsin.")

    if st.button("🚀 Oyunu Başlat", type="primary", use_container_width=True, disabled=not idea.strip()):
        # reset and start
        seed = state["seed"]
        mode = state["mode"]
        preset = state["case_preset"]
        season_len = state["season_len"]
        cash = state["metrics"]["cash"]

        st.session_state["game_state"] = init_state()
        st.session_state["game_state"].update({
            "seed": seed,
            "mode": mode,
            "case_preset": preset,
            "season_len": season_len,
            "player_name": state["player_name"],
            "startup_idea": idea,
            "metrics": default_metrics(mode, cash),
            "phase": "playing",
            "month": 1,
        })
        st.rerun()

def render_choice_ui(state: dict) -> None:
    bundle = state["current_bundle"]
    if not bundle:
        return

    opts = bundle["options"]
    a = opts["A"]
    b = opts["B"]

    # Optional free note
    free_action = st.text_input("İstersen kısa bir not yaz (opsiyonel).", key=f"free_note_{state['month']}_{state['seed']}", placeholder="Örn: 'Kurumsala net bir sınır çizeceğim'")

    col1, col2 = st.columns(2, gap="large")

    with col1:
        st.markdown("<div class='choice-card'>", unsafe_allow_html=True)
        st.markdown(f"<div class='choice-title'>A) {a['title']}</div>", unsafe_allow_html=True)

        steps = a.get("steps", [])
        if isinstance(steps, list) and steps:
            st.markdown("**Plan:**")
            st.markdown("\n".join([f"- {s}" for s in steps]))
        st.markdown("</div>", unsafe_allow_html=True)

        if st.button("A seç", key=f"pickA_{state['month']}", use_container_width=True):
            resolve_choice(state, "A", free_action=free_action)
            st.rerun()

    with col2:
        st.markdown("<div class='choice-card'>", unsafe_allow_html=True)
        st.markdown(f"<div class='choice-title'>B) {b['title']}</div>", unsafe_allow_html=True)

        steps = b.get("steps", [])
        if isinstance(steps, list) and steps:
            st.markdown("**Plan:**")
            st.markdown("\n".join([f"- {s}" for s in steps]))
        st.markdown("</div>", unsafe_allow_html=True)

        if st.button("B seç", key=f"pickB_{state['month']}", use_container_width=True):
            resolve_choice(state, "B", free_action=free_action)
            st.rerun()

def render_playing(state: dict) -> None:
    ensure_bundle(state)
    post_bundle_to_chat(state)

    render_chat(state)

    # Choice UI (kartlar)
    st.markdown("---")
    render_choice_ui(state)

def render_finished(state: dict) -> None:
    render_chat(state)
    st.success("Sezon tamamlandı. Yeni bir vaka için sol alttan 'Oyunu sıfırla' diyebilirsin.")


# =========================
# Main
# =========================

def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    inject_css()

    if "game_state" not in st.session_state:
        st.session_state["game_state"] = init_state()

    state = st.session_state["game_state"]

    sidebar(state)
    top_bar(state)

    # User: API anahtarlarını ekranda paylaştıysa güvenlik uyarısı (metinde anahtarı tekrar etmeyelim)
    st.caption("Not: Eğer API anahtarını yanlışlıkla paylaştıysan, güvenlik için hemen yenilemen iyi olur.")

    if state["phase"] == "setup":
        render_setup(state)
    elif state["phase"] == "playing":
        render_playing(state)
    else:
        render_finished(state)


if __name__ == "__main__":
    main()
