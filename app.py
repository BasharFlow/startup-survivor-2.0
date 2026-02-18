import streamlit as st
import google.generativeai as genai
import json
import random
import time
import re
import html
from typing import Any, Dict, List, Optional, Tuple

# --- 1. SAYFA VE GÖRSEL AYARLAR ---
st.set_page_config(page_title="Startup Survivor RPG", page_icon="🧠", layout="wide")

CSS = """
<style>
.block-container { padding-top: 1.5rem; max-width: 1200px; }
.stChatMessage { margin-bottom: 0.8rem; border-radius: 12px; }

/* SEÇENEK KARTLARI */
.choice-wrap {
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 18px;
    padding: 24px;
    background: linear-gradient(145deg, rgba(255,255,255,0.05), rgba(255,255,255,0.01));
    height: 100%;
    transition: all 0.3s ease;
    box-shadow: 0 4px 15px rgba(0,0,0,0.2);
}
.choice-wrap:hover { 
    border-color: rgba(255,255,255,0.3); 
    transform: translateY(-4px);
    background: rgba(255,255,255,0.07);
}
.choice-title { font-size: 1.4rem; font-weight: 900; margin-bottom: 14px; color: #ffffff; border-bottom: 1px solid #444; padding-bottom: 8px; }
.choice-desc { font-size: 1.05rem; line-height: 1.7; color: rgba(255,255,255,0.85); }

/* SIDEBAR STAT BOX */
.stat-card { background: rgba(255,255,255,0.03); border-radius: 12px; padding: 15px; margin-bottom: 10px; border: 1px solid rgba(255,255,255,0.05); }
.stat-val { font-size: 1.8rem; font-weight: 900; color: #2ECC71; }
.stat-label { font-size: 0.8rem; color: #888; text-transform: uppercase; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# --- 2. AI KONFİGÜRASYONU ---
def get_ai_keys() -> List[str]:
    if "GOOGLE_API_KEYS" in st.secrets: return st.secrets["GOOGLE_API_KEYS"]
    if "GEMINI_API_KEY" in st.secrets: return [st.secrets["GEMINI_API_KEY"]]
    return []

def gemini_generate(prompt: str, temp: float = 0.9) -> Optional[str]:
    keys = get_ai_keys()
    if not keys: return None
    genai.configure(api_key=random.choice(keys))
    try:
        # En stabil model olan 2.5 Flash
        model = genai.GenerativeModel("gemini-2.5-flash")
        resp = model.generate_content(prompt, generation_config={"temperature": temp, "max_output_tokens": 2000})
        return resp.text.strip()
    except Exception as e:
        return None

# --- 3. TOHUM OLAY BANKASI ---
EVENT_SEEDS = {
    "Gerçekçi": ["Sunucu maliyeti krizi", "Rakip özellik kopyalaması", "Kilit çalışan istifası", "Global PR fırsatı", "Ödeme sistemi hatası"],
    "Türkiye": ["Döviz şoku ve API maliyeti", "Büyük müşteri fatura krizi", "KVKK/Bürokrasi denetimi", "Tahsilat gecikmesi", "Enflasyonist kira zammı"],
    "Extreme": ["Elon Musk tweeti", "Emoji kod krizi", "Kült grup uygulaması", "Gelecekten gelen kullanıcı", "Simülasyon grevi"],
    "Zor": ["Yatırımcı geri çekilmesi", "Kitlesel churn dalgası", "Hukuki patent davası", "Veri sızıntısı paniği"],
    "Spartan": ["Tamamen ayı piyasası", "Sıfır toleranslı denetim", "Tedarik zinciri çöküşü", "Ekip içi büyük bölünme"]
}

# --- 4. MODA ÖZEL TALİMATLAR (MODLARIN ÇALIŞMASI İÇİN) ---
MOD_PROMPTS = {
    "Gerçekçi": "Profesyonel, mantıklı ve veri odaklı bir dil kullan. Startup dünyasının gerçeklerini (burn rate, churn, product-market fit) ciddiyetle ele al.",
    "Türkiye": "Türkiye ekonomisinin gerçeklerini (kur dalgalanması, stopaj, SGK, tanıdık bulma/network, vadeli ödemeler) hikayeye derinlemesine işle. 'Hallederiz' kültürüyle bürokrasi arasında bir ton yakala.",
    "Extreme": "Tamamen absürt, kaotik ve sürreal olaylar yarat. Mantık arama ama sonucun finansal/itibarsal etkisi gerçek olsun. İnternet mizahını ve meme kültürünü kullan.",
    "Zor": "Karamsar ve baskıcı bir dil kullan. Her olayda bir şeylerin kaybedileceğini hissettir. Başarıyı çok zor ve pahalı göster.",
    "Spartan": "Acımasız, askeri disiplinde ve duygusuz bir ton. Oyuncuyu batırmak için elinden geleni yap. Şans faktörünü yok say, sadece en sert kararların hayatta kalabileceğini vurgula."
}

# --- 5. GELİŞMİŞ PROMPT MİMARİSİ ---

def build_narrative_prompt(game: Dict[str, Any], seed: str) -> str:
    last_action = game.get("last_choice_summary", "Şirket kurulum aşamasında.")
    mod_style = MOD_PROMPTS.get(game["mode"], MOD_PROMPTS["Gerçekçi"])
    
    return f"""
