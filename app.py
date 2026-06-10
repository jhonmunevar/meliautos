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
    return Service(ChromeDriverManager().install())
from bs4 import BeautifulSoup
import statistics, re, time, threading, json, requests as req
from datetime import datetime, timezone

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "meliautos-secret-2024")
ACCESS_PASSWORD = os.environ.get("ACCESS_PASSWORD", "meli2024")

# ── Anthropic API (IA) ───────────────────────────────────────────────────────
ANTHROPIC_KEY = ""   # opcional: pega tu API key para análisis IA de descripciones

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
            opts.add_argument("--disable-blink-features=AutomationControlled")
            opts.add_argument("--window-size=1920,1080")
            opts.add_argument("--lang=es-CO")
            opts.add_experimental_option("excludeSwitches", ["enable-automation"])
            opts.add_experimental_option("useAutomationExtension", False)
            opts.add_argument(
                "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            svc     = Service(ChromeDriverManager().install())
            _driver = webdriver.Chrome(service=svc, options=opts)
            _driver.execute_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )
            print("  Chrome listo ✓")
    return _driver

# ── Constantes ───────────────────────────────────────────────────────────────
# cat_key: (nombre, slug_venta, slug_arriendo, dominio_base)
CATEGORIAS = {
    "carros":       ("Carros y Camionetas", "carros-camionetas",         None,                          "carros.mercadolibre.com.co"),
    "motos":        ("Motos",               "motos",                     None,                          "motos.mercadolibre.com.co"),
    "camiones":     ("Camiones y Buses",    "camiones-buses",            None,                          "carros.mercadolibre.com.co"),
    "casas":        ("Casas",               "casas-en-venta",            "casas-en-arriendo",           "inmuebles.mercadolibre.com.co"),
    "apartamentos": ("Apartamentos",        "apartamentos-en-venta",     "apartamentos-en-arriendo",    "inmuebles.mercadolibre.com.co"),
    "fincas":       ("Fincas",              "fincas-en-venta",           "fincas-en-arriendo",          "inmuebles.mercadolibre.com.co"),
    "bodegas":      ("Bodegas",             "bodegas-en-venta",          "bodegas-en-arriendo",         "inmuebles.mercadolibre.com.co"),
    "locales":      ("Locales Comerciales", "locales-comerciales-venta", "locales-comerciales-arriendo","inmuebles.mercadolibre.com.co"),
}

# Categorías de vehículos (para mostrar marcas solo en estas)
CATS_VEHICULOS = {"carros", "motos", "camiones"}
# Categorías de inmuebles
CATS_INMUEBLES = {"casas", "apartamentos", "fincas", "bodegas", "locales"}

MARCAS = [
    "", "Chevrolet", "Renault", "Mazda", "Toyota", "Hyundai",
    "Kia", "Ford", "Nissan", "Volkswagen", "Honda",
    "BMW", "Mercedes-Benz", "Audi", "Jeep", "Mitsubishi",
    "Suzuki", "Peugeot", "Fiat", "Dodge", "RAM",
]

# Frases de urgencia/negociación en título o descripción
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

# ── Helpers de fecha ─────────────────────────────────────────────────────────
def dias_desde_publicacion(fecha_str):
    """Convierte fecha ISO o texto ML a días transcurridos."""
    if not fecha_str:
        return None
    # Intentar parsear ISO
    try:
        fecha = datetime.fromisoformat(fecha_str.replace("Z", "+00:00"))
        ahora = datetime.now(timezone.utc)
        return max(0, (ahora - fecha).days)
    except Exception:
        pass
    # Parsear texto de ML: "Publicado hace 3 meses", "hace 1 día", etc.
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
    if dias == 0:
        return "Hoy"
    if dias == 1:
        return "Ayer"
    if dias < 7:
        return f"Hace {dias} días"
    if dias < 30:
        return f"Hace {dias // 7} sem."
    if dias < 365:
        return f"Hace {dias // 30} meses"
    return f"Hace {dias // 365} años"

# ── Detección de frases (sin IA) ─────────────────────────────────────────────
def detectar_frases(texto):
    texto_l = texto.lower()
    urgencia   = [f for f in FRASES_URGENCIA   if f in texto_l]
    unico      = [f for f in FRASES_UNICO_DUENO if f in texto_l]
    negociable = [f for f in FRASES_NEGOCIABLE  if f in texto_l]
    return urgencia, unico, negociable

