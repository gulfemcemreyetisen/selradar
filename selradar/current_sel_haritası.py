import argparse
import json
import math
import tempfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import shapes
from rasterio.transform import from_origin
from rasterio.warp import reproject
from scipy.ndimage import label, median_filter
from shapely.geometry import shape

# --------------------------------------------------------------------------
# Ayarlar (komut satirindan da degistirilebilir)
BOLGE = (32.5, -25.0, 33.5, -24.0)  # bati, guney, dogu, kuzey  (event.json ile ayni)
COZUNURLUK_M = 30                   # cikis piksel boyutu (metre)
FARK_ESIGI_DB = -3.0                # sonra - once en az bu kadar dusmeli
MAKS_EGIM = 5.0                     # derece; daha dik yerlerde sel aranmaz
MIN_ALAN_KM2 = 0.05                 # bundan kucuk lekeler gurultu sayilir
FILTRE_BOYUTU = 5                   # medyan (speckle) filtresi penceresi


def izgara_kur(bolge, cozunurluk_m):
    """Bolgeyi kaplayan EPSG:4326 izgarasi (transform, genislik, yukseklik, piksel derecesi)."""
    bati, guney, dogu, kuzey = bolge
    derece = cozunurluk_m / 111_320.0
    genislik = int(math.ceil((dogu - bati) / derece))
    yukseklik = int(math.ceil((kuzey - guney) / derece))
    return from_origin(bati, kuzey, derece, derece), genislik, yukseklik, derece


def izgaraya_oku(yol, transform, genislik, yukseklik, resampling):
    """Bir raster dosyasini proje izgarasina yeniden orneklendirerek okur."""
    with rasterio.open(yol) as src:
        kw = {}
        if src.crs is not None and not src.transform.is_identity:
            kw.update(src_transform=src.transform, src_crs=src.crs)
            konum = f"koordinatli ({src.crs.to_string()})"
        elif src.gcps[0]:
            gcps, gcp_crs = src.gcps
            kw.update(gcps=gcps, src_crs=gcp_crs)
            konum = f"GCP noktalariyla ({len(gcps)} nokta)"
        else:
            raise SystemExit(
                f"HATA: {yol} dosyasinda koordinat bilgisi yok (CRS veya GCP).\n"
                "Haritadaki yerini bilmeden sel poligonu cikarilamaz. Koordinatli bir GeoTIFF "
                "(or. ASF RTC urunu) kullanin."
            )
        src_nodata = src.nodata if src.nodata is not None else 0
        hedef = np.full((yukseklik, genislik), np.nan, dtype="float32")
        reproject(
            source=rasterio.band(src, 1),
            destination=hedef,
            src_nodata=src_nodata,
            dst_transform=transform,
            dst_crs="EPSG:4326",
            dst_nodata=np.nan,
            resampling=resampling,
            **kw,
        )
        return hedef, src.dtypes[0], konum


def db_yap(dizi, tip, dtype):
    """Goruntuyu desibele cevirir. tip: otomatik | db | guc | genlik"""
    if tip == "otomatik":
        gecerli = dizi[np.isfinite(dizi)]
        if np.issubdtype(np.dtype(dtype), np.integer):
            tip = "genlik"          # ham GRD: tamsayi genlik (DN)
        elif gecerli.size and (gecerli < 0).mean() > 0.5:
            tip = "db"              # zaten desibel
        else:
            tip = "guc"             # dogrusal guc (gamma0 / sigma0)
    if tip == "db":
        return dizi, tip
    pozitif = np.where(dizi > 0, dizi, np.nan)
    if tip == "genlik":
        return 20.0 * np.log10(pozitif), tip   # genlik -> guc icin karesi alinir
    return 10.0 * np.log10(pozitif), tip


def medyan_filtre(dizi, boyut):
    """NaN'lara dayanikli medyan filtre (bos pikseller sonra tekrar bos birakilir)."""
    bos = ~np.isfinite(dizi)
    doldurulmus = np.where(bos, np.nanmedian(dizi), dizi)
    sonuc = median_filter(doldurulmus, size=boyut)
    sonuc[bos] = np.nan
    return sonuc


