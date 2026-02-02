# app.py
# Startup Survivor RPG — Streamlit single-file app

from __future__ import annotations

import json
import os
import random
import re
from dataclasses import dataclass
from datetime import datetime
from html import escape as html_escape
from typing import Any, List, Tuple

import streamlit as st


# =========================
# Config / Theme
# =========================

APP_TITLE = "Startup Survivor RPG"
APP_SUBTITLE = "Sohbet akışı korunur. Ay 1'den başlar. Durum Analizi → Kriz → A/B seçimi."
APP_VERSION = "2.1.0"

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

CSS = """
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2rem;}
section[data-testid="stSidebar"] .block-container {padding-top: 1.0rem;}
.card {
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 16px;
  padding: 14px 16px;
  background: rgba(255,255,255,0.03);
}
.card h3 {margin: 0 0 .4rem 0;}
.muted {opacity: .75;}
hr.soft {border: none; border-top: 1px solid rgba(255,255,255,0.08); margin: 1rem 0;}
.choice {
  border: 1px solid rgba(255,255,255,0.10);
  border-radius: 18px;
  padding: 18px 18px 14px 18px;
  background: rgba(255,255,255,0.02);
  min-height: 260px;
}
.choice .title {font-size: 1.45rem; font-weight: 800; margin-bottom: .45rem;}
.choice ul {margin-top: .25rem; margin-bottom: .75rem;}
.choice li {margin-bottom: .25rem;}
div.stButton > button {
  border-radius: 14px;
  padding: .55rem 1.1rem;
  font-weight: 700;
}
.smallcaps {font-variant: small-caps; letter-spacing: .02em;}
[data-testid="stChatMessage"] {border-radius: 18px;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# =========================
# Helpers
# =========================

def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

def money(v: float) -> str:
    try:
        s = f"{int(round(v)):,}".replace(",", ".")
        return f"{s} ₺"
    except Exception:
        return f"{v} ₺"

def pct(v: float) -> str:
    return f"%{v*100:.1f}"

def now_id() -> str:
    return datetime.utcnow().strftime("%Y%m%d%H%M%S")

def md_escape_li(items: List[str]) -> str:
    lis = "".join(f"<li>{html_escape(str(s))}</li>" for s in items)
    return f"<ul class='choice-steps'>{lis}</ul>"

def ensure_list(x: Any) -> List[Any]:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]

def try_parse_json(s: str) -> dict | None:
    if not s:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.DOTALL | re.IGNORECASE)
    if fence:
        s2 = fence.group(1).strip()
        try:
            return json.loads(s2)
        except Exception:
            pass
    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        blob = s[start:end+1]
        try:
            return json.loads(blob)
        except Exception:
            blob2 = re.sub(r",(\s*[}\]])", r"\1", blob)
            try:
                return json.loads(blob2)
            except Exception:
                return None
    return None


# =========================
# Real-world inspired cases (safe, simplified)
# =========================

@dataclass
class CaseSeason:
    key: str
    title: str
    blurb: str
    seed: int
    inspired_by: str

CASE_LIBRARY: List[CaseSeason] = [
    CaseSeason("free", "Serbest (Rastgele)", "Kendi fikrine göre rastgele olaylar. Her ay farklı kriz.", 1, ""),
    CaseSeason("airbnb_2008", "Vaka: Talep Çöküşü (2008)", "Bütçeler kısılır, talep düşer; hayatta kalma ve yeniden konumlama.", 2008, "Airbnb'nin 2008 dönemi (genel esin)"),
    CaseSeason("wework_2019", "Vaka: Aşırı Büyüme & Güven Krizi (2019)", "Hız, PR, yatırımcı güveni ve 'ne satıyoruz?' sorusu aynı anda patlar.", 2019, "WeWork 2019 tartışmaları (genel esin)"),
    CaseSeason("theranos_style", "Vaka: Vaat-Gerçeklik Uçurumu", "Ürün gerçeği yetişmiyor; beklenti yönetimi, doğruluk, güven.", 31415, "Sağlık/medtech skandalları (genel esin)"),
    CaseSeason("ftx_2022_style", "Vaka: Güven, Şeffaflık, Likidite (2022)", "Güven bir gecede buharlaşır; iletişim ve risk yönetimi sınavı.", 2022, "Büyük çöküşler ve güven krizleri (genel esin)"),
]


# =========================
# Modes / Difficulty
# =========================

MODES = {
    "Normal": {
        "desc": "Dengeli. İyi kararlar ödüllenir, kötü kararlar acıtır.",
        "temp": 0.8,
        "swing": 1.0,
        "tone": "gerçekçi, net, dramatik ama abartısız",
    },
    "Extreme": {
        "desc": "Kaos ve absürt. Paylaşmalık olaylar. Sonuç metriklere çarpar.",
        "temp": 1.0,
        "swing": 1.45,
        "tone": "çok yüksek gerilim, keskin mizah, şok edici ama anlaşılır",
    },
    "Hard": {
        "desc": "Zor. Hata affetmez. Kısa vadeli çözümler uzun vadede geri teper.",
        "temp": 0.9,
        "swing": 1.25,
        "tone": "sert, soğukkanlı, acımasız derecede gerçekçi",
    },
}


# =========================
# Gemini wrapper (new SDK + legacy fallback)
# =========================

@dataclass
class LLMStatus:
    ok: bool
    backend: str  # "genai" | "legacy" | "none"
    model: str
    note: str

class GeminiLLM:
    def __init__(self, api_keys: List[str]):
        self.api_keys = [k.strip() for k in api_keys if str(k).strip()]
        self.backend = "none"
        self.model_in_use = ""
        self.last_error = ""
        self._client = None
        self._legacy = None
        self._init_backend()

    @staticmethod
    def from_env_or_secrets() -> "GeminiLLM":
        keys: List[str] = []

        def pull(name: str) -> Any:
            if name in st.secrets:
                return st.secrets.get(name)
            return os.getenv(name)

        raw = pull("GEMINI_API_KEY")
        if raw is None:
            raw = pull("GOOGLE_API_KEY")

        if isinstance(raw, (list, tuple)):
            keys = [str(x) for x in raw]
        elif isinstance(raw, str) and raw.strip():
            if "," in raw:
                keys = [x.strip() for x in raw.split(",") if x.strip()]
            else:
                keys = [raw.strip()]

        return GeminiLLM(keys)

    def _init_backend(self) -> None:
        if not self.api_keys:
            self.backend = "none"
            self.last_error = "API anahtarı bulunamadı."
            return

        try:
            from google import genai as genai_sdk  # google-genai
            self._client = genai_sdk.Client(api_key=self.api_keys[0])
            self.backend = "genai"
            return
        except Exception as e:
            self.last_error = f"google-genai yüklenemedi: {type(e).__name__}: {e}"

        try:
            import google.generativeai as genai_legacy  # google-generativeai
            genai_legacy.configure(api_key=self.api_keys[0])
            self._legacy = genai_legacy
            self.backend = "legacy"
            return
        except Exception as e:
            self.last_error = f"google-generativeai yüklenemedi: {type(e).__name__}: {e}"
            self.backend = "none"

    def status(self) -> LLMStatus:
        if self.backend == "none":
            return LLMStatus(False, "none", "", self.last_error or "Gemini kapalı.")
        return LLMStatus(True, self.backend, self.model_in_use or "", self.last_error or "")

    def _rotate_key(self) -> None:
        if len(self.api_keys) <= 1:
            return
        self.api_keys = self.api_keys[1:] + self.api_keys[:1]
        self._init_backend()

    def generate_text(self, prompt: str, temperature: float, max_output_tokens: int) -> str:
        candidates = [
            "gemini-3-flash-preview",
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
        ]

        for _ in range(max(1, len(self.api_keys))):
            if self.backend == "genai":
                try:
                    for m in candidates:
                        try:
                            resp = self._client.models.generate_content(  # type: ignore
                                model=m,
                                contents=prompt,
                                config={
                                    "temperature": temperature,
                                    "max_output_tokens": max_output_tokens,
                                },
                            )
                            txt = getattr(resp, "text", None)
                            if txt:
                                self.model_in_use = m
                                self.last_error = ""
                                return str(txt)
                        except Exception as e:
                            self.last_error = f"{type(e).__name__}: {e}"
                            continue
                except Exception as e:
                    self.last_error = f"{type(e).__name__}: {e}"

            if self.backend == "legacy":
                try:
                    for m in candidates:
                        try:
                            model = self._legacy.GenerativeModel(m)  # type: ignore
                            resp = model.generate_content(
                                prompt,
                                generation_config={
                                    "temperature": temperature,
                                    "max_output_tokens": max_output_tokens,
                                },
                            )
                            txt = getattr(resp, "text", None)
                            if txt:
                                self.model_in_use = m
                                self.last_error = ""
                                return str(txt)
                        except Exception as e:
                            self.last_error = f"{type(e).__name__}: {e}"
                            continue
                except Exception as e:
                    self.last_error = f"{type(e).__name__}: {e}"

            self._rotate_key()

        raise RuntimeError(self.last_error or "Gemini yanıt veremedi.")


# =========================
# Offline generator (fallback)
# =========================

def get_case(case_key: str) -> CaseSeason:
    for c in CASE_LIBRARY:
        if c.key == case_key:
            return c
    return CASE_LIBRARY[0]

def offline_month_bundle(seed: int, mode: str, month: int, idea: str, history: List[dict], case: CaseSeason) -> dict:
    rng = random.Random(seed + month * 97 + (123 if mode == "Extreme" else 0))

    idea = (idea or "").strip()
    if not idea:
        idea = "Henüz fikrini netleştirmedin; herkes farklı bir şey anlıyor."

    if month == 1:
        durum = (
            f"İlk ayın: fikrin büyük ama dağınık.\n\n"
            f"**Ürün fikri:** {idea}\n\n"
            "İlk risk, 'anlaşılma' sorunu. İnsanlar seni duyuyor ama aynı şeyi hayal etmiyor. "
            "Bu yüzden ekip bir yandan özellik eklemek isterken, diğer yandan kullanıcı ilk 60 saniyede kayboluyor.\n\n"
            "Bu ayın görevi: tek bir sahneye kilitlenmek mi, yoksa iki akışlı bir yaklaşım mı kurmak?"
        )
    else:
        last = history[-1] if history else {}
        last_choice = last.get("choice", "?")
        last_title = last.get("choice_title", "bir karar")
        durum = (
            f"Ay {month}: geçen ay **{last_choice}** seçtin (*{last_title}*).\n\n"
            "Şimdi ikinci dalga geliyor: seçimlerinin yan etkileri görünmeye başladı. "
            "Kimi kullanıcı hız istiyor, kimi kontrol; ekip ise 'hepsini yapalım' ile 'odak' arasında bölünüyor.\n\n"
            "Bu ay Durum Analizi, bir önceki kararın **neden işe yaradığı / yaramadığı** üzerine kurulu: "
            "Süreçler mi büyüdü, yoksa hikâye mi netleşti?"
        )

    kriz_hooks = [
        "Bir rakip onboarding ekranını 'challenge' yapıyor; herkes 3 saniyede çıkıyor.",
        "Kurumsal bir müşteri 'biz bunu kendi sürecimize uydururuz' diyerek ürünü Excel'e çevirmeye kalkıyor.",
        "Topluluk ürünü bambaşka bir amaçla kullanıyor; sosyal medyada yanlış bir hikâye yayılıyor.",
        "Bir influencer ürünü yanlış anlatıyor; support hattı 'bu böyle mi çalışmalı?' sorularıyla doluyor.",
        "Sunucu maliyetleri patlıyor; aynı anda ilk büyük müşteri SLA istiyor.",
    ]
    hook = rng.choice(kriz_hooks)

    kriz = (
        f"**Kriz:** {hook}\n\n"
        "Sorun ürünün 'kötü' olması değil; ürünün **ne olduğuna dair hikâyenin kontrolünü** kaybetmen. "
        "Herkes seni kendi ihtiyacına çevirirken, sen tek bir cevap veremezsen destek ve altyapı yükü üst üste binmeye başlar.\n\n"
        "Bu ay bir karar vermelisin: ya tek bir vaade kilitlenip gürültüyü susturacaksın, "
        "ya da kaosu yönetecek bir yapı kuracaksın."
    )

    a_title = rng.choice(["Tek vaat protokolü", "Tek sahne kuralı", "Tek cümle manifestosu"])
    b_title = rng.choice(["Çift kulvar planı", "İki akış stratejisi", "Filtreli onboarding"])

    a_steps = [
        "Tek cümlelik değer önerisini yaz ve ekiple kilitle.",
        "Onboarding'i 3 ekrana indir: giriş → tek görev → tek çıktı.",
        "SSS'yi tek sayfa yap; en sık 6 soruya hazır cevap ekle.",
        "Kurumsal talepleri 1 sayfalık kapsam notuna bağla; 'şimdilik hayır' cümlesini standartlaştır.",
        "Destek taleplerini tek formda topla; etiketle ve haftalık triage yap.",
    ]
    b_steps = [
        "Ürünü iki akışa ayır: hızlı kullanım / derin kullanım.",
        "İlk ekranda tek soru sor: 'Hız mı, kontrol mü?' ve akışı ona göre aç.",
        "Kurumsal için 'şablon rapor' paketi çıkar; özel istekleri sıraya al.",
        "Yanlış beklentiyi azaltmak için ödeme/deneme ekranına net sınırlar ekle.",
        "Support'u kategori bazlı ayır; 'yanlış kullanım' ile 'bug'ı ayrı kuyruğa al.",
    ]

    if mode == "Extreme":
        durum += "\n\n*(Extreme ton)*: Her cümle bir PR bombası gibi. Yanlış bir kelime, yanlış bir kitleyi çağırır."
        kriz += "\n\n*(Extreme ton)*: Bugün 'küçük bir yanlış anlaşılma', yarın şirketin yeni ürünü olur: **Excel eklentisi**."

    note = ""
    if case.key != "free":
        note = f"Vaka notu: Bu sezon **{case.title}** temasından esinlenir. ({case.inspired_by})"

    return {
        "durum_analizi": durum,
        "kriz": kriz,
        "A": {"title": a_title, "steps": a_steps},
        "B": {"title": b_title, "steps": b_steps},
        "note": note,
    }


# =========================
# Game state
# =========================

def default_stats(start_cash: int) -> dict:
    return {
        "cash": float(start_cash),
        "mrr": 0.0,
        "reputation": 50.0,
        "support_load": 20.0,
        "infra_load": 20.0,
        "churn": 0.05,
    }

DEFAULT_EXPENSES = {"Salarlar": 50_000, "Sunucu": 6_100, "Pazarlama": 5_300}

def init_state() -> None:
    ss = st.session_state
    ss.setdefault("run_id", now_id())
    ss.setdefault("started", False)
    ss.setdefault("month", 1)
    ss.setdefault("season_length", 12)
    ss.setdefault("mode", "Normal")
    ss.setdefault("case_key", "free")
    ss.setdefault("founder_name", "İsimsiz Girişimci")
    ss.setdefault("startup_idea", "")
    ss.setdefault("start_cash", 1_000_000)
    ss.setdefault("expenses", DEFAULT_EXPENSES.copy())
    ss.setdefault("stats", default_stats(ss["start_cash"]))
    ss.setdefault("history", [])
    ss.setdefault("months", {})
    ss.setdefault("chat", [])
    ss.setdefault("llm_disabled", False)
    ss.setdefault("llm_last_error", "")

def reset_game(keep_settings: bool = True) -> None:
    ss = st.session_state
    keep = {}
    if keep_settings:
        for k in ["season_length", "mode", "case_key", "founder_name", "startup_idea", "start_cash", "expenses"]:
            keep[k] = ss.get(k)
    ss.clear()
    init_state()
    for k, v in keep.items():
        ss[k] = v
    ss["stats"] = default_stats(ss["start_cash"])
    ss["chat"] = []
    ss["history"] = []
    ss["months"] = {}
    ss["month"] = 1
    ss["started"] = False
    ss["llm_disabled"] = False
    ss["llm_last_error"] = ""


# =========================
# Prompting (LLM)
# =========================

def build_prompt(month: int, mode: str, idea: str, history: List[dict], case: CaseSeason, stats: dict) -> str:
    tone = MODES.get(mode, MODES["Normal"])["tone"]
    hist_lines = [
        f"- Ay {h.get('month')}: {h.get('choice')} / {h.get('choice_title')} | not: {h.get('note','-')}"
        for h in history[-4:]
    ]
    hist = "\n".join(hist_lines) if hist_lines else "(henüz seçim yok)"

    context_metrics = (
        f"METRİKLER (sadece arka plan): cash={int(stats['cash'])}, mrr={int(stats['mrr'])}, "
        f"itibar={int(stats['reputation'])}/100, support={int(stats['support_load'])}/100, "
        f"altyapı={int(stats['infra_load'])}/100, kayıp_oranı={stats['churn']:.3f}."
    )

    case_note = ""
    if case.key != "free":
        case_note = (
            f"Sezon teması: {case.title}. Bu içerik '{case.inspired_by}' temasından esinlenebilir ama "
            "olaylar oyunlaştırılmış ve basitleştirilmiş olmalı. "
            "Şirket adı uydur (gerçek isim kullanma)."
        )

    return f"""
