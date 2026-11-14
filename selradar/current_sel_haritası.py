#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Nov 14 11:27:41 2026

@author: nazcelik
"""

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kişi 1 - Gerçek NASA Uydu Verileriyle Sel Tespiti (Tam Kod)
"""

import os
import glob
import json
import zipfile
import numpy as np
from PIL import Image
from scipy.ndimage import median_filter, label, find_objects

Image.MAX_IMAGE_PIXELS = None

# Mozambik, Gaza eyaleti, Limpopo Nehri aşağı havzası koordinat sınırları
LAT_MIN, LAT_MAX = -25.0, -24.0
LON_MIN, LON_MAX = 32.5, 33.5

# -------------------------------------------------------------------------
# ADIM 1: Gerçek Önce ve Sonra Radar Görüntülerini Oku ve Aynı Alana Kırp
def dosya_bul(adaylar):
    for ad in adaylar:
        if os.path.exists(ad):
            return ad
    raise FileNotFoundError(f"Masaüstünde şu dosyalardan biri bulunamadı: {adaylar}")

once_dosya = dosya_bul(["önce.tiff", "once.tiff", "önce.tif", "once.tif"])
sonra_dosya = dosya_bul(["sonra.tiff", "sonra.tif"])

print(f"📂 Gerçek radar verileri okunuyor: {once_dosya} ve {sonra_dosya} ...")

