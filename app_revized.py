# app_v3.py
# Startup Survivor RPG — Streamlit single-file app
# v3: Mode/Case overhaul + bug fixes + locked settings + character archetypes + delayed effects

from __future__ import annotations

import json
import ast
import os
import random
import re
from dataclasses import dataclass
from datetime import datetime
from html import escape as html_escape
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st


# Structured-output JSON schema for month generation (used with google-genai).
# Keeps Gemini responses machine-parseable and prevents "JSON parse edilemedi" issues.
MONTH_RESPONSE_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "durum_analizi": {"type": "string"},
        "kriz": {"type": "string"},
        "A": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "tag": {"type": "string"},
                "steps": {"type": "array", "items": {"type": "string"}},
                "risk": {"type": "string"},
                "delayed_seed": {"type": "string"},
            },
            "required": ["title", "tag", "steps", "risk", "delayed_seed"],
        },
        "B": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "tag": {"type": "string"},
                "steps": {"type": "array", "items": {"type": "string"}},
                "risk": {"type": "string"},
                "delayed_seed": {"type": "string"},
            },
            "required": ["title", "tag", "steps", "risk", "delayed_seed"],
        },
        "note": {"type": "string"},
    },
    "required": ["durum_analizi", "kriz", "A", "B", "note"],
}


# =========================
# Config / Theme
# =========================

APP_TITLE = "Startup Survivor RPG"
APP_SUBTITLE = "Ay bazlı startup simülasyonu: Durum Analizi → Kriz → A/B kararı. True Story vakalar + modlar."
APP_VERSION = "3.0.1"

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

