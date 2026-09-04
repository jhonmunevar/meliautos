"""
Scrapers adicionales para MeLiAutos v6:
- Carroya.com (vehículos)
- Metrocuadrado.com (inmuebles)
- FincaRaíz.com.co (inmuebles)
"""

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import re, time, json
from urllib.parse import quote


# ═══════════════════════════════════════════════════════════════
# CARROYA.COM — Vehículos
# ═══════════════════════════════════════════════════════════════

def build_carroya_url(query, marca="", tipo="carros-y-camionetas",
                      precio_min=None, precio_max=None, anio_min=None, anio_max=None):
    """
    URL de búsqueda de Carroya.
    Ej: https://www.carroya.com/buscar/carros-y-camionetas/usados?q=sandero
    """
    base = f"https://www.carroya.com/buscar/{tipo}/usados"
    params = []
    q_parts = [p for p in [marca, query] if p]
    if q_parts:
        params.append(f"q={quote(' '.join(q_parts))}")
    if precio_min:
        params.append(f"precioDesde={precio_min}")
    if precio_max:
        params.append(f"precioHasta={precio_max}")
    if anio_min:
        params.append(f"anioDesde={anio_min}")
    if anio_max:
        params.append(f"anioHasta={anio_max}")
    return base + ("?" + "&".join(params) if params else "")


def parse_carroya_items(html):
    """Parsea el HTML/JSON de Carroya para extraer vehículos."""
    soup  = BeautifulSoup(html, "html.parser")
    items = []

    # Carroya inyecta __NEXT_DATA__ con todos los items
    next_data = soup.find("script", id="__NEXT_DATA__")
    if next_data:
        try:
            data     = json.loads(next_data.string)
            # Navegar por la estructura de Next.js
            props    = data.get("props", {}).get("pageProps", {})
            listings = (props.get("initialData", {}).get("results") or
                       props.get("listings") or
                       props.get("vehicles") or [])

            for item in listings[:48]:
                precio = 0
                try:
                    precio = int(str(item.get("price", 0)).replace(".", "").replace(",", ""))
                except Exception:
                    pass

                anio = str(item.get("year", item.get("anio", "")))
                km   = item.get("mileage", item.get("kilometraje", item.get("km", "")))
                km_raw = f"{km} km" if km else ""

                titulo = item.get("title", item.get("titulo", ""))
                if not titulo:
                    marca  = item.get("brand", item.get("marca", ""))
                    modelo = item.get("model", item.get("modelo", ""))
                    titulo = f"{marca} {modelo} {anio}".strip()

                slug  = item.get("slug", item.get("url", ""))
                url   = f"https://www.carroya.com{slug}" if slug.startswith("/") else slug or "#"
                img   = ""
                imgs  = item.get("images", item.get("photos", item.get("imagenes", [])))
                if imgs:
                    img = imgs[0].get("url", imgs[0]) if isinstance(imgs[0], dict) else str(imgs[0])

                if titulo and precio > 0:
                    items.append({
                        "id":           f"cy_{item.get('id', '')}",
                        "titulo":       titulo,
                        "precio":       precio,
                        "url":          url,
                        "imagen":       img,
                        "condicion":    "used",
                        "marca":        item.get("brand", item.get("marca", "?")),
                        "modelo":       item.get("model", item.get("modelo", "")),
                        "anio":         anio,
                        "km_raw":       km_raw,
                        "transmision":  item.get("transmission", item.get("transmision", "?")),
                        "combustible":  item.get("fuel", item.get("combustible", "?")),
                        "ciudad":       item.get("city", item.get("ciudad", "")).lower(),
                        "fotos":        len(imgs),
                        "vendedor_nivel": "",
                        "fecha_raw":    item.get("createdAt", item.get("publishedAt", "")),
                        "urgencia":     [],
                        "unico_dueno":  False,
                        "negociable":   False,
                        "fuente":       "carroya",
                        "metros": "", "habitaciones": "", "banos": "", "garaje": "", "estrato": "",
                    })
        except Exception as e:
            print(f"  Carroya JSON parse error: {e}")

    # Fallback: parsear HTML directamente
    if not items:
        items = _parse_carroya_html(soup)

    return items


