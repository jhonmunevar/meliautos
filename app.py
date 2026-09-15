"""
MeLi Autos v5 - IA + Fecha + Único Dueño + Negociable + Pantalla de inicio
Ejecutar: python app.py  →  http://localhost:5000
"""

from flask import Flask, render_template, jsonify, request, session, redirect, url_for
from functools import wraps
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import os as _os

# ChromeDriver local (Chrome 148) — copiado manualmente
_LOCAL_CHROMEDRIVER = _os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)),
    "chromedriver.exe"
)

def get_service():
    """Usa ChromeDriver local si existe, sino descarga automáticamente."""
    if _os.path.exists(_LOCAL_CHROMEDRIVER):
        return Service(_LOCAL_CHROMEDRIVER)
    # En Railway usar chromedriver del sistema
    if _os.path.exists("/usr/local/bin/chromedriver"):
        return Service("/usr/local/bin/chromedriver")
    return Service(ChromeDriverManager().install())

from bs4 import BeautifulSoup
import statistics, re, time, threading, json, requests as req, random

# Scrapers adicionales (Carroya, Metrocuadrado, FincaRaíz)
try:
    from scrapers import scrape_carroya, scrape_metrocuadrado, scrape_fincaraiz
    SCRAPERS_OK = True
except ImportError:
    SCRAPERS_OK = False
from datetime import datetime, timezone

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "meliautos-secret-2024")
ACCESS_PASSWORD = os.environ.get("ACCESS_PASSWORD", "meli2024")

# ── Anthropic API (IA) ───────────────────────────────────────────────────────
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY", "")

# ── Auth ─────────────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        pwd = request.form.get("password", "")
        if pwd == ACCESS_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("index"))
        error = "Contraseña incorrecta"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ── Cache ─────────────────────────────────────────────────────────────────────
cache      = {}
cache_lock = threading.Lock()

def get_cached(key, ttl=300):
    with cache_lock:
        if key in cache:
            data, ts = cache[key]
            if time.time() - ts < ttl:
                return data
    return None

def set_cached(key, data):
    with cache_lock:
        cache[key] = (data, time.time())

# ── Proxies Webshare ──────────────────────────────────────────────────────────
PROXY_LIST = [
    ("31.59.20.176",    "6754"),
    ("45.38.107.97",    "6014"),
    ("198.105.121.200", "6462"),
    ("64.137.96.74",    "6641"),
    ("198.23.243.226",  "6361"),
    ("38.154.185.97",   "6370"),
    ("84.247.60.125",   "6095"),
    ("142.111.67.146",  "5611"),
    ("191.96.254.138",  "6185"),
    ("31.58.9.4",       "6077"),
]

def get_proxy_arg():
    """
    Retorna argumento de proxy desde variables de entorno.
    Soporta dos modos:
    - PROXY_HOST + PROXY_PORT: proxy fijo (ej: Rotating Residential p.webshare.io:80)
    - PROXY_USER + PROXY_PASS solos: usa lista fija PROXY_LIST (datacenter)
    """
    proxy_user = os.environ.get("PROXY_USER", "")
    proxy_pass = os.environ.get("PROXY_PASS", "")
    if not proxy_user or not proxy_pass:
        return None
    proxy_host = os.environ.get("PROXY_HOST", "")
    proxy_port = os.environ.get("PROXY_PORT", "")
    if proxy_host and proxy_port:
        # Modo residencial: host fijo desde variables
        print(f"  Usando proxy residencial: {proxy_host}:{proxy_port}")
        return f"--proxy-server=http://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}"
    else:
        # Modo datacenter: rotar entre lista fija
        ph, pp = random.choice(PROXY_LIST)
        print(f"  Usando proxy datacenter: {ph}:{pp}")
        return f"--proxy-server=http://{proxy_user}:{proxy_pass}@{ph}:{pp}"

# ── Selenium driver ──────────────────────────────────────────────────────────
_driver      = None
_driver_lock = threading.Lock()

