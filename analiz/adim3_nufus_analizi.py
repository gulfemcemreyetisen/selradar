
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
import rasterio.windows
from rasterio.features import rasterize
from rasterio.windows import Window, from_bounds
from shapely.geometry import box

DEPO = Path(__file__).resolve().parent.parent
VERI = DEPO / "analiz" / "veri"
CIKTI = DEPO / "analiz" / "cikti" / "etkilenen_nufus.json"

SEL_DOSYASI = DEPO / "selradar" / "data" / "flood_extent.geojson"
# Tum Mozambik dosyasi varsa o kullanilir (sel haritasinin tamamini kapsar);
# yoksa analiz/veri/worldpop.tif (sadece 32.5-33.5 D / 25-24 G kirpintisi)
NUFUS_ADAYLARI = [DEPO.parent / "data" / "raw" / "moz_pop_2026_CN_100m_R2025A_v1.tif",
                  VERI / "moz_pop_2026_CN_100m_R2025A_v1.tif",
                  VERI / "worldpop.tif"]
NUFUS_DOSYASI = next((p for p in NUFUS_ADAYLARI if p.exists()), VERI / "worldpop.tif")

METRE_CRS = 32736
TAMPON_M = 100


def nufus_topla(geometriler, nufus, transform):
    """Geometrilerin icindeki piksellerin nufus toplami (piksel merkezi icerdeyse sayilir)."""
    if not geometriler:
        return 0.0
    maske = rasterize(geometriler, out_shape=nufus.shape, transform=transform).astype(bool)
    return float(nufus[maske].sum())


# ---------------------------------------------------------------
# 1) Oku
# ---------------------------------------------------------------
sel = gpd.read_file(SEL_DOSYASI)
if sel.crs is None:
    sel = sel.set_crs(4326)

with rasterio.open(NUFUS_DOSYASI) as src:
    # Sadece sel haritasinin (+ tampon payi) kapladigi pencereyi oku; buyuk dosyada hizli
    b = sel.to_crs(src.crs).total_bounds
    pay = 0.01
    pencere = from_bounds(b[0] - pay, b[1] - pay, b[2] + pay, b[3] + pay, src.transform)
    pencere = pencere.round_offsets().round_lengths().intersection(Window(0, 0, src.width, src.height))
    nufus = src.read(1, window=pencere).astype("float64")
    transform, nufus_crs, nodata = src.window_transform(pencere), src.crs, src.nodata
    nufus_kutusu = box(*rasterio.windows.bounds(pencere, src.transform))

# Bos (nodata) ve gecersiz pikselleri 0 kisi say
if nodata is not None:
    nufus[nufus == nodata] = 0
nufus[~np.isfinite(nufus) | (nufus < 0)] = 0

print(f"Sel haritasi : {len(sel)} poligon")
print(f"WorldPop     : {NUFUS_DOSYASI.name}, {nufus.shape[1]} x {nufus.shape[0]} piksel, "
      f"bolgedeki toplam nufus {nufus.sum():,.0f}")

# ---------------------------------------------------------------
# 2) Sel alanini nufus haritasinin koordinat sistemine getir
#    + 100 m tampon (tampon METRE cinsinden cizilir, sonra geri cevrilir)
# ---------------------------------------------------------------
sel_birlesik_m = sel.to_crs(METRE_CRS).union_all()
sel_r = gpd.GeoSeries([sel_birlesik_m], crs=METRE_CRS).to_crs(nufus_crs).iloc[0]
tampon_r = gpd.GeoSeries([sel_birlesik_m.buffer(TAMPON_M)], crs=METRE_CRS).to_crs(nufus_crs).iloc[0]

# Sel haritasinin WorldPop'un DISINDA kalan kismi hesaba girmez -> kullaniciya soyle
kapsanan = gpd.GeoSeries([sel_r.intersection(nufus_kutusu)], crs=nufus_crs).to_crs(METRE_CRS).area.iloc[0]
oran = 100 * kapsanan / sel_birlesik_m.area
print(f"Sel alaninin %{oran:.0f}'i WorldPop bolgesinin icinde (gerisi hesaba girmedi)")

# ---------------------------------------------------------------
# 3) Topla
# ---------------------------------------------------------------
sel_nufus = nufus_topla([sel_r], nufus, transform)
tampon_nufus = nufus_topla([tampon_r], nufus, transform)

sonuc = {
    "etkilenen_tahmini_nufus": round(sel_nufus),
    f"etkilenen_tahmini_nufus_{TAMPON_M}m_tamponla": round(tampon_nufus),
    "bolgedeki_toplam_nufus": round(float(nufus.sum())),
    "etkilenen_oran_yuzde": round(100 * sel_nufus / nufus.sum(), 1),
    "sel_alani_km2": round(sel_birlesik_m.area / 1e6, 1),
    "sel_alaninin_worldpop_icindeki_yuzdesi": round(oran, 1),
    "sel_haritasi": str(SEL_DOSYASI.relative_to(DEPO)),
    "nufus_kaynagi": "WorldPop 2026, 100 m (CC BY 4.0)",

}

CIKTI.parent.mkdir(parents=True, exist_ok=True)
CIKTI.write_text(json.dumps(sonuc, ensure_ascii=False, indent=2), encoding="utf-8")

print("\n=== SONUC ===")
for k, v in sonuc.items():
    print(f"{k:42s}: {v:,}" if isinstance(v, (int, float)) else f"{k:42s}: {v}")

