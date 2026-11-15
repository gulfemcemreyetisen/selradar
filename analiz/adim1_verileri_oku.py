"""ADIM 1: Verileri projeye dahil etmek.

Ne yapar?
  1) Takimin sel haritasini okur        (selradar/data/flood_extent.geojson)
  2) Kritik yapilari okur               (analiz/veri/critical_places.geojson)
  3) Nufus haritasini kontrol eder      (analiz/veri/worldpop.tif)
  4) Referans haritayi arar             (analiz/veri/referans_sel.geojson)
  5) Hepsini dereceden METREYE cevirir  (EPSG:32736)

Calistirmak icin (depo klasorunde):
    python analiz/adim1_verileri_oku.py
"""
from pathlib import Path

import geopandas as gpd
import rasterio

# ---------------------------------------------------------------
# Dosyalarin yerleri
# ---------------------------------------------------------------
DEPO = Path(__file__).resolve().parent.parent
VERI = DEPO / "analiz" / "veri"

SEL_DOSYASI = DEPO / "selradar" / "data" / "flood_extent.geojson"  # Kisi 3'un haritasi
YAPI_DOSYASI = VERI / "critical_places.geojson"                     # OSM'den gelen yapilar
NUFUS_DOSYASI = VERI / "worldpop.tif"                               # WorldPop nufus
REFERANS_DOSYASI = VERI / "referans_sel.geojson"                    # Copernicus / UNOSAT (henuz yok)

# Mozambik, Gaza eyaleti -> UTM 36 Guney. Birimi METRE.
METRE_CRS = 32736


def oku(yol):
    """GeoJSON dosyasini okur. Koordinat sistemi yazmiyorsa derece (4326) kabul eder."""
    gdf = gpd.read_file(yol)
    if gdf.crs is None:
        gdf = gdf.set_crs(4326)
    return gdf


# ---------------------------------------------------------------
# 1) Takimin sel haritasi
# ---------------------------------------------------------------
sel = oku(SEL_DOSYASI)
print("=== 1) TAKIMIN SEL HARITASI ===")
print("Koordinat sistemi :", sel.crs)
print("Kac parca         :", len(sel))
if "is_sample" in sel.columns and sel["is_sample"].any():
    print("DIKKAT: Bu harita ORNEK (sentetik). Gercek NISAR haritasi gelince sonuclar degisecek.")

# ---------------------------------------------------------------
# 2) Kritik yapilar
# ---------------------------------------------------------------
yapilar = oku(YAPI_DOSYASI)
print("\n=== 2) KRITIK YAPILAR ===")
print("Koordinat sistemi :", yapilar.crs)
print("Kac yapi          :", len(yapilar))
print("Sutunlar          :", [c for c in yapilar.columns if c != "geometry"])
print("Kategoriler       :", yapilar["kategori"].value_counts().to_dict())
print("Sekil tipleri     :", yapilar.geom_type.value_counts().to_dict())

# ---------------------------------------------------------------
# 3) Nufus haritasi (raster: her piksel = o karedeki kisi sayisi)
# ---------------------------------------------------------------
print("\n=== 3) NUFUS HARITASI (WorldPop) ===")
with rasterio.open(NUFUS_DOSYASI) as src:
    print("Koordinat sistemi :", src.crs)
    print("Boyut             :", src.width, "x", src.height, "piksel")

# ---------------------------------------------------------------
# 4) Referans harita (cevap anahtari)
# ---------------------------------------------------------------
print("\n=== 4) REFERANS HARITA (Copernicus / UNOSAT) ===")
if REFERANS_DOSYASI.exists():
    referans = oku(REFERANS_DOSYASI)
    print("Kac parca         :", len(referans))
else:
    referans = None
    print("HENUZ YOK. Adim 4 (dogrulama) icin indirilmesi gerekiyor.")

# ---------------------------------------------------------------
# 5) Dereceden metreye cevir (COK KRITIK)
#    Derecedeyken buffer(100) = 100 DERECE olurdu (dunyanin yarisi!)
# ---------------------------------------------------------------
sel_m = sel.to_crs(METRE_CRS)
yapilar_m = yapilar.to_crs(METRE_CRS)
referans_m = referans.to_crs(METRE_CRS) if referans is not None else None

print("\n=== 5) METREYE CEVIRDIKTEN SONRA ===")
print("Yeni koordinat sistemi:", sel_m.crs, "(birim: metre)")
print("Sel alani             :", round(sel_m.area.sum() / 1_000_000, 1), "km2")
print("\nAdim 1 tamam.")