def otsu_esigi(degerler, kutu=256):
    """Klasik Otsu esigi (asiri uclar %1-%99 araligina kirpilir)."""
    v = degerler[np.isfinite(degerler)]
    alt, ust = np.percentile(v, [1, 99])
    v = v[(v >= alt) & (v <= ust)]
    hist, kenarlar = np.histogram(v, bins=kutu)
    merkez = (kenarlar[:-1] + kenarlar[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * merkez)
    with np.errstate(divide="ignore", invalid="ignore"):
        mu0 = m0 / w0
        mu1 = (m0[-1] - m0) / w1
        varyans = w0 * w1 * (mu0 - mu1) ** 2
    return float(merkez[np.nanargmax(varyans)])


def egim_hesapla(dem, derece, enlem_orta):
    """DEM'den egim (derece). Piksel boyutu metreye cevrilerek hesaplanir."""
    dx_m = derece * 111_320.0 * math.cos(math.radians(enlem_orta))
    dy_m = derece * 110_574.0
    gy, gx = np.gradient(dem, dy_m, dx_m)
    return np.degrees(np.arctan(np.hypot(gx, gy)))


BURASI = Path(__file__).resolve().parent
DEM_ADAYLARI = [Path("elevation.tif"), BURASI / "elevation.tif", BURASI.parent / "elevation.tif",
                BURASI.parent.parent / "data" / "raw" / "elevation.tif"]


def nisar_pngden_hazirla(a, klasor):
    """Sitedeki NISAR PNG'lerini (data/observations.json) koordinatli GeoTIFF'e cevirir.

    PNG'ler gosterim icin uretilmis gri tonlu goruntuler; gri ton -> dB olcegi
    bilinmiyor, -30..0 dB varsayiliyor. Sonuc YAKLASIKTIR, gercek GCOV/RTC GeoTIFF tercih edilmeli.
    """
    from PIL import Image
    from rasterio.transform import from_bounds

    veri = BURASI / "data"
    gozlemler = json.loads((veri / "observations.json").read_text(encoding="utf-8"))
    ilk, son = gozlemler[0], gozlemler[-1]
    (guney, bati), (kuzey, dogu) = ilk["bounds"]
    yollar = []
    for gz, ad in [(ilk, "once.tif"), (son, "sonra.tif")]:
        dizi = np.array(Image.open(veri / Path(gz["image_url"]).name).convert("LA"))
        gri, alfa = dizi[..., 0].astype("float32"), dizi[..., 1]
        db = -30.0 + 30.0 * gri / 255.0
        db[alfa == 0] = np.nan
        h, w = db.shape
        yol = klasor / ad
        with rasterio.open(yol, "w", driver="GTiff", width=w, height=h, count=1, dtype="float32",
                           crs="EPSG:4326", transform=from_bounds(bati, guney, dogu, kuzey, w, h),
                           nodata=np.nan) as d:
            d.write(db, 1)
        yollar.append(str(yol))
    a.once, a.sonra = yollar
    a.tip = "db"
    a.bolge = (bati, guney, dogu, kuzey)
    a.once_tarih, a.sonra_tarih = ilk["date"], son["date"]
    a.kaynak = f"{ilk.get('sensor', 'NISAR')} (sitedeki PNG goruntulerden, yaklasik)"
    print("BILGI: once.tif/sonra.tif yok; sitedeki NISAR PNG goruntuleri kullaniliyor "
          f"({ilk['date']} -> {son['date']}). Sonuc YAKLASIKTIR.")


def koordinat_yuvarla(obj, basamak=5):
    if isinstance(obj, (list, tuple)):
        return [koordinat_yuvarla(o, basamak) for o in obj]
    return round(obj, basamak)


def main():
    ap = argparse.ArgumentParser(description="Radar once-sonra goruntulerinden sel haritasi")
    ap.add_argument("--once", default=None,
                    help="sel oncesi goruntu (GeoTIFF). Verilmezse once.tif, o da yoksa sitedeki NISAR PNG'leri")
    ap.add_argument("--sonra", default=None, help="sel sonrasi goruntu (GeoTIFF)")
    ap.add_argument("--dem", default=None, help="NASADEM yukseklik (GeoTIFF); verilmezse otomatik aranir")
    ap.add_argument("--cikti", default="flood_extent.geojson")
    ap.add_argument("--tip", default="otomatik", choices=["otomatik", "db", "guc", "genlik"],
                    help="goruntu degerlerinin turu")
    ap.add_argument("--bolge", type=float, nargs=4, default=BOLGE,
                    metavar=("BATI", "GUNEY", "DOGU", "KUZEY"))
    ap.add_argument("--cozunurluk", type=float, default=COZUNURLUK_M, help="metre")
    ap.add_argument("--once-tarih", default="2025-12-18")
    ap.add_argument("--sonra-tarih", default="2026-01-17")
    ap.add_argument("--kaynak", default="Sentinel-1 + NASADEM")
    a = ap.parse_args()

    # Goruntu verilmediyse: once.tif/sonra.tif, o da yoksa sitedeki NISAR PNG'leri
    gecici = None
    if a.once is None and a.sonra is None:
        if Path("once.tif").exists() and Path("sonra.tif").exists():
            a.once, a.sonra = "once.tif", "sonra.tif"
        else:
            gecici = tempfile.TemporaryDirectory()
            nisar_pngden_hazirla(a, Path(gecici.name))
    elif a.once is None or a.sonra is None:
        raise SystemExit("HATA: --once ve --sonra birlikte verilmeli.")

    if a.dem is None:
        a.dem = next((str(p) for p in DEM_ADAYLARI if p.exists()), "elevation.tif")

    eksik = [p for p in (a.once, a.sonra) if not Path(p).exists()]
    if eksik:
        raise SystemExit(
            "HATA: Radar goruntusu bulunamadi: " + ", ".join(eksik) + "\n"
            f"Bu klasorde araniyor: {Path.cwd()}\n"
            "Sel oncesi ve sonrasi GeoTIFF dosyalarini buraya koyun ya da --once / --sonra ile yolunu verin."
        )

    transform, W, H, derece = izgara_kur(a.bolge, a.cozunurluk)
    print(f"Izgara: {W} x {H} piksel, {a.cozunurluk:.0f} m, bolge {list(a.bolge)}")

    # 1) Iki goruntuyu da ayni izgaraya oturt (lineer degerlerde ortalama alarak kucult)
    once_ham, once_dtype, k1 = izgaraya_oku(a.once, transform, W, H, Resampling.average)
    sonra_ham, sonra_dtype, k2 = izgaraya_oku(a.sonra, transform, W, H, Resampling.average)
    print(f"Once : {a.once}  -> {k1}")
    print(f"Sonra: {a.sonra} -> {k2}")

    once_db, tip1 = db_yap(once_ham, a.tip, once_dtype)
    sonra_db, tip2 = db_yap(sonra_ham, a.tip, sonra_dtype)
    if tip1 != tip2:
        print(f"UYARI: iki goruntunun turu farkli gorunuyor ({tip1} / {tip2}).")
    if tip1 == "genlik":
        print("UYARI: Ham genlik (kalibre degil). -3 dB esigi yaklasik; mumkunse RTC urunu kullanin.")

    gecerli = np.isfinite(once_db) & np.isfinite(sonra_db)
    oran = gecerli.mean() * 100
    print(f"Iki goruntunun ortak kapladigi alan: bolgenin %{oran:.0f}'i")
    if oran < 1:
        raise SystemExit("HATA: Goruntuler bu bolgeyle (veya birbiriyle) ortusmuyor.")

    # 2) Speckle icin medyan filtre, sonra degisim
    once_f = medyan_filtre(once_db, FILTRE_BOYUTU)
    sonra_f = medyan_filtre(sonra_db, FILTRE_BOYUTU)
    fark = sonra_f - once_f

    # 3) Su esigi (Otsu) sel sonrasi goruntuden
    esik = otsu_esigi(sonra_f[gecerli])
    print(f"Otsu su esigi: {esik:.2f} dB  (tur: {tip1})")

    sel = gecerli & (fark <= FARK_ESIGI_DB) & (sonra_f < esik)
    kalici_su = gecerli & (once_f < esik)          # selden once de su olan yerler
    sel &= ~kalici_su

    # 4) Egim filtresi (gercek DEM)
    if Path(a.dem).exists():
        dem, _, _ = izgaraya_oku(a.dem, transform, W, H, Resampling.bilinear)
        egim = egim_hesapla(dem, derece, (a.bolge[1] + a.bolge[3]) / 2)
        dik = np.isfinite(egim) & (egim > MAKS_EGIM)
        dem_yok = (~np.isfinite(dem)).mean() * 100
        sel &= ~dik
        dem_bilgi = f"NASADEM egim<={MAKS_EGIM:g} derece"
        print(f"Egim filtresi ({a.dem}): {int(dik.sum())} dik piksel cikarildi"
              + (f" (bolgenin %{dem_yok:.0f}'inde DEM yok, oralarda filtre uygulanmadi)" if dem_yok >= 1 else ""))
    else:
        dem_bilgi = "egim filtresi YOK"
        print(f"UYARI: {a.dem} bulunamadi, egim filtresi UYGULANMADI.")

    # 5) Kucuk lekeleri temizle
    piksel_m2 = (derece * 111_320.0 * math.cos(math.radians((a.bolge[1] + a.bolge[3]) / 2))) * (derece * 110_574.0)
    min_piksel = max(1, int(MIN_ALAN_KM2 * 1e6 / piksel_m2))
    etiket, _ = label(sel, structure=np.ones((3, 3)))
    boyutlar = np.bincount(etiket.ravel())
    kucuk = boyutlar < min_piksel
    kucuk[0] = False
    sel[kucuk[etiket]] = False
    print(f"Sel pikseli: {int(sel.sum())} (~{sel.sum() * piksel_m2 / 1e6:.1f} km2)")

    # 6) Gercek sekilli poligonlar
    geoms = [shape(g) for g, d in shapes(sel.astype("uint8"), mask=sel, transform=transform, connectivity=8) if d == 1]
    if not geoms:
        raise SystemExit("Sel alani bulunamadi.")
    gdf = gpd.GeoDataFrame(geometry=geoms, crs="EPSG:4326")
    gdf["area_km2"] = gdf.to_crs(gdf.estimate_utm_crs()).area / 1e6
    gdf = gdf.sort_values("area_km2", ascending=False).reset_index(drop=True)
    gdf["geometry"] = gdf.geometry.simplify(derece / 2, preserve_topology=True)

    yontem = (f"Esik {esik:.1f} dB (Otsu), {a.once_tarih} -> {a.sonra_tarih}, "
              f">={abs(FARK_ESIGI_DB):g} dB dusus, {dem_bilgi}, {a.cozunurluk:.0f} m")
    features = []
    for i, row in gdf.iterrows():
        g = row.geometry.__geo_interface__
        features.append({
            "type": "Feature",
            "properties": {
                "zone_id": f"FZ-{i + 1:03d}",
                "area_km2": round(float(row.area_km2), 3),
                "confidence": "Orta (esik + degisim, temel yontem)",
                "land_cover": "belirlenmedi",
                "method": yontem,
                "kaynak": a.kaynak,
            },
            "geometry": {"type": g["type"], "coordinates": koordinat_yuvarla(g["coordinates"])},
        })

    with open(a.cikti, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, ensure_ascii=False)

    print(f"\nKaydedildi: {a.cikti}")
    print(f"{len(features)} poligon, toplam {gdf.area_km2.sum():.1f} km2, en buyugu {gdf.area_km2.iloc[0]:.1f} km2")


if __name__ == "__main__":
    main()
