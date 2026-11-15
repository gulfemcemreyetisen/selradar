"""ADIM 2: Yapilarin etki analizi (kesisim).

Ne yapar?
  1) Sel haritasini ve kritik yapilari okur, METREYE cevirir   (Adim 1 ile ayni)
  2) Sel alanina 100 m tampon (buffer) ekler
  3) sjoin ile tamponun icinde kalan / sinirina degen yapilari bulur
  4) Sonucu bir sozluge (dictionary) koyar ve JSON olarak kaydeder

Cikti:
    analiz/cikti/etkilenen_yapilar.json

Calistirmak icin (depo klasorunde):
    python analiz/adim2_etki_analizi.py
"""
import json
from pathlib import Path

import geopandas as gpd

# ---------------------------------------------------------------
# Dosyalarin yerleri (Adim 1 ile ayni)
# ---------------------------------------------------------------
DEPO = Path(__file__).resolve().parent.parent
VERI = DEPO / "analiz" / "veri"
CIKTI = DEPO / "analiz" / "cikti" / "etkilenen_yapilar.json"

SEL_DOSYASI = DEPO / "selradar" / "data" / "flood_extent.geojson"
YAPI_DOSYASI = VERI / "critical_places.geojson"

METRE_CRS = 32736      # UTM 36 Guney, birimi METRE
TAMPON_M = 100         # sel sinirina kac metre yakin yapilar da "etkilenmis" sayilsin


def oku(yol):
    gdf = gpd.read_file(yol)
    if gdf.crs is None:
        gdf = gdf.set_crs(4326)
    return gdf


# ---------------------------------------------------------------
# 1) Oku ve metreye cevir
#    (Derecedeyken buffer(100) = 100 DERECE olurdu, mutlaka metreye cevir!)
# ---------------------------------------------------------------
sel_m = oku(SEL_DOSYASI).to_crs(METRE_CRS)
yapilar_m = oku(YAPI_DOSYASI).to_crs(METRE_CRS)
print(f"Sel haritasi : {len(sel_m)} poligon, {sel_m.area.sum() / 1e6:.1f} km2")
print(f"Kritik yapi  : {len(yapilar_m)} adet {yapilar_m['kategori'].value_counts().to_dict()}")

# ---------------------------------------------------------------
# 2) 100 metrelik tampon
#    Once tum sel poligonlarini tek parca yap (union_all), sonra buffer.
#    Boylece ust uste binen tamponlar ayni yapiyi iki kez saymaz.
# ---------------------------------------------------------------
sel_birlesik = sel_m.union_all()
tampon = gpd.GeoDataFrame(geometry=[sel_birlesik.buffer(TAMPON_M)], crs=METRE_CRS)
print(f"Tamponlu alan: {tampon.area.sum() / 1e6:.1f} km2 (+{TAMPON_M} m)")

# ---------------------------------------------------------------
# 3) sjoin: tamponun icinde kalan veya sinirina degen yapilar
#    predicate="intersects" -> icinde olan + kenarina degen + (yol/kopru icin) kesen
# ---------------------------------------------------------------
etkilenen = gpd.sjoin(yapilar_m, tampon, how="inner", predicate="intersects")
etkilenen = etkilenen.drop(columns="index_right").drop_duplicates(subset="id")

# Ek bilgi: yapi selin tam icinde mi, yoksa sadece 100 m yakininda mi?
etkilenen["sel_icinde"] = etkilenen.intersects(sel_birlesik)
etkilenen["sele_mesafe_m"] = etkilenen.distance(sel_birlesik).round()
# Konum (derece): isimsiz yapilari sitede ayirt etmek icin
_nokta = etkilenen.geometry.representative_point().to_crs(4326)
etkilenen["_lon"], etkilenen["_lat"] = _nokta.x, _nokta.y

print(f"\nEtkilenen yapi: {len(etkilenen)} adet")
print(etkilenen.groupby(["kategori", "sel_icinde"]).size().unstack(fill_value=0)
      .rename(columns={True: "sel icinde", False: f"{TAMPON_M} m yakininda"}))

# ---------------------------------------------------------------
# 4) Sozluk (dictionary) olarak topla
# ---------------------------------------------------------------
def kategori(ad):
    return etkilenen[etkilenen["kategori"] == ad]


def isimler(gdf):
    """Isimli olanlarin listesi; isimsizleri sayi olarak ekle."""
    adlar = sorted(a for a in gdf["ad"].fillna("") if a.strip())
    isimsiz = int((gdf["ad"].fillna("").str.strip() == "").sum())
    return adlar + ([f"(isimsiz {isimsiz} adet)"] if isimsiz else [])


yollar = kategori("yol")
sonuc = {
    "tampon_m": TAMPON_M,
    "sel_haritasi": str(SEL_DOSYASI.relative_to(DEPO)),
    "etkilenen_hastane_sayisi": len(kategori("hastane")),
    "etkilenen_hastane_isimleri": isimler(kategori("hastane")),
    "etkilenen_okul_sayisi": len(kategori("okul")),
    "etkilenen_okul_isimleri": isimler(kategori("okul")),
    "etkilenen_kopru_sayisi": len(kategori("kopru")),
    "etkilenen_kopru_isimleri": isimler(kategori("kopru")),
    "etkilenen_yol_parcasi_sayisi": len(yollar),
    # Yolun sadece tamponun icindeki kismi (tum yol degil)
    "etkilenen_yol_km": round(float(yollar.intersection(tampon.geometry.iloc[0]).length.sum() / 1000), 1),
    "sel_icindeki_yapi_sayisi": int(etkilenen["sel_icinde"].sum()),
    "yakinindaki_yapi_sayisi": int((~etkilenen["sel_icinde"]).sum()),
    # Tek tek liste (Adim 5 site dosyasi icin kullanir)
    "yapilar": [
        {"id": r["id"], "kategori": r["kategori"], "ad": (r["ad"] or "").strip(),
         "sel_icinde": bool(r["sel_icinde"]), "sele_mesafe_m": int(r["sele_mesafe_m"]),
         "konum": [round(r["_lon"], 5), round(r["_lat"], 5)]}   # [boylam, enlem]
        for _, r in etkilenen.sort_values(["sel_icinde", "kategori"], ascending=[False, True]).iterrows()
    ],
}

CIKTI.parent.mkdir(parents=True, exist_ok=True)
CIKTI.write_text(json.dumps(sonuc, ensure_ascii=False, indent=2), encoding="utf-8")

print("\n=== SONUC ===")
for k, v in sonuc.items():
    if not isinstance(v, list):
        print(f"{k:32s}: {v}")
print(f"\nKaydedildi: {CIKTI}")
print("Adim 2 tamam.")
