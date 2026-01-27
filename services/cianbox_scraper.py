"""
Servicio de Scraping Cianbox - Obtiene productos del panel web
Mismo método que usa isr-web (login + cookies + parseo HTML)
"""
import os
import time
import requests
from bs4 import BeautifulSoup

# ============================================
# CONFIGURACIÓN
# ============================================
CIANBOX_URL = 'https://cianbox.org/insumosdeseguridadrosario'

# Sesión en memoria
_session = {
    'cookies': None,
    'last_login': 0
}

# ============================================
# AUTENTICACIÓN (Login al panel web)
# ============================================

def cianbox_login():
    """
    Login al panel web de Cianbox (NO la API REST).
    Guarda las cookies de sesión.
    """
    try:
        user = os.environ.get('CIANBOX_USER')
        password = os.environ.get('CIANBOX_PASS')
        
        if not user or not password:
            print('❌ Scraper: CIANBOX_USER o CIANBOX_PASS no configurados')
            return False
        
        login_url = f'{CIANBOX_URL}/login.php'
        
        session = requests.Session()
        response = session.post(
            login_url,
            data={
                'usuario': user,
                'clave': password
            },
            headers={
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            allow_redirects=False,
            timeout=30
        )
        
        # Guardar cookies si el login fue exitoso
        if response.cookies or response.status_code in [200, 302]:
            _session['cookies'] = session.cookies
            _session['last_login'] = time.time()
            print('✅ Scraper: Login Cianbox exitoso')
            return True
        
        print(f'❌ Scraper: Login falló - Status {response.status_code}')
        return False
        
    except Exception as e:
        print(f'❌ Scraper: Error de conexión - {e}')
        return False


def ensure_login():
    """
    Asegura que haya una sesión válida.
    Renueva si pasaron más de 30 minutos.
    """
    THIRTY_MIN = 30 * 60
    
    if not _session['cookies'] or (time.time() - _session['last_login']) > THIRTY_MIN:
        return cianbox_login()
    
    return True


def cianbox_post(sec, extra_params=None):
    """
    Hace POST al panel de Cianbox y devuelve el HTML.
    """
    if not ensure_login():
        return None
    
    if not _session['cookies']:
        print('❌ Scraper: No hay sesión activa')
        return None
    
    params = {
        'sec': sec,
        'userid': '20',
        'userlevel': '1',
        'id_equipo': '0',
        'tipo_a': 'modulo'
    }
    
    if extra_params:
        params.update(extra_params)
    
    try:
        response = requests.post(
            f'{CIANBOX_URL}/content.php',
            data=params,
            cookies=_session['cookies'],
            headers={
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            timeout=60
        )
        
        if response.status_code == 200:
            return response.text
        
        print(f'❌ Scraper: Error en POST - Status {response.status_code}')
        return None
        
    except Exception as e:
        print(f'❌ Scraper: Error de conexión - {e}')
        return None


# ============================================
# OBTENER PRODUCTOS
# ============================================

def parsear_precio(texto):
    """Convierte string de precio a float"""
    if not texto:
        return 0
    try:
        limpio = texto.replace('u$s', '').replace('u$S', '').replace('$', '')
        limpio = limpio.replace('.', '').replace(',', '.').strip()
        return float(limpio) or 0
    except:
        return 0


def obtener_productos_scraping(busqueda=None):
    """
    Obtiene productos del panel web de Cianbox mediante scraping.
    
    Args:
        busqueda: Término de búsqueda (opcional)
    
    Returns:
        Lista de productos con: codigo, nombre, marca, precio, stock, iva
    """
    print(f'🔎 Scraper: Obteniendo productos...', flush=True)
    
    html = cianbox_post('pv_productos')
    
    if not html:
        print('❌ Scraper: No se pudo obtener HTML')
        return []
    
    soup = BeautifulSoup(html, 'html.parser')
    productos = []
    
    for row in soup.find_all('tr'):
        cols = row.find_all('td')
        
        if len(cols) >= 8:
            textos = [col.get_text(strip=True) for col in cols]
            
            marca = textos[0]
            codigo = textos[1]
            descripcion = textos[2]
            stock_total = textos[3]
            final_iva_str = textos[6]
            neto_str = textos[7]
            
            neto = parsear_precio(neto_str)
            final_iva = parsear_precio(final_iva_str)
            
            # Calcular IVA
            iva_percent = 21
            if neto > 0 and final_iva > neto:
                iva_percent = round(((final_iva - neto) / neto) * 100, 1)
            
            if codigo and len(codigo) > 2:
                productos.append({
                    'codigo': codigo,
                    'nombre': descripcion[:80] if descripcion else codigo,
                    'marca': marca,
                    'precio': neto,
                    'precio_final': final_iva,
                    'stock': int(stock_total) if stock_total.isdigit() else 0,
                    'iva': iva_percent
                })
    
    print(f'✅ Scraper: {len(productos)} productos obtenidos', flush=True)
    
    # Filtrar por búsqueda si se especificó
    if busqueda and productos:
        busqueda_lower = busqueda.lower()
        productos_filtrados = [
            p for p in productos
            if busqueda_lower in p['nombre'].lower() 
            or busqueda_lower in p['codigo'].lower()
            or busqueda_lower in p['marca'].lower()
        ]
        print(f'🔎 Scraper: {len(productos_filtrados)} coinciden con "{busqueda}"', flush=True)
        return productos_filtrados[:10]
    
    return productos


def buscar_producto(termino):
    """
    Busca productos por término.
    Wrapper simple para usar desde main.py
    """
    return obtener_productos_scraping(termino)


def inicializar_scraper():
    """
    Inicializa el scraper al arrancar el servidor.
    """
    print('🔄 Scraper: Inicializando...')
    if cianbox_login():
        print('✅ Scraper: Listo')
        return True
    else:
        print('❌ Scraper: No se pudo inicializar')
        return False
