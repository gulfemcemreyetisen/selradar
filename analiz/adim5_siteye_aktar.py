"""ADIM 5: Sonuclari web sitesine aktar.

Adim 2 (yapilar), Adim 3 (nufus) ve Adim 4 (dogruluk) ciktilarini birlestirip
sitenin okudugu dosyayi yazar:
    selradar/data/impact_results.json

Site bu alanlari kullaniyor (js/app.js):
    estimated_affected_population, population_source, closed_roads_count, priority_actions

Once Adim 2, 3 ve 4'u calistirin. Sonra (depo klasorunde):
    python analiz/adim5_siteye_aktar.py
"""
import json
from pathlib import Path

DEPO = Path(__file__).resolve().parent.parent
CIKTI_KLASORU = DEPO / "analiz" / "cikti"
SITE_DOSYASI = DEPO / "selradar" / "data" / "impact_results.json"

# Saha kontrolu listesindeki SIRALAMA KURALI (ekip karari; degistirilebilir):
#   1) once selin ICINDEKILER, sonra 100 m yakinindakiler
#   2) ayni grupta: hastane > kopru > okul > yol
#   3) sonra sele mesafe (yakin olan once)
KATEGORI_SIRASI = {"hastane": 0, "kopru": 1, "okul": 2, "yol": 3}
KATEGORI_ADI = {"hastane": "Hastane", "kopru": "Köprü", "okul": "Okul", "yol": "Yol"}
EN_FAZLA = 15   # listede gosterilecek en fazla kalem


def oku(ad):
    yol = CIKTI_KLASORU / ad
    if not yol.exists():
        raise SystemExit(f"HATA: {yol.name} yok. Once ilgili adimi calistirin.")
    return json.loads(yol.read_text(encoding="utf-8"))


yapilar = oku("etkilenen_yapilar.json")     # Adim 2
nufus = oku("etkilenen_nufus.json")         # Adim 3
dogruluk_yolu = CIKTI_KLASORU / "dogruluk.json"
dogruluk = json.loads(dogruluk_yolu.read_text(encoding="utf-8")) if dogruluk_yolu.exists() else {}

if "yapilar" not in yapilar:
    raise SystemExit("HATA: etkilenen_yapilar.json eski. Adim 2'yi yeniden calistirin.")

# ---------------------------------------------------------------
# Saha kontrolu listesi (sitede "oncelik listesi" olarak gorunur)
# ---------------------------------------------------------------
liste = sorted(
    yapilar["yapilar"],
    key=lambda y: (not y["sel_icinde"], KATEGORI_SIRASI.get(y["kategori"], 9), y["sele_mesafe_m"]),
)
eylemler = []
for i, y in enumerate(liste[:EN_FAZLA], start=1):
    if y["ad"]:
        ad = y["ad"]
    else:   # isimsizse konumuyla yaz (enlem, boylam)
        lon, lat = y.get("konum", [None, None])
        ad = f"isimsiz ({lat:.3f}, {lon:.3f})" if lon is not None else "isimsiz"
    neden = ("Sel alanının içinde; saha kontrolü gerekli." if y["sel_icinde"]
             else f"Sel sınırına {y['sele_mesafe_m']} m; risk altında.")
    eylemler.append({"rank": i, "target": f"{KATEGORI_ADI.get(y['kategori'], '')}: {ad}", "reason": neden})

# Yol: selin icinde kalan yol parcasi sayisi (kesin kapanma bilgisi degil)
sel_icindeki_yol = sum(1 for y in yapilar["yapilar"] if y["kategori"] == "yol" and y["sel_icinde"])

# En yakin tarihli referansla dogruluk (18 Ocak DEL_PRODUCT ya da birlesik referans)
dogruluk_ozet = None
for anahtar in ("EMSR857_AOI01_DEL_PRODUCT_v1", *dogruluk.keys()):
    if anahtar in dogruluk:
        d = dogruluk[anahtar]
        dogruluk_ozet = {"referans": anahtar, "iou": d["iou"], "f1": d["f1"],
                         "kesinlik": d["kesinlik"], "duyarlilik": d["duyarlilik"]}
        break

site = {
    "estimated_affected_population": nufus["etkilenen_tahmini_nufus"],
    "estimated_affected_population_100m": nufus.get("etkilenen_tahmini_nufus_100m_tamponla"),
    "population_source": nufus.get("nufus_kaynagi", "WorldPop 100m"),
    "closed_roads_count": sel_icindeki_yol,
    "affected_road_km": yapilar.get("etkilenen_yol_km"),
    "affected_hospitals": yapilar["etkilenen_hastane_sayisi"],
    "affected_schools": yapilar["etkilenen_okul_sayisi"],
    "affected_bridges": yapilar["etkilenen_kopru_sayisi"],
    "priority_actions": eylemler,
    "priority_rule": "Sıralama: önce sel içindekiler, sonra hastane > köprü > okul > yol, sonra sele mesafe.",
    "validation": dogruluk_ozet,
    "note": "Tahmini değerler; sel haritası gerçek selin bir kısmını kaçırıyor, gerçek sayılar muhtemelen daha yüksek.",
}

SITE_DOSYASI.write_text(json.dumps(site, ensure_ascii=False, indent=2), encoding="utf-8")

print("=== SITEYE AKTARILDI ===")
print(f"Etkilenen nufus     : {site['estimated_affected_population']:,} (100 m tamponla {site['estimated_affected_population_100m']:,})")
print(f"Sel icindeki yol    : {site['closed_roads_count']} parca, {site['affected_road_km']} km")
print(f"Hastane/okul/kopru  : {site['affected_hospitals']} / {site['affected_schools']} / {site['affected_bridges']}")
if dogruluk_ozet:
    print(f"Dogruluk            : IoU %{100*dogruluk_ozet['iou']:.0f}, F1 %{100*dogruluk_ozet['f1']:.0f} ({dogruluk_ozet['referans']})")
print(f"Saha kontrol listesi: {len(eylemler)} kalem (ilk 3: {', '.join(e['target'] for e in eylemler[:3])})")
print(f"\nKaydedildi: {SITE_DOSYASI}")
print("Adim 5 tamam.")