Sen bir startup RPG yazarı ve ürün stratejisti gibi yazıyorsun. Dil: Türkçe. Ton: {tone}.
Amaç: oyuncuya "Durum Analizi" ve "Kriz" anlat, sonra iki seçenek sun (A/B). Seçeneklerde SONUÇ SPOILER'I YOK.
Yani "bunu seçersen support artar" gibi şeyler yazma; sadece uygulanacak planı yaz.

{case_note}

Oyuncu adı: {st.session_state.get('founder_name','Girişimci')}
Oyuncunun startup fikri (Ay 1 için ana kaynak): {idea or "(boş)"}

Geçmiş seçim özeti (Ay 2+ için analizde kullan):
{hist}

{context_metrics}

Şimdi Ay {month} için aşağıdaki JSON'u üret. ÇIKTI SADECE JSON olsun.

Şema:
{{
  "durum_analizi": "2-4 paragraf. Ay 1 ise fikri detaylı analiz et. Ay 2+ ise son seçimlerin etkilerini analiz et.",
  "kriz": "2-4 paragraf. Net ve somut kriz sahnesi. Rakam/metrik yazma.",
  "A": {{"title": "kısa başlık", "steps": ["4-6 maddelik plan", "..."]}},
  "B": {{"title": "kısa başlık", "steps": ["4-6 maddelik plan", "..."]}},
  "note": "opsiyonel not"
}}

