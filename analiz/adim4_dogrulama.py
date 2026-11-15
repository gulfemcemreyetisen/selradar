
import json
import sys
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

DEPO = Path(__file__).resolve().parent.parent
VERI = DEPO / "analiz" / "veri"
SEL_DOSYASI = DEPO / "selradar" / "data" / "flood_extent.geojson"
CIKTI = DEPO / "analiz" / "cikti" / "dogruluk.json"
METRE_CRS = 32736   # UTM 36 Guney, metre
VARSAYILAN_ZIPLER = [
    Path.home() / "Downloads" / ad for ad in (
        "EMSR857_AOI01_FEP_PRODUCT_v1.zip",
        "EMSR857_AOI01_DEL_PRODUCT_v1.zip",
        "EMSR857_AOI01_DEL_MONIT01_v1.zip",
        "EMSR857_AOI01_DEL_MONIT02_v2.zip",
    )
]


def iou_hesapla(sel, referans, kapsam=None):
    """Iki sel haritasini karsilastirir.

    sel      : bizim sel poligonlarimiz (GeoDataFrame)
    referans : Copernicus sel poligonlari (GeoDataFrame)
    kapsam   : (istege bagli) karsilastirmanin yapilacagi alan (shapely geometri, METRE_CRS'te).
               Verilmezse tum alan kullanilir.

    Dondurur (sozluk):
      iou        = kesisim / birlesim               -> genel ortusme (0-1)
      kesinlik   = kesisim / bizim sel              -> "sel" dedigimiz yerin ne kadari gercekten sel
      duyarlilik = kesisim / referans sel           -> gercek selin ne kadarini bulduk
      f1         = kesinlik ve duyarliligin uyumlu ortalamasi
      ve tum alanlar km2 olarak
    """
    A = sel.to_crs(METRE_CRS).union_all()        # bizim harita (tek parca)
    B = referans.to_crs(METRE_CRS).union_all()   # referans (tek parca)
    if kapsam is not None:
        A = A.intersection(kapsam)
        B = B.intersection(kapsam)

    kesisim = A.intersection(B).area
    birlesim = A.union(B).area
    bizim, ref = A.area, B.area

    kesinlik = kesisim / bizim if bizim else 0.0
    duyarlilik = kesisim / ref if ref else 0.0
    f1 = 2 * kesinlik * duyarlilik / (kesinlik + duyarlilik) if (kesinlik + duyarlilik) else 0.0
    return {
        "iou": round(kesisim / birlesim, 4) if birlesim else 0.0,
        "kesinlik": round(kesinlik, 4),
        "duyarlilik": round(duyarlilik, 4),
        "f1": round(f1, 4),
        "bizim_sel_km2": round(bizim / 1e6, 2),
        "referans_sel_km2": round(ref / 1e6, 2),
        "kesisim_km2": round(kesisim / 1e6, 2),
        "yanlis_alarm_km2": round((bizim - kesisim) / 1e6, 2),   # biz sel dedik, referans demedi
        "kacirilan_km2": round((ref - kesisim) / 1e6, 2),        # referans sel dedi, biz kacirdik
        "kapsam_km2": round(kapsam.area / 1e6, 2) if kapsam is not None else None,
    }


def ems_zipten_oku(zip_yolu):
    """Copernicus EMS zip'inden sel poligonlarini ve incelenen alani okur (zip'i acmadan)."""
    zip_yolu = Path(zip_yolu)
    on_ek = zip_yolu.stem.rsplit("_v", 1)[0]                 # or. EMSR857_AOI01_DEL_PRODUCT
    z = f"zip://{zip_yolu.as_posix()}!{on_ek}_"
    referans = gpd.read_file(z + "observedEventA_v1.shp")
    aoi = gpd.read_file(z + "areaOfInterestA_v1.shp").to_crs(METRE_CRS).union_all()
    iz = gpd.read_file(z + "imageFootprintA_v1.shp").to_crs(METRE_CRS).union_all()
    return referans, aoi.intersection(iz)


def main():
    zipler = [Path(p) for p in sys.argv[1:]] or [p for p in VARSAYILAN_ZIPLER if p.exists()]

    # Zip yoksa: analiz/veri icindeki hazir referans (AOI06 17 Ocak + AOI01 18 Ocak) kullanilir
    referanslar = [(z.stem, *ems_zipten_oku(z)) for z in zipler]
    if not referanslar:
        ref_yol, kap_yol = VERI / "referans_sel.geojson", VERI / "referans_kapsam.geojson"
        if not (ref_yol.exists() and kap_yol.exists()):
            raise SystemExit("Referans bulunamadi: Downloads'ta EMSR857 zip'i ya da analiz/veri/referans_sel.geojson yok.")
        kap = gpd.read_file(kap_yol).to_crs(METRE_CRS).union_all()
        referanslar = [("referans_sel (AOI06 17 Ocak + AOI01 18 Ocak)", gpd.read_file(ref_yol), kap)]

    sel = gpd.read_file(SEL_DOSYASI)
    if sel.crs is None:
        sel = sel.set_crs(4326)
    # Bizim haritanin kapladigi kutunun disinda karsilastirma yapma
    sel_kutusu =gpd.GeoSeries([box(*sel.total_bounds)], crs=sel.crs).to_crs(METRE_CRS).iloc[0]

    print(f"Sel haritasi: {SEL_DOSYASI.relative_to(DEPO)} ({len(sel)} poligon)\n")
    print(f"{'Referans':34s} {'IoU':>5s} {'kesinlik':>9s} {'duyarlilik':>10s} {'F1':>5s}")
    sonuclar = {}
    for ad, referans, kapsam in referanslar:
        s = iou_hesapla(sel, referans, kapsam.intersection(sel_kutusu))
        sonuclar[ad] = s
        print(f"{ad:34s} %{100*s['iou']:4.0f} %{100*s['kesinlik']:8.0f} "
              f"%{100*s['duyarlilik']:9.0f} %{100*s['f1']:4.0f}")

    CIKTI.parent.mkdir(parents=True, exist_ok=True)
    CIKTI.write_text(json.dumps(sonuclar, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nKaydedildi: {CIKTI}")


if __name__ == "__main__":
    main()