def _parse_carroya_html(soup):
    """Fallback: parsear HTML de Carroya."""
    items = []
    # Carroya usa cards con clase car-card, vehicle-card o similar
    selectors = [
        "article[class*='card']",
        "div[class*='vehicle-card']",
        "div[class*='car-card']",
        "div[class*='listing-card']",
        "li[class*='result']",
    ]
    cards = []
    for sel in selectors:
        cards = soup.select(sel)
        if cards:
            break

    for card in cards[:48]:
        try:
            titulo_el = card.select_one("h2, h3, [class*='title'], [class*='titulo']")
            titulo    = titulo_el.get_text(strip=True) if titulo_el else ""
            if not titulo:
                continue

            precio_el = card.select_one("[class*='price'], [class*='precio']")
            precio    = 0
            if precio_el:
                nums = re.sub(r"[^\d]", "", precio_el.get_text())
                if nums:
                    precio = int(nums)

            link  = card.select_one("a[href]")
            url   = link["href"] if link else "#"
            if url.startswith("/"):
                url = "https://www.carroya.com" + url

            img_el = card.select_one("img[src], img[data-src]")
            imagen = (img_el.get("src") or img_el.get("data-src") or "") if img_el else ""

            anio_m = re.search(r"(19|20)\d{2}", titulo)
            anio   = anio_m.group(0) if anio_m else ""
            km_m   = re.search(r"[\d\.]+\s*km", titulo, re.IGNORECASE)
            km_raw = km_m.group(0) if km_m else ""

            if titulo and precio > 0:
                items.append({
                    "id": f"cy_{re.sub(r'[^\d]', '', url)[:12]}",
                    "titulo": titulo, "precio": precio, "url": url,
                    "imagen": imagen, "condicion": "used",
                    "marca": "?", "modelo": "", "anio": anio, "km_raw": km_raw,
                    "transmision": "?", "combustible": "?", "ciudad": "",
                    "fotos": 0, "vendedor_nivel": "", "fecha_raw": "",
                    "urgencia": [], "unico_dueno": False, "negociable": False,
                    "fuente": "carroya",
                    "metros": "", "habitaciones": "", "banos": "", "garaje": "", "estrato": "",
                })
        except Exception:
            continue
    return items


def scrape_carroya(driver, cache_get, cache_set, query, marca="",
                   precio_min=None, precio_max=None, anio_min=None, anio_max=None):
    """Scrapea Carroya con Selenium."""
    url       = build_carroya_url(query, marca, precio_min=precio_min,
                                  precio_max=precio_max, anio_min=anio_min, anio_max=anio_max)
    cache_key = f"carroya_{url}"
    cached    = cache_get(cache_key)
    if cached:
        return cached

    try:
        driver.get(url)
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    "article, div[class*='card'], div[class*='result'], #__NEXT_DATA__"))
            )
        except Exception:
            pass
        time.sleep(2)
        driver.execute_script("window.scrollTo(0, 800)")
        time.sleep(1.5)
        html  = driver.page_source
        items = parse_carroya_items(html)
        total = len(items)

        # Intentar obtener total real
        total_el = BeautifulSoup(html, "html.parser").select_one(
            "[class*='results-count'], [class*='total'], [class*='cantidad']"
        )
        if total_el:
            nums = re.findall(r"\d+", total_el.get_text())
            if nums:
                total = int(nums[0])

        print(f"  Carroya: {len(items)} items, URL: {url[:60]}")
        result = {"items": items, "total": total, "url": url, "fuente": "carroya"}
        cache_set(cache_key, result)
        return result
    except Exception as e:
        print(f"  Carroya error: {e}")
        return {"items": [], "total": 0, "url": url, "fuente": "carroya", "error": str(e)}


# ═══════════════════════════════════════════════════════════════
# METROCUADRADO.COM — Inmuebles
# ═══════════════════════════════════════════════════════════════

METRO_TIPOS = {
    "casas":        "casas",
    "apartamentos": "apartamentos",
    "fincas":       "fincas",
    "bodegas":      "bodegas",
    "locales":      "locales-comerciales",
    "oficinas":     "oficinas",
}

def build_metro_url(tipo="apartamentos", operacion="arriendo", ciudad="bogota", query=""):
    """
    URL de Metrocuadrado.
    Ej: https://www.metrocuadrado.com/apartamentos/arriendo/bogota/
    """
    tipo_slug = METRO_TIPOS.get(tipo, tipo)
    base = f"https://www.metrocuadrado.com/{tipo_slug}/{operacion}/{ciudad}/"
    if query:
        base += f"?texto={quote(query)}"
    return base


