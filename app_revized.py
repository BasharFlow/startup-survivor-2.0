# app.py
import os
import json
import random
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple

import streamlit as st

# Gemini
import google.generativeai as genai


APP_TITLE = "Startup Survivor RPG"
MODEL_NAME = "gemini-2.5-flash"

genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))


def money(n: float) -> str:
    try:
        n = float(n)
    except Exception:
        n = 0.0
    return f"{int(round(n)):,}".replace(",", ".") + " ₺"


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def pick_weighted(items: List[Tuple[Any, float]], rng: random.Random):
    total = sum(w for _, w in items)
    r = rng.random() * total
    upto = 0.0
    for item, w in items:
        upto += w
        if upto >= r:
            return item
    return items[-1][0]


def safe_get_model():
    return genai.GenerativeModel(MODEL_NAME)


def llm_json(prompt: str, temperature: float = 0.9, max_output_tokens: int = 1100) -> Dict[str, Any]:
    model = safe_get_model()
    resp = model.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        ),
    )
    text = (resp.text or "").strip()
    if text.startswith("```"):
        # Strip ```json fences
        parts = text.split("```", 2)
        if len(parts) >= 2:
            text = parts[1].strip()
            if text.startswith("json"):
                text = text[4:].strip()

    try:
        return json.loads(text)
    except Exception:
        l = text.find("{")
        r = text.rfind("}")
        if l != -1 and r != -1 and r > l:
            try:
                return json.loads(text[l : r + 1])
            except Exception:
                pass
    return {"error": "json_parse_failed", "raw": text}


@dataclass
class Metrics:
    cash: float
    mrr: float
    churn: float        # 0..1
    reputation: float   # 0..100
    support_load: float # 0..100
    infra: float        # 0..100 (higher = better)

    @property
    def burn(self) -> float:
        base_cost = 55_000
        cost = base_cost + (self.support_load * 250) + ((100 - self.infra) * 180)
        return cost

    def apply_deltas(self, d: Dict[str, float]):
        self.cash += float(d.get("cash", 0))
        self.mrr = max(0.0, self.mrr + float(d.get("mrr", 0)))
        self.churn = clamp(self.churn + float(d.get("churn", 0)), 0.0, 0.95)
        self.reputation = clamp(self.reputation + float(d.get("reputation", 0)), 0.0, 100.0)
        self.support_load = clamp(self.support_load + float(d.get("support_load", 0)), 0.0, 100.0)
        self.infra = clamp(self.infra + float(d.get("infra", 0)), 0.0, 100.0)

    def month_tick(self):
        self.cash += self.mrr - self.burn
        self.cash = max(-10_000_000, self.cash)


def init_state():
    if "game" not in st.session_state:
        st.session_state.game = {
            "started": False,
            "idea": "",
            "mode": "Extreme",
            "month": 1,
            "months_total": 12,
            "rng_seed": 42,
            "last_event_family": None,
            "recent_titles": [],
            "chat": [],
            "metrics": Metrics(
                cash=1_000_000,
                mrr=0,
                churn=0.12,
                reputation=55,
                support_load=35,
                infra=65,
            ),
        }


MODE_DESCRIPTIONS = {
    "Realist": "Dengeli, profesyonel, gerçek dünyaya yakın piyasa/operasyon kararları.",
    "Hard": "Kaynak kıt. Her kararın bedeli var. Kolay çıkış yok.",
    "Spartan": "Acımasız ayı piyasası. Engeller maksimum. Hata affetmez.",
    "Extreme": "Kaos. Absürt olaylar. Mantık ikinci planda. Ama sonuçlar metriklere çarpar.",
    "Türkiye": "Türkiye şartları: kur/enflasyon/ödemeler/bürokrasi/tedarik/işgücü gerçekliği. Dengeli ama sert.",
}

EXTREME_FAMILIES = [
    ("social_platform", 0.50),
    ("surreal_metaphor", 0.30),
    ("scifi_cameo", 0.20),
]