Kurallar:
- Seçenek planları birbirine yakın kalitede olsun.
- Tek bir ayda tek sahne/tek çatışma.
- 'kasa, MRR' gibi metrik isimlerini metin içine koyma.
""".strip()

def generate_month_bundle(llm: GeminiLLM, month: int) -> Tuple[dict, str]:
    ss = st.session_state
    mode = ss["mode"]
    idea = ss["startup_idea"]
    case = get_case(ss["case_key"])
    stats = ss["stats"]
    history = ss["history"]

    if ss.get("llm_disabled"):
        return offline_month_bundle(case.seed, mode, month, idea, history, case), "offline"

    prompt = build_prompt(month, mode, idea, history, case, stats)
    temperature = MODES.get(mode, MODES["Normal"])["temp"]
    try:
        raw = llm.generate_text(prompt, temperature=temperature, max_output_tokens=1600)
        data = try_parse_json(raw)
        if not data:
            raise ValueError("JSON parse edilemedi.")

        def norm_steps(x: Any) -> List[str]:
            out = [str(s).strip() for s in ensure_list(x) if s is not None]
            out = [s for s in out if s][:6]
            return out

        bundle = {
            "durum_analizi": str(data.get("durum_analizi", "")).strip(),
            "kriz": str(data.get("kriz", "")).strip(),
            "A": {
                "title": str((data.get("A") or {}).get("title", "Seçenek A")).strip(),
                "steps": norm_steps((data.get("A") or {}).get("steps", [])),
            },
            "B": {
                "title": str((data.get("B") or {}).get("title", "Seçenek B")).strip(),
                "steps": norm_steps((data.get("B") or {}).get("steps", [])),
            },
            "note": str(data.get("note", "") or "").strip(),
        }

        if len(bundle["A"]["steps"]) < 4 or len(bundle["B"]["steps"]) < 4:
            raise ValueError("Seçenek adımları çok kısa geldi.")

        if len(bundle["durum_analizi"]) < 250 or len(bundle["kriz"]) < 250:
            off = offline_month_bundle(case.seed, mode, month, idea, history, case)
            if len(bundle["durum_analizi"]) < 250:
                bundle["durum_analizi"] = off["durum_analizi"] + "\n\n---\n\n" + bundle["durum_analizi"]
            if len(bundle["kriz"]) < 250:
                bundle["kriz"] = off["kriz"] + "\n\n---\n\n" + bundle["kriz"]

        return bundle, "gemini"
    except Exception as e:
        ss["llm_last_error"] = f"{type(e).__name__}: {e}"
        ss["llm_disabled"] = True
        return offline_month_bundle(case.seed, mode, month, idea, history, case), "offline"


# =========================
# Game mechanics
# =========================

def apply_choice_effects(choice: str, month: int) -> dict:
    ss = st.session_state
    mode = ss["mode"]
    swing = MODES.get(mode, MODES["Normal"])["swing"]
    case = get_case(ss["case_key"])

    seed = hash((ss["run_id"], case.seed, month, choice)) & 0xFFFFFFFF
    rng = random.Random(seed)

    d = {
        "cash": rng.uniform(-120_000, 180_000) * swing,
        "mrr": rng.uniform(-500, 3_500) * swing,
        "reputation": rng.uniform(-12, 14) * swing,
        "support_load": rng.uniform(-10, 18) * swing,
        "infra_load": rng.uniform(-10, 18) * swing,
        "churn": rng.uniform(-0.020, 0.030) * swing,
    }

    if choice == "A":
        d["reputation"] += rng.uniform(2, 10) * swing
        d["support_load"] -= rng.uniform(2, 8) * swing
        d["infra_load"] -= rng.uniform(0, 6) * swing
        d["cash"] -= rng.uniform(20_000, 80_000) * swing
        d["mrr"] += rng.uniform(-200, 1400) * swing
    else:
        d["support_load"] -= rng.uniform(0, 10) * swing
        d["infra_load"] -= rng.uniform(0, 10) * swing
        d["cash"] -= rng.uniform(40_000, 120_000) * swing
        d["mrr"] += rng.uniform(200, 2200) * swing
        d["reputation"] += rng.uniform(-6, 8) * swing

    d["churn"] = clamp(d["churn"], -0.05, 0.08)
    return d

def step_month(choice: str) -> None:
    ss = st.session_state
    month = ss["month"]
    bundle = ss["months"].get(month)
    if not bundle:
        return

    delta = apply_choice_effects(choice, month)
    stats = ss["stats"]

    total_exp = sum(ss["expenses"].values())
    stats["cash"] = max(0.0, stats["cash"] - total_exp + delta["cash"])
    stats["mrr"] = max(0.0, stats["mrr"] + delta["mrr"])
    stats["reputation"] = clamp(stats["reputation"] + delta["reputation"], 0, 100)
    stats["support_load"] = clamp(stats["support_load"] + delta["support_load"], 0, 100)
    stats["infra_load"] = clamp(stats["infra_load"] + delta["infra_load"], 0, 100)
    stats["churn"] = clamp(stats["churn"] + delta["churn"], 0.0, 0.50)

    choice_title = bundle[choice]["title"]
    ss["chat"].append({"role": "user", "kind": "choice", "content": f"{choice} seçtim: **{choice_title}**"})
    result_lines = [
        f"- **Kasa:** {money(stats['cash'])}",
        f"- **MRR:** {money(stats['mrr'])}",
        f"- **İtibar:** {int(stats['reputation'])}/100",
        f"- **Support yükü:** {int(stats['support_load'])}/100",
        f"- **Altyapı yükü:** {int(stats['infra_load'])}/100",
        f"- **Kayıp oranı:** {pct(stats['churn'])}",
    ]
    ss["chat"].append({"role": "assistant", "kind": "result", "content": "✅ Seçimin işlendi. Güncel durum:\n\n" + "\n".join(result_lines)})

    ss["history"].append({"month": month, "choice": choice, "choice_title": choice_title, "note": ss.get("free_note", "").strip(), "delta": delta})
    ss["free_note"] = ""

    if month < ss["season_length"]:
        ss["month"] += 1
    else:
        ss["chat"].append({"role": "assistant", "kind": "end", "content": "🏁 Sezon bitti. İstersen oyunu sıfırlayıp başka bir mod veya vaka sezonu ile tekrar başlayabilirsin."})

def ensure_month_ready(llm: GeminiLLM, month: int) -> None:
    ss = st.session_state
    if month in ss["months"]:
        return
    bundle, source = generate_month_bundle(llm, month)
    ss["months"][month] = bundle
    ss["chat"].append({"role": "assistant", "kind": "analysis", "content": f"**🧩 Durum Analizi (Ay {month})**\n\n{bundle['durum_analizi']}"})
    ss["chat"].append({"role": "assistant", "kind": "crisis", "content": f"**⚠️ Kriz**\n\n{bundle['kriz']}"})
    if bundle.get("note"):
        ss["chat"].append({"role": "assistant", "kind": "note", "content": f"🗂️ {bundle['note']}"})
    if source == "offline" and ss.get("llm_last_error"):
        ss["chat"].append({"role": "assistant", "kind": "warn", "content": f"⚠️ **Gemini kapalı (offline demo)**: {ss['llm_last_error']}\n\nİstersen online için `google-genai` kurup tekrar deneyebilirsin."})


# =========================
# UI
# =========================

def render_sidebar(llm: GeminiLLM) -> None:
    ss = st.session_state
    stats = ss["stats"]

    st.sidebar.markdown(f"## 🧑‍💻 {ss['founder_name']}")
    st.sidebar.markdown(f"<div class='muted smallcaps'>v{APP_VERSION}</div>", unsafe_allow_html=True)

    st.sidebar.markdown("### Mod")
    ss["mode"] = st.sidebar.selectbox("Mod", list(MODES.keys()), index=list(MODES.keys()).index(ss["mode"]), label_visibility="collapsed")
    st.sidebar.caption(MODES[ss["mode"]]["desc"])

    st.sidebar.markdown("### Vaka sezonu (opsiyonel)")
    case_titles = [c.title for c in CASE_LIBRARY]
    cur_idx = next((i for i, c in enumerate(CASE_LIBRARY) if c.key == ss["case_key"]), 0)
    chosen_title = st.sidebar.selectbox("Vaka", case_titles, index=cur_idx, label_visibility="collapsed")
    chosen = next(c for c in CASE_LIBRARY if c.title == chosen_title)
    ss["case_key"] = chosen.key
    st.sidebar.caption(chosen.blurb)

    st.sidebar.markdown("### Sezon uzunluğu (ay)")
    ss["season_length"] = int(st.sidebar.slider("Sezon uzunluğu (ay)", 6, 24, int(ss["season_length"]), 1))
    st.sidebar.progress(min(1.0, ss["month"] / max(1, ss["season_length"])))
    st.sidebar.caption(f"Ay: {ss['month']}/{ss['season_length']}")

    st.sidebar.markdown("### Başlangıç kasası")
    if not ss["started"]:
        ss["start_cash"] = int(st.sidebar.slider("Başlangıç kasası", 50_000, 2_000_000, int(ss["start_cash"]), 50_000))
        ss["stats"] = default_stats(ss["start_cash"])
    else:
        st.sidebar.write(money(stats["cash"]))

    st.sidebar.markdown("## Finansal Durum")
    st.sidebar.metric("Kasa", money(stats["cash"]))
    st.sidebar.metric("MRR", money(stats["mrr"]))

    with st.sidebar.expander("Aylık Gider Detayı", expanded=False):
        total = 0
        for k, v in ss["expenses"].items():
            st.write(f"- {k}: {money(v)}")
            total += v
        st.write(f"**TOPLAM:** {money(total)}")

    st.sidebar.markdown("---")
    st.sidebar.write(f"**İtibar:** {int(stats['reputation'])}/100")
    st.sidebar.write(f"**Support yükü:** {int(stats['support_load'])}/100")
    st.sidebar.write(f"**Altyapı yükü:** {int(stats['infra_load'])}/100")
    st.sidebar.write(f"**Kayıp oranı:** {pct(stats['churn'])}")

    st.sidebar.markdown("---")
    status = llm.status()
    if status.ok and not ss.get("llm_disabled"):
        st.sidebar.success("Gemini hazır (online).")
        if status.model:
            st.sidebar.caption(f"Model: {status.model}")
    else:
        msg = ss.get("llm_last_error") or status.note or "Gemini kapalı."
        st.sidebar.warning(f"Gemini kapalı (offline). {msg[:140]}")

    if st.sidebar.button("Oyunu sıfırla", use_container_width=True):
        reset_game(keep_settings=True)
        st.rerun()

def render_header() -> None:
    c1, c2 = st.columns([0.72, 0.28])
    with c1:
        st.markdown(f"# {APP_TITLE}")
        st.caption(APP_SUBTITLE)
    with c2:
        with st.expander("🛠️ Karakterini ve ayarlarını özelleştir", expanded=False):
            ss = st.session_state
            ss["founder_name"] = st.text_input("Karakter adı", value=ss["founder_name"])
            st.caption("Bu bölüm oyunun metnini etkiler (ileride daha da bağlarız).")

def render_start_screen() -> None:
    ss = st.session_state
    st.markdown("<hr class='soft'/>", unsafe_allow_html=True)
    st.info("Oyuna başlamak için giriş fikrini yaz. Sonra Ay 1 başlar (Durum Analizi → Kriz → A/B).")
    ss["startup_idea"] = st.text_area("Girişim fikrin ne?", value=ss["startup_idea"], height=140, placeholder="Örn: Anlık çeviri yapan bir uygulama...")
    if ss.get("llm_disabled") and ss.get("llm_last_error"):
        st.warning(f"Gemini kapalı: {ss['llm_last_error']}\n\nİstersen offline demo ile devam edebilirsin.")
    start_disabled = not bool(ss["startup_idea"].strip())
    if st.button("🚀 Oyunu Başlat", disabled=start_disabled, use_container_width=True):
        ss["started"] = True
        ss["month"] = 1
        ss["chat"] = []
        ss["history"] = []
        ss["months"] = {}
        ss["llm_disabled"] = False
        ss["llm_last_error"] = ""
        st.rerun()

def render_chat_and_choices(llm: GeminiLLM) -> None:
    ss = st.session_state
    month = ss["month"]
    ensure_month_ready(llm, month)

    for msg in ss["chat"]:
        role = msg.get("role", "assistant")
        kind = msg.get("kind", "")
        avatar = "🤖" if role == "assistant" else "🧑‍💻"
        if kind == "crisis":
            avatar = "⚠️"
        elif kind == "analysis":
            avatar = "🧩"
        elif kind == "result":
            avatar = "✅"
        elif kind == "warn":
            avatar = "🟨"
        elif kind == "note":
            avatar = "🗂️"
        with st.chat_message(role, avatar=avatar):
            st.markdown(msg.get("content", ""))

    if month > ss["season_length"]:
        return

    bundle = ss["months"][month]

    with st.chat_message("assistant", avatar="👉"):
        st.markdown("**Şimdi seçim zamanı. A mı B mi?** *(İstersen aşağıya kısa bir not da yazabilirsin.)*")
        ss["free_note"] = st.text_input("Not (opsiyonel)", value=ss.get("free_note", ""), placeholder="Kısa not...", key=f"note_{month}")

        colA, colB = st.columns(2, gap="large")
        with colA:
            st.markdown("<div class='choice'>", unsafe_allow_html=True)
            st.markdown(f"<div class='title'>A) {html_escape(bundle['A']['title'])}</div>", unsafe_allow_html=True)
            st.markdown(md_escape_li(bundle["A"]["steps"]), unsafe_allow_html=True)
            if st.button("A seç", key=f"A_{month}", use_container_width=True):
                step_month("A")
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        with colB:
            st.markdown("<div class='choice'>", unsafe_allow_html=True)
            st.markdown(f"<div class='title'>B) {html_escape(bundle['B']['title'])}</div>", unsafe_allow_html=True)
            st.markdown(md_escape_li(bundle["B"]["steps"]), unsafe_allow_html=True)
            if st.button("B seç", key=f"B_{month}", use_container_width=True):
                step_month("B")
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

def main() -> None:
    init_state()
    llm = GeminiLLM.from_env_or_secrets()
    render_sidebar(llm)
    render_header()

    ss = st.session_state
    if not ss["started"]:
        render_start_screen()
        return

    st.markdown("<hr class='soft'/>", unsafe_allow_html=True)
    render_chat_and_choices(llm)

if __name__ == "__main__":
    main()