def parse_metro_items(html, operacion="arriendo"):
    """Parsea HTML/JSON de Metrocuadrado."""
    soup  = BeautifulSoup(html, "html.parser")
    items = []

    # Metrocuadrado inyecta datos en __NEXT_DATA__
    next_data = soup.find("script", id="__NEXT_DATA__")
    if next_data:
        try:
            data     = json.loads(next_data.string)
            props    = data.get("props", {}).get("pageProps", {})
            listings = (props.get("listings", {}).get("results") or
                       props.get("properties") or
                       props.get("results") or [])

            for item in listings[:48]:
                precio = 0
                try:
                    precio = int(str(item.get("price", item.get("precio", 0))).replace(".", "").replace(",", ""))
                except Exception:
                    pass

                area        = item.get("area", item.get("m2", ""))
                habitaciones = str(item.get("rooms", item.get("habitaciones", item.get("bedrooms", ""))))
                banos       = str(item.get("bathrooms", item.get("banos", "")))
                garaje      = str(item.get("garages", item.get("garajes", "")))
                estrato     = str(item.get("estrato", item.get("stratum", "")))

                titulo = item.get("title", item.get("titulo", ""))
                if not titulo:
                    tipo_p = item.get("propertyType", item.get("tipo", "Inmueble"))
                    barrio = item.get("neighborhood", item.get("barrio", ""))
                    titulo = f"{tipo_p} en {barrio}".strip() if barrio else tipo_p

                slug  = item.get("link", item.get("url", item.get("slug", "")))
                url   = f"https://www.metrocuadrado.com{slug}" if slug.startswith("/") else slug or "#"
                imgs  = item.get("images", item.get("photos", []))
                img   = ""
                if imgs:
                    img = imgs[0].get("url", imgs[0]) if isinstance(imgs[0], dict) else str(imgs[0])

                if titulo and precio > 0:
                    items.append({
                        "id":           f"mc_{item.get('id', item.get('codigo', ''))}",
                        "titulo":       titulo,
                        "precio":       precio,
                        "url":          url,
                        "imagen":       img,
                        "condicion":    operacion,
                        "marca":        "?", "modelo": "", "anio": "", "km_raw": "",
                        "transmision":  "?", "combustible": "?",
                        "ciudad":       item.get("city", item.get("ciudad", "bogotá")).lower(),
                        "fotos":        len(imgs),
                        "vendedor_nivel": "",
                        "fecha_raw":    item.get("publishedAt", item.get("createdAt", "")),
                        "urgencia":     [], "unico_dueno": False, "negociable": False,
                        "fuente":       "metrocuadrado",
                        "metros":       f"{area} m²" if area else "",
                        "habitaciones": f"{habitaciones} hab." if habitaciones and habitaciones != "None" else "",
                        "banos":        f"{banos} baños" if banos and banos != "None" else "",
                        "garaje":       f"{garaje} garaje(s)" if garaje and garaje not in ("None","0","") else "",
                        "estrato":      f"Estrato {estrato}" if estrato and estrato != "None" else "",
                    })
        except Exception as e:
            print(f"  Metrocuadrado JSON error: {e}")

    if not items:
        items = _parse_metro_html(soup, operacion)

    return items


def _parse_metro_html(soup, operacion):
    """Fallback HTML para Metrocuadrado."""
    items = []
    for card in soup.select("[class*='card'], article, [class*='property']")[:48]:
        try:
            titulo_el = card.select_one("h2, h3, [class*='title']")
            titulo    = titulo_el.get_text(strip=True) if titulo_el else ""
            if not titulo or len(titulo) < 5:
                continue

            precio_el = card.select_one("[class*='price'], [class*='precio'], [class*='valor']")
            precio = 0
            if precio_el:
                nums = re.sub(r"[^\d]", "", precio_el.get_text())
                if nums:
                    precio = int(nums)
            if not precio:
                continue

            link  = card.select_one("a[href]")
            url   = link["href"] if link else "#"
            if url.startswith("/"):
                url = "https://www.metrocuadrado.com" + url

            img_el = card.select_one("img[src], img[data-src]")
            imagen = (img_el.get("src") or img_el.get("data-src") or "") if img_el else ""

            area_m = re.search(r"(\d+)\s*m²", card.get_text())
            hab_m  = re.search(r"(\d+)\s*hab", card.get_text(), re.IGNORECASE)
            ban_m  = re.search(r"(\d+)\s*ba[ñn]", card.get_text(), re.IGNORECASE)

            items.append({
                "id": f"mc_{re.sub(r'[^\d]', '', url)[:12]}",
                "titulo": titulo, "precio": precio, "url": url,
                "imagen": imagen, "condicion": operacion,
                "marca": "?", "modelo": "", "anio": "", "km_raw": "",
                "transmision": "?", "combustible": "?", "ciudad": "bogotá",
                "fotos": 0, "vendedor_nivel": "", "fecha_raw": "",
                "urgencia": [], "unico_dueno": False, "negociable": False,
                "fuente": "metrocuadrado",
                "metros":      f"{area_m.group(1)} m²" if area_m else "",
                "habitaciones": f"{hab_m.group(1)} hab." if hab_m else "",
                "banos":       f"{ban_m.group(1)} baños" if ban_m else "",
                "garaje": "", "estrato": "",
            })
        except Exception:
            continue
    return items