def get_driver():
    global _driver
    with _driver_lock:
        if _driver is None:
            print("  Iniciando Chrome...")
            opts = Options()
            opts.add_argument("--headless=new")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--disable-gpu")
            opts.add_argument("--disable-blink-features=AutomationControlled")
            opts.add_argument("--window-size=1920,1080")
            opts.add_argument("--lang=es-CO")
            opts.add_argument("--disable-extensions")
            opts.add_argument("--single-process")
            opts.add_experimental_option("excludeSwitches", ["enable-automation"])
            opts.add_experimental_option("useAutomationExtension", False)
            opts.add_argument(
                "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            # Proxy Webshare (solo si las variables están configuradas)
            proxy_arg = get_proxy_arg()
            if proxy_arg:
                opts.add_argument(proxy_arg)

            svc     = get_service()
            _driver = webdriver.Chrome(service=svc, options=opts)
            _driver.execute_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )
            print("  Chrome listo ✓")
    return _driver

# ── Constantes ───────────────────────────────────────────────────────────────
CATEGORIAS = {
    "carros":       ("Carros y Camionetas", "carros-camionetas",         None,                           "carros.mercadolibre.com.co"),
    "motos":        ("Motos",               "motos",                     None,                           "motos.mercadolibre.com.co"),
    "camiones":     ("Camiones y Buses",    "camiones-buses",            None,                           "carros.mercadolibre.com.co"),
    "casas":        ("Casas",               "casas-en-venta",            "casas-en-arriendo",            "inmuebles.mercadolibre.com.co"),
    "apartamentos": ("Apartamentos",        "apartamentos-en-venta",     "apartamentos-en-arriendo",     "inmuebles.mercadolibre.com.co"),
    "fincas":       ("Fincas",              "fincas-en-venta",           "fincas-en-arriendo",           "inmuebles.mercadolibre.com.co"),
    "bodegas":      ("Bodegas",             "bodegas-en-venta",          "bodegas-en-arriendo",          "inmuebles.mercadolibre.com.co"),
    "locales":      ("Locales Comerciales", "locales-comerciales-venta", "locales-comerciales-arriendo", "inmuebles.mercadolibre.com.co"),
}

CATS_VEHICULOS = {"carros", "motos", "camiones"}
CATS_INMUEBLES = {"casas", "apartamentos", "fincas", "bodegas", "locales"}

MARCAS = [
    "", "Chevrolet", "Renault", "Mazda", "Toyota", "Hyundai",
    "Kia", "Ford", "Nissan", "Volkswagen", "Honda",
    "BMW", "Mercedes-Benz", "Audi", "Jeep", "Mitsubishi",
    "Suzuki", "Peugeot", "Fiat", "Dodge", "RAM",
]

FRASES_URGENCIA = [
    "vendo urgente", "necesito vender", "viajo", "viaje", "me voy del país",
    "me voy del pais", "liquidación", "liquidacion", "oferta", "ganga",
    "precio negociable", "negociable", "escucho ofertas", "se escuchan ofertas",
    "oportunidad", "remato", "remate", "urge vender", "urgente",
]

FRASES_UNICO_DUENO = [
    "único dueño", "unico dueño", "único dueno", "unico dueno",
    "1 dueño", "un dueño", "primer dueño", "primera mano",
    "1 solo dueño", "un solo dueño",
]

FRASES_NEGOCIABLE = [
    "negociable", "precio negociable", "escucho ofertas", "se escuchan ofertas",
    "oferta", "trato directo", "recibo vehículo", "recibo vehiculo",
]

# ── Helpers ───────────────────────────────────────────────────────────────────
def dias_desde_publicacion(fecha_str):
    if not fecha_str:
        return None
    try:
        fecha = datetime.fromisoformat(fecha_str.replace("Z", "+00:00"))
        ahora = datetime.now(timezone.utc)
        return max(0, (ahora - fecha).days)
    except Exception:
        pass
    txt = fecha_str.lower()
    try:
        if "hoy" in txt or "hace unos minutos" in txt or "hace 1 hora" in txt:
            return 0
        m = re.search(r"hace (\d+) d[ií]a", txt)
        if m: return int(m.group(1))
        m = re.search(r"hace (\d+) semana", txt)
        if m: return int(m.group(1)) * 7
        m = re.search(r"hace (\d+) mes", txt)
        if m: return int(m.group(1)) * 30
        m = re.search(r"hace (\d+) a[ñn]o", txt)
        if m: return int(m.group(1)) * 365
        m = re.search(r"hace un d[ií]a", txt)
        if m: return 1
        m = re.search(r"hace una semana", txt)
        if m: return 7
        m = re.search(r"hace un mes", txt)
        if m: return 30
    except Exception:
        pass
    return None