EXTREME_SEEDS = {
    "social_platform": [
        "Bir influencer ürününü övüyor ama yanlış özelliği 'efsane' diye anlatıyor; beklenmedik kitle akıyor.",
        "Platform algoritması seni 'ilişki koçu' etiketiyle keşfete sokuyor; kullanıcılar bambaşka beklentiyle geliyor.",
        "Bir TikTok trendi ürün adınla aynı kelimeyi kullanıyor; herkes yanlışlıkla seni etiketliyor.",
        "Bir kurumsal LinkedIn postu seni 'Case Study' diye paylaşıyor; ama cümlelerin yarısı yanlış çevrilmiş.",
        "Kullanıcılar 'challenge' başlatıyor: ürünü en saçma yerde kullanma yarışı—support patlıyor.",
        "Bir mem sayfası seni 'startup'ın en komik bug’ı' diye paylaşıyor; itibar ve trafik aynı anda çarpışıyor.",
        "App store yorumlarında tek emoji akımı başlıyor; rating dalgalanıyor, kimse nedenini bilmiyor.",
        "Bir ünlü yanlışlıkla aboneliğe basıp story atıyor: 'Bu ne ya?'—tam da viral oluyor.",
        "Rakip, senin ekran görüntünü 'bizde yok' diye paylaşıyor; insanlar senden o özelliği talep ediyor.",
        "Kullanıcılar ürününü 'ters kullanınca' daha komik buluyor; gerçek kullanım düşüyor ama paylaşım artıyor.",
        "Bir podcast sunucusu seni yanlış okuyup yeni bir jargon uyduruyor; herkes o kelimeyle ürününü arıyor.",
        "Bir marka senin adını yanlışlıkla kampanyaya koyuyor; support'a 'indirim kodu çalışmıyor' yağmuru geliyor.",
        "Kullanıcılar 'AI bunu dedi' diye ekran görüntüsü paylaşıyor; senin sistem mesajın mem oluyor.",
        "Bir spam bot ordusu ürününü 'en romantik çeviri' diye dolduruyor; MRR artıyor ama chargeback kokusu var.",
        "Bir topluluk seni 'bunu asla yapma' listesine koyuyor; ters psikolojiyle kayıt patlıyor.",
    ],
    "surreal_metaphor": [
        "Evren, ürün açıklamanı her sabah başka bir cümleye çeviriyor; ekip aynı sayfayı bulamıyor.",
        "Metrikler konuşmaya başlıyor: churn seni arayıp 'ben gidiyorum' diyor, support 'ben bittim' diye ağlıyor.",
        "Her demo sırasında sunucu, sadece en kritik anda 'naz yapıyor'—sanki bilinçli.",
        "Kullanıcılar ürünü 'şans getiren uygulama' sanıyor; verim değil ritüel için geliyorlar.",
        "Toplantı odasında gerçeklik kayıyor: herkes aynı problemi farklı görüyor ve hepsi haklı gibi.",
        "Ürün, kullanıcıların dilini değil 'niyetini' çeviriyor; yanlış anlaşılmalar romantik/komik kriz çıkarıyor.",
        "Roadmap'in duvarda asılı post-it’leri gece kendi kendine yer değiştiriyor; sabah herkes başka şeye çalışmış.",
    ],
    "scifi_cameo": [
        "Bir AR filtresi hatası yüzünden ürünün uzaylı meme’ine dönüşüyor; talep patlıyor, altyapı çöküyor.",
        "Bir yapay zekâ bot ağı seni 'en iyi çevirmen' ilan ediyor; botlar abone oluyor, faturalar kabarıyor.",
        "Güneş patlaması gibi bir şey: bildirimler gecikiyor, kullanıcılar komplo kuruyor; churn dalgalanıyor.",
        "Zaman çizgisi kayması: dünün verisi bugüne akıyor; herkes yanlış karar veriyor.",
    ],
}

TURKEY_SEEDS = [
    "Kur bir haftada zıplıyor; yabancı servis maliyetin TL’de ikiye katlanıyor.",
    "Ödeme sağlayıcısı 'risk' nedeniyle ek doğrulama istiyor; dönüşüm düşüyor.",
    "KDV/stopaj/masraf kalemleri tahmin edilenden yüksek geliyor; nakit akışı sıkışıyor.",
    "Tedarik/outsourcing maliyeti enflasyonla artıyor; ekip maaş beklentisi güncelleniyor.",
    "Reklam maliyetleri dalgalanıyor; CAC bir anda bozuluyor, büyüme yavaşlıyor.",
    "B2B görüşmeleri uzuyor: 'bir üstten onay' döngüsü; satış döngüsü şişiyor.",
]