def scrape_metrocuadrado(driver, cache_get, cache_set,
                         tipo="apartamentos", operacion="arriendo",
                         ciudad="bogota", query="", precio_min=None, precio_max=None):
    url       = build_metro_url(tipo, operacion, ciudad, query)
    cache_key = f"metro_{url}"
    cached    = cache_get(cache_key)
    if cached:
        return cached
    try:
        driver.get(url)
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    "[class*='card'], article, #__NEXT_DATA__"))
            )
        except Exception:
            pass
        time.sleep(2.5)
        driver.execute_script("window.scrollTo(0, 800)")
        time.sleep(1.5)
        html  = driver.page_source
        items = parse_metro_items(html, operacion)
        print(f"  Metrocuadrado: {len(items)} items, URL: {url[:60]}")
        result = {"items": items, "total": len(items), "url": url, "fuente": "metrocuadrado"}
        cache_set(cache_key, result)
        return result
    except Exception as e:
        print(f"  Metrocuadrado error: {e}")
        return {"items": [], "total": 0, "url": url, "fuente": "metrocuadrado", "error": str(e)}


# ═══════════════════════════════════════════════════════════════
# FINCARAÍZ.COM.CO — Inmuebles
# ═══════════════════════════════════════════════════════════════

FINCARAIZ_TIPOS = {
    "casas":        "casas",
    "apartamentos": "apartamentos",
    "fincas":       "finca-recreo",
    "bodegas":      "bodegas",
    "locales":      "local-comercial",
    "oficinas":     "oficina",
}

def build_fincaraiz_url(tipo="apartamentos", operacion="arriendo", ciudad="bogota", query=""):
    """
    URL de FincaRaíz.
    Ej: https://www.fincaraiz.com.co/arriendo/apartamentos/bogota/
    """
    tipo_slug = FINCARAIZ_TIPOS.get(tipo, tipo)
    url = f"https://www.fincaraiz.com.co/{operacion}/{tipo_slug}/{ciudad}/"
    if query:
        url += f"?texto={quote(query)}"
    return url


def parse_fincaraiz_items(html, operacion="arriendo"):
    """Parsea HTML/JSON de FincaRaíz."""
    soup  = BeautifulSoup(html, "html.parser")
    items = []

    # FincaRaíz también usa Next.js
    next_data = soup.find("script", id="__NEXT_DATA__")
    if next_data:
        try:
            data     = json.loads(next_data.string)
            props    = data.get("props", {}).get("pageProps", {})
            listings = (props.get("listings") or
                       props.get("properties") or
                       props.get("results") or
                       props.get("data", {}).get("listings") or [])

            for item in listings[:48]:
                precio = 0
                try:
                    precio = int(str(item.get("price", item.get("canon", item.get("precio", 0)))
                                    ).replace(".", "").replace(",", ""))
                except Exception:
                    pass

                area         = item.get("area", item.get("areaConstruida", ""))
                habitaciones = str(item.get("rooms", item.get("habitaciones", item.get("alcobas", ""))))
                banos        = str(item.get("bathrooms", item.get("banos", "")))
                garaje       = str(item.get("garages", item.get("garajes", "")))
                estrato      = str(item.get("estrato", ""))

                titulo = item.get("title", item.get("titulo", ""))
                if not titulo:
                    tipo_p = item.get("propertyType", "Inmueble")
                    barrio = item.get("neighborhood", item.get("sector", ""))
                    titulo = f"{tipo_p} en {barrio}".strip() if barrio else tipo_p

                slug  = item.get("link", item.get("url", item.get("slug", "")))
                url_i = f"https://www.fincaraiz.com.co{slug}" if slug.startswith("/") else slug or "#"
                imgs  = item.get("images", item.get("photos", item.get("fotos", [])))
                img   = ""
                if imgs:
                    img = imgs[0].get("url", imgs[0].get("src", "")) if isinstance(imgs[0], dict) else str(imgs[0])

                if titulo and precio > 0:
                    items.append({
                        "id":           f"fr_{item.get('id', item.get('codigo', ''))}",
                        "titulo":       titulo,
                        "precio":       precio,
                        "url":          url_i,
                        "imagen":       img,
                        "condicion":    operacion,
                        "marca":        "?", "modelo": "", "anio": "", "km_raw": "",
                        "transmision":  "?", "combustible": "?",
                        "ciudad":       item.get("city", item.get("ciudad", "bogotá")).lower(),
                        "fotos":        len(imgs),
                        "vendedor_nivel": "",
                        "fecha_raw":    item.get("publishedAt", item.get("fechaPublicacion", "")),
                        "urgencia":     [], "unico_dueno": False, "negociable": False,
                        "fuente":       "fincaraiz",
                        "metros":       f"{area} m²" if area else "",
                        "habitaciones": f"{habitaciones} hab." if habitaciones and habitaciones not in ("None","0","") else "",
                        "banos":        f"{banos} baños" if banos and banos not in ("None","0","") else "",
                        "garaje":       f"{garaje} garaje(s)" if garaje and garaje not in ("None","0","") else "",
                        "estrato":      f"Estrato {estrato}" if estrato and estrato != "None" else "",
                    })
        except Exception as e:
            print(f"  FincaRaíz JSON error: {e}")

    if not items:
        items = _parse_fincaraiz_html(soup, operacion)

    return items