CSS = """
<style>
.block-container {padding-top: 4.0rem; padding-bottom: 2rem;}
section[data-testid="stSidebar"] .block-container {padding-top: 2.5rem;}
.card {
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 16px;
  padding: 14px 16px;
  background: rgba(255,255,255,0.03);
}
.card h3 {margin: 0 0 .4rem 0;}
.muted {opacity: .75;}
.smallcaps {font-variant: all-small-caps; letter-spacing: .04em;}
hr.soft {border: none; border-top: 1px solid rgba(255,255,255,0.08); margin: 1rem 0;}
.choice {
  border: 1px solid rgba(255,255,255,0.10);
  border-radius: 18px;
  padding: 18px 18px 14px 18px;
  background: rgba(255,255,255,0.02);
}
.choice h4 {margin: 0 0 .3rem 0;}
.pill {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  border: 1px solid rgba(255,255,255,0.12);
  font-size: 12px;
  opacity: .85;
}
.pill.warn {border-color: rgba(255,190,90,0.35);}
.pill.ok {border-color: rgba(120,255,160,0.25);}
.pill.bad {border-color: rgba(255,120,120,0.25);}
kbd {padding:2px 6px;border-radius:6px;border:1px solid rgba(255,255,255,0.15);background:rgba(255,255,255,0.04);}
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)


# =========================
# Helpers
# =========================

def now_id() -> str:
    return datetime.utcnow().strftime("%Y%m%d%H%M%S%f")

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def money(x: float) -> str:
    # TRY format
    try:
        return f"{x:,.0f} ₺".replace(",", ".")
    except Exception:
        return f"{x} ₺"

def pct(x: float) -> str:
    return f"%{x * 100:.1f}"

def ensure_list(x: Any) -> List[Any]:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]

def strip_code_fences(s: str) -> str:
    s = (s or "").strip()
    # ```json ... ```
    m = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return s


def escape_newlines_in_json_strings(s: str) -> str:
    """Escape bare newlines inside quoted strings.

    LLM outputs sometimes include literal newlines inside string values, which breaks JSON and even Python-literal parsing.
    We escape \n/\r only when we're *inside* a quoted string (either "..." or '...').
    """
    if not s:
        return s
    out: List[str] = []
    in_str = False
    quote = ""
    esc = False
    for ch in s:
        if in_str:
            if esc:
                out.append(ch)
                esc = False
                continue
            if ch == "\\":  # start escape
                out.append(ch)
                esc = True
                continue
            if ch == quote:
                out.append(ch)
                in_str = False
                quote = ""
                continue
            if ch == "\n":
                out.append("\\n")
                continue
            if ch == "\r":
                out.append("\\r")
                continue
            out.append(ch)
        else:
            if ch in ('"', "'"):
                out.append(ch)
                in_str = True
                quote = ch
            else:
                out.append(ch)
    return "".join(out)

def try_parse_json(raw: str) -> Optional[dict]:
    """Best-effort JSON parser for LLM outputs.

    Tries:
    - strip code fences
    - extract the first {...} block
    - normalize smart quotes
    - remove trailing commas
    - json.loads
    - ast.literal_eval fallback (handles single quotes) after normalizing true/false/null
    """
    if not raw:
        return None

    s = strip_code_fences(raw)

    # Best effort: grab first {...} block
    ss = s.strip()
    if not (ss.startswith("{") and ss.endswith("}")):
        i = s.find("{")
        j = s.rfind("}")
        if i != -1 and j != -1 and j > i:
            s = s[i : j + 1]

    # Normalize common “smart quotes” coming from some models
    s = (s or "").replace("“", "\"").replace("”", "\"").replace("’", "'").replace("‘", "'")

    # Remove non-printable control chars (except whitespace)
    s = "".join(ch for ch in s if (ch >= " " or ch in "\n\r\t"))

    # Fix trailing commas
    s = re.sub(r",\s*([}\]])", r"\1", s)


    # Escape bare newlines inside quoted strings (LLM outputs can violate JSON)
    s = escape_newlines_in_json_strings(s)

    # First attempt: strict JSON
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass

    # Second attempt: Python literal (single quotes etc.)
    try:
        py = re.sub(r"\bnull\b", "None", s, flags=re.IGNORECASE)
        py = re.sub(r"\btrue\b", "True", py, flags=re.IGNORECASE)
        py = re.sub(r"\bfalse\b", "False", py, flags=re.IGNORECASE)
        obj = ast.literal_eval(py)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None

def normalize_steps(x: Any) -> List[str]:
    out = [str(s).strip() for s in ensure_list(x) if s is not None]
    out = [s for s in out if s][:6]
    return out

def normalize_tag(x: Any) -> str:
    allowed = {
        "growth","efficiency","reliability","compliance","fundraising","people",
        "product","sales","marketing","security"
    }
    t = str(x or "").strip().lower()
    if t in allowed:
        return t
    # coarse mapping
    if "growth" in t or "büy" in t:
        return "growth"
    if "eff" in t or "maliyet" in t or "kıs" in t:
        return "efficiency"
    if "reli" in t or "stabil" in t or "altyap" in t or "support" in t:
        return "reliability"
    if "comp" in t or "uyum" in t or "reg" in t:
        return "compliance"
    if "fund" in t or "yat" in t:
        return "fundraising"
    if "people" in t or "ekip" in t or "hr" in t:
        return "people"
    if "sec" in t or "güven" in t:
        return "security"
    if "sale" in t or "sat" in t:
        return "sales"
    if "market" in t or "pazar" in t:
        return "marketing"
    if "product" in t or "ürün" in t:
        return "product"
    return "growth"

def normalize_risk(x: Any) -> str:
    t = str(x or "").strip().lower()
    if t in {"low","med","high"}:
        return t
    if "düş" in t:
        return "low"
    if "yük" in t:
        return "high"
    return "med"

def tag_label(tag: str) -> str:
    return {
        "growth":"Büyüme",
        "efficiency":"Verimlilik",
        "reliability":"Dayanıklılık",
        "compliance":"Uyum/Hukuk",
        "fundraising":"Yatırım/Finansman",
        "people":"Ekip/İK",
        "product":"Ürün",
        "sales":"Satış",
        "marketing":"Pazarlama",
        "security":"Güvenlik",
    }.get(tag, tag)

def risk_label(r: str) -> str:
    return {"low":"Düşük risk", "med":"Orta risk", "high":"Yüksek risk"}.get(r, r)


# =========================
# True Story cases
# =========================

@dataclass
class CaseSeason:
    key: str
    title: str
    years: str
    blurb: str
    seed: int
    inspired_by: str
    sources: List[Tuple[str, str]]
    real_outcome: List[str]

def _src(title: str, url: str) -> Tuple[str, str]:
    return (title, url)

CASE_LIBRARY: List[CaseSeason] = [
    CaseSeason(
        key="free",
        title="Serbest (Rastgele)",
        years="—",
        blurb="Kendi fikrine göre rastgele olaylar. Her ay farklı kriz.",
        seed=1,
        inspired_by="",
        sources=[],
        real_outcome=[],
    ),

    # 10 True Story cases
    CaseSeason(
        key="facebook_privacy_2019",
        title="True Story: Mahremiyet & Regülasyon Kıskacı",
        years="2018–2019",
        blurb="Mahremiyet krizi büyür; regülatör baskısı ve toplu davalar iş modelini sıkıştırır.",
        seed=2019,
        inspired_by="Facebook/FTC gizlilik uzlaşması dinamiği",
        sources=[
            _src("FTC press release (2019) — Facebook privacy restrictions", "https://www.ftc.gov/news-events/news/press-releases/2019/07/ftc-imposes-5-billion-penalty-sweeping-new-privacy-restrictions-facebook"),
        ],
        real_outcome=[
            "ABD FTC, 2019'da Facebook'a 5 milyar $ ceza ve kapsamlı gizlilik yükümlülükleri getirdi.",
            "Şirketin gizlilik programı ve yönetim düzeyinde sorumluluk mekanizmaları güçlendirildi.",
        ],
    ),
    CaseSeason(
        key="wework_ipo_2019",
        title="True Story: IPO Çöküşü & Güven Krizi",
        years="2019",
        blurb="Hiper büyüme, nakit yakımı ve yönetişim sorunları halka arzı çökertir.",
        seed=2019_2,
        inspired_by="WeWork 2019 IPO süreci dinamiği",
        sources=[
            _src("Business Wire (2019) — WeWork withdraws S‑1", "https://www.businesswire.com/news/home/20190930005559/en/WeWork-Withdraw-S-1-Registration-Statement"),
        ],
        real_outcome=[
            "WeWork 30 Eylül 2019'da S‑1 kayıt beyanını geri çektiğini duyurdu.",
            "Ardından yeniden yapılanma ve finansman arayışı gündeme geldi.",
        ],
    ),
    CaseSeason(
        key="blackberry_platform_shift",
        title="True Story: Ekosistem Kayması — Kalite Yetmiyor",
        years="2007–2016",
        blurb="Ürün kaliteli olsa da ekosistem/pazar standardı değişir; platform kayması boğar.",
        seed=2007,
        inspired_by="BlackBerry'nin platform kayması ve dönüşümü dinamiği",
        sources=[
            _src("Platform Digit — Rise/Fall of BlackBerry", "https://d3.harvard.edu/platform-digit/submission/the-rise-and-fall-and-rise-again-of-blackberry/"),
            _src("WIRED (2016) — BlackBerry handsets shift (context)", "https://www.wired.com/story/blackberry-stop-making-handsets/"),
        ],
        real_outcome=[
            "Akıllı telefon pazarı uygulama ekosistemi ve UX standardı etrafında hızla değişti.",
            "BlackBerry 2016'da donanım odağını bırakıp yazılım/servislere daha fazla yöneldi.",
        ],
    ),
    CaseSeason(
        key="samsung_note7_recall",
        title="True Story: Ürün Güvenliği & Küresel Geri Çağırma",
        years="2016",
        blurb="Safety krizi geri çağırma dalgasına dönüşür; nakit, itibar ve operasyon aynı anda yanar.",
        seed=2016,
        inspired_by="Galaxy Note7 geri çağırma dinamiği",
        sources=[
            _src("US CPSC recall notice (2016)", "https://www.cpsc.gov/Recalls/2016/Samsung-Recalls-Galaxy-Note7-Smartphones"),
        ],
        real_outcome=[
            "2016'da ürün güvenliği riski nedeniyle geniş kapsamlı geri çağırma ve üretim durdurma adımları atıldı.",
            "Maliyet, itibar ve tedarik zinciri baskısı aynı anda yönetilmek zorunda kaldı.",
        ],
    ),
    CaseSeason(
        key="uber_2017_crisis",
        title="True Story: Kültür Skandalı & Yönetim Krizi",
        years="2017",
        blurb="Davalar, kamuoyu ve kültür sorunları birleşir; yönetim krizi büyümeyi tehdit eder.",
        seed=2017,
        inspired_by="Uber 2017 kriz zinciri dinamiği",
        sources=[
            _src("TIME (2017) — Kalanick resigns", "https://time.com/4826194/uber-travis-kalanick-resigns/"),
        ],
        real_outcome=[
            "2017'de şirket içi kültür ve kamuoyu baskısı liderlik krizine dönüştü.",
            "Üst yönetim değişiklikleri ve itibar onarımı gündeme geldi.",
        ],
    ),
    CaseSeason(
        key="equifax_breach_settlement",
        title="True Story: Dev Veri İhlali & Tazminat Baskısı",
        years="2017–2019",
        blurb="Data breach sonrası güven çöküşü; regülatör ve tazminat maliyeti şirketi sıkıştırır.",
        seed=2017_2,
        inspired_by="Equifax 2017 ihlali sonrası settlement dinamiği",
        sources=[
            _src("FTC (2019) — Equifax settlement", "https://www.ftc.gov/news-events/news/press-releases/2019/07/equifax-pay-575-million-part-settlement-ftc-cfpb-states-related-2017-data-breach"),
        ],
        real_outcome=[
            "Equifax 2017 ihlali sonrası FTC/CFPB/eyaletlerle 2019'da kapsamlı settlement duyuruldu.",
            "Güven onarımı, güvenlik programı ve mali tazminat baskısı birlikte yönetildi.",
        ],
    ),
    CaseSeason(
        key="vw_dieselgate",
        title="True Story: Regülasyon İhlali & Büyük Yaptırım",
        years="2015–2017",
        blurb="Uyum ihlali büyük cezaya dönüşür; hukuk, itibar, operasyon aynı anda krize girer.",
        seed=2015,
        inspired_by="Volkswagen Dieselgate dinamiği",
        sources=[
            _src("US DOJ (2017) — Volkswagen plea and penalties", "https://www.justice.gov/archives/opa/pr/volkswagen-ag-agrees-plead-guilty-and-pay-43-billion-criminal-and-civil-penalties-six"),
        ],
        real_outcome=[
            "Skandal sonrası milyarlarca $ ceza/uzlaşma ve kapsamlı uyum yükümlülükleri gündeme geldi.",
            "Şirketin uyum ve itibar onarımı uzun soluklu bir dönüşüm sürecine dönüştü.",
        ],
    ),
    CaseSeason(
        key="boeing_737max_grounding",
        title="True Story: Güvenlik Krizi & Ürün Durdurma",
        years="2019",
        blurb="Ürün güvenliği ve kamu baskısı operasyonu durdurmaya kadar gider; sert regülasyon devreye girer.",
        seed=2019_3,
        inspired_by="Boeing 737 MAX grounding dinamiği",
        sources=[
            _src("US DOT (2019) — Temporary grounding statement", "https://www.transportation.gov/briefing-room/statement-temporary-grounding-boeing-737-max-aircraft-operated-us-airlines-or-us"),
        ],
        real_outcome=[
            "2019'da 737 MAX uçuşları birçok otorite tarafından geçici olarak durduruldu (grounding).",
            "Güvenlik, sertifikasyon ve itibar boyutu aynı anda ele alındı.",
        ],
    ),
    CaseSeason(
        key="wells_fargo_accounts",
        title="True Story: Satış Baskısı & Sahte Hesap Skandalı",
        years="2016",
        blurb="Hedef baskısı yanlış teşvikler doğurur; uyum ve itibar krizi patlar.",
        seed=2016_2,
        inspired_by="Wells Fargo unauthorized accounts dinamiği",
        sources=[
            _src("CFPB enforcement (2016) — Wells Fargo", "https://www.consumerfinance.gov/enforcement/actions/wells-fargo-bank-2016/"),
        ],
        real_outcome=[
            "2016'da izinsiz hesap açma iddiaları sonrası düzenleyici yaptırımlar gündeme geldi.",
            "Teşvik sistemi, kültür ve uyum programları yeniden ele alındı.",
        ],
    ),
    CaseSeason(
        key="deepwater_horizon",
        title="True Story: Felaket Operasyon & Dev Tazminat",
        years="2010–2015",
        blurb="Operasyon felaketi, uzun soluklu hukuk ve tazminat yüküne dönüşür; şirket sarsılır.",
        seed=2010,
        inspired_by="Deepwater Horizon sonrası settlement dinamiği",
        sources=[
            _src("US DOJ (2015) — BP historic settlement", "https://www.justice.gov/archives/opa/pr/us-and-five-gulf-states-reach-historic-settlement-bp-resolve-civil-lawsuit-over-deepwater"),
        ],
        real_outcome=[
            "2015'te ABD ve Gulf eyaletleriyle büyük bir uzlaşma açıklandı; tazminat ve ceza yükü büyüktü.",
            "Operasyon güvenliği ve risk yönetimi şirket stratejisinin merkezine oturdu.",
        ],
    ),
]

def get_case(case_key: str) -> CaseSeason:
    for c in CASE_LIBRARY:
        if c.key == case_key:
            return c
    return CASE_LIBRARY[0]


# =========================
# Modes / Difficulty
# =========================

MODES: Dict[str, Dict[str, Any]] = {
    "Gerçekçi": {
        "desc": "Tam gerçek dünya hissi. Trade-off net, mucize yok.",
        "temp": 0.75,
        "swing": 1.00,
        "tone": "tamamen gerçekçi, operatif, net; abartı yok; ölçülü dramatik",
        "require_reason": False,
        "deceptive": False,
        "antagonistic": False,
        "turkey": False,
        "absurd": False,
    },
    "Zor": {
        "desc": "Gerçekçi ama daha zor. Seçenekler yanıltıcı olabilir; kısa gerekçe yazmanı ister.",
        "temp": 0.82,
        "swing": 1.25,
        "tone": "sert ama adil; belirsizlik yüksek; hızlı karar baskısı",
        "require_reason": True,
        "deceptive": True,
        "antagonistic": False,
        "turkey": False,
        "absurd": False,
    },
    "Spartan": {
        "desc": "En zor. Anlatıcı antagonistik; dünya acımasız ama mantıklı.",
        "temp": 0.88,
        "swing": 1.45,
        "tone": "acımasız derecede gerçekçi; iğneleyici ama saygılı; baskı çok yüksek",
        "require_reason": True,
        "deceptive": True,
        "antagonistic": True,
        "turkey": False,
        "absurd": False,
    },
    "Türkiye": {
        "desc": "Türkiye şartları: kur/enflasyon, vergi/SGK, denetimler, tahsilat gecikmesi, afet riski.",
        "temp": 0.78,
        "swing": 1.10,
        "tone": "Türkiye iş dünyası gerçekleri; maliyet ve uyum detaylı; somut ve gerçekçi",
        "require_reason": False,
        "deceptive": False,
        "antagonistic": False,
        "turkey": True,
        "absurd": False,
    },
    "Extreme": {
        "desc": "Absürt ve komik. Mantıksız ama eğlenceli krizler (sadece bu modda).",
        "temp": 1.05,
        "swing": 1.40,
        "tone": "yüksek tempo, absürt mizah, şaşırtıcı ve yaratıcı",
        "require_reason": False,
        "deceptive": False,
        "antagonistic": False,
        "turkey": False,
        "absurd": True,
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
            # Streamlit secrets: top-level or nested tables (TOML sections)
            try:
                if name in st.secrets:
                    return st.secrets.get(name)
                for _, v in dict(st.secrets).items():
                    if isinstance(v, dict) and name in v:
                        return v.get(name)
            except Exception:
                pass
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
            self.last_error = "API key yok."
            return

        # Try new SDK: google-genai
        try:
            from google import genai  # type: ignore
            self._client = genai.Client(api_key=self.api_keys[0])
            self.backend = "genai"
            self.model_in_use = "gemini-2.5-pro"
            return
        except Exception as e:
            self._client = None
            self.last_error = f"google-genai yok/başarısız: {e}"

        # Try legacy: google-generativeai
        try:
            import google.generativeai as genai_legacy  # type: ignore
            genai_legacy.configure(api_key=self.api_keys[0])
            self._legacy = genai_legacy
            self.backend = "legacy"
            self.model_in_use = "gemini-2.5-pro"
            return
        except Exception as e:
            self._legacy = None
            self.backend = "none"
            self.last_error = f"google-generativeai yok/başarısız: {e}"

    def status(self) -> LLMStatus:
        if self.backend == "none":
            return LLMStatus(False, "none", "", self.last_error)
        return LLMStatus(True, self.backend, self.model_in_use, "")

    def _rotate_key(self) -> None:
        if len(self.api_keys) <= 1:
            return
        self.api_keys = self.api_keys[1:] + self.api_keys[:1]
        # re-init with next key
        self._init_backend()

    def generate_text(self, prompt: str, temperature: float = 0.8, max_output_tokens: int = 1400) -> str:
        """Generate text with key rotation + model fallback.

        - Tries a small list of candidate Gemini model names.
        - Rotates across all provided API keys if an error occurs.
        """
        candidates = [
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-3-flash-preview",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
        ]

        last_err: Optional[Exception] = None

        # Try each key (rotate on failure). For each key, try candidate models.
        for _ in range(max(1, len(self.api_keys))):
            if self.backend == "genai" and self._client is not None:
                for m in candidates:
                    try:
                        res = None
                        try:
                            # Prefer JSON-safe responses when supported by the installed SDK.
                            res = self._client.models.generate_content(
                                model=m,
                                contents=prompt,
                                config={
                                    "temperature": float(temperature),
                                    "max_output_tokens": int(max_output_tokens),
                                    "response_mime_type": "application/json",
                                },
                            )
                        except TypeError:
                            # Older SDK versions may not support response_mime_type.
                            res = self._client.models.generate_content(
                                model=m,
                                contents=prompt,
                                config={
                                    "temperature": float(temperature),
                                    "max_output_tokens": int(max_output_tokens),
                                },
                            )
                        txt = getattr(res, "text", "") or ""
                        if txt.strip():
                            self.model_in_use = m
                            return txt
                    except Exception as e:
                        last_err = e
                        continue

            if self.backend == "legacy" and self._legacy is not None:
                for m in candidates:
                    try:
                        model = self._legacy.GenerativeModel(m)
                        res = None
                        try:
                            res = model.generate_content(
                                prompt,
                                generation_config={
                                    "temperature": float(temperature),
                                    "max_output_tokens": int(max_output_tokens),
                                    "response_mime_type": "application/json",
                                },
                            )
                        except Exception:
                            res = model.generate_content(
                                prompt,
                                generation_config={
                                    "temperature": float(temperature),
                                    "max_output_tokens": int(max_output_tokens),
                                },
                            )
                        txt = getattr(res, "text", "") or ""
                        if txt.strip():
                            self.model_in_use = m
                            return txt
                    except Exception as e:
                        last_err = e
                        continue

            # rotate to next key and re-init backend
            self._rotate_key()

        raise RuntimeError(f"Gemini hata: {last_err}" if last_err else "Gemini yanıt veremedi.")

    def generate_month_json(self, prompt: str, temperature: float = 0.8, max_output_tokens: int = 2000) -> Tuple[Optional[dict], str]:
        """Generate a month bundle as JSON.

        - With google-genai backend: uses structured output (response_mime_type + JSON schema) for reliable JSON.
        - With legacy backend: falls back to best-effort parsing + one repair pass.
        Returns (data_or_none, raw_text).
        """
        # Candidate models (first one is preferred)
        candidates = [
            "gemini-2.5-pro",
            "gemini-2.5-pro-latest",
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-1.5-pro",
        ]

        if self.backend == "genai" and self._client is not None:
            last_err = ""
            for model in candidates:
                # Try with current key; rotate on API errors (quota, auth, etc.)
                for _ in range(max(1, len(self.api_keys))):
                    try:
                        cfg = {"temperature": temperature, "max_output_tokens": max_output_tokens}
                        try:
                            # Preferred: structured outputs (JSON mode + schema).
                            cfg2 = dict(cfg)
                            cfg2.update({
                                "response_mime_type": "application/json",
                                "response_json_schema": MONTH_RESPONSE_JSON_SCHEMA,
                            })
                            resp = self._client.models.generate_content(
                                model=model,
                                contents=prompt,
                                config=cfg2,
                            )
                        except TypeError:
                            # Older SDK versions may not support response_json_schema / response_mime_type.
                            try:
                                cfg3 = dict(cfg)
                                cfg3.update({"response_mime_type": "application/json"})
                                resp = self._client.models.generate_content(
                                    model=model,
                                    contents=prompt,
                                    config=cfg3,
                                )
                            except TypeError:
                                resp = self._client.models.generate_content(
                                    model=model,
                                    contents=prompt,
                                    config=cfg,
                                )
                        raw = (getattr(resp, "text", "") or "").strip()
                        # Should already be valid JSON, but keep a defensive parser.
                        data = try_parse_json(raw) or json.loads(raw)
                        self.model_in_use = model
                        return data, raw
                    except Exception as e:
                        last_err = str(e)
                        self.last_error = last_err
                        # rotate to next key and re-init backend
                        self._rotate_key()
                        # refresh client if we have keys
                        if self.backend != "genai":
                            break
                        continue
            return None, (last_err or "")

        # Legacy / none: use text generation + parse
        raw = ""
        try:
            raw = self.generate_text(prompt, temperature=temperature, max_output_tokens=max_output_tokens)
        except Exception as e:
            self.last_error = str(e)
            return None, raw

        data = try_parse_json(raw)
        if data:
            return data, raw

        # Repair once
        try:
            repaired = self.generate_text(build_json_repair_prompt(raw), temperature=0.1, max_output_tokens=max_output_tokens + 300)
            data = try_parse_json(repaired)
            if data:
                return data, repaired
        except Exception as e:
            self.last_error = str(e)

        return None, raw





# =========================
# Game state
# =========================

DEFAULT_EXPENSES = {"Salarlar": 50_000, "Sunucu": 6_100, "Pazarlama": 5_300}

@dataclass
class Archetype:
    key: str
    title: str
    blurb: str
    rep: float
    support: float
    infra: float
    churn: float
    cash_mult: float = 1.0

ARCHETYPES: List[Archetype] = [
    Archetype("tech", "Teknik Kurucu", "Altyapı güçlü, ama support hızla büyüyebilir.", 48, 22, 16, 0.050, 1.00),
    Archetype("sales", "Satışçı Kurucu", "Gelir baskın, ama operasyon yükü ve churn riski artabilir.", 52, 25, 22, 0.060, 1.00),
    Archetype("product", "Ürüncü Kurucu", "Kullanıcı deneyimi iyi; dengeli ilerler.", 55, 20, 20, 0.045, 1.00),
    Archetype("ops", "Operasyoncu Kurucu", "Düzen ve verimlilik; büyüme yavaş ama sağlam.", 50, 18, 18, 0.050, 1.05),
    Archetype("finance", "Finansçı Kurucu", "Runway odaklı; risk yönetimi güçlü.", 47, 22, 22, 0.055, 1.10),
]

def default_stats(start_cash: int, archetype: Archetype) -> dict:
    return {
        "cash": float(start_cash),
        "mrr": 0.0,
        "reputation": float(archetype.rep),
        "support_load": float(archetype.support),
        "infra_load": float(archetype.infra),
        "churn": float(archetype.churn),
    }

def init_state() -> None:
    ss = st.session_state
    ss.setdefault("run_id", now_id())
    ss.setdefault("started", False)
    ss.setdefault("ended", False)

    ss.setdefault("month", 1)
    ss.setdefault("season_length", 12)

    ss.setdefault("mode", "Gerçekçi")
    ss.setdefault("case_key", "free")

    ss.setdefault("founder_name", "İsimsiz Girişimci")
    ss.setdefault("archetype_key", "product")
    ss.setdefault("startup_idea", "")

    ss.setdefault("start_cash", 1_000_000)
    ss.setdefault("expenses", DEFAULT_EXPENSES.copy())

    arch = next((a for a in ARCHETYPES if a.key == ss["archetype_key"]), ARCHETYPES[0])
    ss.setdefault("stats", default_stats(int(ss["start_cash"] * arch.cash_mult), arch))

    ss.setdefault("history", [])          # list of past month choices
    ss.setdefault("months", {})           # month -> content bundle
    ss.setdefault("month_sources", {})    # month -> "gemini" | "offline"
    ss.setdefault("chat", [])             # chat messages
    ss.setdefault("delayed_queue", [])    # list of delayed effects dicts

    ss.setdefault("pending_note", "")
    ss.setdefault("pending_reason", "")
    ss.setdefault("locked_settings", {})  # frozen snapshot when started

    ss.setdefault("llm_disabled", False)
    ss.setdefault("llm_fail_count", 0)
    ss.setdefault("llm_last_error", "")
    ss.setdefault("llm_last_raw", "")
    ss.setdefault("llm_last_raw_repaired", "")

def reset_game(keep_settings: bool = True) -> None:
    ss = st.session_state
    keep: Dict[str, Any] = {}
    if keep_settings:
        for k in ["mode", "case_key", "season_length", "start_cash", "founder_name", "startup_idea", "archetype_key"]:
            keep[k] = ss.get(k)

    for k in list(ss.keys()):
        del ss[k]
    init_state()

    if keep_settings:
        for k, v in keep.items():
            ss[k] = v

    # reset stats from archetype & cash
    arch = next((a for a in ARCHETYPES if a.key == ss["archetype_key"]), ARCHETYPES[0])
    ss["stats"] = default_stats(int(ss["start_cash"] * arch.cash_mult), arch)

def lock_settings() -> None:
    ss = st.session_state
    ss["locked_settings"] = {
        "mode": ss["mode"],
        "case_key": ss["case_key"],
        "season_length": int(ss["season_length"]),
        "start_cash": int(ss["start_cash"]),
        "founder_name": ss["founder_name"],
        "archetype_key": ss["archetype_key"],
        "startup_idea": ss["startup_idea"],
    }

def is_locked() -> bool:
    return bool(st.session_state.get("started"))

def get_locked(k: str, default: Any = None) -> Any:
    ss = st.session_state
    if ss.get("started") and ss.get("locked_settings"):
        return ss["locked_settings"].get(k, default)
    return ss.get(k, default)


# =========================
# Prompting (LLM)
# =========================

def build_prompt(month: int, mode: str, idea: str, history: List[dict], case: CaseSeason, stats: dict) -> str:
    spec = MODES.get(mode, MODES["Gerçekçi"])
    tone = spec["tone"]
    is_turkey = bool(spec.get("turkey"))
    is_absurd = bool(spec.get("absurd"))
    deceptive = bool(spec.get("deceptive"))
    antagonistic = bool(spec.get("antagonistic"))

    hist_lines = [
        f"- Ay {h.get('month')}: {h.get('choice')} / {h.get('choice_title')} | not: {h.get('note','-')}"
        for h in history[-4:]
    ]
    hist = "\n".join(hist_lines) if hist_lines else "(henüz seçim yok)"

    # Background metrics for coherence ONLY (no mention in text)
    context_metrics = (
        f"ARKA PLAN (metin içinde yazma): cash={int(stats['cash'])}, mrr={int(stats['mrr'])}, "
        f"itibar={int(stats['reputation'])}/100, support={int(stats['support_load'])}/100, "
        f"altyapı={int(stats['infra_load'])}/100, churn={stats['churn']:.3f}."
    )

    case_note = ""
    if case.key != "free":
        case_note = (
            f"TRUE STORY vaka teması: {case.title} ({case.years}). Esin: {case.inspired_by}.\n"
            "Senaryo gerçek dinamiklerden esinlenir ama oyunlaştırılmıştır; olayları spoiler vermeden kurgula.\n"
            "Şirket adı uydur (gerçek şirket adını metin içinde kullanma)."
        )

    mode_rules = []
    if is_turkey:
        mode_rules.append("Türkiye bağlamı kullan: kur/enflasyon, vergi/SGK, denetim, tahsilat gecikmesi, afet riski, sözleşme pratikleri.")
    if deceptive:
        mode_rules.append("Seçenekler yanıltıcı olabilir: ikisi de mantıklı görünsün; ancak gizli risk/bedel barındırabilir. Bunları açıkça söyleme (spoiler yok).")
    if antagonistic:
        mode_rules.append("Anlatıcı antagonistik: baskı kur, iğneleyici ol ama hakaret etme. Mantık dışı ceza yok.")
    if is_absurd:
        mode_rules.append("Absürt ve komik krizler serbest; ama metin anlaşılır kalsın.")
    if not is_absurd:
        mode_rules.append("Mucize/absürt olay yasak. Tam gerçek dünya.")

    mode_rules_text = "\n".join(f"- {x}" for x in mode_rules) if mode_rules else "- (ek kural yok)"

    allowed_tags = "growth, efficiency, reliability, compliance, fundraising, people, product, sales, marketing, security"

    return f"""