def fmt_fecha(dias):
    if dias is None:
        return ""
    if dias == 0: return "Hoy"
    if dias == 1: return "Ayer"
    if dias < 7:  return f"Hace {dias} días"
    if dias < 30: return f"Hace {dias // 7} sem."
    if dias < 365: return f"Hace {dias // 30} meses"
    return f"Hace {dias // 365} años"

def detectar_frases(texto):
    texto_l = texto.lower()
    urgencia   = [f for f in FRASES_URGENCIA    if f in texto_l]
    unico      = [f for f in FRASES_UNICO_DUENO if f in texto_l]
    negociable = [f for f in FRASES_NEGOCIABLE  if f in texto_l]
    return urgencia, unico, negociable

def analizar_con_ia(titulo, descripcion, precio, mediana):
    if not ANTHROPIC_KEY or not descripcion:
        return None
    cached = get_cached(f"ia_{titulo[:30]}")
    if cached:
        return cached
    try:
        prompt = f"""Analiza este anuncio de vehículo en Colombia y responde SOLO con JSON válido.

Título: {titulo}
Precio: ${precio:,} COP
Mediana del mercado: ${mediana:,} COP
Descripción: {descripcion[:800]}

Responde exactamente con este JSON (sin markdown):
{{
  "urgencia_venta": true/false,
  "unico_dueno": true/false,
  "precio_negociable": true/false,
  "señales_positivas": ["lista de señales buenas encontradas"],
  "señales_negativas": ["lista de alertas o riesgos encontrados"],
  "resumen": "una frase corta del análisis",
  "puntaje_ia": número del 0 al 20
}}"""
        r = req.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 400, "messages": [{"role": "user", "content": prompt}]},
            timeout=10,
        )
        text = r.json()["content"][0]["text"]
        result = json.loads(text)
        set_cached(f"ia_{titulo[:30]}", result)
        return result
    except Exception:
        return None

def scrape_descripcion(item_id, url):
    cache_key = f"desc_{item_id}"
    cached = get_cached(cache_key, ttl=3600)
    if cached:
        return cached
    driver = get_driver()
    try:
        driver.get(url)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "h1, .ui-pdp-title")))
        time.sleep(1)
        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")
        desc = ""
        for sel in [".ui-pdp-description__content", ".item-description__text", "[class*='description']"]:
            el = soup.select_one(sel)
            if el:
                desc = el.get_text(" ", strip=True)[:1000]
                break
        fecha_str = ""
        for sel in ["time[datetime]", "[class*='date']", "[class*='fecha']"]:
            el = soup.select_one(sel)
            if el:
                fecha_str = el.get("datetime") or el.get_text(strip=True)
                break
        result = {"descripcion": desc, "fecha_raw": fecha_str}
        set_cached(cache_key, result)
        return result
    except Exception:
        return {"descripcion": "", "fecha_raw": ""}

# ── Scraping ──────────────────────────────────────────────────────────────────
def build_url(cat_slug, query, marca, precio_min, precio_max, offset, dominio="carros.mercadolibre.com.co", orden=""):
    terminos = "-".join(t.replace(" ", "-") for t in filter(None, [marca, query]))
    base = f"https://{dominio}/{cat_slug}"
    url  = f"{base}/{terminos}" if terminos else base
    if precio_min or precio_max:
        pmin = int(precio_min) if precio_min else ""
        pmax = int(precio_max) if precio_max else ""
        if pmin and pmax:
            url += f"_PriceRange_{pmin}COP-{pmax}COP"
        elif pmin:
            url += f"_PriceRange_{pmin}COP-*"
        elif pmax:
            url += f"_PriceRange_*-{pmax}COP"
    if orden == "reciente":
        url += "_OrderId_10"
    if offset > 0:
        url += f"_Desde_{offset + 1}_NoIndex_True"
    return url

_fecha_lock = threading.Lock()

def scrape_fecha_item(item_url):
    cache_key = "fecha_" + item_url
    cached = get_cached(cache_key, ttl=3600)
    if cached is not None:
        return cached
    resultado = ""
    try:
        with _fecha_lock:
            driver = get_driver()
            driver.get(item_url)
            try:
                WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "h1, .ui-pdp-title")))
            except Exception:
                pass
            time.sleep(1)
            html = driver.page_source
        PAT = re.compile(
            u"Publicado hace [0-9]+ (?:d[i\u00ed]as?|semanas?|meses?|a[n\u00f1]os?)"
            u"|Publicado hoy|Publicado ayer",
            re.IGNORECASE
        )
        m = PAT.search(html)
        if m:
            resultado = m.group(0).strip()
        else:
            for p in [u'"start_time":"(20[0-9][0-9]-[^"]+)"', u'"date_created":"(20[0-9][0-9]-[^"]+)"']:
                m2 = re.search(p, html)
                if m2:
                    resultado = m2.group(1)
                    break
    except Exception:
        pass
    set_cached(cache_key, resultado if resultado else "no_fecha")
    return resultado