def mode_style_block(mode: str) -> str:
    if mode == "Realist":
        return (
            "Ton: profesyonel, ölçülü, gerçekçi. Absürt mizah YOK.\n"
            "Olaylar: piyasa, ürün, satış, finans, operasyon. Gerçek dünya mantığı.\n"
        )
    if mode == "Hard":
        return (
            "Ton: ciddi, sert ama adil. Her seçeneğin bedeli (trade-off) var.\n"
            "Olaylar: bütçe kısıtları, zor pazarlıklar, kapasite, gelir-gider gerilimi.\n"
        )
    if mode == "Spartan":
        return (
            "Ton: acımasız ayı piyasası. Kötümser ama net.\n"
            "Olaylar: hukuki/teknik/finansal engeller, kriz üstüne kriz, şans minimum.\n"
        )
    if mode == "Türkiye":
        return (
            "Ton: Türkiye gerçekliği. Dengeli ama gerçekçi. Mizah olabilir ama absürt değil.\n"
            "Olaylar: kur/enflasyon/ödeme/vergiler/tedarik/işgücü, yerel pazar dinamikleri.\n"
        )
    return (
        "Ton: kaotik, komik, paylaşılabilir, özgün. Danışman gibi konuşma YASAK.\n"
        "Olaylar: %80 sosyal medya/platform/influencer/kurumsal saçmalık/kullanıcı davranışı absürtlüğü.\n"
        "%15 abartılmış gerçek/sürreal metafor.\n"
        "%5 sci-fi cameo çok nadir ama etkisi gerçek.\n"
        "Kural: Ne kadar saçma olursa olsun, sonuçlar mutlaka metriklere bağlanacak.\n"
    )


def build_turn_prompt(state: Dict[str, Any], event_seed: str = None, event_family: str = None) -> str:
    m: Metrics = state["metrics"]
    mode = state["mode"]
    month = state["month"]
    idea = state["idea"]

    recent_titles = state.get("recent_titles", [])[-3:]
    last_family = state.get("last_event_family")

    last_msgs = state["chat"][-4:]
    history_compact = []
    for msg in last_msgs:
        role = msg.get("role", "assistant")
        content = (msg.get("content", "") or "").strip()
        if len(content) > 400:
            content = content[:400] + "…"
        history_compact.append(f"{role.upper()}: {content}")
    history_compact_str = "\n".join(history_compact) if history_compact else "(yok)"

    seed_block = ""
    if event_seed:
        seed_block = f"\nBu ay olay tohumu (mutlaka kullan): {event_seed}\nOlay ailesi: {event_family}\n"
    else:
        seed_block = "\nBu ay olay tohumu: (serbest)\n"

    ban_block = ""
    if recent_titles:
        ban_block = f"\nTekrar yasağı: Aşağıdaki başlık/kalıpları tekrarlama veya yakın benzerini yazma: {recent_titles}\n"
    if last_family:
        ban_block += f"Tekrar yasağı: Bir önceki olay ailesi '{last_family}' idi. Bu ay mümkünse farklı bir aile seç.\n"

    return f"""
Sen bir "startup RPG" tur motorusun. Çıktıyı SADECE geçerli JSON ver.

{mode_style_block(mode)}

GİRİŞİM FİKRİ:
{idea}

MEVCUT DURUM (Ay {month}):
- Kasa: {money(m.cash)}
- MRR: {money(m.mrr)}
- Churn: {round(m.churn*100,1)}%
- İtibar: {round(m.reputation,1)}/100
- Support yükü: {round(m.support_load,1)}/100
- Altyapı (stabilite): {round(m.infra,1)}/100
- Aylık gider (yaklaşık burn): {money(m.burn)}

SOHBET BAĞLAMI (son mesajlar):
{history_compact_str}

{seed_block}
{ban_block}

İSTENEN YAPI (sırayı bozma):
1) "durum_analizi": 1 paragraf, hikayesel ve özgün. Fikri yorumla ama danışman gibi ders verme.
   UYARI: "sahnede/yer kayıyor" gibi tekrar eden metaforları KULLANMA.
2) "kriz": 2-4 cümle, detaylı. Kriz başlığı + ne oldu + neden oldu + metriklere etkisi
   (en az 3 metrik adı geçsin: kasa/mrr/churn/itibar/support/altiyapi).
3) "secenekler": iki seçenek:
   - "A": başlık + 1 paragraf (çözüm planı + risk/bedel). Ne çok kısa ne çok uzun.
   - "B": başlık + 1 paragraf (çözüm planı + risk/bedel). Ne çok kısa ne çok uzun.
4) "deltalar": A ve B için yaklaşık etkiler:
   - "A": {{cash, mrr, churn, reputation, support_load, infra}}
   - "B": {{cash, mrr, churn, reputation, support_load, infra}}

ÖNEMLİ:
- Aynı kriz cümlelerini ve aynı durum analizi kalıbını tekrar etme.
- Extreme modda olay mutlaka komik/absürt ve paylaşılabilir olsun. Danışman tonu yasak.
- Türkiye modunda gerçek Türkiye koşullarına benzesin (kur/enflasyon/ödeme/vergiler vs).
- Spartan modda acımasız ol, kurtuluş zor olsun.

JSON ŞEMASI:
{{
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
    "A": {{ "cash": number, "mrr": number, "churn": number, "reputation": number, "support_load": number, "infra": number }},
    "B": {{ "cash": number, "mrr": number, "churn": number, "reputation": number, "support_load": number, "infra": number }}
  }},
  "event_family": "string",
  "title_fingerprint": "string"
}}
""".strip()