Sen bir startup simülasyonu için vaka yazarı ve ürün stratejisti gibi yazıyorsun. Dil: Türkçe.
Ton: {tone}

Amaç: Ay {month} için önce "Durum Analizi", sonra "Kriz" yaz, sonra iki seçenek sun (A/B).
Seçeneklerde SONUÇ SPOILER'I YOK: metrik/sonuç isimleri yazma (kasa, MRR, churn vb. geçmesin).
Sadece uygulanacak planı yaz.

{case_note}

MOD kuralları:
{mode_rules_text}

Oyuncu adı: {st.session_state.get('founder_name','Girişimci')}
Oyuncunun startup fikri: {idea or "(boş)"}

Geçmiş seçim özeti:
{hist}

{context_metrics}

Şimdi sadece aşağıdaki JSON'u üret (çıktı SADECE JSON olsun).
ÖNEMLİ JSON KURALLARI:
- SADECE JSON döndür: markdown/code fence yok, başlık yok, açıklama yok.
- Tüm anahtarlar ve string değerler çift tırnak (") kullanmalı.
- "durum_analizi" ve "kriz" alanlarında paragraf ayrımı gerekiyorsa gerçek satır sonu kullanma; bunun yerine "\n\n" dizisini kullan.


Şema:
{{
  "durum_analizi": "2-4 paragraf. Ay 1 ise fikri detaylı analiz et. Ay 2+ ise son seçimlerin yan etkilerini gerçekçi şekilde analiz et.",
  "kriz": "2-4 paragraf. Net ve somut kriz sahnesi. Metrik isimleri/sonuç yazma.",
  "A": {{
    "title": "kısa başlık",
    "steps": ["4-6 maddelik plan", "..."],
    "tag": "{allowed_tags} içinden",
    "risk": "low|med|high",
    "delayed_seed": "1-6 kelime (gecikmeli yan etki tohumu)"
  }},
  "B": {{
    "title": "kısa başlık",
    "steps": ["4-6 maddelik plan", "..."],
    "tag": "{allowed_tags} içinden",
    "risk": "low|med|high",
    "delayed_seed": "1-6 kelime (gecikmeli yan etki tohumu)"
  }},
  "note": "opsiyonel kısa not"
}}

Kurallar:
- A ve B birbirine yakın kalitede olsun; ikisi de mantıklı.
- Tek bir ayda tek ana çatışma.
- Metrik isimlerini metne koyma.
""".strip()

def build_json_repair_prompt(bad_output: str) -> str:
    """Ask the model to return ONLY valid JSON matching our expected schema."""
    bad_output = (bad_output or "").strip()
    schema = r'''
{
  "durum_analizi": "string (>= 220 karakter)",
  "kriz": "string (>= 220 karakter)",
  "A": {
    "title": "string",
    "tag": "growth|efficiency|reliability|compliance|fundraising|people|product|sales|marketing|security",
    "steps": ["en az 4 madde"],
    "risk": "low|med|high",
    "delayed_seed": "kısa tohum (<= 6 kelime)"
  },
  "B": { "title": "...", "tag": "...", "steps": ["..."], "risk": "...", "delayed_seed": "..." },
  "note": "opsiyonel"
}
'''.strip()

    return f"""Aşağıdaki metin, beklenen şemaya göre JSON olmalıydı ama geçerli JSON değil.
Görevin: Metni AYNEN aynı anlamı koruyarak geçerli JSON'a dönüştürmek.

KURALLAR:
- SADECE JSON döndür. Başka hiçbir açıklama, markdown, kod bloğu, ön/son metin YOK.
- Çıktın mutlaka tek bir JSON nesnesi olsun ({{...}}).
- Türkçe karakterler serbest.
- Çok satırlı alanlarda satır sonlarını \\n olarak kaçır; string içinde çıplak newline karakteri OLMASIN.
- Şema alanları eksikse, mantıklı şekilde tamamla ama uydurma uzun hikâye ekleme.

BEKLENEN ŞEMA:
{schema}

DÖNÜŞTÜRÜLECEK METİN:
{bad_output}
"""
def offline_month_bundle(month: int, mode: str, idea: str, history: List[dict], case: CaseSeason) -> dict:
    """Deterministic offline month generator.

    Keeps the game playable when Gemini is unavailable (no API key, quota, network, SDK mismatch).
    Metric-free narrative to preserve suspense (no 'cash/MRR/churn' words).
    """
    seed = hash((st.session_state.get("run_id",""), case.seed, "offline", month, mode)) & 0xFFFFFFFF
    rng = random.Random(seed)

    tags = ["growth","efficiency","reliability","compliance","fundraising","people","product","sales","marketing","security"]

    tagA = rng.choice(tags)
    tagB = rng.choice([t for t in tags if t != tagA])

    def risk_for(tag: str) -> str:
        base = {"fundraising":"med","compliance":"med","security":"med","reliability":"med",
                "efficiency":"med","people":"med","product":"med","sales":"med","marketing":"med","growth":"high"}[tag]
        if mode in {"Zor","Spartan"} and rng.random() < 0.45:
            return "high"
        if mode == "Gerçekçi" and rng.random() < 0.25:
            return "low"
        return base

    step_bank = {
        "growth": [
            "Tek bir kanala odaklan: 2 hafta yoğun test, net hedef kitle ve teklif.",
            "Hızlı bir landing + demo akışı kur; günlük geri bildirim topla.",
            "Fiyat/packaging’i 1 değişkenle sadeleştir; satış konuşmasını standardize et.",
            "Haftalık 5 müşteri görüşmesi; itiraz haritası çıkar.",
            "Operasyonun kaldırabileceği kadar kapasite planı yap; aşırı söz verme.",
        ],
        "efficiency": [
            "Giderleri kalem kalem denetle; ilk 3 kaçak noktayı kes.",
            "Süreçleri yazılı hale getir; tekrarlayan işleri otomasyona taşı.",
            "En pahalı 1-2 aracı alternatifle değiştir (risk analiziyle).",
            "Performans ve öncelik matrisi: 'hemen' değil 'etkisi yüksek' işleri seç.",
            "Kritik rolleri koru; rastgele kesinti yerine hedefli optimizasyon yap.",
        ],
        "reliability": [
            "En çok sorun çıkaran modülü izleme/alert ile görünür yap.",
            "Kritik akışlara test + rollback planı ekle.",
            "Müşteri destek akışını triage ile düzene sok; SLA sözünü gerçekçi tut.",
            "Teknik borç listesi çıkar; 2 haftalık 'stabilizasyon sprint'i planla.",
            "Basit bir incident raporu rutini başlat: neden–ders–aksiyon.",
        ],
        "compliance": [
            "Sözleşme/kvkk maddelerini avukatla gözden geçir; riskli vaadi kaldır.",
            "Veri saklama ve erişim politikasını yaz; erişimleri daralt.",
            "Şikâyet/denetim senaryosu için tek sayfalık 'playbook' hazırla.",
            "Kritik kayıtları düzenle: log, onay, rıza, değişiklik izi.",
            "Büyük müşteri için uyum doküman seti hazırla (kısa ve net).",
        ],
        "fundraising": [
            "1 sayfalık hikâye + 8 slayt pitch iskeleti hazırla (problem–çözüm–kanıt).",
            "Hedef yatırımcı listesi + tanıştırma zinciri çıkar; haftada 10 temas.",
            "Due diligence klasörü: finans, sözleşmeler, ürün, roadmap.",
            "Alternatif finansman: gelir paylaşımı, müşteri ön ödemesi, hibeler.",
            "Görüşmeleri haftalık ritme bağla; takip e-postalarını sistemleştir.",
        ],
        "people": [
            "Rolleri netleştir: kim neyden sorumlu, hangi çıktı haftalık ölçülür.",
            "Tek bir kritik işe odaklı sprint planı; toplantıları %30 azalt.",
            "Ekip içi gerilim varsa 'çatışma çözüm' oturumu ve karar kaydı yap.",
            "İşe alım değilse: mevcut ekipte skill-gap kapatma planı çıkar.",
            "Performans geri bildirimi: kısa, yazılı ve düzenli.",
        ],
        "product": [
            "Kullanıcı yolculuğunda tek bir 'aha' anı seç; onu güçlendir.",
            "En çok talep edilen 3 özelliği değil, en büyük problemi çözeni yap.",
            "Onboarding’i kısalt; ilk değer anına giden adımları azalt.",
            "Haftalık demo: değişiklikleri müşteriye göster, geri bildirim al.",
            "Roadmap’i 4 haftaya indir; büyük vizyonu parçala.",
        ],
        "sales": [
            "Outbound listesi: ICP’ye göre 100 hedef; günlük 10 temas.",
            "Tek itiraz–tek cevap dokümanı çıkar; herkes aynı dili kullansın.",
            "Satış hunisini görünür yap; her hafta bir darboğazı düzelt.",
            "Demo şablonu + kapanış adımı standardize et (takvim linki, teklif paketi).",
            "Referans iste: memnun 3 müşteriden 1 tanıştırma.",
        ],
        "marketing": [
            "Bir ana mesaj seç; 3 içerik formatına dönüştür (post/video/mail).",
            "Case study yaz: önce/sonra hikâyesi + somut süreç.",
            "Topluluk/partner kanalı dene: 2 ortak webinar/etkinlik.",
            "SEO için 5 anahtar kelime: niyet yüksek sayfalara odaklan.",
            "Ölçüm altyapısı kur: UTM, dönüşüm olayı, haftalık rapor.",
        ],
        "security": [
            "En kritik varlıkları listele; erişimleri minimuma indir.",
            "MFA ve temel güvenlik hijyeni: ana hesaplar, paneller, repo.",
            "Zafiyet taraması + hızlı yamalama takvimi oluştur.",
            "Veri için şifreleme/backup kontrolü yap.",
            "Olay müdahale planı: kim, neyi, ne zaman yapar?",
        ],
    }

    hist = ""
    if history:
        last = history[-1]
        hist = f'Son ay "{last.get("choice_title","")}" yönünde ilerledin; bunun yan etkileri bu ay masaya geliyor.'

    case_line = ""
    if case.key != "free":
        case_line = f"Bu sezonun teması: {case.title} ({case.years}). Gerçek dinamiklerden esinlenen bir baskı katmanı var."

    tr_line = ""
    if mode == "Türkiye":
        tr_line = "Türkiye gerçekleri: tahsilat gecikmesi, kur oynaklığı, denetim ve sözleşme pratikleri kararları sertleştiriyor."

    durum = (
        f"Ay {month}. {case_line}\n\n"
        f"Girişim fikrin: {idea or '(boş)'}\n\n"
        f"{hist} {tr_line}\n\n"
        "Bu ay öncelik: tek bir kritik darboğazı seçip, diğer her şeyi bilinçli olarak ertelemek."
    )

    crisis_templates = [
        "Büyük bir müşteri ‘kanıt’ istiyor: süreç, güven ve teslim tarihleri aynı anda masada.",
        "Operasyonda bir çatlak büyüyor: küçük bir hata, zincirleme şikâyetleri tetikliyor.",
        "Pazarda rakip agresifleşti: fiyat kırıyor ve müşterileri hızlıca ikna ediyor.",
        "Ekip içinde karar yorgunluğu var: herkes farklı yöne çekiyor, hız düşüyor.",
        "Beklenmedik bir dış baskı çıktı: uyum/denetim/tedarik tarafında dosya açıldı.",
    ]
    kriz = rng.choice(crisis_templates)
    if mode == "Türkiye" and rng.random() < 0.6:
        kriz += " Üstüne bir de tahsilat gecikmesi ve kur oynaklığı planları sıkıştırıyor."

    kriz_text = (
        f"{kriz}\n\n"
        "Kriz tek bir noktada düğümleniyor: ya büyümeyi zorlayıp risk alacaksın ya da sistemi sağlamlaştırıp hızdan feragat edeceksin."
    )

    def make_option(tag: str, letter: str) -> dict:
        steps = step_bank[tag][:]
        rng.shuffle(steps)
        steps = steps[:5]
        title_map = {
            "growth":"Büyüme Atağı", "efficiency":"Maliyet & Odak", "reliability":"Stabilizasyon", "compliance":"Uyum Kalkanı",
            "fundraising":"Finansman Sprinti", "people":"Ekip Reset", "product":"Ürün Netleştirme", "sales":"Satış Baskısı",
            "marketing":"Dağıtım Hamlesi", "security":"Güvenlik Sertleşmesi"
        }
        return {
            "title": title_map.get(tag, f"Plan {letter}"),
            "steps": steps,
            "tag": tag,
            "risk": risk_for(tag),
            "delayed_seed": rng.choice([
                "Beklenmeyen geri tepki", "İç direnç büyüyor", "Teknik borç faturası",
                "Regülatör yakın takip", "Partner kırgınlığı", "Müşteri beklentisi şişiyor"
            ]),
        }

    return {
        "durum_analizi": durum.strip(),
        "kriz": kriz_text.strip(),
        "A": make_option(tagA, "A"),
        "B": make_option(tagB, "B"),
        "note": "Offline içerik üretimi (Gemini yok/başarısız). İstersen online olunca bu ayı yeniden üretebilirsin.",
    }


def generate_month_bundle(llm: GeminiLLM, month: int) -> Tuple[dict, str]:
    ss = st.session_state
    mode = get_locked("mode", ss["mode"])
    idea = get_locked("startup_idea", ss["startup_idea"])
    case = get_case(get_locked("case_key", ss["case_key"]))
    stats = ss["stats"]
    history = ss["history"]

    with st.sidebar.expander("🛠️ LLM Debug", expanded=False):
        if ss.get("llm_last_error"):
            st.write(f"**Son hata:** {ss.get('llm_last_error')}")
        raw = ss.get("llm_last_raw", "")
        rep = ss.get("llm_last_raw_repaired", "")
        if raw:
            st.caption("Son ham yanıt (kısaltılmış):")
            st.code(raw[:1500])
        if rep:
            st.caption("Onarım sonrası yanıt (kısaltılmış):")
            st.code(rep[:1500])

    status = llm.status()
    if (not status.ok) or ss.get("llm_disabled"):
        ss["llm_last_error"] = ss.get("llm_last_error") or (status.note or "Gemini kullanılamıyor.")
        return offline_month_bundle(month, mode, idea, history, case), "offline"

    prompt = build_prompt(month, mode, idea, history, case, stats)
    temperature = float(MODES.get(mode, MODES["Gerçekçi"])["temp"])

    try:
        data, raw = llm.generate_month_json(prompt, temperature=temperature, max_output_tokens=2200)
        ss["llm_last_raw"] = (raw or "")[:8000]
        if not data:
            raise ValueError("JSON parse edilemedi.")

        bundle = {
            "durum_analizi": str(data.get("durum_analizi", "")).strip(),
            "kriz": str(data.get("kriz", "")).strip(),
            "A": {
                "title": str((data.get("A") or {}).get("title", "Seçenek A")).strip(),
                "steps": normalize_steps((data.get("A") or {}).get("steps", [])),
                "tag": normalize_tag((data.get("A") or {}).get("tag", "growth")),
                "risk": normalize_risk((data.get("A") or {}).get("risk", "med")),
                "delayed_seed": str((data.get("A") or {}).get("delayed_seed", "")).strip()[:60],
            },
            "B": {
                "title": str((data.get("B") or {}).get("title", "Seçenek B")).strip(),
                "steps": normalize_steps((data.get("B") or {}).get("steps", [])),
                "tag": normalize_tag((data.get("B") or {}).get("tag", "growth")),
                "risk": normalize_risk((data.get("B") or {}).get("risk", "med")),
                "delayed_seed": str((data.get("B") or {}).get("delayed_seed", "")).strip()[:60],
            },
            "note": str(data.get("note", "") or "").strip()[:240],
        }

        if len(bundle["A"]["steps"]) < 4 or len(bundle["B"]["steps"]) < 4:
            raise ValueError("Seçenek adımları çok kısa geldi.")
        if len(bundle["durum_analizi"]) < 220 or len(bundle["kriz"]) < 220:
            raise ValueError("Metin çok kısa geldi.")

        ss["llm_fail_count"] = 0
        ss["llm_last_error"] = ""
        return bundle, "gemini"

    except Exception as e:
        ss["llm_last_error"] = f"{type(e).__name__}: {e}"
        ss["llm_fail_count"] = int(ss.get("llm_fail_count", 0)) + 1
        if ss["llm_fail_count"] >= 2:
            ss["llm_disabled"] = True
        return offline_month_bundle(month, mode, idea, history, case), "offline"
# =========================
# Game mechanics
# =========================

# Map tags to delta templates (these are "expected direction"; we add bounded noise)
TEMPLATES: Dict[str, Dict[str, Tuple[float, float]]] = {
    # (base, variance)
    "growth":       {"cash": (-60_000, 55_000), "mrr": (1_200, 900), "reputation": (3, 4), "support_load": (9, 6), "infra_load": (9, 6), "churn": (0.010, 0.010)},
    "efficiency":   {"cash": (40_000, 50_000),  "mrr": (-200, 350), "reputation": (-2, 4), "support_load": (-6, 6), "infra_load": (-6, 6), "churn": (0.004, 0.008)},
    "reliability":  {"cash": (-55_000, 45_000), "mrr": (-150, 250), "reputation": (4, 4), "support_load": (-10, 7), "infra_load": (-10, 7), "churn": (-0.008, 0.010)},
    "compliance":   {"cash": (-70_000, 55_000), "mrr": (-250, 250), "reputation": (6, 4), "support_load": (2, 4), "infra_load": (2, 4), "churn": (-0.004, 0.008)},
    "fundraising":  {"cash": (180_000, 160_000),"mrr": (0, 200),    "reputation": (1, 5), "support_load": (3, 4), "infra_load": (3, 4), "churn": (0.000, 0.006)},
    "people":       {"cash": (-45_000, 45_000), "mrr": (150, 250),  "reputation": (3, 4), "support_load": (-8, 7), "infra_load": (-5, 6), "churn": (-0.003, 0.008)},
    "product":      {"cash": (-50_000, 45_000), "mrr": (700, 650),  "reputation": (3, 4), "support_load": (-3, 6), "infra_load": (2, 5), "churn": (-0.006, 0.010)},
    "sales":        {"cash": (-25_000, 35_000), "mrr": (900, 850),  "reputation": (1, 4), "support_load": (4, 5), "infra_load": (3, 4), "churn": (0.006, 0.010)},
    "marketing":    {"cash": (-45_000, 45_000), "mrr": (650, 650),  "reputation": (4, 4), "support_load": (2, 4), "infra_load": (2, 4), "churn": (-0.002, 0.009)},
    "security":     {"cash": (-60_000, 50_000), "mrr": (-120, 250), "reputation": (5, 4), "support_load": (-6, 6), "infra_load": (-5, 6), "churn": (-0.006, 0.010)},
}

def rng_for(month: int, choice: str) -> random.Random:
    ss = st.session_state
    case = get_case(get_locked("case_key", ss["case_key"]))
    seed = hash((ss["run_id"], case.seed, month, choice)) & 0xFFFFFFFF
    return random.Random(seed)

def _sample_delta(tag: str, rng: random.Random, swing: float) -> Dict[str, float]:
    tpl = TEMPLATES.get(tag, TEMPLATES["growth"])
    d: Dict[str, float] = {}
    for k, (base, var) in tpl.items():
        # sample within [base-var, base+var]
        val = rng.uniform(base - var, base + var) * swing
        d[k] = float(val)
    # clamp churn delta to reasonable bounds
    d["churn"] = clamp(d["churn"], -0.05, 0.08)
    return d

def _mode_adjustments(d: Dict[str, float], rng: random.Random, mode: str) -> Dict[str, float]:
    spec = MODES.get(mode, MODES["Gerçekçi"])
    if spec.get("antagonistic"):
        # Spartan: add negative drift
        d["cash"] -= rng.uniform(10_000, 40_000) * spec["swing"]
        d["churn"] += rng.uniform(0.002, 0.010) * spec["swing"]
        d["reputation"] -= rng.uniform(0, 4) * spec["swing"]
    if mode == "Zor":
        # Slightly harsher volatility
        if rng.random() < 0.35:
            d["cash"] -= rng.uniform(5_000, 25_000) * spec["swing"]
    return d

def _case_bias(d: Dict[str, float], tag: str, month: int) -> Dict[str, float]:
    # Simple per-case bias: compliance/security matters more in privacy case, etc.
    ss = st.session_state
    case_key = get_locked("case_key", ss["case_key"])
    if case_key == "facebook_privacy_2019":
        if tag in {"compliance","security"}:
            d["reputation"] += 3.0
            d["churn"] -= 0.004
        if tag in {"growth","marketing"}:
            d["reputation"] -= 2.0
            d["churn"] += 0.004
    if case_key == "blackberry_platform_shift":
        if tag in {"product","growth","marketing"}:
            d["mrr"] += 250
        if tag == "reliability":
            d["mrr"] -= 150  # quality alone doesn't move market fast
    if case_key == "wework_ipo_2019":
        if tag == "fundraising":
            d["cash"] += 60_000
            d["reputation"] -= 1.5
        if tag == "efficiency":
            d["reputation"] += 1.5
    return d

def schedule_delayed_effect(month: int, choice: str, tag: str, risk: str, seed_phrase: str) -> None:
    ss = st.session_state
    mode = get_locked("mode", ss["mode"])
    spec = MODES.get(mode, MODES["Gerçekçi"])
    rng = rng_for(month, choice)

    p = {"low": 0.35, "med": 0.60, "high": 0.82}[risk]
    if spec.get("antagonistic"):
        p = min(0.95, p + 0.10)
    if rng.random() > p:
        return

    due = month + (1 if rng.random() < 0.6 else 2)
    # delayed tends to be more negative for risky growth/cuts
    delayed_tag = tag
    if tag == "efficiency":
        delayed_tag = "people" if rng.random() < 0.5 else "reliability"
    if tag == "growth":
        delayed_tag = "reliability" if rng.random() < 0.4 else "growth"

    base = _sample_delta(delayed_tag, rng, swing=0.55 * spec["swing"])
    # Make delayed "lean negative"
    base["cash"] -= abs(base["cash"]) * 0.25
    base["reputation"] -= max(0.0, base["reputation"]) * 0.15
    base["churn"] += abs(base["churn"]) * 0.35

    ss["delayed_queue"].append({
        "due_month": int(due),
        "delta": base,
        "hint": seed_phrase or "Gecikmeli etki",
        "from_month": int(month),
    })

def apply_due_delays(month: int) -> List[Dict[str, Any]]:
    ss = st.session_state
    due = [x for x in ss.get("delayed_queue", []) if int(x.get("due_month", 0)) == int(month)]
    if not due:
        return []
    ss["delayed_queue"] = [x for x in ss.get("delayed_queue", []) if int(x.get("due_month", 0)) != int(month)]
    return due

def turkey_macro_cost(month: int) -> float:
    # Deterministic-ish macro pressure: increases with month
    # We avoid mutating base expenses; this is "extra friction".
    ss = st.session_state
    case = get_case(get_locked("case_key", ss["case_key"]))
    seed = hash((ss["run_id"], case.seed, "turkey_macro", month)) & 0xFFFFFFFF
    rng = random.Random(seed)
    inflation = 0.03 + (0.01 * (month / 6.0))  # grows over time
    fx_shock = rng.uniform(-0.01, 0.05)
    audit = 0.0
    if rng.random() < 0.18:
        audit = rng.uniform(15_000, 85_000)
    disaster = 0.0
    if rng.random() < 0.06:
        disaster = rng.uniform(25_000, 160_000)
    # return extra cost
    return max(0.0, 0.0 + (inflation + fx_shock) * 40_000 + audit + disaster)

def apply_delta_to_stats(stats: dict, delta: Dict[str, float]) -> None:
    stats["cash"] = max(0.0, stats["cash"] + float(delta.get("cash", 0.0)))
    stats["mrr"] = max(0.0, stats["mrr"] + float(delta.get("mrr", 0.0)))
    stats["reputation"] = clamp(stats["reputation"] + float(delta.get("reputation", 0.0)), 0, 100)
    stats["support_load"] = clamp(stats["support_load"] + float(delta.get("support_load", 0.0)), 0, 100)
    stats["infra_load"] = clamp(stats["infra_load"] + float(delta.get("infra_load", 0.0)), 0, 100)
    stats["churn"] = clamp(stats["churn"] + float(delta.get("churn", 0.0)), 0.0, 0.50)

def step_month(choice: str) -> None:
    ss = st.session_state
    if ss.get("ended"):
        return

    month = int(ss["month"])
    if any(h.get("month") == month for h in ss.get("history", [])):
        ss["chat"].append({"role": "assistant", "kind": "warn", "content": f"🟨 Ay {month} için zaten seçim yaptın. Aynı ay tekrar işlenmez."})
        return

    bundle = ss["months"].get(month)
    if not bundle:
        return

    mode = get_locked("mode", ss["mode"])
    spec = MODES.get(mode, MODES["Gerçekçi"])
    stats = ss["stats"]

    # Apply delayed effects due this month (before new choice)
    due = apply_due_delays(month)
    for ev in due:
        apply_delta_to_stats(stats, ev.get("delta", {}))
        ss["chat"].append({
            "role": "assistant",
            "kind": "note",
            "content": f"⏳ **Gecikmeli etki (Ay {month})** — {ev.get('hint','Yan etki')} (Ay {ev.get('from_month','?')} kararının sonucu).",
        })

    # Monthly expenses
    total_exp = float(sum(ss["expenses"].values()))
    macro_extra = 0.0
    if spec.get("turkey"):
        macro_extra = turkey_macro_cost(month)
    stats["cash"] = max(0.0, stats["cash"] - total_exp - macro_extra)

    # Immediate delta based on choice profile
    choice_obj = bundle.get(choice, {})
    tag = str(choice_obj.get("tag", "growth"))
    risk = str(choice_obj.get("risk", "med"))
    seed_phrase = str(choice_obj.get("delayed_seed", "")).strip()

    rng = rng_for(month, choice)
    swing = float(spec["swing"])
    delta = _sample_delta(tag, rng, swing=swing)
    delta = _mode_adjustments(delta, rng, mode)
    delta = _case_bias(delta, tag, month)

    apply_delta_to_stats(stats, delta)

    # Schedule delayed effects
    schedule_delayed_effect(month, choice, tag, risk, seed_phrase)

    # Log to chat & history
    choice_title = str(choice_obj.get("title", f"Seçenek {choice}")).strip()
    note = (ss.get("pending_note") or "").strip()
    reason = (ss.get("pending_reason") or "").strip()

    ss["chat"].append({"role": "user", "kind": "choice", "content": f"{choice} seçtim: **{choice_title}**"})
    if reason:
        ss["chat"].append({"role": "user", "kind": "note", "content": f"📝 Gerekçem: {reason}"})
    if note:
        ss["chat"].append({"role": "user", "kind": "note", "content": f"🗒️ Not: {note}"})

    result_lines = [
        f"- **Kasa:** {money(stats['cash'])}",
        f"- **MRR:** {money(stats['mrr'])}",
        f"- **İtibar:** {int(stats['reputation'])}/100",
        f"- **Support yükü:** {int(stats['support_load'])}/100",
        f"- **Altyapı yükü:** {int(stats['infra_load'])}/100",
        f"- **Kayıp oranı:** {pct(stats['churn'])}",
    ]
    if macro_extra > 0:
        result_lines.append(f"- **Türkiye makro ek maliyet:** {money(macro_extra)}")

    ss["chat"].append({"role": "assistant", "kind": "result", "content": "✅ Seçimin işlendi. Güncel durum:\n\n" + "\n".join(result_lines)})

    ss["history"].append({
        "month": month,
        "choice": choice,
        "choice_title": choice_title,
        "note": note,
        "reason": reason,
        "tag": tag,
        "risk": risk,
        "delta": delta,
    })
    ss["pending_note"] = ""
    ss["pending_reason"] = ""

    # Advance month / end season
    if month < int(get_locked("season_length", ss["season_length"])):
        ss["month"] = month + 1
    else:
        ss["ended"] = True
        ss["month"] = int(get_locked("season_length", ss["season_length"])) + 1
        ss["chat"].append({"role": "assistant", "kind": "end", "content": "🏁 Sezon bitti. Özet aşağıda."})


# =========================
# Month preparation
# =========================

def ensure_month_ready(llm: GeminiLLM, month: int) -> None:
    ss = st.session_state
    if ss.get("ended"):
        return
    if month in ss["months"]:
        return
    try:
        bundle, source = generate_month_bundle(llm, month)
    except Exception as e:
        ss["fatal_error"] = f"{type(e).__name__}: {e}"
        ss["fatal_where"] = f"Ay {month} içerik üretimi"
        return

    ss["months"][month] = bundle
    ss["month_sources"][month] = source

    ss["chat"].append({"role": "assistant", "kind": "analysis", "content": f"**🧩 Durum Analizi (Ay {month})**\n\n{bundle['durum_analizi']}"})
    ss["chat"].append({"role": "assistant", "kind": "crisis", "content": f"**⚠️ Kriz (Ay {month})**\n\n{bundle['kriz']}"})
    if bundle.get("note"):
        ss["chat"].append({"role": "assistant", "kind": "note", "content": f"🗒️ {bundle['note']}"})


# =========================
# UI
# =========================

def render_sidebar(llm: GeminiLLM) -> None:
    ss = st.session_state
    stats = ss["stats"]
    locked = is_locked()

    st.sidebar.markdown(f"## 🧑‍💻 {html_escape(get_locked('founder_name', ss['founder_name']))}")
    st.sidebar.markdown(f"<div class='muted smallcaps'>v{APP_VERSION}</div>", unsafe_allow_html=True)

    # Mode
    st.sidebar.markdown("### Mod")
    if not locked:
        ss["mode"] = st.sidebar.selectbox("Mod", list(MODES.keys()), index=list(MODES.keys()).index(ss["mode"]), label_visibility="collapsed")
        st.sidebar.caption(MODES[ss["mode"]]["desc"])
    else:
        st.sidebar.write(f"**{get_locked('mode')}**")
        st.sidebar.caption(MODES[get_locked('mode')]["desc"])

    # Case selection
    st.sidebar.markdown("### Vaka sezonu")
    case_titles = [c.title for c in CASE_LIBRARY]
    cur_idx = next((i for i, c in enumerate(CASE_LIBRARY) if c.key == ss["case_key"]), 0)
    if not locked:
        chosen_title = st.sidebar.selectbox("Vaka", case_titles, index=cur_idx, label_visibility="collapsed")
        chosen = next(c for c in CASE_LIBRARY if c.title == chosen_title)
        ss["case_key"] = chosen.key
    else:
        chosen = get_case(get_locked("case_key", ss["case_key"]))
        st.sidebar.write(f"**{chosen.title}**")
    st.sidebar.caption(chosen.blurb)

    if chosen.key != "free":
        st.sidebar.markdown(f"<span class='pill ok'>True Story</span> <span class='pill'>{chosen.years}</span>", unsafe_allow_html=True)
        with st.sidebar.expander("Kaynaklar (spoiler içerebilir)", expanded=False):
            for t, url in chosen.sources:
                st.markdown(f"- [{t}]({url})")

    # Season length
    st.sidebar.markdown("### Sezon uzunluğu (ay)")
    if not locked:
        ss["season_length"] = int(st.sidebar.slider("Sezon uzunluğu (ay)", 6, 24, int(ss["season_length"]), 1))
    else:
        st.sidebar.write(f"**{get_locked('season_length')} ay**")
    st.sidebar.progress(min(1.0, int(ss["month"]) / max(1, int(get_locked("season_length", ss["season_length"])))))
    st.sidebar.caption(f"Ay: {int(ss['month'])}/{int(get_locked('season_length', ss['season_length']))}")

    # Start cash
    st.sidebar.markdown("### Başlangıç kasası")
    if not locked:
        ss["start_cash"] = int(st.sidebar.slider("Başlangıç kasası", 50_000, 2_000_000, int(ss["start_cash"]), 50_000))
        # live preview of starting stats
        arch = next((a for a in ARCHETYPES if a.key == ss["archetype_key"]), ARCHETYPES[0])
        ss["stats"] = default_stats(int(ss["start_cash"] * arch.cash_mult), arch)
    else:
        st.sidebar.write(money(get_locked("start_cash", int(stats["cash"]))))

    # Current financials
    st.sidebar.markdown("## Finansal Durum")
    st.sidebar.metric("Kasa", money(stats["cash"]))
    st.sidebar.metric("MRR", money(stats["mrr"]))

    with st.sidebar.expander("Aylık Gider Detayı", expanded=False):
        total = 0
        for k, v in ss["expenses"].items():
            st.write(f"- {k}: {money(v)}")
            total += v
        st.write(f"**TOPLAM:** {money(total)}")
        if MODES.get(get_locked("mode", ss["mode"]), {}).get("turkey") and locked:
            st.caption("Türkiye modunda her ay ek makro maliyet doğabilir (enflasyon/kur/denetim/afet).")

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
        st.sidebar.caption(f"Anahtarlar: {len(llm.api_keys)}")
        st.sidebar.caption(f"Backend: {status.backend}")
    else:
        msg = ss.get("llm_last_error") or status.note or "Gemini erişilemiyor."
        st.sidebar.warning(f"Gemini kullanılamıyor. Offline içerik üretimi devrede. {msg[:140]}")

    # Eğer bu ay offline üretildiyse (JSON format problemi), kullanıcı tek tıkla yeniden denesin.
    cur_m = int(ss.get("month", 1))
    if ss.get("started") and not ss.get("ended") and ss.get("month_sources", {}).get(cur_m) == "offline" and status.ok and not ss.get("llm_disabled"):
        if st.sidebar.button("🔁 Bu ayı Gemini ile yeniden üret", use_container_width=True):
            try:
                if cur_m in ss.get("months", {}):
                    del ss["months"][cur_m]
                ss.get("month_sources", {}).pop(cur_m, None)
            except Exception:
                pass
            ss["llm_last_error"] = ""
            st.rerun()


    if ss.get("llm_disabled"):
        if st.sidebar.button("Gemini\'yi yeniden dene", use_container_width=True):
            ss["llm_disabled"] = False
            ss["llm_fail_count"] = 0
            ss["llm_last_error"] = ""
            st.rerun()

    if st.sidebar.button("Oyunu sıfırla", use_container_width=True):
        reset_game(keep_settings=False)
        st.rerun()

def render_header() -> None:
    c1, c2 = st.columns([0.72, 0.28])
    with c1:
        st.markdown(f"# {APP_TITLE}")
        st.caption(APP_SUBTITLE)
    with c2:
        ss = st.session_state
        if ss.get("started"):
            arch = next((a for a in ARCHETYPES if a.key == get_locked("archetype_key", ss["archetype_key"])), ARCHETYPES[0])
            with st.expander("🧑‍💻 Karakter (kilitli)", expanded=False):
                st.write(f"**{get_locked('founder_name')}** — {arch.title}")
                st.caption(arch.blurb)
        else:
            with st.expander("🧑‍💻 Karakterini seç (sezon başında kilitlenir)", expanded=True):
                st.session_state["founder_name"] = st.text_input("Karakter adı", value=st.session_state.get("founder_name", "İsimsiz Girişimci"))
                titles = [a.title for a in ARCHETYPES]
                cur_idx = next((i for i,a in enumerate(ARCHETYPES) if a.key == ss.get("archetype_key")), 0)
                pick_title = st.selectbox("Arketip", titles, index=cur_idx)
                ss["archetype_key"] = next(a.key for a in ARCHETYPES if a.title == pick_title)

                if st.button("🎲 Rastgele karakter", use_container_width=True):
                    rng = random.Random(hash((ss["run_id"], "randchar")) & 0xFFFFFFFF)
                    a = rng.choice(ARCHETYPES)
                    ss["archetype_key"] = a.key
                    names = ["Başar", "Deniz", "Ece", "Mert", "Zeynep", "Kerem", "Elif", "Cem", "İrem", "Can"]
                    ss["founder_name"] = rng.choice(names) + " " + rng.choice(["Kaya", "Yılmaz", "Demir", "Aydın", "Şahin"])
                    st.rerun()


def render_start_screen() -> None:
    ss = st.session_state
    st.markdown("<hr class='soft'/>", unsafe_allow_html=True)
    st.info("Oyuna başlamak için girişim fikrini yaz. Sezon başladıktan sonra mod/vaka/para/karakter kilitlenir.")
    ss["startup_idea"] = st.text_area(
        "Girişim fikrin ne?",
        value=ss["startup_idea"],
        height=140,
        placeholder="Örn: KOBİ'ler için otomatik fatura takibi + tahsilat hatırlatma...",
    )

    arch = next((a for a in ARCHETYPES if a.key == ss["archetype_key"]), ARCHETYPES[0])
    st.markdown("### Başlangıç özeti")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.write(f"**Mod:** {ss['mode']}")
        st.caption(MODES[ss["mode"]]["desc"])
    with c2:
        case = get_case(ss["case_key"])
        st.write(f"**Vaka:** {case.title}")
        if case.key != "free":
            st.caption(f"True Story · {case.years}")
        else:
            st.caption(case.blurb)
    with c3:
        st.write(f"**Karakter:** {ss['founder_name']} — {arch.title}")
        st.caption(arch.blurb)

    if not ss["startup_idea"].strip():
        st.warning("Başlamak için girişim fikrini yazmalısın.")
        return

    if st.button("🚀 Sezonu başlat", type="primary", use_container_width=True):
        # Hard reset but keep chosen settings
        reset_game(keep_settings=True)
        ss["started"] = True
        ss["ended"] = False
        ss["month"] = 1
        ss["history"] = []
        ss["months"] = {}
        ss["chat"] = []
        ss["delayed_queue"] = []
        ss["llm_disabled"] = False
        ss["llm_last_error"] = ""

        # lock settings and reset stats based on archetype
        lock_settings()
        arch2 = next((a for a in ARCHETYPES if a.key == ss["archetype_key"]), ARCHETYPES[0])
        ss["stats"] = default_stats(int(ss["start_cash"] * arch2.cash_mult), arch2)

        # Opening message
        case = get_case(get_locked("case_key"))
        intro = f"Sezon başladı. **{case.title}**"
        if case.key != "free":
            intro += f" · <span class='pill ok'>True Story</span> <span class='pill'>{case.years}</span>"
        st.session_state["chat"].append({"role":"assistant","kind":"note","content":intro})
        st.rerun()


def render_season_summary() -> None:
    ss = st.session_state
    stats = ss["stats"]
    case = get_case(get_locked("case_key", ss["case_key"]))

    st.markdown("## 🏁 Sezon Özeti")
    st.write("Final durum:")
    st.write(
        f"- **Kasa:** {money(stats['cash'])}\n"
        f"- **MRR:** {money(stats['mrr'])}\n"
        f"- **İtibar:** {int(stats['reputation'])}/100\n"
        f"- **Support yükü:** {int(stats['support_load'])}/100\n"
        f"- **Altyapı yükü:** {int(stats['infra_load'])}/100\n"
        f"- **Kayıp oranı:** {pct(stats['churn'])}"
    )

    with st.expander("Seçim geçmişi", expanded=False):
        if not ss["history"]:
            st.caption("Seçim yok.")
        else:
            for h in ss["history"]:
                st.markdown(
                    f"- Ay {h['month']}: **{h['choice']}** — {h['choice_title']} "
                    f"(<span class='pill'>{tag_label(h.get('tag',''))}</span> "
                    f"<span class='pill warn'>{risk_label(h.get('risk',''))}</span>)",
                    unsafe_allow_html=True,
                )
                if h.get("reason"):
                    st.caption(f"Gerekçe: {h['reason']}")
                if h.get("note"):
                    st.caption(f"Not: {h['note']}")

    if case.key != "free":
        with st.expander("Gerçekte ne oldu? (spoiler)", expanded=False):
            for bullet in case.real_outcome:
                st.markdown(f"- {bullet}")
            st.markdown("**Kaynaklar:**")
            for t, url in case.sources:
                st.markdown(f"- [{t}]({url})")

def render_chat_and_choices(llm: GeminiLLM) -> None:
    ss = st.session_state
    month = int(ss["month"])
    season_length = int(get_locked("season_length", ss["season_length"]))

    # Prepare month content only if season ongoing
    if not ss.get("ended") and month <= season_length:
        ensure_month_ready(llm, month)

    # Render chat log
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
        elif kind == "end":
            avatar = "🏁"

        with st.chat_message(role, avatar=avatar):
            st.markdown(msg.get("content", ""))

    # If season ended, show summary and stop
    if ss.get("ended") or month > season_length:
        render_season_summary()
        return

    bundle = ss["months"].get(month)
    if not bundle:
        return

    mode = get_locked("mode", ss["mode"])
    spec = MODES.get(mode, MODES["Gerçekçi"])

    st.markdown("<hr class='soft'/>", unsafe_allow_html=True)
    st.subheader(f"Ay {month}: Kararını ver")

    # Optional reason for Zor/Spartan
    if spec.get("require_reason"):
        ss["pending_reason"] = st.text_area(
            "1–3 cümle: Bu ay neden bu kararı vereceksin? (Zor/Spartan modu)",
            value=ss.get("pending_reason", ""),
            height=80,
            placeholder="Örn: Runway kısa, güveni koruyup riskli büyümeyi ertelemeliyim çünkü ...",
        )

    ss["pending_note"] = st.text_input("Opsiyonel not", value=ss.get("pending_note", ""), placeholder="Kendine not: ...")

    cA, cB = st.columns(2, gap="large")

    def render_choice(col, key: str) -> None:
        obj = bundle.get(key, {})
        title = html_escape(str(obj.get("title", f"Seçenek {key}")))
        steps = obj.get("steps", [])
        tag = str(obj.get("tag","growth"))
        risk = str(obj.get("risk","med"))
        with col:
            st.markdown(
                f"<div class='choice'><h4>{key}. {title}</h4>"
                f"<span class='pill'>{tag_label(tag)}</span> "
                f"<span class='pill warn'>{risk_label(risk)}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
            for s in steps:
                st.write(f"- {s}")

            disabled = False
            if spec.get("require_reason") and not (ss.get("pending_reason") or "").strip():
                disabled = True

            if st.button(f"{key} seç", key=f"btn_{month}_{key}", use_container_width=True, disabled=disabled):
                if spec.get("require_reason") and not (ss.get("pending_reason") or "").strip():
                    ss["chat"].append({"role":"assistant","kind":"warn","content":"🟨 Bu modda seçim yapmadan önce kısa bir gerekçe yazmalısın."})
                    st.rerun()
                step_month(key)
                st.rerun()

    render_choice(cA, "A")
    render_choice(cB, "B")


def render_main(llm: GeminiLLM) -> None:
    ss = st.session_state
    if ss.get("fatal_error"):
        st.error(f"Gemini içerik üretiminde hata: {ss.get('fatal_where','')} — {ss['fatal_error']}")
        colA, colB = st.columns(2)
        with colA:
            if st.button("🔁 Tekrar dene (bu ay)", use_container_width=True):
                cur = int(ss.get("month", 1))
                ss["months"].pop(cur, None)
                ss["month_sources"].pop(cur, None)
                ss["fatal_error"] = ""
                ss["fatal_where"] = ""
                st.rerun()
        with colB:
            if st.button("🧹 Hata durumunu temizle", use_container_width=True):
                ss["fatal_error"] = ""
                ss["fatal_where"] = ""
                st.rerun()

        with st.expander("🛠️ Debug: Son Gemini yanıtı"):
            raw = ss.get("llm_last_raw", "")
            rep = ss.get("llm_last_raw_repaired", "")
            if raw:
                st.caption("Ham yanıt (kısaltılmış):")
                st.code(raw[:3000])
            if rep:
                st.caption("Onarım sonrası (kısaltılmış):")
                st.code(rep[:3000])
        st.stop()

    render_header()

    if not ss.get("started"):
        render_start_screen()
        return

    render_chat_and_choices(llm)


def main() -> None:
    init_state()
    llm = GeminiLLM.from_env_or_secrets()
    render_sidebar(llm)
    render_main(llm)

if __name__ == "__main__":
    main()