def extraer_fechas_json(soup):
    fechas = {}
    for script in soup.find_all('script'):
        txt = script.string or ''
        for pat in [
            r'"id"\s*:\s*"(MCO\d+)"[^}]{0,400}"start_time"\s*:\s*"([^"]+)"',
            r'"id"\s*:\s*"(MCO\d+)"[^}]{0,400}"date_created"\s*:\s*"([^"]+)"',
        ]:
            for item_id, fecha in re.findall(pat, txt):
                if item_id not in fechas:
                    fechas[item_id] = fecha
    return fechas

def parse_html_items(soup, fechas_por_id=None):
    items = []
    for card in soup.select("li.ui-search-layout__item"):
        try:
            titulo_el = card.select_one("h2.ui-search-item__title, .poly-component__title, [class*='title']")
            titulo = titulo_el.get_text(strip=True) if titulo_el else ""
            if not titulo:
                continue
            precio = 0
            p_el = card.select_one(".andes-money-amount__fraction, .price-tag-fraction, [class*='price__fraction']")
            if p_el:
                precio = int(re.sub(r"[^\d]", "", p_el.get_text()) or "0")
            link    = card.select_one("a[href]")
            url     = link["href"] if link else "#"
            id_m    = re.search(r"MCO[\d]+", url)
            item_id = id_m.group() if id_m else ""
            img     = card.select_one("img[src]:not([src*='data:']), img[data-src]")
            imagen  = ""
            if img:
                imagen = img.get("src") or img.get("data-src") or ""
                if imagen.startswith("data:"):
                    imagen = img.get("data-src") or ""
            imagen = imagen.replace("http://", "https://")
            anio = km_raw = transmision = metros = habitaciones = banos = garaje = estrato = ""
            for a in card.select(".poly-attributes__item, [class*='attribute'], .ui-search-card-attributes__attribute"):
                txt   = a.get_text(strip=True)
                txt_l = txt.lower()
                if re.match(r"^(19|20)\d{2}$", txt):           anio = txt
                elif "km" in txt_l and re.search(r"\d", txt):  km_raw = txt
                elif txt_l in ["automático", "manual", "automatico"]: transmision = txt
                elif "m²" in txt or "m2" in txt_l:             metros = txt
                elif "hab" in txt_l:                            habitaciones = txt
                elif "baño" in txt_l or "bano" in txt_l:       banos = txt
                elif "garaje" in txt_l or "parquead" in txt_l: garaje = txt
                elif "estrato" in txt_l:                        estrato = txt
            loc    = card.select_one("[class*='location'], .poly-component__location")
            ciudad = loc.get_text(strip=True).lower() if loc else ""
            fecha_raw = ""
            PAT_F = re.compile(
                u"Publicado hace [0-9]+ (?:d[i\u00ed]as?|semanas?|meses?|a[n\u00f1]os?)"
                u"|Publicado hoy|Publicado ayer", re.IGNORECASE
            )
            mf = PAT_F.search(str(card))
            if mf:
                fecha_raw = mf.group(0).strip()
            if not fecha_raw and fechas_por_id and item_id in fechas_por_id:
                fecha_raw = fechas_por_id[item_id]
            if not fecha_raw:
                time_el = card.select_one("time[datetime]")
                if time_el:
                    fecha_raw = time_el.get("datetime", "")
            urgencia_t, unico_t, negociable_t = detectar_frases(titulo)
            items.append({
                "id": item_id, "titulo": titulo, "precio": precio, "url": url,
                "imagen": imagen, "condicion": "used", "marca": extraer_marca(titulo),
                "modelo": "", "anio": anio, "km_raw": km_raw,
                "transmision": transmision or "?", "combustible": "?",
                "ciudad": ciudad, "fotos": 0, "vendedor_nivel": "",
                "fecha_raw": fecha_raw, "urgencia": urgencia_t,
                "unico_dueno": bool(unico_t), "negociable": bool(negociable_t),
                "metros": metros, "habitaciones": habitaciones,
                "banos": banos, "garaje": garaje, "estrato": estrato,
            })
        except Exception:
            continue
    return items

