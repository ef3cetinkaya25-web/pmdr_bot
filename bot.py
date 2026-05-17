import asyncio
import io
import os
import random
import re
import sqlite3
import time
from datetime import date, datetime, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters, ContextTypes
)
from google import genai as google_genai

# ══════════════════════════════════════════════════════════
TELEGRAM_TOKEN = "8628027064:AAEbxBxrjtyJ3t3_uqV6CobXd5piX0vpQlM"
GEMINI_API_KEY = "AIzaSyABXghQNgdRbdR3m3Ee4O-XN6SXvisVveM"
# ══════════════════════════════════════════════════════════

(
    ST_NOT_DERS, ST_NOT_METIN,
    ST_KONU,
    ST_TEST_SONUC, ST_TEST_SORULAR,
    ST_SORU_CEVAP,
    ST_HEDEF,
    ST_PROGRAM_SINAV, ST_PROGRAM_DERSLER,
) = range(9)

aktif_pomodorolar: dict = {}

ROZETLER = [
    {"id": "ilk_adim",  "isim": "Ilk Adim",       "ikon": "🌱", "aciklama": "Ilk pomodoronu tamamladin!",        "kosul": lambda t, s, g: t >= 1},
    {"id": "azimli",    "isim": "Azimli Ogrenci", "ikon": "📚", "aciklama": "5 pomodoro tamamladin!",            "kosul": lambda t, s, g: t >= 5},
    {"id": "saatci",    "isim": "Saatci",          "ikon": "⏰", "aciklama": "Tek gunde 2+ saat calistın!",      "kosul": lambda t, s, g: s >= 120},
    {"id": "maraton",   "isim": "Maraton Kosucu",  "ikon": "🏃", "aciklama": "25 pomodoro tamamladin!",          "kosul": lambda t, s, g: t >= 25},
    {"id": "demir",     "isim": "Demir Disiplin",  "ikon": "🔩", "aciklama": "7 gun ust uste calistın!",        "kosul": lambda t, s, g: g >= 7},
    {"id": "ustasi",    "isim": "Calisma Ustasi",  "ikon": "🧙", "aciklama": "100 pomodoro tamamladin!",         "kosul": lambda t, s, g: t >= 100},
    {"id": "efsane",    "isim": "Efsane",           "ikon": "👑", "aciklama": "30 gun ust uste calistın!",       "kosul": lambda t, s, g: g >= 30},
]

SEVIYELER = [
    (0,   "🐣 Caylak"),
    (5,   "📖 Ogrenci"),
    (15,  "🎓 Asistan"),
    (30,  "⭐ Uzman"),
    (60,  "🔥 Ustat"),
    (100, "👑 Efsane"),
]

def seviye_hesapla(toplam_pomodoro: int) -> str:
    seviye = SEVIYELER[0][1]
    for esik, isim in SEVIYELER:
        if toplam_pomodoro >= esik:
            seviye = isim
    return seviye

HIKAYELER = [
    {"isim": "Elon Musk",       "hikaye": "🚀 *Elon Musk* SpaceX'i kurduğunda 3 kez roket firlatti ve 3 kez basarisiz oldu. 4. denemede basarili oldu ve NASA ile 1.6 milyar dolarlik anlasma imzaladi.\n\n💡 *Ders:* Basarisizlik sonu degil, surecin bir parcasidir."},
    {"isim": "J.K. Rowling",    "hikaye": "📚 *J.K. Rowling* Harry Potter'i yazdiginda issiz ve yoksulluk icindeydi. 12 yayinevi reddetti. 13. yayinevi kabul etti.\n\n💡 *Ders:* Hayir cevabi seni durduramaz."},
    {"isim": "Thomas Edison",   "hikaye": "💡 *Thomas Edison* ampulu icat etmeden once 10.000 kez basarisiz oldu. 'Ben 10.000 ise yaramayan yontemi kesfettim' dedi.\n\n💡 *Ders:* Perspektifin her seyi degistirir."},
    {"isim": "Steve Jobs",      "hikaye": "🍎 *Steve Jobs* 30 yasinda kendi kurdugu Apple'dan kovuldu. Ama bu surecte NeXT ve Pixar'i kurdu.\n\n💡 *Ders:* En buyuk darbe, en buyuk firsatin baslangici olabilir."},
    {"isim": "Albert Einstein", "hikaye": "🧠 *Albert Einstein* cocukken 'geri zekali' denildi. Universite sinavini ilk girisde gecemedi. Nobel odulu kazandi.\n\n💡 *Ders:* Baskalarin etiketi senin gercegin degil."},
]

SINAVLAR = {
    "YKS (TYT/AYT)":  {"tarih": datetime(2026, 6, 21), "basvuru_bitis": datetime(2026, 3, 31), "aciklama": "Universite yerlestirme sinavi"},
    "LGS":             {"tarih": datetime(2026, 6, 7),  "basvuru_bitis": datetime(2026, 3, 15), "aciklama": "Liseye gecis sinavi"},
    "KPSS Lisans":     {"tarih": datetime(2026, 7, 5),  "basvuru_bitis": datetime(2026, 5, 10), "aciklama": "Kamu personeli secme sinavi"},
    "KPSS Onlisans":   {"tarih": datetime(2026, 7, 12), "basvuru_bitis": datetime(2026, 5, 10), "aciklama": "Kamu personeli secme sinavi"},
    "ALES":            {"tarih": datetime(2026, 9, 6),  "basvuru_bitis": datetime(2026, 7, 20), "aciklama": "Akademik lisansustu sinavi"},
    "DGS":             {"tarih": datetime(2026, 7, 19), "basvuru_bitis": datetime(2026, 5, 25), "aciklama": "Dikey gecis sinavi"},
    "YOKDIL":          {"tarih": datetime(2026, 5, 24), "basvuru_bitis": datetime(2026, 4, 15), "aciklama": "Yuksekogretim dil sinavi"},
    "MSU":             {"tarih": datetime(2026, 5, 10), "basvuru_bitis": datetime(2026, 3, 1),  "aciklama": "Milli Savunma Universitesi sinavi"},
    "PMYO":            {"tarih": datetime(2026, 6, 15), "basvuru_bitis": datetime(2026, 4, 30), "aciklama": "Polis meslek yuksekokullari sinavi"},
    "EKPSS":           {"tarih": datetime(2026, 8, 2),  "basvuru_bitis": datetime(2026, 6, 15), "aciklama": "Engelli kamu personeli sinavi"},
}

INDIRIMLI_KITAPLAR = [
    {"isim": "TYT Soru Bankasi (Tum Dersler)", "yayinevi": "Hiz ve Renk", "eski_fiyat": 380, "yeni_fiyat": 228, "indirim": 40, "url": "https://www.bkmkitap.com", "ikon": "📗"},
    {"isim": "AYT Matematik Soru Bankasi",      "yayinevi": "Karekok",     "eski_fiyat": 320, "yeni_fiyat": 208, "indirim": 35, "url": "https://www.kitapyurdu.com", "ikon": "📘"},
    {"isim": "YKS Turkce Dil Bilgisi",          "yayinevi": "Palme",       "eski_fiyat": 260, "yeni_fiyat": 182, "indirim": 30, "url": "https://www.bkmkitap.com", "ikon": "📙"},
    {"isim": "LGS Matematik Fasikul Seti",      "yayinevi": "Birey",       "eski_fiyat": 450, "yeni_fiyat": 315, "indirim": 30, "url": "https://www.kitapyurdu.com", "ikon": "📕"},
    {"isim": "KPSS Genel Kultur Soru Bankasi",  "yayinevi": "Isem",        "eski_fiyat": 290, "yeni_fiyat": 217, "indirim": 25, "url": "https://www.bkmkitap.com", "ikon": "📒"},
    {"isim": "AYT Fizik Konu Anlatimli",        "yayinevi": "Nitelik",     "eski_fiyat": 310, "yeni_fiyat": 248, "indirim": 20, "url": "https://www.kitapyurdu.com", "ikon": "📔"},
]