GÖREV: Startup Survivor RPG için Ay {game['month']} içeriğini üret.
DİL: Türkçe.
MOD TALİMATI: {mod_style}

İSTENEN FORMAT: SADECE AŞAĞIDAKİ JSON OBJESİNİ DÖNDÜR. JSON DIŞINDA HİÇBİR ŞEY YAZMA.

{{
  "analysis": "Geçen ayki şu karar üzerine odaklanan, 3-4 paragraftan oluşan, sayısal veri dökmeden durumun felsefesini anlatan derinlemesine analiz. (Karar: {last_action})",
  "crisis": "Tohumu {seed} olan, en az 250 kelimelik, içinde diyaloglar veya somut olay detayları barındıran sürükleyici bir kriz metni. Neden karar verilmesi gerektiğini hissettir. İçinde tırnak içinde bir vurgu cümlesi olsun.",
  "options": {{
    "A": {{
      "title": "Stratejik Yol A Başlığı",
      "desc": "Krizin çözümüne yönelik, en az 3-4 cümlelik zengin bir eylem planı paragrafı."
    }},
    "B": {{
      "title": "Stratejik Yol B Başlığı",
      "desc": "Alternatif çözüm yolu, riskleri ve eylemleri içeren detaylı bir paragraf."
    }}
  }}
}}