def extraer_marca(titulo):
    for m in MARCAS[1:]:
        if m.upper() in titulo.upper():
            return m
    return "?"

def extraer_km(km_raw):
    if not km_raw:
        return None
    nums = re.sub(r"[^\d]", "", str(km_raw))
    return int(nums) if nums else None

def scrape_listado(cat_slug, query, marca, precio_min, precio_max, pagina, dominio="carros.mercadolibre.com.co", orden=""):
    offset    = pagina * 48
    url       = build_url(cat_slug, query, marca, precio_min, precio_max, offset, dominio, orden)
    cache_key = f"list_{url}"
    cached    = get_cached(cache_key)
    if cached:
        return cached
    driver = get_driver()
    try:
        driver.get(url)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "li.ui-search-layout__item, .andes-card"))
        )
        time.sleep(1.5)
    except Exception:
        time.sleep(2)
    html  = driver.page_source
    soup  = BeautifulSoup(html, "html.parser")
    fechas_por_id = extraer_fechas_json(soup)
    items = parse_html_items(soup, fechas_por_id)
    total = 0
    for sel in [".ui-search-search-result__quantity-results", "h2.ui-search-search-result__title"]:
        el = soup.select_one(sel)
        if el:
            nums = re.findall(r"[\d\.]+", el.get_text())
            if nums:
                total = int(re.sub(r"\.", "", nums[0]))
                break
    if not total:
        total = len(items) + offset
    result = {"items": items, "total": total, "url": url}
    set_cached(cache_key, result)
    return result