def sinav_sayaci_metni() -> str:
    bugun = datetime.now()
    satirlar = ["📅 *Turkiye Sinav Takvimi 2026*\n"]
    for sinav, bilgi in SINAVLAR.items():
        tarih = bilgi["tarih"]
        basvuru = bilgi["basvuru_bitis"]
        kalan = (tarih - bugun).days
        basvuru_kalan = (basvuru - bugun).days
        if kalan < 0:
            emoji, kalan_str = "✅", "Tamamlandi"
        elif kalan == 0:
            emoji, kalan_str = "🔥", "BUGUN!"
        elif kalan <= 30:
            emoji, kalan_str = "⚠️", f"`{kalan} gun kaldi!`"
        else:
            emoji, kalan_str = "📅", f"`{kalan} gun kaldi`"
        basvuru_str = f"\n   📝 Basvuru bitis: {basvuru.strftime('%d.%m.%Y')} ({basvuru_kalan} gun)" if basvuru_kalan > 0 else "\n   📝 Basvuru suresi doldu"
        satirlar.append(f"{emoji} *{sinav}* — {kalan_str}\n   _{bilgi['aciklama']}_{basvuru_str}")
    return "\n\n".join(satirlar)

# ══════════════════════════════════════════════════════════
#  VERİTABANI
# ══════════════════════════════════════════════════════════
def veritabani_baslat():
    conn = sqlite3.connect("pomodoro.db")
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS istatistik (
            kullanici_id INTEGER, tarih TEXT,
            tamamlanan INTEGER DEFAULT 0, toplam_dakika INTEGER DEFAULT 0,
            PRIMARY KEY (kullanici_id, tarih)
        );
        CREATE TABLE IF NOT EXISTS notlar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kullanici_id INTEGER, tarih TEXT, ders TEXT, not_metni TEXT
        );
        CREATE TABLE IF NOT EXISTS test_sonuclari (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kullanici_id INTEGER, tarih TEXT, ders TEXT,
            dogru INTEGER DEFAULT 0, yanlis INTEGER DEFAULT 0,
            bos INTEGER DEFAULT 0, toplam INTEGER DEFAULT 0, analiz_metni TEXT
        );
        CREATE TABLE IF NOT EXISTS konu_gecmisi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kullanici_id INTEGER, tarih TEXT, konu TEXT, ozet TEXT
        );
        CREATE TABLE IF NOT EXISTS rozetler (
            kullanici_id INTEGER, rozet_id TEXT, kazanildi_tarih TEXT,
            PRIMARY KEY (kullanici_id, rozet_id)
        );
        CREATE TABLE IF NOT EXISTS kullanici_bilgi (
            kullanici_id INTEGER PRIMARY KEY, ad TEXT,
            hatirlatici_aktif INTEGER DEFAULT 1,
            gunluk_hedef INTEGER DEFAULT 4,
            kayit_tarihi TEXT
        );
        CREATE TABLE IF NOT EXISTS hedefler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kullanici_id INTEGER, haftalik_hedef INTEGER DEFAULT 20,
            baslangic_tarihi TEXT, bitis_tarihi TEXT
        );
    """)
    conn.commit()
    conn.close()

def pomodoro_kaydet(uid, dakika):
    conn = sqlite3.connect("pomodoro.db")
    c = conn.cursor()
    c.execute("""
        INSERT INTO istatistik (kullanici_id, tarih, tamamlanan, toplam_dakika)
        VALUES (?, ?, 1, ?)
        ON CONFLICT(kullanici_id, tarih)
        DO UPDATE SET tamamlanan = tamamlanan + 1, toplam_dakika = toplam_dakika + ?
    """, (uid, str(date.today()), dakika, dakika))
    conn.commit(); conn.close()

def bugun_istatistik(uid):
    conn = sqlite3.connect("pomodoro.db")
    c = conn.cursor()
    c.execute("SELECT tamamlanan, toplam_dakika FROM istatistik WHERE kullanici_id=? AND tarih=?", (uid, str(date.today())))
    r = c.fetchone(); conn.close()
    return r if r else (0, 0)

def haftalik_istatistik(uid):
    conn = sqlite3.connect("pomodoro.db")
    c = conn.cursor()
    c.execute("SELECT tarih, tamamlanan, toplam_dakika FROM istatistik WHERE kullanici_id=? AND tarih >= ? ORDER BY tarih",
              (uid, str(date.today() - timedelta(days=6))))
    r = c.fetchall(); conn.close()
    return r

def aylik_istatistik(uid):
    conn = sqlite3.connect("pomodoro.db")
    c = conn.cursor()
    c.execute("SELECT tarih, tamamlanan, toplam_dakika FROM istatistik WHERE kullanici_id=? AND tarih >= ? ORDER BY tarih",
              (uid, str(date.today() - timedelta(days=29))))
    r = c.fetchall(); conn.close()
    return r

def toplam_pomodoro(uid):
    conn = sqlite3.connect("pomodoro.db")
    c = conn.cursor()
    c.execute("SELECT COALESCE(SUM(tamamlanan), 0) FROM istatistik WHERE kullanici_id=?", (uid,))
    r = c.fetchone()[0]; conn.close()
    return r

def ardisik_gun_sayisi(uid):
    conn = sqlite3.connect("pomodoro.db")
    c = conn.cursor()
    c.execute("SELECT tarih FROM istatistik WHERE kullanici_id=? AND tamamlanan > 0 ORDER BY tarih DESC", (uid,))
    gunler = [row[0] for row in c.fetchall()]; conn.close()
    if not gunler: return 0
    sayi = 0; kontrol = date.today()
    for gun in gunler:
        if str(kontrol) == gun:
            sayi += 1; kontrol -= timedelta(days=1)
        else: break
    return sayi

def not_kaydet(uid, ders, metin):
    conn = sqlite3.connect("pomodoro.db")
    c = conn.cursor()
    c.execute("INSERT INTO notlar (kullanici_id, tarih, ders, not_metni) VALUES (?,?,?,?)", (uid, str(date.today()), ders, metin))
    conn.commit(); conn.close()

def notlar_getir(uid):
    conn = sqlite3.connect("pomodoro.db")
    c = conn.cursor()
    c.execute("SELECT tarih, ders, not_metni FROM notlar WHERE kullanici_id=? ORDER BY id DESC LIMIT 10", (uid,))
    r = c.fetchall(); conn.close()
    return r

def test_sonucu_kaydet(uid, ders, dogru, yanlis, bos, analiz):
    conn = sqlite3.connect("pomodoro.db")
    c = conn.cursor()
    c.execute("INSERT INTO test_sonuclari (kullanici_id, tarih, ders, dogru, yanlis, bos, toplam, analiz_metni) VALUES (?,?,?,?,?,?,?,?)",
              (uid, str(date.today()), ders, dogru, yanlis, bos, dogru+yanlis+bos, analiz))
    conn.commit(); conn.close()

def son_testler(uid, limit=5):
    conn = sqlite3.connect("pomodoro.db")
    c = conn.cursor()
    c.execute("SELECT tarih, ders, dogru, yanlis, bos, toplam FROM test_sonuclari WHERE kullanici_id=? ORDER BY id DESC LIMIT ?", (uid, limit))
    r = c.fetchall(); conn.close()
    return r

def rozet_kontrol_ve_ver(uid):
    t = toplam_pomodoro(uid); s = bugun_istatistik(uid)[1]; g = ardisik_gun_sayisi(uid)
    conn = sqlite3.connect("pomodoro.db")
    c = conn.cursor()
    c.execute("SELECT rozet_id FROM rozetler WHERE kullanici_id=?", (uid,))
    mevcut = {r[0] for r in c.fetchall()}
    yeni = []
    for rozet in ROZETLER:
        if rozet["id"] not in mevcut and rozet["kosul"](t, s, g):
            c.execute("INSERT INTO rozetler (kullanici_id, rozet_id, kazanildi_tarih) VALUES (?,?,?)", (uid, rozet["id"], str(date.today())))
            yeni.append(rozet)
    conn.commit(); conn.close()
    return yeni

def tum_rozetler(uid):
    conn = sqlite3.connect("pomodoro.db")
    c = conn.cursor()
    c.execute("SELECT rozet_id, kazanildi_tarih FROM rozetler WHERE kullanici_id=?", (uid,))
    r = c.fetchall(); conn.close()
    return r

def hedef_kaydet(uid, haftalik):
    conn = sqlite3.connect("pomodoro.db")
    c = conn.cursor()
    c.execute("INSERT INTO hedefler (kullanici_id, haftalik_hedef, baslangic_tarihi, bitis_tarihi) VALUES (?,?,?,?)",
              (uid, haftalik, str(date.today()), str(date.today() + timedelta(days=7))))
    conn.commit(); conn.close()

def aktif_hedef(uid):
    conn = sqlite3.connect("pomodoro.db")
    c = conn.cursor()
    c.execute("SELECT haftalik_hedef, baslangic_tarihi, bitis_tarihi FROM hedefler WHERE kullanici_id=? AND bitis_tarihi >= ? ORDER BY id DESC LIMIT 1",
              (uid, str(date.today())))
    r = c.fetchone(); conn.close()
    return r

def haftalik_toplam(uid):
    conn = sqlite3.connect("pomodoro.db")
    c = conn.cursor()
    c.execute("SELECT COALESCE(SUM(tamamlanan), 0) FROM istatistik WHERE kullanici_id=? AND tarih >= ?",
              (uid, str(date.today() - timedelta(days=6))))
    r = c.fetchone()[0]; conn.close()
    return r

def kullanici_kaydet(uid, ad):
    conn = sqlite3.connect("pomodoro.db")
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO kullanici_bilgi (kullanici_id, ad, kayit_tarihi) VALUES (?,?,?)", (uid, ad, str(date.today())))
    conn.commit(); conn.close()

def hatirlatici_toggle(uid):
    conn = sqlite3.connect("pomodoro.db")
    c = conn.cursor()
    c.execute("SELECT hatirlatici_aktif FROM kullanici_bilgi WHERE kullanici_id=?", (uid,))
    r = c.fetchone()
    yeni = 0 if (r and r[0]) else 1
    c.execute("UPDATE kullanici_bilgi SET hatirlatici_aktif=? WHERE kullanici_id=?", (yeni, uid))
    conn.commit(); conn.close()
    return bool(yeni)

def tum_kullanicilar():
    conn = sqlite3.connect("pomodoro.db")
    c = conn.cursor()
    c.execute("SELECT kullanici_id FROM kullanici_bilgi WHERE hatirlatici_aktif=1")
    r = [row[0] for row in c.fetchall()]; conn.close()
    return r

def liderboard_getir(limit=10):
    conn = sqlite3.connect("pomodoro.db")
    c = conn.cursor()
    c.execute("""
        SELECT i.kullanici_id, COALESCE(k.ad, 'Bilinmiyor'), i.tamamlanan
        FROM istatistik i LEFT JOIN kullanici_bilgi k ON i.kullanici_id = k.kullanici_id
        WHERE i.tarih = ? ORDER BY i.tamamlanan DESC LIMIT ?
    """, (str(date.today()), limit))
    r = c.fetchall(); conn.close()
    return r

def konu_gecmisi_kaydet(uid, konu, ozet):
    conn = sqlite3.connect("pomodoro.db")
    c = conn.cursor()
    c.execute("INSERT INTO konu_gecmisi (kullanici_id, tarih, konu, ozet) VALUES (?,?,?,?)", (uid, str(date.today()), konu, ozet))
    conn.commit(); conn.close()

# ══════════════════════════════════════════════════════════
#  GRAFİK  (FİX: ASCII etiketler — Türkçe karakter sorunu yok)
# ══════════════════════════════════════════════════════════
def haftalik_grafik_olustur(uid):
    veri = haftalik_istatistik(uid)
    veri_dict = {row[0]: (row[1], row[2]) for row in veri}
    gunler, pomodorolar, dakikalar = [], [], []
    gun_isimleri = ["Pzt", "Sal", "Car", "Per", "Cum", "Cmt", "Paz"]
    for i in range(6, -1, -1):
        t = date.today() - timedelta(days=i)
        tarih_str = str(t)
        gun_idx = t.weekday()
        gunler.append(f"{gun_isimleri[gun_idx]}\n{t.strftime('%d')}")
        p, d = veri_dict.get(tarih_str, (0, 0))
        pomodorolar.append(p); dakikalar.append(d)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7), facecolor="#1a1a2e")
    fig.suptitle("Haftalik Calisma Raporu", color="white", fontsize=15, fontweight="bold")
    max_p = max(pomodorolar) if any(pomodorolar) else 1
    renkler = ["#e94560" if p == max_p and p > 0 else "#0f3460" for p in pomodorolar]
    bars = ax1.bar(gunler, pomodorolar, color=renkler, edgecolor="#e94560", linewidth=0.5)
    ax1.set_facecolor("#16213e"); ax1.tick_params(colors="white"); ax1.spines[:].set_color("#0f3460")
    ax1.set_ylabel("Pomodoro", color="white"); ax1.set_ylim(0, max_p + 2)
    for bar, val in zip(bars, pomodorolar):
        if val > 0:
            ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1, str(val), ha="center", color="white", fontsize=9)
    ax2.plot(range(len(gunler)), dakikalar, color="#e94560", linewidth=2.5, marker="o", markersize=7, markerfacecolor="white")
    ax2.fill_between(range(len(gunler)), dakikalar, alpha=0.15, color="#e94560")
    ax2.set_facecolor("#16213e"); ax2.tick_params(colors="white"); ax2.spines[:].set_color("#0f3460")
    ax2.set_ylabel("Dakika", color="white"); ax2.set_xticks(range(len(gunler))); ax2.set_xticklabels(gunler, color="white")
    plt.tight_layout()
    buf = io.BytesIO(); plt.savefig(buf, format="png", dpi=130, bbox_inches="tight"); buf.seek(0); plt.close()
    return buf

def aylik_grafik_olustur(uid):
    veri = aylik_istatistik(uid)
    if not veri:
        fig, ax = plt.subplots(figsize=(10, 4), facecolor="#1a1a2e")
        ax.text(0.5, 0.5, "Henuz veri yok", ha="center", va="center", color="white", fontsize=14)
        ax.set_facecolor("#16213e"); ax.axis("off")
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0); plt.close()
        return buf
    tarihler = [row[0][5:] for row in veri]; pomodorolar = [row[1] for row in veri]
    fig, ax = plt.subplots(figsize=(12, 5), facecolor="#1a1a2e")
    ax.fill_between(range(len(tarihler)), pomodorolar, alpha=0.3, color="#e94560")
    ax.plot(range(len(tarihler)), pomodorolar, color="#e94560", linewidth=2)
    ax.set_facecolor("#16213e"); ax.tick_params(colors="white", labelsize=7); ax.spines[:].set_color("#0f3460")
    ax.set_xticks(range(len(tarihler))); ax.set_xticklabels(tarihler, rotation=45, color="white", fontsize=7)
    ax.set_ylabel("Pomodoro", color="white"); ax.set_title("Aylik Calisma Grafigi", color="white", fontsize=13, fontweight="bold")
    plt.tight_layout()
    buf = io.BytesIO(); plt.savefig(buf, format="png", dpi=130); buf.seek(0); plt.close()
    return buf

# ══════════════════════════════════════════════════════════
#  GEMİNİ  (FİX: retry + model fallback + quota handling)
# ══════════════════════════════════════════════════════════
GEMINI_MODELLER = ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash"]

def _gemini(prompt, max_deneme=3):
    """
    Quota/429 hatasında farklı modellere geçer ve retry yapar.
    """
    client = google_genai.Client(api_key=GEMINI_API_KEY)
    for model in GEMINI_MODELLER:
        for deneme in range(max_deneme):
            try:
                r = client.models.generate_content(model=model, contents=prompt)
                return r.text.strip()
            except Exception as e:
                hata = str(e)
                if "429" in hata or "RESOURCE_EXHAUSTED" in hata:
                    # retry in X saniye bilgisini parse etmeye çalış
                    bekleme = 5
                    import re as _re
                    m = _re.search(r"retry in ([0-9.]+)s", hata)
                    if m:
                        bekleme = min(float(m.group(1)), 15)  # max 15 sn bekle
                    if deneme < max_deneme - 1:
                        time.sleep(bekleme)
                        continue
                    # Bu model quota doldu, sıradaki modele geç
                    break
                elif "404" in hata or "not found" in hata.lower():
                    # Model mevcut değil, sıradakine geç
                    break
                else:
                    raise
    raise Exception("Tum Gemini modelleri quota limitine ulasti. Lutfen biraz bekleyip tekrar deneyin.")

def motivasyon_al(tamamlanan=0, sure=0):
    try:
        rastgele = random.randint(1, 99999)
        return _gemini(f"Bir ogrenci bugun {tamamlanan} pomodoro tamamladi, {sure} dakika calisti. Turkce, samimi, OZGUN 2-3 cumlelik motivasyon yaz. Emoji kullan. (ID:{rastgele})")
    except Exception as e:
        mesajlar = [
            "Harika is cikardin! Devam et! 💪",
            "Her adim seni hedefe yaklastiriyor! 🎯",
            "Bugun de muhtemsemsin! 🌟",
            "Calismanin meyvesini mutlaka toplayacaksin! 🏆",
        ]
        return random.choice(mesajlar)

def konu_ozeti_uret(konu):
    try:
        return _gemini(
            f"Sen Turk lise/universite sinav kocusun. MEB muzfredatina uygun, "
            f"YKS/LGS/KPSS hazirlayan ogrenciler icin '{konu}' konusunu anlat.\n"
            f"1. Maks 5 madde\n2. Karmasik terimleri Turkce acikla\n"
            f"3. En cok sinava giren alt konulari belirt\n4. Sonuna 1 ornek soru ekle\n"
            f"5. Sade Turkce. Emoji kullanabilirsin."
        )
    except Exception as e:
        return f"'{konu}' icin ozet simdilik uretilemedi.\n\n⚠️ Hata: {str(e)[:100]}\n\nLutfen birkaç dakika bekleyip tekrar dene."

def test_analizi_uret(ders, dogru, yanlis, bos, sorular=""):
    try:
        toplam = dogru + yanlis + bos
        net = dogru - yanlis / 4
        soru_bilgisi = f"\nYanlis yapilan konular:\n{sorular}" if sorular else ""
        return _gemini(
            f"Turk sinav danismanisın. Ogrenci {ders} dersinden {toplam} soruda "
            f"{dogru} dogru, {yanlis} yanlis, {bos} bos yapti. Net: {net:.2f}{soru_bilgisi}\n"
            f"1. Performansi degerlendir\n2. 3+ eksik konu listele\n"
            f"3. Calisma plani ver\n4. Yapici kapanis yaz\nTurkce, emoji kullan."
        )
    except Exception as e:
        return f"Analiz simdilik uretilemedi.\n\n⚠️ {str(e)[:100]}\n\nLutfen birkaç dakika bekleyip tekrar dene."

def serbest_soru_cevapla(soru):
    try:
        return _gemini(
            f"Sen Turk ogrencilere yardimci olan sinav kocusun. "
            f"YKS, LGS, KPSS sorularini Turkce, sade ve anlasilir yanitla. Adim adim acikla.\n\nSoru: {soru}"
        )
    except Exception as e:
        return f"Cevap simdilik uretilemedi.\n\n⚠️ {str(e)[:100]}\n\nLutfen birkaç dakika bekleyip tekrar dene."

def gorsel_soru_coz(image_bytes, soru_metni=""):
    try:
        import base64
        img_b64 = base64.standard_b64encode(image_bytes).decode()
        client = google_genai.Client(api_key=GEMINI_API_KEY)
        for model in GEMINI_MODELLER:
            try:
                r = client.models.generate_content(
                    model=model,
                    contents=[
                        {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}},
                        f"Bu gorseldeki soruyu coz. {soru_metni}\nAdim adim cozum yap. Turkce acikla."
                    ]
                )
                return r.text.strip()
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    time.sleep(5)
                    continue
                raise
        return "Gorsel cozumlenemedi: Tum modeller mesgul. Lutfen bekleyip tekrar dene."
    except Exception as e:
        return f"Gorsel cozumlenemedi: {str(e)[:150]}"

def akilli_program_olustur(sinav, sinav_tarihi, dersler, mevcut_pomodoro):
    try:
        return _gemini(
            f"Ogrenci '{sinav}' sinavina hazirlaniyor. Sinav tarihi: {sinav_tarihi}.\n"
            f"Calisacagi dersler: {dersler}\nGunluk ortalama {mevcut_pomodoro} pomodoro.\n\n"
            f"1. Haftalik program olustur (Pzt-Paz)\n2. Her gun kac pomodoro calisacagini belirt\n"
            f"3. Oncelikleri sirala\n4. Tavsiyeler ver\nTurkce, motive edici. Emoji kullan."
        )
    except Exception as e:
        return f"Program simdilik olusturulamadi.\n\n⚠️ {str(e)[:100]}\n\nLutfen birkaç dakika bekleyip tekrar dene."

def kisisel_tavsiye_uret(uid):
    try:
        testler = son_testler(uid, 5)
        hafta = haftalik_istatistik(uid)
        toplam_p = toplam_pomodoro(uid)
        ardisik = ardisik_gun_sayisi(uid)
        test_ozeti = "".join([f"• {t[1]}: {t[2]}D/{t[3]}Y/{t[4]}B (net:{t[2]-t[3]/4:.1f})\n" for t in testler]) or "Test kaydi yok"
        hafta_ozeti = "".join([f"• {h[0]}: {h[1]} pomodoro ({h[2]} dk)\n" for h in hafta]) or "Veri yok"
        return _gemini(
            f"Ogrencinin verileri:\nToplam pomodoro: {toplam_p}\nArdisik gun: {ardisik}\n"
            f"Bu hafta:\n{hafta_ozeti}\nSon testler:\n{test_ozeti}\n\n"
            f"1. Guclu/zayif yonleri belirt\n2. Hangi konulara odaklanmali?\n"
            f"3. Calisma duzeni yorumu\n4. 3 somut tavsiye ver\n"
            f"Kisisel, icten, motive edici. Turkce. Emoji kullan."
        )
    except Exception as e:
        return f"Tavsiye simdilik uretilemedi.\n\n⚠️ {str(e)[:100]}\n\nLutfen birkaç dakika bekleyip tekrar dene."

def sinav_haberleri_getir():
    try:
        return _gemini(
            "Turkiye'deki guncel sinav haberleri hakkinda bilgi ver. "
            "YKS, LGS, KPSS, ALES, DGS sinavlariyla ilgili son gelismeleri Turkce ozetle. "
            "Madde madde yaz. Emoji kullan."
        )
    except Exception as e:
        return f"Haberler simdilik alinamadi.\n\n⚠️ {str(e)[:100]}\n\nLutfen birkaç dakika bekleyip tekrar dene."

# ══════════════════════════════════════════════════════════
#  YARDIMCI
# ══════════════════════════════════════════════════════════
def metni_bol(metin, limit=4000):
    parcalar = []
    while len(metin) > limit:
        k = metin.rfind("\n", 0, limit)
        if k == -1: k = limit
        parcalar.append(metin[:k]); metin = metin[k:].lstrip()
    if metin: parcalar.append(metin)
    return parcalar

async def uzun_mesaj_gonder(mesaj_obj, metin, parse_mode="Markdown", reply_markup=None):
    parcalar = metni_bol(metin)
    for i, parca in enumerate(parcalar):
        rm = reply_markup if i == len(parcalar)-1 else None
        try:
            await mesaj_obj.reply_text(parca, parse_mode=parse_mode, reply_markup=rm)
        except Exception:
            await mesaj_obj.reply_text(parca, reply_markup=rm)

def test_girdisi_ayristir(metin):
    # "Matematik 20D 5Y 5B" veya "Matematik 20 5 5"
    m = re.match(r"^(\w[\w\s]*?)\s+(\d+)[Dd]\s*(\d+)[Yy]\s*(\d+)[Bb]$", metin.strip())
    if m: return m.group(1).strip(), int(m.group(2)), int(m.group(3)), int(m.group(4))
    m = re.match(r"^(\w[\w\s]*?)\s+(\d+)\s+(\d+)\s+(\d+)$", metin.strip())
    if m: return m.group(1).strip(), int(m.group(2)), int(m.group(3)), int(m.group(4))
    return None

# ══════════════════════════════════════════════════════════
#  MENÜLER
# ══════════════════════════════════════════════════════════
ANA_MENU = ReplyKeyboardMarkup([
    [KeyboardButton("📚 Çalış"), KeyboardButton("📊 Takip & Analiz")],
    [KeyboardButton("🤖 AI Araçlar"), KeyboardButton("🏆 Başarılar")],
    [KeyboardButton("⚙️ Ayarlar"), KeyboardButton("❓ Yardım")],
], resize_keyboard=True, is_persistent=True)

CALIS_MENU = ReplyKeyboardMarkup([
    [KeyboardButton("🍅 Pomodoro Başlat"), KeyboardButton("🛑 Durdur")],
    [KeyboardButton("🗓️ Çalışma Programı"), KeyboardButton("🎯 Hedef Belirle")],
    [KeyboardButton("📝 Not Ekle"), KeyboardButton("📚 Notlarım")],
    [KeyboardButton("🔙 Ana Menü")],
], resize_keyboard=True, is_persistent=True)

TAKIP_MENU = ReplyKeyboardMarkup([
    [KeyboardButton("📊 Bugün"), KeyboardButton("📈 Haftalık Grafik")],
    [KeyboardButton("📅 Aylık Grafik"), KeyboardButton("🔬 Kişisel Tavsiye")],
    [KeyboardButton("📋 Son Testlerim"), KeyboardButton("📅 Sınav Sayaçları")],
    [KeyboardButton("📰 Sınav Haberleri"), KeyboardButton("🔙 Ana Menü")],
], resize_keyboard=True, is_persistent=True)

AI_MENU = ReplyKeyboardMarkup([
    [KeyboardButton("🧠 Konu Özeti"), KeyboardButton("📋 Test Analizi")],
    [KeyboardButton("💬 Soru Sor"), KeyboardButton("📸 Görsel Soru Çöz")],
    [KeyboardButton("💪 Motivasyon"), KeyboardButton("🔙 Ana Menü")],
], resize_keyboard=True, is_persistent=True)

BASARI_MENU = ReplyKeyboardMarkup([
    [KeyboardButton("🏅 Rozetlerim"), KeyboardButton("⭐ Seviyem")],
    [KeyboardButton("🏆 Başarı Hikayeleri"), KeyboardButton("🥇 Liderboard")],
    [KeyboardButton("🔙 Ana Menü")],
], resize_keyboard=True, is_persistent=True)

AYARLAR_MENU = ReplyKeyboardMarkup([
    [KeyboardButton("🔔 Hatırlatıcı Aç/Kapat"), KeyboardButton("💰 İndirimli Kitaplar")],
    [KeyboardButton("🔙 Ana Menü")],
], resize_keyboard=True, is_persistent=True)

# ══════════════════════════════════════════════════════════
#  GERİ SAYIM
# ══════════════════════════════════════════════════════════
async def geri_sayim_dongusu(bot, chat_id, uid, mesaj, toplam_dakika):
    try:
        toplam_saniye = toplam_dakika * 60
        son_guncelleme = ""; bildirim_dakikalari = set()
        for kalan in range(toplam_saniye, -1, -1):
            if uid not in aktif_pomodorolar: return
            dk = kalan // 60; sn = kalan % 60
            gecen = toplam_dakika - dk
            dolu = int((gecen / toplam_dakika) * 10)
            cubuk = "🟩" * dolu + "⬜" * (10 - dolu)
            yeni = (f"🍅 *Pomodoro Devam Ediyor!*\n\n⏳ Kalan: `{dk:02d}:{sn:02d}`\n📊 {cubuk}\n\n🛑 Durdurmak icin *Durdur* butonuna bas.")
            if kalan % 5 == 0 and yeni != son_guncelleme:
                try:
                    await mesaj.edit_text(yeni, parse_mode="Markdown"); son_guncelleme = yeni
                except Exception:
                    pass
            if kalan > 0 and kalan % (10 * 60) == 0:
                kalan_dk = kalan // 60
                if kalan_dk not in bildirim_dakikalari:
                    bildirim_dakikalari.add(kalan_dk)
                    asyncio.create_task(bot.send_message(chat_id=chat_id, text=f"⏰ *{kalan_dk} dakika kaldi!* 💪", parse_mode="Markdown"))
            if kalan == 0: break
            await asyncio.sleep(1)
        if uid not in aktif_pomodorolar: return
        del aktif_pomodorolar[uid]
        pomodoro_kaydet(uid, toplam_dakika)
        yeni_rozetler = rozet_kontrol_ve_ver(uid)
        await asyncio.sleep(0.3)
        tamamlanan, toplam = bugun_istatistik(uid)
        motivasyon = await asyncio.get_event_loop().run_in_executor(None, motivasyon_al, tamamlanan, toplam)
        toplam_p = toplam_pomodoro(uid)
        seviye = seviye_hesapla(toplam_p)
        hedef = aktif_hedef(uid)
        hedef_str = f"\n🎯 Haftalik: *{haftalik_toplam(uid)}/{hedef[0]}* pomodoro" if hedef else ""
        await mesaj.edit_text(f"🎉 *{toplam_dakika} dakika tamamlandi!*", parse_mode="Markdown")
        await bot.send_message(chat_id=chat_id,
            text=(f"📊 *Bugunku Istatistiklerin:*\n\n🍅 Tamamlanan: *{tamamlanan} pomodoro*\n"
                  f"⏱️ Toplam: *{toplam} dakika*\n👤 Seviye: {seviye}{hedef_str}\n\n💬 {motivasyon}\n\n☕ Mola ver!"),
            parse_mode="Markdown", reply_markup=ANA_MENU)
        for rozet in yeni_rozetler:
            await bot.send_message(chat_id=chat_id,
                text=f"🎊 *YENI ROZET!*\n\n{rozet['ikon']} *{rozet['isim']}*\n_{rozet['aciklama']}_", parse_mode="Markdown")
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"Geri sayim hatasi: {e}")

# ══════════════════════════════════════════════════════════
#  HATIRLATICI
# ══════════════════════════════════════════════════════════
async def sabah_hatirlatici(bot):
    for uid in tum_kullanicilar():
        try:
            await bot.send_message(chat_id=uid, text="☀️ *Gunaydın!* Bugün de harika calismalar! 🍅", parse_mode="Markdown")
        except Exception:
            pass

async def aksam_ozeti(bot):
    for uid in tum_kullanicilar():
        try:
            tamamlanan, toplam = bugun_istatistik(uid)
            if tamamlanan == 0: continue
            await bot.send_message(chat_id=uid, text=f"🌙 *Gunluk Ozet*\n\n🍅 Bugün: *{tamamlanan} pomodoro* ({toplam} dk)\n\nHarika! Yarin da devam et 💪", parse_mode="Markdown")
        except Exception:
            pass

# ══════════════════════════════════════════════════════════
#  CONVERSATION HANDLERS
# ══════════════════════════════════════════════════════════
async def not_baslat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📝 *Hangi ders icin not ekleyeceksin?*\n\nDers adini yaz:",
        parse_mode="Markdown", reply_markup=ReplyKeyboardRemove()
    )
    return ST_NOT_DERS

async def not_ders_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["not_ders"] = update.message.text.strip()
    await update.message.reply_text(
        f"📖 *{context.user_data['not_ders']}* icin notunu yaz:", parse_mode="Markdown"
    )
    return ST_NOT_METIN

async def not_metin_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ders = context.user_data.get("not_ders", "Genel")
    not_kaydet(update.effective_user.id, ders, update.message.text.strip())
    await update.message.reply_text(
        f"✅ *Not kaydedildi!*\n\n📚 *{ders}*\n📝 {update.message.text.strip()}",
        parse_mode="Markdown", reply_markup=CALIS_MENU
    )
    return ConversationHandler.END

async def konu_baslat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🧠 *Konu Ozeti Al!*\n\nAnlamak istedigin konuyu yaz:\n\n• `Trigonometri`\n• `Osmanli'nin cokus nedenleri`\n• `Hucre bolunmesi`\n• `Integral`",
        parse_mode="Markdown", reply_markup=ReplyKeyboardRemove()
    )
    return ST_KONU

async def konu_ozet_uret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    konu = update.message.text.strip()
    uid = update.effective_user.id
    bekle = await update.message.reply_text(f"🔍 *'{konu}'* arastiriliyor...")
    ozet = await asyncio.get_event_loop().run_in_executor(None, konu_ozeti_uret, konu)
    konu_gecmisi_kaydet(uid, konu, ozet)
    await bekle.delete()
    await uzun_mesaj_gonder(update.message, f"🧠 *{konu} — Ozet*\n\n{ozet}", reply_markup=AI_MENU)
    return ConversationHandler.END

async def test_baslat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *Test Analizi!*\n\nTest sonucunu gir:\n`[Ders] [D]D [Y]Y [B]B`\n\nOrnek: `Matematik 20D 5Y 5B`",
        parse_mode="Markdown", reply_markup=ReplyKeyboardRemove()
    )
    return ST_TEST_SONUC

async def test_sonuc_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sonuc = test_girdisi_ayristir(update.message.text)
    if not sonuc:
        await update.message.reply_text("⚠️ Format hatali. Ornek: `Matematik 20D 5Y 5B`", parse_mode="Markdown")
        return ST_TEST_SONUC
    ders, d, y, b = sonuc
    context.user_data["test_durum"] = {"ders": ders, "dogru": d, "yanlis": y, "bos": b}
    await update.message.reply_text(
        f"✅ *{ders}* — {d}D / {y}Y / {b}B → Net: *{d - y/4:.2f}*\n\nYanlis yaptigin konulari yaz (veya `gec` yaz):",
        parse_mode="Markdown"
    )
    return ST_TEST_SORULAR

async def test_sorular_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sorular = "" if update.message.text.strip().lower() in ["geç", "gec"] else update.message.text.strip()
    durum = context.user_data.get("test_durum", {})
    uid = update.effective_user.id
    bekle = await update.message.reply_text("🔍 Analiz yapiliyor...")
    analiz = await asyncio.get_event_loop().run_in_executor(
        None, test_analizi_uret, durum["ders"], durum["dogru"], durum["yanlis"], durum["bos"], sorular
    )
    test_sonucu_kaydet(uid, durum["ders"], durum["dogru"], durum["yanlis"], durum["bos"], analiz)
    await bekle.delete()
    await uzun_mesaj_gonder(update.message, f"📋 *Test Analizi — {durum['ders']}*\n\n{analiz}", reply_markup=AI_MENU)
    return ConversationHandler.END

async def soru_baslat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💬 *Serbest Soru-Cevap Modu*\n\nAklindaki soruyu sor!\nCikmak icin /iptal yaz.",
        parse_mode="Markdown", reply_markup=ReplyKeyboardRemove()
    )
    return ST_SORU_CEVAP

async def soru_cevapla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    soru = update.message.text.strip()
    bekle = await update.message.reply_text("🤔 Dusunuyorum...")
    cevap = await asyncio.get_event_loop().run_in_executor(None, serbest_soru_cevapla, soru)
    await bekle.delete()
    await uzun_mesaj_gonder(
        update.message,
        f"💬 {cevap}\n\n_Baska soru sorabilirsin veya /iptal ile cik._",
        reply_markup=ReplyKeyboardRemove()
    )
    return ST_SORU_CEVAP

async def hedef_baslat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mevcut = aktif_hedef(update.effective_user.id)
    mevcut_str = f"\n\n_Mevcut hedef: {mevcut[0]} pomodoro/hafta_" if mevcut else ""
    await update.message.reply_text(
        f"🎯 *Haftalik Hedef Belirle!*{mevcut_str}\n\nBu hafta kac pomodoro yapmak istiyorsun? (ornek: `20`)",
        parse_mode="Markdown", reply_markup=ReplyKeyboardRemove()
    )
    return ST_HEDEF

async def hedef_kaydet_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sayi = int(update.message.text.strip())
        if sayi < 1 or sayi > 200: raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ 1-200 arasi bir sayi gir.")
        return ST_HEDEF
    uid = update.effective_user.id
    hedef_kaydet(uid, sayi)
    await update.message.reply_text(
        f"✅ *Haftalik hedefin: {sayi} pomodoro!*\n\n📅 Gunluk ortalama: *{sayi//7} pomodoro*\n💪 Basarilar!",
        parse_mode="Markdown", reply_markup=CALIS_MENU
    )
    return ConversationHandler.END

# FİX: program_baslat - doğrudan InlineKeyboard göster, callback state'e geçiş doğru
async def program_baslat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    klavye = [[InlineKeyboardButton(sinav, callback_data=f"prog_{sinav}")] for sinav in SINAVLAR.keys()]
    klavye.append([InlineKeyboardButton("📝 Ozel Sinav Gir", callback_data="prog_OZEL")])
    await update.message.reply_text(
        "🗓️ *Akilli Calisma Programi!*\n\nHangi sinava hazirlaniyorsun?",
        reply_markup=InlineKeyboardMarkup(klavye),
        parse_mode="Markdown"
    )
    return ST_PROGRAM_SINAV

# FİX: program_sinav_sec - callback_data "prog_SINAV_ADI" parse et
async def program_sinav_sec(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # "prog_YKS (TYT/AYT)" gibi — prefix'i kes
    sinav = query.data[len("prog_"):]
    if sinav == "OZEL":
        context.user_data["prog_sinav"] = "Ozel"
        context.user_data["prog_tarih"] = "Belirtilmedi"
        await query.edit_message_text(
            "📝 Hangi dersleri calismak istiyorsun?\nVirgülle yaz: `Matematik, Turkce, Fizik`",
            parse_mode="Markdown"
        )
    else:
        context.user_data["prog_sinav"] = sinav
        context.user_data["prog_tarih"] = SINAVLAR[sinav]["tarih"].strftime("%d.%m.%Y") if sinav in SINAVLAR else "Bilinmiyor"
        await query.edit_message_text(
            f"✅ *{sinav}* secildi\n\nHangi dersleri calismak istiyorsun?\nVirgülle yaz: `Matematik, Turkce, Fizik`",
            parse_mode="Markdown"
        )
    return ST_PROGRAM_DERSLER

async def program_dersler_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dersler = update.message.text.strip()
    sinav = context.user_data.get("prog_sinav", "Sinav")
    tarih = context.user_data.get("prog_tarih", "Bilinmiyor")
    uid = update.effective_user.id
    ort_p = haftalik_toplam(uid) // 7 or 2
    bekle = await update.message.reply_text("📅 Program olusturuluyor...")
    program = await asyncio.get_event_loop().run_in_executor(
        None, akilli_program_olustur, sinav, tarih, dersler, ort_p
    )
    await bekle.delete()
    await uzun_mesaj_gonder(update.message, f"🗓️ *{sinav} icin Calisma Programin*\n\n{program}", reply_markup=CALIS_MENU)
    return ConversationHandler.END

async def iptal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Iptal edildi.", reply_markup=ANA_MENU)
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════
#  TEMEL HANDLER'LAR
# ══════════════════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ad = update.effective_user.first_name
    kullanici_kaydet(uid, ad)
    toplam_p = toplam_pomodoro(uid)
    seviye = seviye_hesapla(toplam_p)
    ardisik = ardisik_gun_sayisi(uid)
    await update.message.reply_text(
        f"👋 *Merhaba {ad}!* Ben Pomodoro Arkadasinim! 🍅\n\n"
        f"👤 Seviye: {seviye}\n🍅 Toplam: *{toplam_p} pomodoro*\n🔥 Seri: *{ardisik} gun*\n\nMenuden baslayabilirsin 👇",
        reply_markup=ANA_MENU, parse_mode="Markdown"
    )

# FİX: gorsel_isle - her durumda fotoğraf alınca çalışır, conversation state gerektirmez
async def gorsel_isle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        return
    photo = update.message.photo[-1]
    bekle = await update.message.reply_text("🔍 Soru cozuluyor...")
    try:
        file = await context.bot.get_file(photo.file_id)
        img_bytes = await file.download_as_bytearray()
        cevap = await asyncio.get_event_loop().run_in_executor(
            None, gorsel_soru_coz, bytes(img_bytes), update.message.caption or ""
        )
    except Exception as e:
        cevap = f"Gorsel isleme hatasi: {e}"
    await bekle.delete()
    await uzun_mesaj_gonder(update.message, f"📸 *Gorsel Soru Cozumu:*\n\n{cevap}", reply_markup=AI_MENU)

async def mesaj_isle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    metin = update.message.text
    uid = update.effective_user.id

    if metin == "📚 Çalış":
        await update.message.reply_text("📚 *Calisma Menusu*", parse_mode="Markdown", reply_markup=CALIS_MENU)

    elif metin == "📊 Takip & Analiz":
        await update.message.reply_text("📊 *Takip & Analiz Menusu*", parse_mode="Markdown", reply_markup=TAKIP_MENU)

    elif metin == "🤖 AI Araçlar":
        await update.message.reply_text("🤖 *AI Araclar Menusu*", parse_mode="Markdown", reply_markup=AI_MENU)

    elif metin == "🏆 Başarılar":
        await update.message.reply_text("🏆 *Basari Menusu*", parse_mode="Markdown", reply_markup=BASARI_MENU)

    elif metin == "⚙️ Ayarlar":
        await update.message.reply_text("⚙️ *Ayarlar*", parse_mode="Markdown", reply_markup=AYARLAR_MENU)

    elif metin == "🔙 Ana Menü":
        await update.message.reply_text("🏠 Ana Menu", reply_markup=ANA_MENU)

    elif metin == "🍅 Pomodoro Başlat":
        if uid in aktif_pomodorolar:
            await update.message.reply_text("⚠️ Zaten aktif pomodoro var!", reply_markup=CALIS_MENU)
            return
        klavye = [[
            InlineKeyboardButton("🍅 25 dk", callback_data="sure_25"),
            InlineKeyboardButton("⏱ 40 dk", callback_data="sure_40"),
            InlineKeyboardButton("🔥 60 dk", callback_data="sure_60")
        ]]
        await update.message.reply_text(
            "⏳ *Kac dakika calismak istiyorsun?*",
            reply_markup=InlineKeyboardMarkup(klavye), parse_mode="Markdown"
        )

    elif metin == "🛑 Durdur":
        if uid not in aktif_pomodorolar:
            await update.message.reply_text("❌ Aktif pomodoro yok.", reply_markup=CALIS_MENU)
            return
        aktif_pomodorolar[uid].cancel()
        del aktif_pomodorolar[uid]
        await update.message.reply_text("🛑 *Pomodoro durduruldu.*", parse_mode="Markdown", reply_markup=CALIS_MENU)

    elif metin == "📚 Notlarım":
        notlar = notlar_getir(uid)
        if not notlar:
            await update.message.reply_text("📭 Henüz not yok!", reply_markup=CALIS_MENU)
            return
        m = "📚 *Son Notlarin:*\n\n"
        for tarih, ders, nt in notlar:
            m += f"📅 {tarih} | 📖 *{ders}*\n{nt}\n\n"
        await uzun_mesaj_gonder(update.message, m, reply_markup=CALIS_MENU)

    elif metin == "📊 Bugün":
        tamamlanan, dk = bugun_istatistik(uid)
        toplam_p = toplam_pomodoro(uid)
        seviye = seviye_hesapla(toplam_p)
        ardisik = ardisik_gun_sayisi(uid)
        hedef = aktif_hedef(uid)
        hedef_str = ""
        if hedef:
            hafta_t = haftalik_toplam(uid)
            yuzde = int(hafta_t / hedef[0] * 100) if hedef[0] > 0 else 0
            yuzde = min(yuzde, 100)
            bar = "🟦" * (yuzde // 10) + "⬜" * (10 - yuzde // 10)
            hedef_str = f"\n\n🎯 *Haftalik Hedef:* {hafta_t}/{hedef[0]} — {bar} %{yuzde}"
        await update.message.reply_text(
            f"📊 *Gunluk Istatistikler*\n\n🍅 Bugün: *{tamamlanan} pomodoro* ({dk} dk)\n"
            f"📚 Toplam: *{toplam_p} pomodoro*\n👤 Seviye: {seviye}\n🔥 Seri: *{ardisik} gun*{hedef_str}",
            parse_mode="Markdown", reply_markup=TAKIP_MENU
        )

    elif metin == "📈 Haftalık Grafik":
        bekle = await update.message.reply_text("📊 Grafik olusturuluyor...")
        buf = await asyncio.get_event_loop().run_in_executor(None, haftalik_grafik_olustur, uid)
        await bekle.delete()
        await update.message.reply_photo(photo=buf, caption="📈 *Haftalik Calisma Grafigin*", parse_mode="Markdown")
        await update.message.reply_text("👆", reply_markup=TAKIP_MENU)

    elif metin == "📅 Aylık Grafik":
        bekle = await update.message.reply_text("📅 Aylik grafik hazirlaniyor...")
        buf = await asyncio.get_event_loop().run_in_executor(None, aylik_grafik_olustur, uid)
        await bekle.delete()
        await update.message.reply_photo(photo=buf, caption="📅 *Aylik Calisma Grafigin*", parse_mode="Markdown")
        await update.message.reply_text("👆", reply_markup=TAKIP_MENU)

    elif metin == "🔬 Kişisel Tavsiye":
        bekle = await update.message.reply_text("🔬 Veriler analiz ediliyor...")
        tavsiye = await asyncio.get_event_loop().run_in_executor(None, kisisel_tavsiye_uret, uid)
        await bekle.delete()
        await uzun_mesaj_gonder(update.message, f"🔬 *Kisisel Calisma Analizin*\n\n{tavsiye}", reply_markup=TAKIP_MENU)

    elif metin == "📋 Son Testlerim":
        testler = son_testler(uid)
        if not testler:
            await update.message.reply_text("📭 Henüz test kaydi yok!", reply_markup=TAKIP_MENU)
            return
        m = "📋 *Son Test Sonuclarin:*\n\n"
        for t in testler:
            m += f"📅 {t[0]} | 📖 *{t[1]}*\n✔️{t[2]} ✖️{t[3]} ⬜{t[4]} → Net: *{t[2]-t[3]/4:.1f}*\n\n"
        await uzun_mesaj_gonder(update.message, m, reply_markup=TAKIP_MENU)

    elif metin == "📅 Sınav Sayaçları":
        await update.message.reply_text(sinav_sayaci_metni(), parse_mode="Markdown", reply_markup=TAKIP_MENU)

    elif metin == "📰 Sınav Haberleri":
        bekle = await update.message.reply_text("📰 Haberler aliniyor...")
        haberler = await asyncio.get_event_loop().run_in_executor(None, sinav_haberleri_getir)
        await bekle.delete()
        await uzun_mesaj_gonder(update.message, f"📰 *Guncel Sinav Haberleri*\n\n{haberler}", reply_markup=TAKIP_MENU)

    # FİX: "📸 Görsel Soru Çöz" butonu — kullanıcıya fotoğraf göndermesini söyle
    elif metin == "📸 Görsel Soru Çöz":
        await update.message.reply_text(
            "📸 *Gorsel Soru Cozumu*\n\nSoru fotografini gonder, adim adim cozeyim!\n\n"
            "💡 Fotografi direkt gonder (caption opsiyonel).",
            parse_mode="Markdown", reply_markup=ReplyKeyboardRemove()
        )

    elif metin == "💪 Motivasyon":
        tamamlanan, toplam = bugun_istatistik(uid)
        bekle = await update.message.reply_text("⏳ Motivasyon uretiliyor...")
        mot = await asyncio.get_event_loop().run_in_executor(None, motivasyon_al, tamamlanan, toplam)
        await bekle.edit_text(f"💪 *Gunun Motivasyonu:*\n\n{mot}", parse_mode="Markdown")
        await update.message.reply_text("👆", reply_markup=AI_MENU)

    elif metin == "🏅 Rozetlerim":
        kazanilan = {r[0]: r[1] for r in tum_rozetler(uid)}
        m = "🏅 *Rozetlerin:*\n\n"
        for rozet in ROZETLER:
            if rozet["id"] in kazanilan:
                m += f"{rozet['ikon']} *{rozet['isim']}* ✅\n_{rozet['aciklama']}_\n📅 {kazanilan[rozet['id']]}\n\n"
            else:
                m += f"🔒 *{rozet['isim']}*\n_{rozet['aciklama']}_\n\n"
        await uzun_mesaj_gonder(update.message, m, reply_markup=BASARI_MENU)

    elif metin == "⭐ Seviyem":
        toplam_p = toplam_pomodoro(uid)
        seviye = seviye_hesapla(toplam_p)
        ardisik = ardisik_gun_sayisi(uid)
        sonraki = next(
            (f"\n⏭️ Sonraki seviye icin *{esik - toplam_p} pomodoro* daha → {isim}"
             for esik, isim in SEVIYELER if toplam_p < esik), ""
        )
        await update.message.reply_text(
            f"⭐ *Seviye Kartin*\n\n👤 Seviye: {seviye}\n🍅 Toplam: *{toplam_p} pomodoro*\n🔥 Ardisik: *{ardisik} gun*{sonraki}",
            parse_mode="Markdown", reply_markup=BASARI_MENU
        )

    elif metin == "🏆 Başarı Hikayeleri":
        klavye = [[InlineKeyboardButton(f"🏆 {h['isim']}", callback_data=f"hikaye_{i}")] for i, h in enumerate(HIKAYELER)]
        await update.message.reply_text(
            "🏆 *Hangi basari hikayesini okumak istiyorsun?*",
            reply_markup=InlineKeyboardMarkup(klavye), parse_mode="Markdown"
        )

    elif metin == "🥇 Liderboard":
        lider = liderboard_getir()
        if not lider:
            await update.message.reply_text("📭 Bugün henüz kimse calismadi!", reply_markup=BASARI_MENU)
            return
        m = "🥇 *Bugunun Liderboard'u*\n\n"
        madalyalar = ["🥇", "🥈", "🥉"]
        for i, (lid_uid, ad, pom) in enumerate(lider):
            emoji = madalyalar[i] if i < 3 else f"{i+1}."
            sen = " ← *Sen*" if lid_uid == uid else ""
            m += f"{emoji} *{ad}* — {pom} pomodoro{sen}\n"
        await update.message.reply_text(m, parse_mode="Markdown", reply_markup=BASARI_MENU)

    elif metin == "🔔 Hatırlatıcı Aç/Kapat":
        yeni = hatirlatici_toggle(uid)
        await update.message.reply_text(
            f"🔔 Hatirlaticilar: *{'✅ Acik' if yeni else '❌ Kapali'}*",
            parse_mode="Markdown", reply_markup=AYARLAR_MENU
        )

    elif metin == "💰 İndirimli Kitaplar":
        sirali = sorted(INDIRIMLI_KITAPLAR, key=lambda x: x["indirim"], reverse=True)
        klavye = [[InlineKeyboardButton(
            f"{k['ikon']} %{k['indirim']} — {k['isim'][:28]}",
            callback_data=f"kitap_{i}"
        )] for i, k in enumerate(sirali)]
        ozet = "💰 *Indirimli Sinav Kitaplari*\n\n"
        for k in sirali:
            ozet += f"{k['ikon']} *{k['isim']}*\n   ~~{k['eski_fiyat']}₺~~ → *{k['yeni_fiyat']}₺* (%{k['indirim']})\n\n"
        await update.message.reply_text(
            ozet + "_Detay icin tikla:_",
            reply_markup=InlineKeyboardMarkup(klavye), parse_mode="Markdown"
        )

    elif metin == "❓ Yardım":
        await update.message.reply_text(
            "❓ *Yardim Menusu*\n\n"
            "📚 *Calis:* Pomodoro, Program, Not\n"
            "📊 *Takip:* Grafik, Istatistik, Sinav Sayaclari, Haberler\n"
            "🤖 *AI:* Konu Ozeti, Test Analizi, Soru-Cevap, Gorsel Cozum\n"
            "🏆 *Basarilar:* Rozetler, Seviye, Liderboard",
            parse_mode="Markdown", reply_markup=ANA_MENU
        )

# ══════════════════════════════════════════════════════════
#  BUTON HANDLER (FİX: program callback sadece burada, conversation dışı)
# ══════════════════════════════════════════════════════════
async def buton_isle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    chat_id = query.message.chat_id
    veri = query.data

    if veri.startswith("sure_"):
        if uid in aktif_pomodorolar:
            await query.edit_message_text("⚠️ Zaten aktif pomodoro var!")
            return
        sure = int(veri.split("_")[1])
        mesaj = await query.edit_message_text(
            f"🍅 *{sure} dakikalik pomodoro basladi!*\n\n⏳ Kalan: `{sure:02d}:00`\n📊 ⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜\n\n🛑 Durdurmak icin *Durdur* butonuna bas.",
            parse_mode="Markdown"
        )
        task = asyncio.create_task(geri_sayim_dongusu(context.bot, chat_id, uid, mesaj, sure))
        aktif_pomodorolar[uid] = task

    elif veri.startswith("hikaye_"):
        idx = int(veri.split("_")[1])
        if idx < len(HIKAYELER):
            await query.edit_message_text(HIKAYELER[idx]["hikaye"], parse_mode="Markdown")

    elif veri.startswith("kitap_"):
        idx = int(veri.split("_")[1])
        sirali = sorted(INDIRIMLI_KITAPLAR, key=lambda x: x["indirim"], reverse=True)
        if idx < len(sirali):
            k = sirali[idx]
            tasarruf = k["eski_fiyat"] - k["yeni_fiyat"]
            await query.edit_message_text(
                f"{k['ikon']} *{k['isim']}*\n\n🏢 {k['yayinevi']}\n"
                f"💲 Eski: ~~{k['eski_fiyat']}₺~~\n✅ *{k['yeni_fiyat']}₺* ({tasarruf}₺ tasarruf!)\n"
                f"🔖 *%{k['indirim']} indirim*\n\n🛒 {k['url']}\n\n_Fiyatlar degisebilir._",
                parse_mode="Markdown"
            )

    # NOTE: prog_ callback'leri artık ConversationHandler içinde handle ediliyor
    # Ama eğer conversation dışında tetiklenirse burada yakala
    elif veri.startswith("prog_"):
        await program_sinav_sec(update, context)

# ══════════════════════════════════════════════════════════
#  BAŞLAT
# ══════════════════════════════════════════════════════════
async def post_init(application):
    scheduler = AsyncIOScheduler(timezone="Europe/Istanbul")
    scheduler.add_job(sabah_hatirlatici, "cron", hour=8, minute=0, args=[application.bot])
    scheduler.add_job(aksam_ozeti, "cron", hour=21, minute=30, args=[application.bot])
    scheduler.start()
    print("✅ Hatirlaticilar aktif!")

if __name__ == "__main__":
    veritabani_baslat()
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .concurrent_updates(True)
        .post_init(post_init)
        .build()
    )

    # ConversationHandler'lar
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 Not Ekle$"), not_baslat)],
        states={
            ST_NOT_DERS:  [MessageHandler(filters.TEXT & ~filters.COMMAND, not_ders_al)],
            ST_NOT_METIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, not_metin_al)],
        },
        fallbacks=[CommandHandler("iptal", iptal)],
        name="not_conv", persistent=False
    ))

    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🧠 Konu Özeti$"), konu_baslat)],
        states={ST_KONU: [MessageHandler(filters.TEXT & ~filters.COMMAND, konu_ozet_uret)]},
        fallbacks=[CommandHandler("iptal", iptal)],
        name="konu_conv", persistent=False
    ))

    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📋 Test Analizi$"), test_baslat)],
        states={
            ST_TEST_SONUC:  [MessageHandler(filters.TEXT & ~filters.COMMAND, test_sonuc_al)],
            ST_TEST_SORULAR:[MessageHandler(filters.TEXT & ~filters.COMMAND, test_sorular_al)],
        },
        fallbacks=[CommandHandler("iptal", iptal)],
        name="test_conv", persistent=False
    ))

    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💬 Soru Sor$"), soru_baslat)],
        states={ST_SORU_CEVAP: [MessageHandler(filters.TEXT & ~filters.COMMAND, soru_cevapla)]},
        fallbacks=[CommandHandler("iptal", iptal)],
        name="soru_conv", persistent=False
    ))

    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎯 Hedef Belirle$"), hedef_baslat)],
        states={ST_HEDEF: [MessageHandler(filters.TEXT & ~filters.COMMAND, hedef_kaydet_handler)]},
        fallbacks=[CommandHandler("iptal", iptal)],
        name="hedef_conv", persistent=False
    ))

    # FİX: Çalışma Programı conversation — callback pattern düzeltildi
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🗓️ Çalışma Programı$"), program_baslat)],
        states={
            ST_PROGRAM_SINAV: [CallbackQueryHandler(program_sinav_sec, pattern="^prog_")],
            ST_PROGRAM_DERSLER: [MessageHandler(filters.TEXT & ~filters.COMMAND, program_dersler_al)],
        },
        fallbacks=[CommandHandler("iptal", iptal)],
        name="program_conv", persistent=False
    ))

    # Temel handler'lar
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buton_isle))  # prog_ dışındaki callback'ler
    app.add_handler(MessageHandler(filters.PHOTO, gorsel_isle))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mesaj_isle))

    print("✅ Bot v3.2 calisiyor... Durdurmak icin CTRL+C")
    app.run_polling(drop_pending_updates=True)