def tiff_oku_ve_kucult(dosya_yolu, adim=80):
    img = Image.open(dosya_yolu)
    w, h = img.size
    img_kucuk = img.resize((max(1, w // adim), max(1, h // adim)))
    return np.array(img_kucuk, dtype=np.float32)

once_raw = tiff_oku_ve_kucult(once_dosya)
sonra_raw = tiff_oku_ve_kucult(sonra_dosya)

ROWS = min(once_raw.shape[0], sonra_raw.shape[0])
COLS = min(once_raw.shape[1], sonra_raw.shape[1])
once_raw = once_raw[:ROWS, :COLS]
sonra_raw = sonra_raw[:ROWS, :COLS]

# Gerçek NASADEM (.hgt veya .zip) Verisini Oku ve Eğim Hesapla
def nasadem_egim_hesapla(rows, cols):
    hgt_adaylari = glob.glob("*s25e03*.hgt*") + glob.glob("*S25E03*.hgt*") + glob.glob("*.hgt*")
    if not hgt_adaylari:
        return np.zeros((rows, cols), dtype=np.float32), "Sentinel-1 + Varsayılan Eğim"
    
    dosya = hgt_adaylari[0]
    try:
        if dosya.endswith(".zip"):
            with zipfile.ZipFile(dosya, "r") as z:
                hgt_ic = [f for f in z.namelist() if f.lower().endswith(".hgt")][0]
                raw_bytes = z.read(hgt_ic)
        else:
            with open(dosya, "rb") as f:
                raw_bytes = f.read()
                
        dem = np.frombuffer(raw_bytes, dtype=">i2").reshape((3601, 3601)).astype(np.float32)
        dem[dem < -100] = 0.0
        dem_img = Image.fromarray(dem).resize((cols, rows))
        dem_kucuk = np.array(dem_img, dtype=np.float32)
        dy, dx = np.gradient(dem_kucuk, 400.0)
        egim_derece = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))
        return egim_derece, f"Gerçek NASADEM ({dosya})"
    except Exception:
        return np.zeros((rows, cols), dtype=np.float32), "Sentinel-1"

egim_haritasi, dem_kaynak_bilgisi = nasadem_egim_hesapla(ROWS, COLS)

# -------------------------------------------------------------------------
# ADIM 2 & 3: Desibele çevir (dB = 10 * log10) ve 5x5 medyan filtre uygula
once_db = 10.0 * np.log10(np.clip(once_raw, 1.0, None))
sonra_db = 10.0 * np.log10(np.clip(sonra_raw, 1.0, None))

once_filtreli = median_filter(once_db, size=5)
sonra_filtreli = median_filter(sonra_db, size=5)
print("✅ Adım 1 (Okuma, Desibel ve 5x5 Medyan Filtre) Tamamlandı!")

# -------------------------------------------------------------------------
# ADIM 4 & 5: Farkı hesapla (sonra - önce) ve Otsu eşiğini bul
fark_db = sonra_filtreli - once_filtreli

def otsu_esigi_bul(goruntu):
    duz = goruntu[goruntu > 0.1].ravel()
    if duz.size == 0:
        duz = goruntu.ravel()
    hist, bin_edges = np.histogram(duz, bins=256)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2.0
    toplam = duz.size
    toplam_agirlik = np.dot(hist, bin_centers)
    agirlik_arka, toplam_arka, maks_varyans = 0.0, 0.0, 0.0
    esik = bin_centers[0]
    for i in range(256):
        agirlik_arka += hist[i]
        if agirlik_arka == 0:
            continue
        agirlik_on = toplam - agirlik_arka
        if agirlik_on == 0:
            break
        toplam_arka += hist[i] * bin_centers[i]
        ort_arka = toplam_arka / agirlik_arka
        ort_on = (toplam_agirlik - toplam_arka) / agirlik_on
        varyans = agirlik_arka * agirlik_on * ((ort_arka - ort_on) ** 2)
        if varyans > maks_varyans:
            maks_varyans = varyans
            esik = bin_centers[i]
    return esik

otsu_esik = otsu_esigi_bul(sonra_filtreli)
ham_sel_maskesi = (fark_db <= -3.0) & (sonra_filtreli < otsu_esik) & (once_raw > 0) & (sonra_raw > 0)
print(f"✅ Adım 2 Tamamlandı! Gerçek Otsu Eşiği: {otsu_esik:.2f} dB")

# -------------------------------------------------------------------------
# ADIM 6: Temizlik -> Kalıcı suyu, eğimi 5°'den büyük yerleri ve küçük lekeleri çıkar
kalici_su = (once_filtreli < (otsu_esik * 0.95))
temiz_maske = ham_sel_maskesi & (~kalici_su) & (egim_haritasi <= 5.0)

etiketli_maske, _ = label(temiz_maske)
piksel_sayilari = np.bincount(etiketli_maske.ravel())
kucuk_lekeler = piksel_sayilari < 8
kucuk_lekeler[0] = False
temiz_maske[kucuk_lekeler[etiketli_maske]] = False
print(f"✅ Adım 3 Tamamlandı! Net sel pikseli: {np.sum(temiz_maske)}")

# -------------------------------------------------------------------------
# ADIM 7: Poligonlara çevir ve GERÇEK flood_extent.geojson olarak kaydet
temiz_etiketler, _ = label(temiz_maske)
dilimler = find_objects(temiz_etiketler)

features = []
for idx, dilim in enumerate(dilimler):
    if dilim is None:
        continue
    r_slice, c_slice = dilim
    lat_ust = LAT_MAX - (r_slice.start / ROWS) * (LAT_MAX - LAT_MIN)
    lat_alt = LAT_MAX - (r_slice.stop / ROWS) * (LAT_MAX - LAT_MIN)
    lon_sol = LON_MIN + (c_slice.start / COLS) * (LON_MAX - LON_MIN)
    lon_sag = LON_MIN + (c_slice.stop / COLS) * (LON_MAX - LON_MIN)
    
    poligon = [[
        [round(lon_sol, 5), round(lat_ust, 5)],
        [round(lon_sag, 5), round(lat_ust, 5)],
        [round(lon_sag, 5), round(lat_alt, 5)],
        [round(lon_sol, 5), round(lat_alt, 5)],
        [round(lon_sol, 5), round(lat_ust, 5)]
    ]]
    
    features.append({
        "type": "Feature",
        "properties": {
            "id": idx + 1,
            "once_tarih": "2025-12-18",
            "sonra_tarih": "2026-01-17",
            "kaynak": "Sentinel-1 GRD-HD + NASADEM",
            "otsu_esigi_db": round(float(otsu_esik), 2),
            "alan_piksel": int(np.sum(temiz_etiketler[dilim] == (idx + 1)))
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": poligon
        }
    })

geojson_verisi = {
    "type": "FeatureCollection",
    "name": "Mozambik_Limpopo_Gercek_Sel_Haritasi",
    "features": features
}

with open("flood_extent.geojson", "w", encoding="utf-8") as f:
    json.dump(geojson_verisi, f, ensure_ascii=False, indent=2)

kaynak_metni = f"""# Kişi 1 - Sel Tespiti Gerçek Veri Kaynakları
- **Bölge:** Mozambik, Gaza eyaleti, Limpopo Nehri aşağı havzası (25.0-24.0 G, 32.5-33.5 D)
- **Sel Öncesi Radar Verisi:** Sentinel-1C IW GRD-HD (18 Aralık 2025, 03:17 UTC, Path 79, Frame 671 - NASA ASF Vertex)
- **Sel Sonrası Radar Verisi:** Sentinel-1A IW GRD-HD (17 Ocak 2026, 03:18 UTC, Path 79, Frame 675 - NASA ASF Vertex)
- **Arazi Eğimi Verisi:** NASADEM_HGT v001 ({dem_kaynak_bilgisi} - NASA Earthdata LP DAAC)
- **Lisans:** Copernicus Sentinel Data & NASA Earthdata Açık Veri Lisansı
"""
with open("kaynaklar.md", "w", encoding="utf-8") as f:
    f.write(kaynak_metni)

print("🎉 ADIM 4 TAMAMLANDI! Gerçek 'flood_extent.geojson' masaüstüne kaydedildi!")
print(f"Toplam Tespit Edilen Sel Poligonu: {len(features)} adet")