# ── Análisis ──────────────────────────────────────────────────────────────────
def analizar(items_raw, enriquecer_descripciones=False):
    items = [{**i, "km": extraer_km(i.get("km_raw", ""))} for i in items_raw]
    grupos = {}
    for it in items:
        if it["precio"] > 0:
            clave = f"{it['marca']} {it['modelo']} {it['anio']}".strip()
            grupos.setdefault(clave, []).append(it["precio"])
    medianas = {k: statistics.median(v) for k, v in grupos.items() if v}
    resultado = []
    for it in items:
        precio = it["precio"]
        if precio == 0:
            continue
        clave   = f"{it['marca']} {it['modelo']} {it['anio']}".strip()
        mediana = medianas.get(clave, precio)
        km      = it["km"]
        anio    = it["anio"]
        puntaje = 50
        razones = []
        alertas = []
        badges  = []
        if mediana > 0:
            ratio = precio / mediana
            if ratio < 0.75:
                puntaje += 35; razones.append(f"Precio {round((1-ratio)*100)}% bajo la mediana")
            elif ratio < 0.88:
                puntaje += 20; razones.append(f"Precio {round((1-ratio)*100)}% bajo la mediana")
            elif ratio < 0.95:
                puntaje += 10; razones.append("Precio por debajo del mercado")
            elif ratio > 1.15:
                puntaje -= 15; alertas.append("Precio sobre el mercado")
        if km and anio and str(anio).isdigit():
            edad = datetime.now().year - int(anio)
            if edad > 0:
                esp = edad * 15000
                if km < esp * 0.5:
                    puntaje += 20; razones.append(f"Bajo km ({km:,} en {edad} años)")
                elif km < esp * 0.75:
                    puntaje += 10; razones.append("Km por debajo del promedio")
                elif km > esp * 1.5:
                    puntaje -= 15; alertas.append(f"Alto km ({km:,})")
        dias = dias_desde_publicacion(it.get("fecha_raw", ""))
        if dias is not None:
            if dias == 0:
                puntaje += 15; razones.append("Publicado hoy 🔥"); badges.append("HOY")
            elif dias <= 2:
                puntaje += 12; razones.append(f"Publicado hace {dias} días"); badges.append("RECIENTE")
            elif dias <= 7:
                puntaje += 7; razones.append(f"Publicado hace {dias} días")
            elif dias > 60:
                puntaje -= 5; alertas.append(f"Publicado hace {dias // 30} meses")
        if it.get("unico_dueno"):
            puntaje += 12; razones.append("Único dueño"); badges.append("1 DUEÑO")
        if it.get("negociable"):
            puntaje += 8; razones.append("Precio negociable"); badges.append("NEGOCIABLE")
        urgencia = it.get("urgencia", [])
        if urgencia:
            puntaje += 10; razones.append(f"Señal de urgencia: \"{urgencia[0].capitalize()}\""); badges.append("URGENTE")
        fotos = it.get("fotos", 0)
        if fotos >= 8:
            puntaje += 5; razones.append(f"{fotos} fotos")
        elif 0 < fotos <= 2:
            puntaje -= 5; alertas.append("Pocas fotos")
        nivel = it.get("vendedor_nivel", "")
        if nivel in ("5_green", "4_light_green"):
            puntaje += 5; razones.append("Vendedor ★ alta reputación")
        elif nivel in ("1_red", "2_orange"):
            puntaje -= 10; alertas.append("Vendedor baja reputación")
        ia_result = None
        if enriquecer_descripciones and ANTHROPIC_KEY and it.get("url"):
            desc_data = scrape_descripcion(it["id"], it["url"])
            desc_txt  = desc_data.get("descripcion", "")
            if not it.get("fecha_raw") and desc_data.get("fecha_raw"):
                it["fecha_raw"] = desc_data["fecha_raw"]
            urg_d, unico_d, neg_d = detectar_frases(desc_txt)
            if unico_d and not it.get("unico_dueno"):
                puntaje += 12; razones.append("Único dueño (en descripción)"); badges.append("1 DUEÑO")
            if neg_d and not it.get("negociable"):
                puntaje += 8; razones.append("Negociable (en descripción)")
            ia_result = analizar_con_ia(it["titulo"], desc_txt, precio, mediana)
            if ia_result:
                bonus = max(-15, min(20, ia_result.get("puntaje_ia", 0)))
                puntaje += bonus
                razones += ia_result.get("señales_positivas", [])[:2]
                alertas += ia_result.get("señales_negativas", [])[:2]
        puntaje = max(0, min(100, puntaje))
        if puntaje >= 85:   cls, color = "EXCELENTE", "#00e676"
        elif puntaje >= 70: cls, color = "MUY BUENA", "#40c4ff"
        elif puntaje >= 55: cls, color = "BUENA",     "#69f0ae"
        elif puntaje >= 40: cls, color = "REGULAR",   "#ffd740"
        else:               cls, color = "BAJA",      "#ff5252"
        diff     = round((1 - precio / mediana) * 100, 1) if mediana > 0 else 0
        dias_pub = dias_desde_publicacion(it.get("fecha_raw", ""))
        resultado.append({
            **it,
            "precio_fmt": f"${precio:,.0f}", "moneda": "COP",
            "condicion":  "Usado" if it.get("condicion") == "used" else "Nuevo",
            "km_fmt":     f"{km:,}" if km else "N/D",
            "anio":       anio or "?",
            "mediana_grupo":  f"${mediana:,.0f}",
            "diferencia_pct": diff,
            "dias_publicado": dias_pub,
            "fecha_fmt":      fmt_fecha(dias_pub),
            "puntaje": puntaje, "clasificacion": cls, "color": color,
            "razones": razones, "alertas": alertas, "badges": badges,
            "ia_resumen": ia_result.get("resumen") if ia_result else "",
        })
    resultado.sort(key=lambda x: (-x["puntaje"], x["dias_publicado"] if x["dias_publicado"] is not None else 9999))
    return resultado

# ── Rutas ─────────────────────────────────────────────────────────────────────
@app.route("/")
@login_required
def index():
    return render_template("index.html", categorias=CATEGORIAS, marcas=MARCAS)

@app.route("/api/inicio")
@login_required
def api_inicio():
    resultados = []
    for cat_key, cat_info in CATEGORIAS.items():
        if cat_key in CATS_INMUEBLES:
            continue
        nombre, slug, _, dominio = cat_info
        try:
            raw   = scrape_listado(slug, "", "", None, None, 0, dominio)
            items = analizar(raw.get("items", []))
            top   = [i for i in items if i["puntaje"] >= 85][:4]
            for i in top:
                i["categoria_nombre"] = nombre
            resultados.extend(top)
        except Exception:
            pass
    resultados.sort(key=lambda x: (-x["puntaje"], x["dias_publicado"] if x["dias_publicado"] is not None else 9999))
    return jsonify({"items": resultados[:12]})