def choose_event_for_mode(state: Dict[str, Any], rng: random.Random) -> Tuple[str, str]:
    mode = state["mode"]
    if mode == "Extreme":
        last_family = state.get("last_event_family")
        picked = pick_weighted(EXTREME_FAMILIES, rng)
        if picked == last_family and rng.random() < 0.85:
            picked = pick_weighted(EXTREME_FAMILIES, rng)
        seed = rng.choice(EXTREME_SEEDS[picked])
        return seed, picked

    if mode == "Türkiye":
        return rng.choice(TURKEY_SEEDS), "turkiye"

    return None, mode.lower()


def apply_choice_and_advance(state: Dict[str, Any], choice: str, deltas: Dict[str, Any]):
    m: Metrics = state["metrics"]
    m.apply_deltas(deltas.get(choice, {}))
    m.month_tick()
    state["month"] += 1


def generate_turn(state: Dict[str, Any]) -> Dict[str, Any]:
    rng = random.Random(state["rng_seed"] + state["month"] * 101)

    event_seed, event_family = choose_event_for_mode(state, rng)
    prompt = build_turn_prompt(state, event_seed=event_seed, event_family=event_family)

    out = llm_json(
        prompt,
        temperature=0.95 if state["mode"] == "Extreme" else 0.75,
        max_output_tokens=1200,
    )

    if "error" in out:
        out = {
            "durum_analizi": "Bu turda motor tökezledi. Aynı turu tekrar üretmek için bir seçim yap.",
            "kriz": {"baslik": "JSON Krizi", "metin": "Model düzgün JSON üretmedi. Tekrar deneyelim."},
            "secenekler": {
                "A": {"baslik": "Tekrar Üret", "metin": "Aynı ayı yeniden üret."},
                "B": {"baslik": "Devam Et", "metin": "Bu turu minimum etkiyle geç."},
            },
            "deltalar": {
                "A": {"cash": 0, "mrr": 0, "churn": 0, "reputation": 0, "support_load": 0, "infra": 0},
                "B": {"cash": -2000, "mrr": 0, "churn": 0.01, "reputation": -1, "support_load": 3, "infra": -1},
            },
            "event_family": event_family,
            "title_fingerprint": f"fallback-{state['month']}",
        }

    state["last_event_family"] = out.get("event_family", event_family)
    fp = out.get("title_fingerprint", "")
    if fp:
        state["recent_titles"].append(fp)
        state["recent_titles"] = state["recent_titles"][-6:]

    return out


def chat_bubble(role: str, text: str):
    if role == "user":
        st.markdown(
            f"<div style='padding:12px;border-radius:12px;background:#1f2937;margin:6px 0'>"
            f"<b>🧑 Sen</b><br>{text}</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<div style='padding:12px;border-radius:12px;background:#111827;margin:6px 0'>"
            f"<b>🤖 Oyun</b><br>{text}</div>",
            unsafe_allow_html=True,
        )


def render_sidebar(state: Dict[str, Any]):
    st.sidebar.markdown("## İsimsiz Girişimci")

    mode = st.sidebar.selectbox(
        "Mod",
        ["Realist", "Hard", "Spartan", "Extreme", "Türkiye"],
        index=["Realist", "Hard", "Spartan", "Extreme", "Türkiye"].index(state["mode"]),
        help=MODE_DESCRIPTIONS.get(state["mode"], ""),
    )
    state["mode"] = mode

    st.sidebar.markdown(f"**Ay:** {state['month']}/{state['months_total']}")
    st.sidebar.progress(min(1.0, state["month"] / max(1, state["months_total"])))

    st.sidebar.markdown("---")
    st.sidebar.markdown("### Finansal Durum")
    m: Metrics = state["metrics"]
    st.sidebar.metric("Kasa", money(m.cash))

    with st.sidebar.expander("Aylık Gider Detayı", expanded=True):
        st.write(f"Toplam (yaklaşık burn): **{money(m.burn)}**")
        st.caption("Not: support ve altyapı baskısı dahil yaklaşık hesap.")

    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**İtibar:** {int(m.reputation)} / 100")
    st.sidebar.progress(m.reputation / 100.0)

    st.sidebar.markdown(f"**Support yükü:** {int(m.support_load)} / 100")
    st.sidebar.progress(m.support_load / 100.0)

    st.sidebar.markdown(f"**Altyapı:** {int(m.infra)} / 100")
    st.sidebar.progress(m.infra / 100.0)

    st.sidebar.markdown("---")
    if st.sidebar.button("Oyunu Sıfırla"):
        st.session_state.pop("game", None)
        init_state()
        st.rerun()


