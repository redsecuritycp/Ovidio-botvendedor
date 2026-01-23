"""
Servicio de Cianbox - Integración con API REST
Maneja autenticación, renovación de tokens y consultas
"""
import os
import time
import requests

# ============================================
# CONFIGURACIÓN
# ============================================
CIANBOX_BASE_URL = 'https://cianbox.org/insumosdeseguridadrosario/api/v2'

# Tokens en memoria
_tokens = {
    'access_token': None,
    'refresh_token': None,
    'expires_at': 0  # Timestamp de cuando vence
}

# ============================================
# AUTENTICACIÓN
# ============================================

def obtener_token():
    """
    Obtiene token nuevo usando CIANBOX_USER y CIANBOX_PASS.
    Se usa al inicio o cuando el refresh_token también venció.
    """
    try:
        user = os.environ.get('CIANBOX_USER')
        password = os.environ.get('CIANBOX_PASS')
        
        if not user or not password:
            print('❌ CIANBOX_USER o CIANBOX_PASS no configurados')
            return None
        
        response = requests.post(
            f'{CIANBOX_BASE_URL}/auth/credentials',
            json={
                'app_name': 'Ovidio Bot',
                'app_code': 'ovidio-bot',
                'user': user,
                'password': password
            },
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'ok':
                body = data.get('body', {})
                _tokens['access_token'] = body.get('access_token')
                _tokens['refresh_token'] = body.get('refresh_token')
                expires_in = body.get('expires_in', 86400)
                _tokens['expires_at'] = time.time() + expires_in - 300
                
                print('✅ Cianbox: Token obtenido correctamente')
                return _tokens['access_token']
        
        print(f'❌ Cianbox: Error obteniendo token - {response.text}')
        return None
        
    except Exception as e:
        print(f'❌ Cianbox: Error de conexión - {e}')
        return None


def renovar_token():
    """
    Renueva el access_token usando el refresh_token.
    Más eficiente que pedir token nuevo con usuario/contraseña.
    """
    try:
        if not _tokens['refresh_token']:
            print('⚠️ Cianbox: No hay refresh_token, pidiendo token nuevo')
            return obtener_token()
        
        response = requests.post(
            f'{CIANBOX_BASE_URL}/auth/refresh',
            json={
                'refresh_token': _tokens['refresh_token']
            },
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'ok':
                body = data.get('body', {})
                _tokens['access_token'] = body.get('access_token')
                _tokens['refresh_token'] = body.get('refresh_token')
                expires_in = body.get('expires_in', 86400)
                _tokens['expires_at'] = time.time() + expires_in - 300
                
                print('✅ Cianbox: Token renovado correctamente')
                return _tokens['access_token']
        
        print('⚠️ Cianbox: Refresh falló, pidiendo token nuevo')
        return obtener_token()
        
    except Exception as e:
        print(f'❌ Cianbox: Error renovando token - {e}')
        return obtener_token()


def get_token():
    """
    Devuelve un token válido.
    - Si no hay token: obtiene uno nuevo
    - Si está vencido: lo renueva con refresh_token
    - Si está vigente: devuelve el actual
    """
    if not _tokens['access_token']:
        return obtener_token()
    
    if time.time() >= _tokens['expires_at']:
        print('⚠️ Cianbox: Token vencido, renovando...')
        return renovar_token()
    
    return _tokens['access_token']


# ============================================
# CONSULTAS A CIANBOX
# ============================================

def _hacer_request(endpoint, params=None):
    """
    Hace una request a Cianbox con manejo automático de token.
    Si el token es inválido, lo renueva y reintenta.
    """
    token = get_token()
    if not token:
        return None
    
    if params is None:
        params = {}
    params['access_token'] = token
    
    try:
        response = requests.get(
            f'{CIANBOX_BASE_URL}/{endpoint}',
            params=params,
            timeout=30
        )
        
        data = response.json()
        
        if data.get('status') == 'error' and 'token' in data.get('message', '').lower():
            print('⚠️ Cianbox: Token inválido, renovando...')
            token = renovar_token()
            if token:
                params['access_token'] = token
                response = requests.get(
                    f'{CIANBOX_BASE_URL}/{endpoint}',
                    params=params,
                    timeout=30
                )
                data = response.json()
        
        if data.get('status') == 'ok':
            return data
        
        print(f'❌ Cianbox: Error en {endpoint} - {data.get("message", "Error desconocido")}')
        return None
        
    except Exception as e:
        print(f'❌ Cianbox: Error de conexión en {endpoint} - {e}')
        return None


def buscar_cliente_por_celular(celular):
    """
    Busca un cliente en Cianbox por número de celular.
    VERIFICA que el celular coincida exactamente antes de devolver.
    
    Args:
        celular: Número de celular (ej: "3415551234" o "5493415551234")
    
    Returns:
        dict con datos del cliente o None si no encuentra
    """
    # Limpiar el número (quitar +, espacios, etc)
    celular_limpio = ''.join(filter(str.isdigit, celular))
    
    # Si viene con código de país 54 y 9, quitarlos
    if celular_limpio.startswith('549'):
        celular_busqueda = celular_limpio[3:]
    elif celular_limpio.startswith('54'):
        celular_busqueda = celular_limpio[2:]
    else:
        celular_busqueda = celular_limpio
    
    print(f'🔍 Cianbox: Buscando cliente con celular {celular_busqueda}')
    
    data = _hacer_request('clientes', {'celular': celular_busqueda})
    
    if data and data.get('body'):
        clientes = data['body']
        
        # Buscar coincidencia EXACTA del celular
        for cliente in clientes:
            celular_cliente = cliente.get('celular', '') or ''
            # Limpiar celular del cliente
            celular_cliente_limpio = ''.join(filter(str.isdigit, celular_cliente))
            
            # Verificar coincidencia exacta (puede estar con o sin código de área)
            if celular_cliente_limpio and (
                celular_cliente_limpio == celular_busqueda or
                celular_cliente_limpio.endswith(celular_busqueda) or
                celular_busqueda.endswith(celular_cliente_limpio)
            ):
                print(f'✅ Cianbox: Cliente encontrado con celular exacto - {cliente.get("razon")}')
                return {
                    'id': cliente.get('id'),
                    'razon_social': cliente.get('razon'),
                    'condicion_iva': cliente.get('condicion'),
                    'cuit': cliente.get('numero_documento'),
                    'domicilio': cliente.get('domicilio'),
                    'localidad': cliente.get('localidad'),
                    'provincia': cliente.get('provincia'),
                    'telefono': cliente.get('telefono'),
                    'celular': cliente.get('celular'),
                    'email': cliente.get('email'),
                    'tiene_cuenta_corriente': cliente.get('ctacte'),
                    'saldo': cliente.get('saldo'),
                    'descuento': cliente.get('descuento'),
                    'listas_precio': cliente.get('listas_precio', [0])
                }
        
        print(f'⚠️ Cianbox: Se encontraron {len(clientes)} clientes pero ninguno con celular exacto {celular_busqueda}')
    
    print(f'⚠️ Cianbox: Cliente no encontrado con celular {celular_busqueda}')
    return None


def buscar_cliente_por_cuit(cuit):
    """
    Busca un cliente en Cianbox por CUIT.
    """
    cuit_limpio = ''.join(filter(str.isdigit, cuit))
    
    print(f'🔍 Cianbox: Buscando cliente con CUIT {cuit_limpio}')
    
    data = _hacer_request('clientes', {'numero_documento': cuit_limpio})
    
    if data and data.get('body'):
        clientes = data['body']
        if len(clientes) > 0:
            cliente = clientes[0]
            print(f'✅ Cianbox: Cliente encontrado - {cliente.get("razon")}')
            return {
                'id': cliente.get('id'),
                'razon_social': cliente.get('razon'),
                'condicion_iva': cliente.get('condicion'),
                'cuit': cliente.get('numero_documento'),
                'domicilio': cliente.get('domicilio'),
                'localidad': cliente.get('localidad'),
                'provincia': cliente.get('provincia'),
                'telefono': cliente.get('telefono'),
                'celular': cliente.get('celular'),
                'email': cliente.get('email'),
                'tiene_cuenta_corriente': cliente.get('ctacte'),
                'saldo': cliente.get('saldo'),
                'descuento': cliente.get('descuento'),
                'listas_precio': cliente.get('listas_precio', [0])
            }
    
    print(f'⚠️ Cianbox: Cliente no encontrado con CUIT {cuit_limpio}')
    return None


def buscar_cliente_por_email(email):
    """
    Busca un cliente en Cianbox por email.
    Útil cuando el celular no está registrado pero el cliente
    tiene cuenta en seguridadrosario.com
    
    Args:
        email: Email del cliente
    
    Returns:
        dict con datos del cliente o None si no encuentra
    """
    email_limpio = email.strip().lower()
    
    print(f'🔍 Cianbox: Buscando cliente con email {email_limpio}')
    
    data = _hacer_request('clientes', {'email': email_limpio})
    
    if data and data.get('body'):
        clientes = data['body']
        if len(clientes) > 0:
            cliente = clientes[0]
            print(f'✅ Cianbox: Cliente encontrado - {cliente.get("razon")}')
            return {
                'id': cliente.get('id'),
                'razon_social': cliente.get('razon'),
                'condicion_iva': cliente.get('condicion'),
                'cuit': cliente.get('numero_documento'),
                'domicilio': cliente.get('domicilio'),
                'localidad': cliente.get('localidad'),
                'provincia': cliente.get('provincia'),
                'telefono': cliente.get('telefono'),
                'celular': cliente.get('celular'),
                'email': cliente.get('email'),
                'tiene_cuenta_corriente': cliente.get('ctacte'),
                'saldo': cliente.get('saldo'),
                'descuento': cliente.get('descuento'),
                'listas_precio': cliente.get('listas_precio', [0])
            }
    
    print(f'⚠️ Cianbox: Cliente no encontrado con email {email_limpio}')
    return None


def obtener_productos(busqueda=None, limite=20):
    """
    Obtiene productos de Cianbox con precios e IVA.
    """
    params = {'limit': limite}
    if busqueda:
        params['q'] = busqueda
    
    print(f'🔍 Cianbox: Buscando productos "{busqueda or "todos"}"')
    
    data = _hacer_request('productos', params)
    
    if data and data.get('body'):
        productos = []
        for p in data['body']:
            productos.append({
                'id': p.get('id'),
                'codigo': p.get('codigo'),
                'nombre': p.get('nombre'),
                'marca': p.get('marca'),
                'categoria': p.get('categoria'),
                'precio': p.get('precio'),
                'precio_con_iva': p.get('precio_final'),
                'iva': p.get('iva'),
                'stock': p.get('stock'),
                'descripcion': p.get('descripcion')
            })
        print(f'✅ Cianbox: {len(productos)} productos encontrados')
        return productos
    
    print('⚠️ Cianbox: No se encontraron productos')
    return []


def obtener_cotizacion():
    """
    Obtiene la cotización actual USD/ARS de Cianbox.
    """
    data = _hacer_request('general/cotizaciones')
    
    if data and data.get('body'):
        cotizaciones = data['body']
        if len(cotizaciones) > 0:
            cot = cotizaciones[0]
            print(f'✅ Cianbox: Cotización USD = ${cot.get("valor")}')
            return {
                'moneda': cot.get('moneda'),
                'valor': cot.get('valor')
            }
    
    return None


def inicializar_cianbox():
    """
    Inicializa la conexión con Cianbox al arrancar el servidor.
    """
    print('🔄 Cianbox: Inicializando conexión...')
    token = obtener_token()
    if token:
        print('✅ Cianbox: Conexión establecida')
        return True
    else:
        print('❌ Cianbox: No se pudo conectar')
        return False