Girişim Fikri: {game['idea']} | Mod: {game['mode']}
""".strip()

# --- 6. OYUN MOTORU ---

def generate_month_packet(game: Dict[str, Any]) -> Dict[str, Any]:
    pool = EVENT_SEEDS.get(game["mode"], EVENT_SEEDS["Gerçekçi"])
    used = st.session_state.get("used_seeds", [])
    candidates = [s for s in pool if s not in used]
    if not candidates: candidates = pool; st.session_state.used_seeds = []
    seed = random.choice(candidates)
    st.session_state.used_seeds.append(seed)

    # 3 Deneme hakkı (Hata koruması için)
    for i in range(3):
        packet_raw = gemini_generate(build_narrative_prompt(game, seed))
        if not packet_raw: continue
        
        try:
            # JSON temizle (Regex ile sadece { } arasını al)
            json_match = re.search(r'\{.*\}', packet_raw, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                # Gelen verinin eksiksiz olduğunu kontrol et
                if "analysis" in data and "crisis" in data and "options" in data:
                    return data
        except Exception:
            time.sleep(1)
            continue

    # Tamamen başarısız olursa Fallback
    return {
        "analysis": f"{game['mode']} piyasasında dengeler değişiyor. Ekibiniz bir önceki ayın etkilerini derinlemesine analiz ediyor.",
        "crisis": f"Beklenmedik bir operasyonel kriz: {seed}. Bu durum şirketin geleceğini tehdit ediyor.",
        "options": {
            "A": {"title": "Radikal Odaklanma", "desc": "Tüm ikincil operasyonları durdurup ekibi bu soruna kanalize edersiniz. Gecikmeler yaşanabilir ancak ana sorun hızla çözülür."},
            "B": {"title": "Esnek Adaptasyon", "desc": "Sorunu mevcut iş akışına yedirip zamana yayarak çözmeye çalışırsınız. Hız kesmezsiniz ama hata payınızın artmasını göze alırsınız."}
        }
    }

def calculate_expenses(stats, month):
    # Gerçekçi gider hesaplama motoru
    salary = stats['team'] * 1200
    server = (month ** 2) * 500
    marketing = 5000
    total = salary + server + marketing
    return salary, server, marketing, total

# --- 7. UI VE RENDER ---

def reset_game():
    for k in list(st.session_state.keys()): del st.session_state[k]
    st.rerun()

if "chat" not in st.session_state:
    st.session_state.update({
        "chat": [], "month": 1, "game_started": False, "choice_done": False,
        "metrics": {"cash": 200000, "team": 50, "itibar": 50},
        "last_choice_summary": "Şirket kurulumu tamamlandı.",
        "current_packet": None, "used_seeds": []
    })

# SIDEBAR
with st.sidebar:
    st.markdown("<h2 style='text-align:center;'>🚀 DASHBOARD</h2>", unsafe_allow_html=True)
    m = st.session_state.metrics
    st.markdown(f"<div class='stat-card'><div class='stat-label'>Kasa (₺)</div><div class='stat-val'>{m['cash']:,}</div></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='stat-card'><div class='stat-label'>İtibar Skoru</div><div class='stat-val'>{m['itibar']}/100</div></div>", unsafe_allow_html=True)
    st.divider()
    st.write(f"🗓️ **Süreç:** Ay {st.session_state.month} / 12")
    st.progress(st.session_state.month / 12)
    if st.button("Simülasyonu Sıfırla", use_container_width=True): reset_game()

st.title("Startup Survivor RPG")

# GİRİŞ EKRANI
if not st.session_state.game_started:
    col1, col2 = st.columns(2)
    with col1: idea = st.text_area("İş Fikrin", height=150, placeholder="Neyi simüle etmek istiyorsun?")
    with col2: 
        mode = st.selectbox("Oyun Modu", ["Gerçekçi", "Türkiye", "Zor", "Spartan", "Extreme"])
        st.info(f"💡 {mode} Modu Aktif: AI bu moda uygun bir dil ve zorluk seviyesi kullanacaktır.")
    
    if st.button("SİMÜLASYONU BAŞLAT", type="primary", use_container_width=True):
        if idea:
            st.session_state.update({"idea": idea, "mode": mode, "game_started": True})
            st.rerun()
        else: st.warning("Lütfen bir fikir yazın.")
    st.stop()

# OYUN DÖNGÜSÜ
if st.session_state.current_packet is None:
    game_ctx = {"mode": st.session_state.mode, "month": st.session_state.month, "idea": st.session_state.idea, "last_choice_summary": st.session_state.last_choice_summary}
    with st.spinner(f"AI {st.session_state.mode} modunda senaryoyu kurguluyor..."):
        st.session_state.current_packet = generate_month_packet(game_ctx)
    
    st.session_state.chat.append({"role": "assistant", "content": f"🧠 **DURUM ANALİZİ (Ay {st.session_state.month})**\n\n{st.session_state.current_packet['analysis']}"})
    st.session_state.chat.append({"role": "assistant", "content": f"⚠️ **YENİ KRİZ**\n\n{st.session_state.current_packet['crisis']}"})

# Mesajları Göster
for msg in st.session_state.chat:
    with st.chat_message(msg["role"], avatar="🤖" if msg["role"] == "assistant" else "👤"):
        st.markdown(msg["content"])

# Karar Alanı
if not st.session_state.choice_done:
    packet = st.session_state.current_packet
    st.markdown("---")
    st.markdown("### 🛠️ Stratejik Karar")
    
    c1, c2 = st.columns(2, gap="large")
    for i, (letter, data) in enumerate(packet["options"].items()):
        with (c1 if i == 0 else c2):
            st.markdown(f"""<div class="choice-wrap"><div class="choice-title">{letter}) {html.escape(data['title'])}</div><div class="choice-desc">{html.escape(data['desc'])}</div></div>""", unsafe_allow_html=True)
            if st.button(f"{letter} Yolunu Seç", key=f"btn_{letter}_{st.session_state.month}", use_container_width=True):
                # Finansal Hesaplama
                sal, ser, mar, total = calculate_expenses(st.session_state.metrics, st.session_state.month)
                st.session_state.metrics["cash"] -= total
                
                # Karar Etkisi
                res_prompt = f"Ay {st.session_state.month} sonucu: '{data['title']}' seçildi. Toplam gider: {total} TL. Kısa bir hikaye sonucu yaz."
                outcome = gemini_generate(res_prompt) or "Kararınızın etkileri bir sonraki aya devrediyor."
                
                st.session_state.chat.append({"role": "user", "content": f"**Seçimim:** {letter} - {data['title']}"})
                st.session_state.chat.append({"role": "assistant", "content": f"✅ **SONUÇ**\n\n{outcome}\n\n*Ay sonu toplam gideriniz: {total:,} ₺*"})
                st.session_states.last_choice_summary = f"Ay {st.session_state.month} kararı: {data['title']}"
                st.session_state.choice_done = True
                st.rerun()
else:
    if st.session_state.month < 12:
        if st.button("SONRAKİ AYA GEÇ →", type="primary", use_container_width=True):
            st.session_state.month += 1
            st.session_state.choice_done = False
            st.session_state.current_packet = None
            st.rerun()
    else:
        st.balloons()
        st.success("🏆 12 AYI TAMAMLADIN! ŞİRKETİNİN GELECEĞİ PARLAK GÖRÜNÜYOR.")
        if st.button("Yeniden Başlat"): reset_game()