# ── Análisis IA de descripción (opcional) ────────────────────────────────────
def analizar_con_ia(titulo, descripcion, precio, mediana):
    """Usa Claude para analizar la descripción y detectar señales adicionales."""
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
  "puntaje_ia": número del 0 al 20 (bonus/malus sobre el puntaje base)
}}"""

        r = req.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 400,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=10,
        )
        text = r.json()["content"][0]["text"]
        result = json.loads(text)
        set_cached(f"ia_{titulo[:30]}", result)
        return result
    except Exception:
        return None

# ── Scraping de descripción de un item ───────────────────────────────────────
def scrape_descripcion(item_id, url):
    """Obtiene descripción y fecha de publicación de la página del item."""
    cache_key = f"desc_{item_id}"
    cached = get_cached(cache_key, ttl=3600)
    if cached:
        return cached

    driver = get_driver()
    try:
        driver.get(url)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "h1, .ui-pdp-title"))
        )
        time.sleep(1)
        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")

        # Descripción
        desc = ""
        for sel in [".ui-pdp-description__content", ".item-description__text",
                    "[class*='description']"]:
            el = soup.select_one(sel)
            if el:
                desc = el.get_text(" ", strip=True)[:1000]
                break

        # Fecha publicación
        fecha_str = ""
        for sel in ["time[datetime]", "[class*='date']", "[class*='fecha']"]:
            el = soup.select_one(sel)
            if el:
                fecha_str = el.get("datetime") or el.get_text(strip=True)
                break

        # Buscar en JSON embebido
        for script in soup.find_all("script", type="application/json"):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, dict):
                    fecha_str = (
                        data.get("date_created") or
                        data.get("start_time") or
                        fecha_str
                    )
                    if not desc:
                        desc = str(data.get("plain_text", ""))[:1000]
            except Exception:
                pass

        result = {"descripcion": desc, "fecha_raw": fecha_str}
        set_cached(cache_key, result)
        return result
    except Exception:
        return {"descripcion": "", "fecha_raw": ""}

# ── Scraping del listado ──────────────────────────────────────────────────────
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
    # Orden por fecha: ML usa _OrderId_TPRICE o parámetro
    if orden == "reciente":
        url += "_OrderId_10"  # más recientes primero en ML
    if offset > 0:
        url += f"_Desde_{offset + 1}_NoIndex_True"
    return url


# ── Driver secundario para fechas ────────────────────────────────────────────
_driver2      = None
_driver2_lock = threading.Lock()

def get_driver2():
    """Driver de Chrome separado, dedicado a scraping de fechas."""
    global _driver2
    with _driver2_lock:
        if _driver2 is None:
            opts = Options()
            opts.add_argument("--headless=new")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--disable-blink-features=AutomationControlled")
            opts.add_argument("--window-size=1280,720")
            opts.add_argument("--lang=es-CO")
            opts.add_experimental_option("excludeSwitches", ["enable-automation"])
            opts.add_experimental_option("useAutomationExtension", False)
            opts.add_argument(
                "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            svc = Service(ChromeDriverManager().install())
            _driver2 = webdriver.Chrome(service=svc, options=opts)
            _driver2.execute_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )
    return _driver2

# Lock para que el driver2 solo procese un ítem a la vez
_fecha_lock = threading.Lock()

def scrape_fecha_item(item_url):
    """Extrae fecha de publicación usando el driver principal (cookies de ML activas)."""
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
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "h1, .ui-pdp-title")
                    )
                )
            except Exception:
                pass
            time.sleep(1)
            html = driver.page_source

        # Patrón probado contra HTML real de ML
        PAT = re.compile(
            u"Publicado hace [0-9]+ (?:d[ií]as?|semanas?|meses?|a[nñ]os?)"
            u"|Publicado hoy|Publicado ayer",
            re.IGNORECASE
        )
        m = PAT.search(html)
        if m:
            resultado = m.group(0).strip()
        else:
            # Fallback ISO
            pat_iso = u'"start_time":"(20[0-9][0-9]-[^"]+)"'
            pat_iso2 = u'"date_created":"(20[0-9][0-9]-[^"]+)"'
            for p in [pat_iso, pat_iso2]:
                m2 = re.search(p, html)
                if m2:
                    resultado = m2.group(1)
                    break
    except Exception:
        pass
    set_cached(cache_key, resultado if resultado else "no_fecha")
    return resultado


def enriquecer_fechas(items, max_items=8):
    """Visita páginas individuales secuencialmente con driver2 para obtener fechas."""
    sin_fecha = [i for i in items if not i.get("fecha_raw")][:max_items]
    for item in sin_fecha:
        try:
            fecha = scrape_fecha_item(item["url"])
            if fecha and fecha != "no_fecha":
                item["fecha_raw"] = fecha
        except Exception:
            pass


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
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "li.ui-search-layout__item, .andes-card")
            )
        )
        time.sleep(1.5)
    except Exception:
        time.sleep(2)

    html  = driver.page_source
    soup  = BeautifulSoup(html, "html.parser")

    fechas_por_id = extraer_fechas_json(soup)
    items = parse_html_items(soup, fechas_por_id)

    # Total
    total = 0
    for sel in [".ui-search-search-result__quantity-results",
                "h2.ui-search-search-result__title"]:
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



def extraer_fechas_dom(driver):
    """Extrae fechas directamente del DOM renderizado usando JavaScript."""
    fechas = {}
    try:
        js = """
        const fechas = {};
        // Buscar en todos los elementos con aria-label que contengan "Publicado"
        document.querySelectorAll('[aria-label*="Publicado"]').forEach(el => {
            const label = el.getAttribute('aria-label') || '';
            const match = label.match(/Publicado (hoy|ayer|hace \d+ \w+)/i);
            if (match) {
                // Subir al li padre para obtener el ID del item
                let parent = el.closest('li[class*="ui-search"]');
                if (parent) {
                    const link = parent.querySelector('a[href*="MCO"]');
                    if (link) {
                        const idMatch = link.href.match(/MCO[\d]+/);
                        if (idMatch) fechas[idMatch[0]] = 'Publicado ' + match[1];
                    }
                }
            }
        });
        // También buscar en spans con texto de fecha
        document.querySelectorAll('span, p, div').forEach(el => {
            const txt = el.textContent || '';
            const match = txt.match(/^Publicado (hoy|ayer|hace \d+ \w+)$/i);
            if (match) {
                let parent = el.closest('li[class*="ui-search"]');
                if (parent) {
                    const link = parent.querySelector('a[href*="MCO"]');
                    if (link) {
                        const idMatch = link.href.match(/MCO[\d]+/);
                        if (idMatch) fechas[idMatch[0]] = 'Publicado ' + match[1];
                    }
                }
            }
        });
        return JSON.stringify(fechas);
        """
        result = driver.execute_script(js)
        if result:
            fechas = json.loads(result)
    except Exception as e:
        pass
    return fechas


def extraer_fechas_json(soup):
    """Extrae mapa item_id->fecha desde JSON embebido en el listado."""
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
            titulo_el = card.select_one(
                "h2.ui-search-item__title, .poly-component__title, "
                "[class*='title']"
            )
            titulo = titulo_el.get_text(strip=True) if titulo_el else ""
            if not titulo:
                continue

            # Precio
            precio = 0
            p_el = card.select_one(
                ".andes-money-amount__fraction, .price-tag-fraction, "
                "[class*='price__fraction']"
            )
            if p_el:
                precio = int(re.sub(r"[^\d]", "", p_el.get_text()) or "0")

            # URL e ID
            link  = card.select_one("a[href]")
            url   = link["href"] if link else "#"
            id_m  = re.search(r"MCO[\d]+", url)
            item_id = id_m.group() if id_m else ""

            # Imagen
            img   = card.select_one("img[src]:not([src*='data:']), img[data-src]")
            imagen = ""
            if img:
                imagen = img.get("src") or img.get("data-src") or ""
                if imagen.startswith("data:"):
                    imagen = img.get("data-src") or ""
            imagen = imagen.replace("http://", "https://")

            # Atributos vehículos e inmuebles
            anio = km_raw = transmision = ""
            metros = habitaciones = banos = garaje = estrato = ""
            for a in card.select(".poly-attributes__item, [class*='attribute'], .ui-search-card-attributes__attribute"):
                txt = a.get_text(strip=True)
                txt_l = txt.lower()
                if re.match(r"^(19|20)\d{2}$", txt):
                    anio = txt
                elif "km" in txt_l and re.search(r"\d", txt):
                    km_raw = txt
                elif txt_l in ["automático", "manual", "automatico"]:
                    transmision = txt
                elif "m²" in txt or "m2" in txt_l or "mt" in txt_l:
                    metros = txt
                elif "hab" in txt_l:
                    habitaciones = txt
                elif "baño" in txt_l or "bano" in txt_l:
                    banos = txt
                elif "garaje" in txt_l or "parking" in txt_l or "parquead" in txt_l:
                    garaje = txt
                elif "estrato" in txt_l:
                    estrato = txt

            # Ciudad
            loc   = card.select_one("[class*='location'], .poly-component__location")
            ciudad = loc.get_text(strip=True).lower() if loc else ""

            # Fecha publicación — está en aria-label: "2022 | 23.120 km · Publicado hace 2 días"
            fecha_raw = ""
            PAT_F = re.compile(
                u"Publicado hace [0-9]+ (?:d[ií]as?|semanas?|meses?|a[nñ]os?)"
                u"|Publicado hoy|Publicado ayer",
                re.IGNORECASE
            )
            # 1. Buscar en aria-label de la card
            card_html = str(card)
            mf = PAT_F.search(card_html)
            if mf:
                fecha_raw = mf.group(0).strip()
            # 2. JSON embebido del listado
            if not fecha_raw and fechas_por_id and item_id in fechas_por_id:
                fecha_raw = fechas_por_id[item_id]
            # 3. time tag
            if not fecha_raw:
                time_el = card.select_one("time[datetime]")
                if time_el:
                    fecha_raw = time_el.get("datetime", "")

            # Detectar frases en el título
            urgencia_t, unico_t, negociable_t = detectar_frases(titulo)

            items.append({
                "id":              item_id,
                "titulo":          titulo,
                "precio":          precio,
                "url":             url,
                "imagen":          imagen,
                "condicion":       "used",
                "marca":           extraer_marca(titulo),
                "modelo":          "",
                "anio":            anio,
                "km_raw":          km_raw,
                "transmision":     transmision or "?",
                "combustible":     "?",
                "ciudad":          ciudad,
                "fotos":           0,
                "vendedor_nivel":  "",
                "fecha_raw":       fecha_raw,
                "urgencia":        urgencia_t,
                "unico_dueno":     bool(unico_t),
                "negociable":      bool(negociable_t),
                # Inmuebles
                "metros":          metros,
                "habitaciones":    habitaciones,
                "banos":           banos,
                "garaje":          garaje,
                "estrato":         estrato,
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

# ── Análisis de oportunidades ─────────────────────────────────────────────────
def analizar(items_raw, enriquecer_descripciones=False):
    items = [{**i, "km": extraer_km(i.get("km_raw", ""))} for i in items_raw]

    # Mediana por grupo
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
        badges  = []   # etiquetas visuales especiales

        # ── 1. Precio vs mediana ──────────────────────────────────────────────
        if mediana > 0:
            ratio = precio / mediana
            if ratio < 0.75:
                puntaje += 35
                razones.append(f"Precio {round((1-ratio)*100)}% bajo la mediana")
            elif ratio < 0.88:
                puntaje += 20
                razones.append(f"Precio {round((1-ratio)*100)}% bajo la mediana")
            elif ratio < 0.95:
                puntaje += 10
                razones.append("Precio por debajo del mercado")
            elif ratio > 1.15:
                puntaje -= 15
                alertas.append("Precio sobre el mercado")

        # ── 2. Kilometraje ────────────────────────────────────────────────────
        if km and anio and str(anio).isdigit():
            edad = datetime.now().year - int(anio)
            if edad > 0:
                esp = edad * 15000
                if km < esp * 0.5:
                    puntaje += 20
                    razones.append(f"Bajo km ({km:,} en {edad} años)")
                elif km < esp * 0.75:
                    puntaje += 10
                    razones.append("Km por debajo del promedio")
                elif km > esp * 1.5:
                    puntaje -= 15
                    alertas.append(f"Alto km ({km:,})")

        # ── 3. Fecha de publicación ───────────────────────────────────────────
        dias = dias_desde_publicacion(it.get("fecha_raw", ""))
        if dias is not None:
            if dias == 0:
                puntaje += 15
                razones.append("Publicado hoy 🔥")
                badges.append("HOY")
            elif dias <= 2:
                puntaje += 12
                razones.append(f"Publicado hace {dias} días")
                badges.append("RECIENTE")
            elif dias <= 7:
                puntaje += 7
                razones.append(f"Publicado hace {dias} días")
            elif dias > 60:
                puntaje -= 5
                alertas.append(f"Publicado hace {dias // 30} meses (lleva tiempo sin vender)")

        # ── 4. Único dueño ────────────────────────────────────────────────────
        if it.get("unico_dueno"):
            puntaje += 12
            razones.append("Único dueño")
            badges.append("1 DUEÑO")

        # ── 5. Precio negociable ──────────────────────────────────────────────
        if it.get("negociable"):
            puntaje += 8
            razones.append("Precio negociable")
            badges.append("NEGOCIABLE")

        # ── 6. Urgencia del vendedor ──────────────────────────────────────────
        urgencia = it.get("urgencia", [])
        if urgencia:
            puntaje += 10
            razon_urg = urgencia[0].capitalize()
            razones.append(f"Señal de urgencia: \"{razon_urg}\"")
            badges.append("URGENTE")

        # ── 7. Fotos ──────────────────────────────────────────────────────────
        fotos = it.get("fotos", 0)
        if fotos >= 8:
            puntaje += 5
            razones.append(f"{fotos} fotos")
        elif 0 < fotos <= 2:
            puntaje -= 5
            alertas.append("Pocas fotos")

        # ── 9. Reputación vendedor ────────────────────────────────────────────
        nivel = it.get("vendedor_nivel", "")
        if nivel in ("5_green", "4_light_green"):
            puntaje += 5
            razones.append("Vendedor ★ alta reputación")
        elif nivel in ("1_red", "2_orange"):
            puntaje -= 10
            alertas.append("Vendedor baja reputación")

        # ── 10. Análisis IA (si hay API key y se pide enriquecimiento) ────────
        ia_result = None
        if enriquecer_descripciones and ANTHROPIC_KEY and it.get("url"):
            desc_data = scrape_descripcion(it["id"], it["url"])
            desc_txt  = desc_data.get("descripcion", "")
            if not it.get("fecha_raw") and desc_data.get("fecha_raw"):
                it["fecha_raw"] = desc_data["fecha_raw"]

            # Re-detectar frases en descripción
            urg_d, unico_d, neg_d = detectar_frases(desc_txt)
            if unico_d and not it.get("unico_dueno"):
                puntaje += 12
                razones.append("Único dueño (en descripción)")
                badges.append("1 DUEÑO")
            if neg_d and not it.get("negociable"):
                puntaje += 8
                razones.append("Negociable (en descripción)")

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

        diff = round((1 - precio / mediana) * 100, 1) if mediana > 0 else 0
        dias_pub = dias_desde_publicacion(it.get("fecha_raw", ""))

        resultado.append({
            **it,
            "precio_fmt":     f"${precio:,.0f}",
            "moneda":         "COP",
            "condicion":      "Usado" if it.get("condicion") == "used" else "Nuevo",
            "km_fmt":         f"{km:,}" if km else "N/D",
            "anio":           anio or "?",
            "mediana_grupo":  f"${mediana:,.0f}",
            "diferencia_pct": diff,
            "dias_publicado": dias_pub,
            "fecha_fmt":      fmt_fecha(dias_pub),
            "puntaje":        puntaje,
            "clasificacion":  cls,
            "color":          color,
            "razones":        razones,
            "alertas":        alertas,
            "badges":         badges,
            "ia_resumen":     ia_result.get("resumen") if ia_result else "",
        })

    # Ordenar: primero por puntaje, luego por fecha más reciente
    resultado.sort(key=lambda x: (
        -x["puntaje"],
        x["dias_publicado"] if x["dias_publicado"] is not None else 9999
    ))
    return resultado

# ── Rutas ─────────────────────────────────────────────────────────────────────
@app.route("/")
@login_required
def index():
    return render_template("index.html", categorias=CATEGORIAS, marcas=MARCAS)


@app.route("/api/inicio")
@login_required
def api_inicio():
    """Carga las mejores oportunidades del momento para la pantalla de inicio."""
    resultados = []
    for cat_key, cat_info in CATEGORIAS.items():
        if cat_key in CATS_INMUEBLES:
            continue  # solo vehículos en pantalla de inicio
        nombre, slug, dominio = cat_info
        try:
            raw   = scrape_listado(slug, "", "", None, None, 0, dominio)
            items = analizar(raw.get("items", []))
            top   = [i for i in items if i["puntaje"] >= 85][:4]
            for i in top:
                i["categoria_nombre"] = nombre
            resultados.extend(top)
        except Exception:
            pass
    resultados.sort(key=lambda x: (-x["puntaje"],
                    x["dias_publicado"] if x["dias_publicado"] is not None else 9999))
    return jsonify({"items": resultados[:12]})


@app.route("/api/buscar")
@login_required
def api_buscar():
    query      = request.args.get("q", "").strip()
    cat_key    = request.args.get("categoria", "carros")
    marca      = request.args.get("marca", "").strip()
    precio_min = request.args.get("precio_min", type=int)
    precio_max = request.args.get("precio_max", type=int)
    pagina     = request.args.get("pagina", 0, type=int)
    con_ia     = request.args.get("ia", "0") == "1"

    cat_info     = CATEGORIAS.get(cat_key, CATEGORIAS["carros"])
    tipo_negocio = request.args.get("tipo_negocio", "")  # "venta", "arriendo" o ""
    orden        = request.args.get("orden", "")
    anio_min     = request.args.get("anio_min", type=int)
    anio_max     = request.args.get("anio_max", type=int)

    # Seleccionar slug según tipo de negocio
    if len(cat_info) == 4:
        nombre, slug_venta, slug_arriendo, dominio = cat_info
        if tipo_negocio == "arriendo" and slug_arriendo:
            cat_slug = slug_arriendo
        elif tipo_negocio == "venta" and slug_venta:
            cat_slug = slug_venta
        else:
            # Sin filtro: usar slug de venta (ML lo usa como base)
            cat_slug = slug_venta or slug_arriendo
    else:
        cat_slug, dominio = cat_info[1], cat_info[2]

    try:
        raw = scrape_listado(cat_slug, query, marca, precio_min, precio_max, pagina, dominio, orden)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    items_raw  = raw.get("items", [])
    total      = raw.get("total", 0)
    analizados = analizar(items_raw, enriquecer_descripciones=con_ia)

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


@app.route("/api/test_fecha")
def api_test_fecha():
    """Debug: prueba extraer fecha de un item real."""
    url = request.args.get("url", "https://moto.mercadolibre.com.co/MCO-1234")
    try:
        with _fecha_lock:
            driver = get_driver()
            driver.get(url)
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "h1, .ui-pdp-title"))
                )
            except Exception:
                pass
            time.sleep(1)
            html = driver.page_source

        # Find all "publicado" mentions
        import re as _re
        menciones = _re.findall(r".{0,30}[Pp]ublicado.{0,50}", html)
        menciones2 = _re.findall(r".{0,20}hace \d+.{0,30}", html, _re.IGNORECASE)
        
        return jsonify({
            "url": url,
            "html_length": len(html),
            "menciones_publicado": menciones[:5],
            "menciones_hace": menciones2[:5],
            "primeros_500": html[:500],
        })
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/fechas", methods=["POST"])
def api_fechas():
    """Recibe lista de {id, url} y devuelve fechas usando Selenium driver2."""
    data  = request.get_json() or {}
    items = data.get("items", [])[:8]  # máximo 8 para no tardar demasiado

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



# ════════════════════════════════════════════════════════════════════════════
# FACEBOOK MARKETPLACE
# ════════════════════════════════════════════════════════════════════════════

CHROME_USER_DATA = r"C:\Users\jhonp\AppData\Local\Google\Chrome\User Data"

_fb_driver      = None
_fb_driver_lock = threading.Lock()

def _crear_fb_driver():
    """Crea una nueva instancia del driver de Chrome para Facebook."""
    opts = Options()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=es-CO,es")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-popup-blocking")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    svc = get_service()
    drv = webdriver.Chrome(service=svc, options=opts)
    drv.execute_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
    )
    return drv


def get_fb_driver():
    """Retorna el driver de FB, recreándolo si fue cerrado."""
    global _fb_driver
    with _fb_driver_lock:
        # Verificar si el driver sigue vivo
        if _fb_driver is not None:
            try:
                _ = _fb_driver.current_url  # test si responde
            except Exception:
                print("  Chrome FB cerrado — recreando...")
                try:
                    _fb_driver.quit()
                except Exception:
                    pass
                _fb_driver = None

        if _fb_driver is None:
            print("  Iniciando Chrome FB...")
            _fb_driver = _crear_fb_driver()
            print("  Chrome FB listo ✓")
    return _fb_driver

_fb_lock = threading.Lock()

FB_CATEGORIAS = {
    "vehiculos":   "vehicles",
    "carros":      "vehicles/cars",
    "motos":       "vehicles/motorcycles",
    "camiones":    "vehicles/trucks",
    "casas":       "propertyrentals",
    "apartamentos":"propertyrentals",
    "fincas":      "propertyrentals",
    "todos":       "",
}

def scrape_fb_marketplace(query, categoria="vehiculos", precio_min=None, precio_max=None):
    """Scrapea Facebook Marketplace Colombia."""
    from urllib.parse import quote
    from selenium.webdriver.common.keys import Keys

    cat_path = FB_CATEGORIAS.get(categoria, "vehicles")

    items = []
    try:
        with _fb_lock:
            driver = get_fb_driver()
            cur_url = ""
            try:
                cur_url = driver.current_url
            except Exception:
                cur_url = ""

            # Paso 1: Asegurar login
            if "facebook.com" not in cur_url:
                driver.get("https://www.facebook.com/")
                time.sleep(3)

            # Paso 2: Verificar sesión
            logueado = False
            for _ in range(18):
                try:
                    cur = driver.current_url
                    src = driver.page_source
                    if ("facebook.com" in cur and "login" not in cur and
                            "checkpoint" not in cur and len(src) > 30000):
                        logueado = True
                        break
                    print("  FB: esperando login manual...")
                except Exception:
                    pass
                time.sleep(5)

            if not logueado:
                return {"items": [], "total": 0, "error": "login_required", "url": ""}

            # Paso 3: Ir a Marketplace Bogotá
            driver.get("https://www.facebook.com/marketplace/bogota/")
            time.sleep(3)
            print(f"  FB: en marketplace, buscando: {query}")

            # Paso 4: Navegar directo a la URL de búsqueda de Marketplace
            # (más confiable que buscar el campo de texto)
            if query:
                url_busqueda = f"https://www.facebook.com/marketplace/bogota/search?query={quote(query)}"
                if cat_path in ("vehicles", "vehicles/cars"):
                    url_busqueda += "&categoryId=vehicles"
                elif cat_path == "propertyrentals":
                    url_busqueda += "&categoryId=propertyrentals"
                driver.get(url_busqueda)
                print(f"  FB: navegando a {url_busqueda}")
                time.sleep(5)
                print(f"  FB: URL actual = {driver.current_url}")

            # Paso 5: Esperar resultados y scroll
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/marketplace/item/']"))
                )
            except Exception:
                pass
            time.sleep(2)
            driver.execute_script("window.scrollTo(0, 1000)")
            time.sleep(2)
            html = driver.page_source
            print(f"  FB: {len(html)} chars, URL: {driver.current_url[:80]}")

        if len(html) < 5000:
            return {"items": [], "total": 0, "error": "login_required", "url": ""}

        items = parse_fb_items(html, debug=True)
        print(f"  FB: {len(items)} items encontrados")
    except Exception as e:
        print(f"  FB error: {e}")
        return {"items": [], "total": 0, "error": str(e), "url": ""}

    return {"items": items, "total": len(items), "url": ""}

def parse_precio_fb(txt):
    """Maneja ambos formatos FB: '$ 87.000.000' y '$ 27 900 000'"""
    txt_norm = txt.replace(" ", " ")
    # Formato con puntos: "$ 87.000.000"
    m = re.search(r"\$\s*(\d{1,3}(?:[.]\d{3})+)", txt_norm)
    if m:
        nums = re.sub(r"[^\d]", "", m.group(1))
        if 5 <= len(nums) <= 11:
            return int(nums)
    # Formato con espacios: "$ 27 900 000"
    m = re.search(r"\$\s*(\d{1,3}(?:[ ]\d{3})+)", txt_norm)
    if m:
        nums = re.sub(r"[^\d]", "", m.group(1))
        if 5 <= len(nums) <= 11:
            return int(nums)
    return 0


def parse_fb_items(html, base_url="", debug=False):
    """Parsea items de Facebook Marketplace."""
    soup  = BeautifulSoup(html, "html.parser")
    items = []
    links = soup.select("a[href*='/marketplace/item/']")
    seen  = set()
    if debug:
        print(f"  FB parser: {len(links)} links encontrados")

    for link in links:
        try:
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            url = "https://www.facebook.com" + href if href.startswith("/") else href

            # Imagen
            img    = link.select_one("img[src]")
            imagen = img.get("src", "") if img else ""

            # FB combina todo en un texto con   como separador
            full_text = link.get_text(" ", strip=True)
            if debug and len(items) < 3:
                print(f"  FB link text: {repr(full_text[:100])}")

            # 1. Extraer precio con   normalizado
            precio = parse_precio_fb(full_text)

            # 2. Normalizar   y quitar precio(s) (puntos o espacios)
            full_norm = full_text.replace(" ", " ")
            sin_precio = re.sub(r"\$\s*\d{1,3}(?:[.]\d{3})+", "", full_norm)
            sin_precio = re.sub(r"\$\s*\d{1,3}(?:[ ]\d{3})+", "", sin_precio)
            sin_precio = re.sub(r"\s+", " ", sin_precio).strip()
            if debug and len(items) < 3:
                print(f"  FB precio={precio} sin_precio={repr(sin_precio[:60])}")

            # 3. Separar título de ciudad
            # Las ciudades colombianas conocidas suelen estar al final
            ciudades = ["Bogotá", "Medellín", "Cali", "Barranquilla", "Bucaramanga",
                       "Pereira", "Manizales", "Cartagena", "Cúcuta", "Ibagué",
                       "Soacha", "Bello", "Santa Marta", "Villavicencio", "Mosquera",
                       "Funza", "Chía", "Zipaquirá", "Girardot", "Tunja", "Tocaima",
                       "Bogota", "Medellin"]
            ubicacion = ""
            titulo = sin_precio
            for ciudad in ciudades:
                if sin_precio.endswith(ciudad):
                    ubicacion = ciudad
                    titulo = sin_precio[:-len(ciudad)].strip()
                    break
            # Si no encontramos ciudad conocida, las últimas palabras cortas pueden ser ciudad
            if not ubicacion and len(sin_precio.split()) > 2:
                partes = sin_precio.rsplit(' ', 1)
                if len(partes[1]) < 20:
                    ubicacion = partes[1]
                    titulo = partes[0].strip()

            if not titulo or not precio:
                continue

            # Extraer marca del título
            marca = extraer_marca(titulo)

            # Detectar frases de urgencia/negociable en título
            urgencia_t, unico_t, negociable_t = detectar_frases(titulo)

            # Atributos básicos del título
            anio_m = re.search(r"(19|20)\d{2}", titulo)
            anio   = anio_m.group(0) if anio_m else ""

            km_m   = re.search(r"(\d[\d\.]*)\s*km", titulo, re.IGNORECASE)
            km_raw = km_m.group(0) if km_m else ""

            items.append({
                "id":            "fb_" + re.sub(r"[^\d]", "", href)[:15],
                "titulo":        titulo,
                "precio":        precio,
                "url":           url,
                "imagen":        imagen,
                "condicion":     "used",
                "marca":         marca,
                "modelo":        "",
                "anio":          anio,
                "km_raw":        km_raw,
                "transmision":   "?",
                "combustible":   "?",
                "ciudad":        ubicacion,
                "fotos":         1,
                "vendedor_nivel": "",
                "fecha_raw":     "",
                "urgencia":      urgencia_t,
                "unico_dueno":   bool(unico_t),
                "negociable":    bool(negociable_t),
                "fuente":        "facebook",
                # Inmuebles
                "metros":        "",
                "habitaciones":  "",
                "banos":         "",
                "garaje":        "",
                "estrato":       "",
            })
        except Exception:
            continue

    return items[:48]


@app.route("/api/buscar_fb")
def api_buscar_fb():
    """Búsqueda en Facebook Marketplace."""
    query      = request.args.get("q", "").strip()
    categoria  = request.args.get("categoria", "vehiculos")
    precio_min = request.args.get("precio_min", type=int)
    precio_max = request.args.get("precio_max", type=int)

    raw = scrape_fb_marketplace(query, categoria, precio_min, precio_max)

    if "error" in raw and not raw.get("items"):
        return jsonify({"error": raw["error"], "items": [], "stats": {}}), 500

    items_raw  = raw.get("items", [])
    analizados = analizar(items_raw)

    precios = [i["precio"] for i in analizados if i["precio"] > 0]
    stats   = {}
    if precios:
        stats = {
            "total_encontrados":        len(analizados),
            "en_pagina":                len(analizados),
            "precio_min":               f"${min(precios):,.0f}",
            "precio_max":               f"${max(precios):,.0f}",
            "precio_mediana":           f"${statistics.median(precios):,.0f}",
            "precio_promedio":          f"${statistics.mean(precios):,.0f}",
            "oportunidades_excelentes": sum(1 for i in analizados if i["clasificacion"] == "EXCELENTE"),
            "oportunidades_buenas":     sum(1 for i in analizados if i["clasificacion"] in ("MUY BUENA","BUENA")),
            "con_urgencia":             sum(1 for i in analizados if i.get("urgencia")),
            "negociables":              sum(1 for i in analizados if i.get("negociable")),
        }

    return jsonify({
        "items":  analizados,
        "stats":  stats,
        "total":  len(analizados),
        "url_fb": raw.get("url", ""),
    })

@app.route("/api/debug_fb")
def api_debug_fb():
    """Debug: muestra qué HTML obtiene el scraper de FB."""
    query = request.args.get("q", "sandero")
    try:
        with _fb_lock:
            driver = get_fb_driver()
            from urllib.parse import quote
            url = f"https://www.facebook.com/marketplace/bogota/search?query={quote(query)}&categoryId=vehicles"
            driver.get(url)
            time.sleep(5)
            html = driver.page_source

        soup = BeautifulSoup(html, "html.parser")
        
        # Buscar todos los tipos de links
        item_links    = soup.select("a[href*='/marketplace/item/']")
        all_a         = soup.select("a[href]")
        
        # Buscar hrefs que contengan 'item'
        item_hrefs = [a.get("href","") for a in all_a if "item" in a.get("href","")][:10]
        
        # Sample de todos los hrefs
        all_hrefs = list(set([a.get("href","")[:60] for a in all_a if a.get("href","").startswith("/")]))[:20]
        
        # Buscar spans con precios
        spans_precio = [s.get_text(strip=True) for s in soup.select("span") 
                       if re.search(r"\$\s*\d", s.get_text())][:10]

        return jsonify({
            "url_actual": driver.current_url,
            "html_length": len(html),
            "item_links_found": len(item_links),
            "total_links": len(all_a),
            "item_hrefs": item_hrefs,
            "sample_hrefs": all_hrefs[:15],
            "spans_precio": spans_precio,
            "primeros_2000": html[:2000],
        })
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/reset_fb")
def api_reset_fb():
    """Reinicia el driver de Facebook para forzar nuevo login."""
    global _fb_driver
    with _fb_driver_lock:
        if _fb_driver:
            try:
                _fb_driver.quit()
            except Exception:
                pass
            _fb_driver = None
    return jsonify({"ok": True})


if __name__ == "__main__":
    print("\n" + "="*55)
    print("  🚗  MeLi Autos v5 - IA + Señales + Fecha")
    print("="*55)
    get_driver()
    print("  Servidor en: http://localhost:5000")
    print("  Ctrl+C para detener")
    print("="*55 + "\n")
    app.run(debug=False, port=5000, host="0.0.0.0")