@app.route("/api/buscar")
@login_required
def api_buscar():
    query        = request.args.get("q", "").strip()
    cat_key      = request.args.get("categoria", "carros")
    marca        = request.args.get("marca", "").strip()
    precio_min   = request.args.get("precio_min", type=int)
    precio_max   = request.args.get("precio_max", type=int)
    pagina       = request.args.get("pagina", 0, type=int)
    con_ia       = request.args.get("ia", "0") == "1"
    tipo_negocio = request.args.get("tipo_negocio", "")
    orden        = request.args.get("orden", "")
    anio_min     = request.args.get("anio_min", type=int)
    anio_max     = request.args.get("anio_max", type=int)

    cat_info = CATEGORIAS.get(cat_key, CATEGORIAS["carros"])
    nombre, slug_venta, slug_arriendo, dominio = cat_info
    if tipo_negocio == "arriendo" and slug_arriendo:
        cat_slug = slug_arriendo
    elif tipo_negocio == "venta" and slug_venta:
        cat_slug = slug_venta
    else:
        cat_slug = slug_venta or slug_arriendo

    try:
        raw = scrape_listado(cat_slug, query, marca, precio_min, precio_max, pagina, dominio, orden)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    items_raw  = raw.get("items", [])
    total      = raw.get("total", 0)
    analizados = analizar(items_raw, enriquecer_descripciones=con_ia)

    if anio_min or anio_max:
        def en_rango(item):
            try:
                anio = int(item.get("anio", 0))
                if anio_min and anio < anio_min: return False
                if anio_max and anio > anio_max: return False
                return True
            except Exception:
                return True
        analizados = [i for i in analizados if en_rango(i)]

    precios = [i["precio"] for i in analizados if i["precio"] > 0]
    stats   = {}
    if precios:
        stats = {
            "total_encontrados":        total,
            "en_pagina":                len(analizados),
            "precio_min":               f"${min(precios):,.0f}",
            "precio_max":               f"${max(precios):,.0f}",
            "precio_mediana":           f"${statistics.median(precios):,.0f}",
            "precio_promedio":          f"${statistics.mean(precios):,.0f}",
            "oportunidades_excelentes": sum(1 for i in analizados if i["clasificacion"] == "EXCELENTE"),
            "oportunidades_buenas":     sum(1 for i in analizados if i["clasificacion"] in ("MUY BUENA","BUENA")),
            "con_urgencia":             sum(1 for i in analizados if i.get("urgencia")),
            "unico_dueno":              sum(1 for i in analizados if i.get("unico_dueno")),
            "negociables":              sum(1 for i in analizados if i.get("negociable")),
        }
    return jsonify({"items": analizados, "stats": stats, "pagina": pagina, "total": total})

@app.route("/api/fechas", methods=["POST"])
def api_fechas():
    data  = request.get_json() or {}
    items = data.get("items", [])[:8]
    resultados = {}
    for it in items:
        item_id  = it.get("id", "")
        item_url = it.get("url", "")
        if not item_url or not item_id:
            continue
        fecha = scrape_fecha_item(item_url)
        if fecha and fecha != "no_fecha":
            resultados[item_id] = fecha
    return jsonify(resultados)

@app.route("/api/debug_ml")
def api_debug_ml():
    """Debug: verifica qué devuelve ML."""
    try:
        driver = get_driver()
        driver.get("https://carros.mercadolibre.com.co/carros-camionetas/clio")
        time.sleep(3)
        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")
        items = soup.select("li.ui-search-layout__item")
        links = [a.get("href","")[:80] for a in soup.select("a[href]") if "MCO" in a.get("href","")][:5]
        return jsonify({
            "url_actual": driver.current_url,
            "html_length": len(html),
            "items_encontrados": len(items),
            "links_mco": links,
            "primeros_500": html[:500],
            "proxy_activo": bool(os.environ.get("PROXY_USER")),
        })
    except Exception as e:
        return jsonify({"error": str(e)})

# ── Driver 3 — Carroya, Metrocuadrado, FincaRaíz ─────────────────────────────
_driver3      = None
_driver3_lock = threading.Lock()