def render_turn(out: Dict[str, Any]) -> Tuple[bool, bool]:
    st.markdown("### 🧠 DURUM ANALİZİ")
    st.markdown(out["durum_analizi"])

    st.markdown("### ⚠️ KRİZ")
    st.markdown(f"**{out['kriz']['baslik']}** — {out['kriz']['metin']}")

    st.markdown("### 🎯 Bu ay ne yapacaksın?")
    colA, colB = st.columns(2)

    with colA:
        st.markdown(f"#### A) {out['secenekler']['A']['baslik']}")
        st.write(out["secenekler"]["A"]["metin"])
        a_clicked = st.button("A seç", use_container_width=True)

    with colB:
        st.markdown(f"#### B) {out['secenekler']['B']['baslik']}")
        st.write(out["secenekler"]["B"]["metin"])
        b_clicked = st.button("B seç", use_container_width=True)

    return a_clicked, b_clicked


def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    init_state()
    state = st.session_state.game

    render_sidebar(state)

    st.markdown(f"# {APP_TITLE}")
    st.caption("Ay 1'den başlar. Akış: Durum analizi → Kriz → A/B hamle. Sohbet geçmişi kaybolmaz.")

    st.markdown("---")
    for msg in state["chat"]:
        chat_bubble(msg["role"], msg["content"])

    if not state["started"]:
        idea = st.text_input("Girişim fikrin ne?", placeholder="Örn: Üniversiteliler için proje yönetimi SaaS…")
        if st.button("Oyunu Başlat", type="primary") and idea.strip():
            state["idea"] = idea.strip()
            state["started"] = True
            state["month"] = 1
            state["rng_seed"] = abs(hash(state["idea"])) % (10**7)
            state["chat"].append({"role": "user", "content": state["idea"]})

            out = generate_turn(state)
            assistant_text = (
                f"**DURUM ANALİZİ:** {out['durum_analizi']}\n\n"
                f"**KRİZ — {out['kriz']['baslik']}:** {out['kriz']['metin']}\n\n"
                f"**A)** {out['secenekler']['A']['baslik']}: {out['secenekler']['A']['metin']}\n\n"
                f"**B)** {out['secenekler']['B']['baslik']}: {out['secenekler']['B']['metin']}"
            )
            state["last_turn"] = out
            state["chat"].append({"role": "assistant", "content": assistant_text})
            st.rerun()
        return

    if "last_turn" not in state:
        state["last_turn"] = generate_turn(state)

    out = state["last_turn"]

    user_action = st.text_input(
        "İstersen serbest hamle yaz (opsiyonel)",
        placeholder="Örn: onboarding'i kısalt, fiyatı test et, kampanya dene…",
    )

    a_clicked, b_clicked = render_turn(out)

    if a_clicked or b_clicked:
        choice = "A" if a_clicked else "B"
        chosen_title = out["secenekler"][choice]["baslik"]
        state["chat"].append(
            {
                "role": "user",
                "content": f"{choice} seçtim: {chosen_title}" + (f" | Serbest hamle: {user_action}" if user_action.strip() else ""),
            }
        )

        apply_choice_and_advance(state, choice, out.get("deltalar", {}))

        if state["month"] > state["months_total"]:
            state["chat"].append({"role": "assistant", "content": "🏁 Sezon bitti! İstersen oyunu sıfırla ve yeniden başla."})
            state.pop("last_turn", None)
            st.rerun()

        next_out = generate_turn(state)
        assistant_text = (
            f"**DURUM ANALİZİ:** {next_out['durum_analizi']}\n\n"
            f"**KRİZ — {next_out['kriz']['baslik']}:** {next_out['kriz']['metin']}\n\n"
            f"**A)** {next_out['secenekler']['A']['baslik']}: {next_out['secenekler']['A']['metin']}\n\n"
            f"**B)** {next_out['secenekler']['B']['baslik']}: {next_out['secenekler']['B']['metin']}"
        )
        state["last_turn"] = next_out
        state["chat"].append({"role": "assistant", "content": assistant_text})
        st.rerun()


if __name__ == "__main__":
    main()