def _parse_fincaraiz_html(soup, operacion):
    items = []
    for card in soup.select("[class*='card'], article, [class*='listing'], [class*='property']")[:48]:
        try:
            titulo_el = card.select_one("h2, h3, [class*='title'], [class*='titulo']")
            titulo    = titulo_el.get_text(strip=True) if titulo_el else ""
            if not titulo or len(titulo) < 5:
                continue

            precio_el = card.select_one("[class*='price'], [class*='precio'], [class*='valor'], [class*='canon']")
            precio = 0
            if precio_el:
                nums = re.sub(r"[^\d]", "", precio_el.get_text())
                if nums:
                    precio = int(nums)
            if not precio:
                continue

            link  = card.select_one("a[href]")
            url   = link["href"] if link else "#"
            if url.startswith("/"):
                url = "https://www.fincaraiz.com.co" + url

            img_el = card.select_one("img[src], img[data-src]")
            imagen = (img_el.get("src") or img_el.get("data-src") or "") if img_el else ""

            txt   = card.get_text()
            area_m = re.search(r"(\d+)\s*m²", txt)
            hab_m  = re.search(r"(\d+)\s*(?:hab|alc)", txt, re.IGNORECASE)
            ban_m  = re.search(r"(\d+)\s*ba[ñn]", txt, re.IGNORECASE)
            est_m  = re.search(r"[Ee]strato\s*(\d)", txt)

            items.append({
                "id": f"fr_{re.sub(r'[^\d]', '', url)[:12]}",
                "titulo": titulo, "precio": precio, "url": url,
                "imagen": imagen, "condicion": operacion,
                "marca": "?", "modelo": "", "anio": "", "km_raw": "",
                "transmision": "?", "combustible": "?", "ciudad": "bogotá",
                "fotos": 0, "vendedor_nivel": "", "fecha_raw": "",
                "urgencia": [], "unico_dueno": False, "negociable": False,
                "fuente": "fincaraiz",
                "metros":       f"{area_m.group(1)} m²" if area_m else "",
                "habitaciones": f"{hab_m.group(1)} hab." if hab_m else "",
                "banos":        f"{ban_m.group(1)} baños" if ban_m else "",
                "garaje": "",
                "estrato":      f"Estrato {est_m.group(1)}" if est_m else "",
            })
        except Exception:
            continue
    return items


def scrape_fincaraiz(driver, cache_get, cache_set,
                     tipo="apartamentos", operacion="arriendo",
                     ciudad="bogota", query="", precio_min=None, precio_max=None):
    url       = build_fincaraiz_url(tipo, operacion, ciudad, query)
    cache_key = f"fr_{url}"
    cached    = cache_get(cache_key)
    if cached:
        return cached
    try:
        driver.get(url)
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    "[class*='card'], article, [class*='listing'], #__NEXT_DATA__"))
            )
        except Exception:
            pass
        time.sleep(2.5)
        driver.execute_script("window.scrollTo(0, 800)")
        time.sleep(1.5)
        html  = driver.page_source
        items = parse_fincaraiz_items(html, operacion)
        print(f"  FincaRaíz: {len(items)} items, URL: {url[:60]}")
        result = {"items": items, "total": len(items), "url": url, "fuente": "fincaraiz"}
        cache_set(cache_key, result)
        return result
    except Exception as e:
        print(f"  FincaRaíz error: {e}")
        return {"items": [], "total": 0, "url": url, "fuente": "fincaraiz", "error": str(e)}