def get_driver3():
    global _driver3
    with _driver3_lock:
        if _driver3 is not None:
            try:
                _ = _driver3.current_url
            except Exception:
                try: _driver3.quit()
                except Exception: pass
                _driver3 = None
        if _driver3 is None:
            print("  Iniciando Chrome 3 (fuentes extra)...")
            opts = Options()
            opts.add_argument("--headless=new")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--disable-gpu")
            opts.add_argument("--disable-blink-features=AutomationControlled")
            opts.add_argument("--window-size=1920,1080")
            opts.add_argument("--lang=es-CO")
            opts.add_argument("--disable-extensions")
            opts.add_argument("--single-process")
            opts.add_experimental_option("excludeSwitches", ["enable-automation"])
            opts.add_experimental_option("useAutomationExtension", False)
            opts.add_argument(
                "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            proxy_arg = get_proxy_arg()
            if proxy_arg:
                opts.add_argument(proxy_arg)
            svc      = get_service()
            _driver3 = webdriver.Chrome(service=svc, options=opts)
            _driver3.execute_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )
            print("  Chrome 3 listo ✓")
    return _driver3


@app.route("/api/buscar_carroya")
@login_required
def api_buscar_carroya():
    if not SCRAPERS_OK:
        return jsonify({"error": "scrapers.py no encontrado", "items": []}), 500
    query      = request.args.get("q", "").strip()
    marca      = request.args.get("marca", "").strip()
    precio_min = request.args.get("precio_min", type=int)
    precio_max = request.args.get("precio_max", type=int)
    anio_min   = request.args.get("anio_min", type=int)
    anio_max   = request.args.get("anio_max", type=int)

    driver = get_driver3()
    raw    = scrape_carroya(driver, get_cached, set_cached, query, marca,
                            precio_min, precio_max, anio_min, anio_max)
    items  = analizar(raw.get("items", []))
    precios = [i["precio"] for i in items if i["precio"] > 0]
    stats = {}
    if precios:
        stats = {
            "total_encontrados":        len(items),
            "precio_min":               f"${min(precios):,.0f}",
            "precio_max":               f"${max(precios):,.0f}",
            "precio_mediana":           f"${statistics.median(precios):,.0f}",
            "oportunidades_excelentes": sum(1 for i in items if i["clasificacion"] == "EXCELENTE"),
            "oportunidades_buenas":     sum(1 for i in items if i["clasificacion"] in ("MUY BUENA","BUENA")),
        }
    return jsonify({"items": items, "stats": stats, "total": len(items), "fuente": "carroya"})


@app.route("/api/buscar_inmuebles")
@login_required
def api_buscar_inmuebles():
    if not SCRAPERS_OK:
        return jsonify({"error": "scrapers.py no encontrado", "items": []}), 500
    tipo       = request.args.get("tipo", "apartamentos")
    operacion  = request.args.get("operacion", "arriendo")
    ciudad     = request.args.get("ciudad", "bogota")
    query      = request.args.get("q", "").strip()
    fuente     = request.args.get("fuente", "metrocuadrado")
    precio_min = request.args.get("precio_min", type=int)
    precio_max = request.args.get("precio_max", type=int)

    driver = get_driver3()
    if fuente == "fincaraiz":
        raw = scrape_fincaraiz(driver, get_cached, set_cached,
                               tipo, operacion, ciudad, query, precio_min, precio_max)
    else:
        raw = scrape_metrocuadrado(driver, get_cached, set_cached,
                                   tipo, operacion, ciudad, query, precio_min, precio_max)

    items   = analizar(raw.get("items", []))
    precios = [i["precio"] for i in items if i["precio"] > 0]
    stats   = {}
    if precios:
        stats = {
            "total_encontrados":        len(items),
            "precio_min":               f"${min(precios):,.0f}",
            "precio_max":               f"${max(precios):,.0f}",
            "precio_mediana":           f"${statistics.median(precios):,.0f}",
            "oportunidades_excelentes": sum(1 for i in items if i["clasificacion"] == "EXCELENTE"),
            "oportunidades_buenas":     sum(1 for i in items if i["clasificacion"] in ("MUY BUENA","BUENA")),
        }
    return jsonify({"items": items, "stats": stats, "total": len(items), "fuente": fuente})


if __name__ == "__main__":
    print("\n" + "="*55)
    print("  🚗  MeLi Autos v5 - IA + Señales + Fecha")
    print("="*55)
    print("  Servidor en: http://localhost:5000")
    print("  Chrome se iniciará en la primera búsqueda")
    print("="*55 + "\n")
    import os as _os2
    port = int(_os2.environ.get("PORT", 5000))
    app.run(debug=False, port=port, host="0.0.0.0")