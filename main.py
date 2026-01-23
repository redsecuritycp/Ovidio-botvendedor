import os
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify
from pymongo import MongoClient
from datetime import datetime
import requests
from openai import OpenAI
from services.cianbox_service import inicializar_cianbox, buscar_cliente_por_celular, buscar_cliente_por_cuit, buscar_cliente_por_email

app = Flask(__name__)

# ============================================
# CONFIGURACIÓN
# ============================================
client_openai = None

def get_openai_client():
    global client_openai
    if client_openai is None:
        api_key = os.environ.get('OPENAI_API_KEY')
        if api_key:
            try:
                client_openai = OpenAI(api_key=api_key)
            except Exception as e:
                print(f'⚠️ Error inicializando OpenAI client: {e}')
                return None
    return client_openai

# Control de mensajes procesados (evita duplicados)
processed_messages = set()

# ============================================
# MONGODB
# ============================================
mongo_client = None
db = None

def conectar_mongodb():
    global mongo_client, db
    try:
        mongo_client = MongoClient(os.environ.get('MONGODB_URI'))
        db = mongo_client['ovidio_db']
        print('✅ MongoDB conectado')
        return db
    except Exception as e:
        print(f'❌ Error MongoDB: {e}')
        return None

# ============================================
# DICCIONARIOS DE BÚSQUEDA INTELIGENTE
# ============================================

# Corrección de marcas (errores comunes → marca correcta)
MARCAS_CORRECCION = {
    'dahau': 'dahua', 'daua': 'dahua', 'dahuaa': 'dahua', 'dahu': 'dahua',
    'dahuwa': 'dahua', 'dauha': 'dahua',
    'hikvisión': 'hikvision', 'hikvicion': 'hikvision', 'hik': 'hikvision',
    'hikvison': 'hikvision', 'hikivision': 'hikvision', 'hikvission': 'hikvision',
    'hivision': 'hikvision', 'hkvision': 'hikvision', 'hikvi': 'hikvision',
    'ayax': 'ajax', 'ajaz': 'ajax', 'ajaks': 'ajax',
    'imuo': 'imou', 'imu': 'imou', 'imo': 'imou',
    'esbis': 'ezviz', 'ezvis': 'ezviz', 'esviz': 'ezviz', 'ezvs': 'ezviz',
    'dcs': 'dsc'
}

MARCAS_VALIDAS = ['dahua', 'hikvision', 'ajax', 'imou', 'ezviz', 'dsc', 'epcom', 'provision', 'honeywell']

# Sinónimos de tipos de producto
SINONIMOS_PRODUCTO = {
    'camara': ['camara', 'cámara', 'camera', 'cam', 'camra', 'cámra'],
    'bullet': ['bullet', 'tubo', 'cilindrica', 'cilíndrica', 'bala', 'tubular'],
    'domo': ['domo', 'dome', 'cupula', 'cúpula', 'redonda', 'techo'],
    'ptz': ['ptz', 'motorizada', 'robotica', 'robótica', 'movimiento'],
    'dvr': ['dvr', 'grabador', 'grabadora', 'videograbador'],
    'nvr': ['nvr', 'grabador ip', 'grabador de red'],
    'disco': ['disco', 'hdd', 'disco rigido', 'disco rígido', 'disco duro', 'rigido', 'rígido'],
    'alarma': ['alarma', 'panel', 'central'],
    'switch': ['switch', 'poe', 'switch poe'],
    'fuente': ['fuente', 'transformador', 'alimentador', 'power']
}

# Sinónimos de características
SINONIMOS_CARACTERISTICAS = {
    'exterior': ['exterior', 'afuera', 'outdoor', 'intemperie', 'externo', 'ip67', 'ip66'],
    'interior': ['interior', 'adentro', 'indoor', 'interno'],
    'wifi': ['wifi', 'inalambrica', 'inalámbrica', 'wireless', 'sin cable'],
    'poe': ['poe', 'power over ethernet'],
    'audio': ['audio', 'microfono', 'micrófono', 'sonido', 'con audio'],
    'color': ['color', 'full color', 'colorvu', 'color vu', 'color de noche']
}

# ============================================
# FUNCIONES DE BÚSQUEDA INTELIGENTE
# ============================================

def normalizar_texto(texto):
    import unicodedata
    normalizado = texto.lower()
    normalizado = unicodedata.normalize('NFD', normalizado)
    normalizado = ''.join(c for c in normalizado if unicodedata.category(c) != 'Mn')
    normalizado = re.sub(r'[^\w\s]', ' ', normalizado)
    normalizado = re.sub(r'\s+', ' ', normalizado).strip()
    return normalizado

def calcular_similaridad(str1, str2):
    if str1 == str2:
        return 1
    if len(str1) < 2 or len(str2) < 2:
        return 0
    bigrams1 = set(str1[i:i+2] for i in range(len(str1) - 1))
    matches = sum(1 for i in range(len(str2) - 1) if str2[i:i+2] in bigrams1)
    return (2 * matches) / (len(str1) + len(str2) - 2)

def detectar_marca(texto):
    normalizado = normalizar_texto(texto)
    palabras = normalizado.split()
    for palabra in palabras:
        if palabra in MARCAS_VALIDAS:
            return palabra
        if palabra in MARCAS_CORRECCION:
            return MARCAS_CORRECCION[palabra]
        for marca in MARCAS_VALIDAS:
            if calcular_similaridad(palabra, marca) > 0.7:
                return marca
    return None

def detectar_tipo_producto(texto):
    normalizado = normalizar_texto(texto)
    for tipo, sinonimos in SINONIMOS_PRODUCTO.items():
        for sinonimo in sinonimos:
            if sinonimo in normalizado:
                return tipo
    return None

def detectar_caracteristicas(texto):
    normalizado = normalizar_texto(texto)
    caracteristicas = []
    for caracteristica, sinonimos in SINONIMOS_CARACTERISTICAS.items():
        for sinonimo in sinonimos:
            if sinonimo in normalizado:
                caracteristicas.append(caracteristica)
                break
    return caracteristicas

def detectar_resolucion(texto):
    normalizado = normalizar_texto(texto)
    patrones = [
        (r'(\d+)\s*(?:mega|mp|megapixel)', 1),
        (r'1080p?', '2'),
        (r'2k', '4'),
        (r'4k', '8'),
        (r'full\s*hd', '2')
    ]
    for patron, resultado in patrones:
        match = re.search(patron, normalizado)
        if match:
            if isinstance(resultado, int):
                return match.group(resultado)
            return resultado
    return None

def detectar_canales(texto):
    normalizado = normalizar_texto(texto)
    match = re.search(r'(\d+)\s*(?:canales|ch|channels|camaras|cámaras)', normalizado)
    if match:
        return match.group(1)
    return None

def buscar_en_api(termino):
    try:
        api_base = os.environ.get('API_BASE_URL')
        if not api_base:
            print('❌ API_BASE_URL no configurada')
            return []
        response = requests.get(api_base, params={
            'Producto': termino,
            'CategoriaId': 0,
            'MarcaId': 0,
            'OrdenId': 2,
            'SucursalId': 2,
            'Oferta': 'false'
        }, timeout=10)
        data = response.json()
        if data and 'producto' in data:
            return [{
                'nombre': p.get('producto', ''),
                'codigo': p.get('codigoInterno', ''),
                'stock': int(p.get('disponible', 0)),
                'precio_usd': float(p.get('precioUSD', 0)),
                'precio_ars': float(p.get('precioARS', 0)),
                'marca': p.get('marca', ''),
                'categoria': p.get('categoria', ''),
                'descripcion': p.get('descripcion', '')
            } for p in data['producto']]
        return []
    except Exception as e:
        print(f'❌ Error buscando "{termino}": {e}')
        return []

def buscar_inteligente(texto_cliente):
    print(f'\n🧠 ========== BÚSQUEDA INTELIGENTE ==========')
    print(f'📝 Texto original: "{texto_cliente}"')
    
    marca = detectar_marca(texto_cliente)
    tipo = detectar_tipo_producto(texto_cliente)
    caracteristicas = detectar_caracteristicas(texto_cliente)
    resolucion = detectar_resolucion(texto_cliente)
    canales = detectar_canales(texto_cliente)
    
    print(f'🏷️ Marca detectada: {marca or "ninguna"}')
    print(f'📦 Tipo producto: {tipo or "ninguno"}')
    print(f'⚙️ Características: {", ".join(caracteristicas) if caracteristicas else "ninguna"}')
    print(f'📊 Resolución: {resolucion + "MP" if resolucion else "no especificada"}')
    print(f'📺 Canales: {canales or "no especificados"}')
    
    productos = []
    termino_busqueda = ''
    
    if marca:
        termino_busqueda = marca
        productos = buscar_en_api(marca)
        print(f'🔍 Búsqueda por marca "{marca}": {len(productos)} resultados')
    
    if not productos and tipo:
        termino_busqueda = tipo
        productos = buscar_en_api(tipo)
        print(f'🔍 Búsqueda por tipo "{tipo}": {len(productos)} resultados')
    
    if not productos:
        palabras = [p for p in normalizar_texto(texto_cliente).split() if len(p) > 3]
        palabras.sort(key=len, reverse=True)
        for palabra in palabras[:3]:
            productos = buscar_en_api(palabra)
            if productos:
                termino_busqueda = palabra
                print(f'🔍 Búsqueda por palabra "{palabra}": {len(productos)} resultados')
                break
    
    if not productos:
        print('❌ No se encontraron productos')
        return {'encontrado': False, 'busqueda': texto_cliente}
    
    filtrados = productos
    
    if marca and len(filtrados) > 5:
        por_marca = [p for p in filtrados if marca in p['nombre'].lower() or marca in p['marca'].lower()]
        if por_marca:
            filtrados = por_marca
            print(f'✂️ Filtrado por marca: {len(filtrados)} productos')
    
    if resolucion and len(filtrados) > 1:
        por_res = [p for p in filtrados if f'{resolucion}mp' in p['nombre'].lower() or f'{resolucion} mp' in p['nombre'].lower()]
        if por_res:
            filtrados = por_res
            print(f'✂️ Filtrado por resolución {resolucion}MP: {len(filtrados)} productos')
    
    if tipo and tipo in ['bullet', 'domo', 'ptz'] and len(filtrados) > 1:
        por_tipo = [p for p in filtrados if tipo in p['nombre'].lower()]
        if por_tipo:
            filtrados = por_tipo
            print(f'✂️ Filtrado por tipo {tipo}: {len(filtrados)} productos')
    
    for caract in caracteristicas:
        if len(filtrados) > 1:
            if caract == 'exterior':
                por_caract = [p for p in filtrados if any(x in p['nombre'].lower() for x in ['ip67', 'ip66', 'exterior', 'outdoor', 'bullet'])]
            elif caract == 'wifi':
                por_caract = [p for p in filtrados if 'wifi' in p['nombre'].lower() or 'wireless' in p['nombre'].lower()]
            elif caract == 'audio':
                por_caract = [p for p in filtrados if 'audio' in p['nombre'].lower()]
            elif caract == 'color':
                por_caract = [p for p in filtrados if 'color' in p['nombre'].lower()]
            else:
                por_caract = [p for p in filtrados if caract in p['nombre'].lower()]
            if por_caract:
                filtrados = por_caract
                print(f'✂️ Filtrado por {caract}: {len(filtrados)} productos')
    
    if canales and len(filtrados) > 1:
        por_canales = [p for p in filtrados if f'{canales} canales' in p['nombre'].lower() or f'{canales}ch' in p['nombre'].lower()]
        if por_canales:
            filtrados = por_canales
            print(f'✂️ Filtrado por {canales} canales: {len(filtrados)} productos')
    
    filtrados.sort(key=lambda x: x['stock'] > 0, reverse=True)
    
    print(f'✅ Resultado final: {len(filtrados)} productos')
    print('🧠 ==========================================\n')
    
    if len(filtrados) > 1:
        return {
            'encontrado': True,
            'multiple': True,
            'cantidad': len(filtrados),
            'busqueda': termino_busqueda,
            'opciones': [{
                'nombre': p['nombre'],
                'codigo': p['codigo'],
                'stock': p['stock'],
                'precio_usd': p['precio_usd'],
                'precio_ars': p['precio_ars'],
                'marca': p['marca'],
                'disponible': p['stock'] > 0
            } for p in filtrados[:5]]
        }
    
    producto = filtrados[0]
    return {
        'encontrado': True,
        'multiple': False,
        'nombre': producto['nombre'],
        'codigo': producto['codigo'],
        'stock': producto['stock'],
        'precio_usd': producto['precio_usd'],
        'precio_ars': producto['precio_ars'],
        'marca': producto['marca'],
        'categoria': producto['categoria'],
        'disponible': producto['stock'] > 0
    }

def buscar_alternativas(categoria, marca):
    try:
        resultado = buscar_inteligente(categoria)
        if resultado.get('encontrado') and resultado.get('multiple'):
            return [p for p in resultado['opciones'] if p['disponible']]
        return []
    except Exception as e:
        print(f'❌ Error buscando alternativas: {e}')
        return []

# ============================================
# EXTRACTOR DE PRODUCTOS (GPT-4o-mini)
# ============================================

def extraer_producto(mensaje, historial_conversacion=None):
    try:
        client = get_openai_client()
        if not client:
            print('⚠️ OpenAI client no disponible')
            return ''
        
        contexto_conversacion = ''
        if historial_conversacion:
            ultimos = historial_conversacion[-6:]
            contexto_conversacion = '\n'.join([
                f"{'Cliente' if m['rol'] == 'usuario' else 'Ovidio'}: {m['contenido']}"
                for m in ultimos
            ])
        
        response = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {
                    'role': 'system',
                    'content': f'''Extraés términos de búsqueda de productos de seguridad electrónica.

CONTEXTO DE LA CONVERSACIÓN:
{contexto_conversacion or '(Primera interacción)'}

REGLAS:
1. Si mencionan producto directo: "cámara IP" → "cámara IP"
2. Si dan características después de que Ovidio preguntó:
   - "exterior, 2mp, dahua" (hablaban de cámaras) → "cámara dahua 2mp"
   - "4 canales, hikvision" (hablaban de DVR) → "dvr hikvision 4"
3. SIEMPRE incluí marca si la mencionan
4. SIEMPRE incluí características técnicas (2mp, 4mp, exterior, etc)
5. Saludos sin producto → ""

Respondé SOLO con los términos de búsqueda.'''
                },
                {'role': 'user', 'content': mensaje}
            ],
            temperature=0.3,
            max_tokens=100
        )
        
        producto = response.choices[0].message.content.strip()
        if producto in ['""', "''", '(ninguno)', 'ninguno']:
            producto = ''
        producto = producto.strip('"\'')
        
        print(f'🔍 Mensaje original: "{mensaje}"')
        print(f'📦 Producto extraído: "{producto}"')
        
        return producto
    except Exception as e:
        print(f'❌ Error extrayendo producto: {e}')
        return ''

# ============================================
# EXTRACCIÓN DE DATOS DEL CLIENTE
# ============================================

def extraer_datos_cliente(mensaje, cliente):
    texto = mensaje.lower()
    datos_actualizados = False
    
    cuit_match = re.search(r'\b(\d{2})[-\s]?(\d{8})[-\s]?(\d{1})\b', mensaje)
    if cuit_match and not cliente.get('cuit'):
        cliente['cuit'] = f"{cuit_match.group(1)}-{cuit_match.group(2)}-{cuit_match.group(3)}"
        print(f'💼 CUIT guardado: {cliente["cuit"]}')
        datos_actualizados = True
    
    razon_patterns = [
        r'raz[oó]n\s*social[:\s]+([^,\n]+)',
        r'empresa[:\s]+([^,\n]+)',
        r'\b([A-Z][a-zA-Z\s]+(S\.?R\.?L\.?|S\.?A\.?|S\.?A\.?S\.?))\b'
    ]
    for pattern in razon_patterns:
        match = re.search(pattern, mensaje, re.IGNORECASE)
        if match and not cliente.get('razon_social'):
            cliente['razon_social'] = match.group(1).strip()
            print(f'🏢 Razón Social guardada: {cliente["razon_social"]}')
            datos_actualizados = True
            break
    
    pago_patterns = [
        r'forma\s*de\s*pago[:\s]+([^,\n]+)',
        r'pago[:\s]+(efectivo|transferencia|cheque[s]?|contado|tarjeta)',
        r'(contado|efectivo|transferencia|tarjeta)'
    ]
    for pattern in pago_patterns:
        match = re.search(pattern, mensaje, re.IGNORECASE)
        if match and not cliente.get('forma_pago'):
            cliente['forma_pago'] = match.group(1).strip()
            print(f'💳 Forma de pago guardada: {cliente["forma_pago"]}')
            datos_actualizados = True
            break
    
    email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', mensaje)
    if email_match:
        email_encontrado = email_match.group(0).lower()
        
        # Si el cliente no tiene id_cianbox, intentar vincular por email
        if not cliente.get('id_cianbox'):
            print(f'📧 Email detectado: {email_encontrado}, buscando en Cianbox...')
            cliente_cianbox = buscar_cliente_por_email(email_encontrado)
            
            if cliente_cianbox:
                print(f'✅ Cliente vinculado por email: {cliente_cianbox.get("razon_social")}')
                if db:
                    db['clientes'].update_one(
                        {'telefono': cliente.get('telefono')},
                        {'$set': {
                            'email': email_encontrado,
                            'cuit': cliente_cianbox.get('cuit', '') or cliente.get('cuit', ''),
                            'razon_social': cliente_cianbox.get('razon_social', '') or cliente.get('razon_social', ''),
                            'ubicacion': f"{cliente_cianbox.get('localidad', '')}, {cliente_cianbox.get('provincia', '')}" or cliente.get('ubicacion', ''),
                            'condicion_iva': cliente_cianbox.get('condicion_iva', ''),
                            'domicilio': cliente_cianbox.get('domicilio', ''),
                            'saldo_cianbox': cliente_cianbox.get('saldo', 0),
                            'id_cianbox': cliente_cianbox.get('id'),
                            'estado': 'cianbox',
                            'actualizado': datetime.utcnow()
                        }}
                    )
                datos_actualizados = True
        
        # Guardar email si no lo tenía
        if not cliente.get('email'):
            if db:
                db['clientes'].update_one(
                    {'telefono': cliente.get('telefono')},
                    {'$set': {'email': email_encontrado, 'actualizado': datetime.utcnow()}}
                )
            datos_actualizados = True
    
    rubro_patterns = [
        r'(?:me\s+dedico\s+a|trabajo\s+(?:en|con)|soy|rubro)[:\s]+([^,\n]+)',
        r'(instalador|integrador|electricista|técnico|comercio|mayorista|minorista)'
    ]
    for pattern in rubro_patterns:
        match = re.search(pattern, mensaje, re.IGNORECASE)
        if match and not cliente.get('rubro'):
            cliente['rubro'] = match.group(1).strip()
            print(f'🔧 Rubro guardado: {cliente["rubro"]}')
            datos_actualizados = True
            break
    
    ubicacion_patterns = [
        r'(?:soy\s+de|estoy\s+en|ubicad[oa]\s+en|ciudad)[:\s]+([^,\n]+)',
        r'(rosario|buenos aires|córdoba|mendoza|santa fe|tucumán)'
    ]
    for pattern in ubicacion_patterns:
        match = re.search(pattern, mensaje, re.IGNORECASE)
        if match and not cliente.get('ubicacion'):
            cliente['ubicacion'] = (match.group(1) if match.lastindex else match.group(0)).strip()
            print(f'📍 Ubicación guardada: {cliente["ubicacion"]}')
            datos_actualizados = True
            break
    
    marcas = ['hikvision', 'dahua', 'ajax', 'dsc', 'imou', 'ezviz', 'honeywell', 'epcom']
    marcas_encontradas = [m for m in marcas if m in texto]
    if marcas_encontradas and not cliente.get('marcas_preferidas'):
        cliente['marcas_preferidas'] = ', '.join(marcas_encontradas)
        print(f'🏷️ Marcas preferidas: {cliente["marcas_preferidas"]}')
        datos_actualizados = True
    
    return datos_actualizados

# ============================================
# SERVICIO DE EMAIL
# ============================================

def enviar_email(asunto, html, destinatario=None):
    try:
        email_user = os.environ.get('EMAIL_USER')
        email_pass = os.environ.get('EMAIL_PASS')
        
        if not email_user or not email_pass:
            print('⚠️ EMAIL_USER o EMAIL_PASS no configurados')
            return False
        
        dest = destinatario or email_user
        
        msg = MIMEMultipart('alternative')
        msg['Subject'] = asunto
        msg['From'] = email_user
        msg['To'] = dest
        msg.attach(MIMEText(html, 'html'))
        
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(email_user, email_pass)
            server.sendmail(email_user, dest, msg.as_string())
        
        print(f'📧 Email enviado: {asunto}')
        return True
    except Exception as e:
        print(f'❌ Error enviando email: {e}')
        return False

def notificar_sin_stock(producto, cliente, historial):
    asunto = f'⚠️ SIN STOCK - {producto}'
    
    historial_html = '<br>'.join([
        f"<b>{'Cliente' if m['rol'] == 'usuario' else 'Ovidio'}:</b> {m['contenido']}"
        for m in historial[-10:]
    ]) if historial else 'Sin historial'
    
    html = f'''
    <h2>Producto Sin Stock - Sin Alternativas</h2>
    <p><strong>Producto solicitado:</strong> {producto}</p>
    <hr>
    <h3>Datos del Cliente</h3>
    <p><strong>Nombre:</strong> {cliente.get('nombre', 'No proporcionado')}</p>
    <p><strong>Teléfono:</strong> {cliente.get('telefono', 'No proporcionado')}</p>
    <p><strong>CUIT:</strong> {cliente.get('cuit', 'No proporcionado')}</p>
    <p><strong>Razón Social:</strong> {cliente.get('razon_social', 'No proporcionada')}</p>
    <p><strong>Email:</strong> {cliente.get('email', 'No proporcionado')}</p>
    <p><strong>Rubro:</strong> {cliente.get('rubro', 'No especificado')}</p>
    <hr>
    <h3>Historial de Conversación</h3>
    <p>{historial_html}</p>
    <hr>
    <p><em>Consultar disponibilidad, precio y demora con proveedores.</em></p>
    '''
    
    return enviar_email(asunto, html)

# ============================================
# SERVICIO DE IA (OpenAI GPT-4)
# ============================================

def generar_respuesta(mensaje_usuario, historial, contexto_stock, cliente):
    max_reintentos = 3
    ultimo_error = None
    
    for intento in range(1, max_reintentos + 1):
        try:
            # Determinar tipo de saludo según contexto
            es_cliente_nuevo = cliente.get('estado') == 'nuevo'
            fecha_hoy = datetime.utcnow().date()
            
            # Verificar si es el primer mensaje del día
            es_primer_mensaje_del_dia = True
            if historial and len(historial) > 0:
                ultimo_msg = historial[-1]
                fecha_ultimo = ultimo_msg.get('fecha')
                if fecha_ultimo and hasattr(fecha_ultimo, 'date'):
                    es_primer_mensaje_del_dia = fecha_ultimo.date() < fecha_hoy
            
            # Instrucciones de saludo según contexto
            if es_cliente_nuevo and (not historial or len(historial) <= 2):
                instruccion_saludo = f'''SALUDO INICIAL (primera vez que habla este cliente):
Presentate UNA SOLA VEZ así: "¡Hola {cliente.get('nombre', 'Cliente')}! Soy Ovidio, asesor comercial de GRUPO SER. ¿En qué puedo asistirte?"
Después de este primer mensaje, NUNCA más te presentes con nombre completo.'''
            elif es_primer_mensaje_del_dia:
                instruccion_saludo = f'''SALUDO NUEVO DÍA (cliente que ya te conoce):
Saludá casual: "¡Hola {cliente.get('nombre', 'Cliente')}! ¿En qué puedo ayudarte hoy?"
NO te presentes, ya te conoce.'''
            else:
                instruccion_saludo = '''CONVERSACIÓN EN CURSO (mismo día):
NO saludes, continuá la conversación directamente. Ya hablaron hoy.'''
            
            system_prompt = f'''Sos OVIDIO, asesor comercial EXPERTO de GRUPO SER, empresa de seguridad electrónica en Rosario.

=== PERSONALIDAD ===
- Cordial y cercano, evitando excesos de formalidad
- Disponible 24/7, respondés a la brevedad
- Empático: recordás gustos, fechas importantes, intereses del cliente
- Concreto y claro: identificás rápido la necesidad y ofrecés soluciones ágiles
- Español rioplatense SIN usar "che"

{instruccion_saludo}

=== REGLAS DE CONVERSACIÓN ===
1. Si el cliente no responde a alguna pregunta, CONTINUÁ sin insistir ni ser repetitivo
2. NUNCA repitas preguntas que ya hiciste o datos que ya tenés
3. Recordá el historial de conversaciones y compras previas
4. Adaptá la interacción según el perfil y comportamiento del cliente

=== CONOCIMIENTO TÉCNICO ===
- CÁMARAS: 2MP=1080p, 4MP=2K, 8MP=4K. Bullet=exterior, Domo=interior. ColorVu=color de noche.
- MARCAS: Hikvision=premium, Dahua=calidad/precio, Ajax=alarmas inalámbricas premium, DSC=alarmas cableadas
- DVR/NVR: DVR=analógicas (coaxial), NVR=IP (red). XVR=híbrido. 1TB=7 días con 4 cámaras 2MP.
- DISCOS: WD Purple=videovigilancia, SSD=más rápido pero más caro.
- Conocés TODO el stock y las fichas técnicas de los productos para ofrecer alternativas

=== FLUJO DE VENTA ===
1. Identificar necesidad del cliente rápidamente
2. Ofrecer productos específicos con PRECIOS y STOCK real
3. Si hay intención de compra → Presupuesto INMEDIATO
4. Acompañar hasta confirmación, despejar dudas
5. Usar descuentos si es necesario para cerrar la venta
6. Ofrecer TODAS las alternativas de pago disponibles

=== CUANDO NO HAY STOCK ===
1. Sugerir alternativas equivalentes
2. Si no hay alternativa → Comprometerse a consultar con Compras
3. Mantener informado al cliente del seguimiento
4. (El sistema enviará email automático a Compras con los datos)

=== DATOS A RECOPILAR (de forma gradual y no invasiva) ===
Para clientes nuevos, ir preguntando naturalmente:
- Email de registro en seguridadrosario.com (para vincular cuenta)
- Rubro: ¿conectividad, alarmas, cámaras, etc.?
- Marcas que usa actualmente
- Proveedores habituales (para posicionarnos como opción principal)
- CUIT (explicar: "solo para presupuesto formal, no facturación inmediata")
- Ubicación geográfica
- Preferencia de pago: facturado, transferencia, cheque, financiación
- Opcional: gustos personales, cumpleaños (para fidelización)

=== DATOS DEL CLIENTE (YA GUARDADOS) ===
Nombre: {cliente.get('nombre', 'Cliente')}
Teléfono: {cliente.get('telefono', '')}
Email: {cliente.get('email', 'No proporcionado')}
CUIT: {cliente.get('cuit', 'No proporcionado')}
Razón Social: {cliente.get('razon_social', 'No proporcionada')}
Condición IVA: {cliente.get('condicion_iva', '')}
Forma de pago: {cliente.get('forma_pago', 'No especificada')}
Rubro: {cliente.get('rubro', '')}
Ubicación: {cliente.get('ubicacion', '')}
Marcas preferidas: {cliente.get('marcas_preferidas', '')}
Estado: {cliente.get('estado', 'nuevo')}
Saldo en cuenta: {cliente.get('saldo_cianbox', 0)}

Si el cliente YA proporcionó algún dato, NO lo vuelvas a pedir. Usá los datos guardados.
Si es cliente NUEVO sin email, pedile amablemente el email de registro en seguridadrosario.com para vincular su cuenta.

=== STOCK DISPONIBLE ===
{contexto_stock or 'Consultá stock cuando el cliente pida productos específicos.'}

=== REGLAS FINALES ===
- Precios incluyen IVA
- Horario atención humana: Lun-Vie 8-17hs (pero vos atendés 24/7)
- Ser proactivo: ofrecer promociones, capacitaciones gratuitas si el cliente acepta
- Objetivo: fidelizar al cliente y posicionarnos como su proveedor principal'''

            messages = [{'role': 'system', 'content': system_prompt}]
            
            if historial:
                for msg in historial[-8:]:
                    messages.append({
                        'role': 'user' if msg['rol'] == 'usuario' else 'assistant',
                        'content': msg['contenido']
                    })
            
            messages.append({'role': 'user', 'content': mensaje_usuario})
            
            print(f'🤖 Llamando a OpenAI (intento {intento}/{max_reintentos})...')
            
            client = get_openai_client()
            if not client:
                print('⚠️ OpenAI client no disponible')
                return 'Disculpá, el servicio de IA no está disponible en este momento.'
            
            response = client.chat.completions.create(
                model='gpt-4',
                messages=messages,
                temperature=0.7,
                max_tokens=1000
            )
            
            print('✅ OpenAI respondió')
            return response.choices[0].message.content
            
        except Exception as e:
            ultimo_error = e
            print(f'❌ Intento {intento}/{max_reintentos} falló: {e}')
            if intento < max_reintentos:
                import time
                time.sleep(intento * 3)
    
    print(f'❌ Todos los intentos fallaron: {ultimo_error}')
    return 'Disculpá, tuve un problema técnico. ¿Podés repetirme tu consulta?'

# ============================================
# SERVICIO DE WHATSAPP
# ============================================

def enviar_mensaje_whatsapp(destinatario, texto):
    try:
        url = f"https://graph.facebook.com/v21.0/{os.environ.get('PHONE_NUMBER_ID')}/messages"
        
        response = requests.post(url, 
            headers={
                'Authorization': f"Bearer {os.environ.get('WHATSAPP_TOKEN')}",
                'Content-Type': 'application/json'
            },
            json={
                'messaging_product': 'whatsapp',
                'to': destinatario,
                'type': 'text',
                'text': {'body': texto}
            }
        )
        
        print(f'✅ Mensaje enviado a {destinatario}')
        return response.json()
    except Exception as e:
        print(f'❌ Error enviando mensaje: {e}')
        return None

# ============================================
# WEBHOOK Y PROCESAMIENTO
# ============================================

@app.route('/webhook', methods=['GET'])
def verificar_webhook():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    
    if mode == 'subscribe' and token == os.environ.get('WHATSAPP_VERIFY_TOKEN'):
        print('✅ Webhook verificado')
        return challenge, 200
    return 'Error', 403

@app.route('/webhook', methods=['POST'])
def recibir_mensaje():
    try:
        body = request.get_json()
        
        if body.get('object') == 'whatsapp_business_account':
            entry = body.get('entry', [{}])[0]
            changes = entry.get('changes', [{}])[0]
            value = changes.get('value', {})
            
            if 'messages' in value:
                mensaje = value['messages'][0]
                mensaje_id = mensaje.get('id')
                
                if mensaje_id in processed_messages:
                    print(f'⚠️ Mensaje {mensaje_id} ya procesado, ignorando duplicado')
                    return jsonify({'status': 'ok'}), 200
                
                processed_messages.add(mensaje_id)
                
                remitente = mensaje.get('from')
                texto = mensaje.get('text', {}).get('body', '')
                
                if texto:
                    print(f'\n{"="*50}')
                    print(f'📩 Mensaje de {remitente}: {texto}')
                    print(f'{"="*50}')
                    
                    procesar_mensaje(remitente, texto, value)
        
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        print(f'❌ Error webhook: {e}')
        return jsonify({'status': 'error'}), 500

def procesar_mensaje(remitente, texto, value):
    try:
        if db is None:
            conectar_mongodb()
        
        contactos = value.get('contacts', [{}])
        nombre = contactos[0].get('profile', {}).get('name', 'Cliente') if contactos else 'Cliente'
        
        print(f'🔄 Paso 1: Buscando cliente en MongoDB...')
        clientes = db['clientes']
        cliente = clientes.find_one({'telefono': remitente})
        
        if not cliente:
            print(f'👤 Cliente nuevo, buscando en Cianbox...')
            
            # Buscar en Cianbox por celular
            cliente_cianbox = buscar_cliente_por_celular(remitente)
            
            if cliente_cianbox:
                print(f'✅ Cliente encontrado en Cianbox: {cliente_cianbox.get("razon_social")}')
                cliente = {
                    'telefono': remitente,
                    'nombre': nombre,
                    'cuit': cliente_cianbox.get('cuit', ''),
                    'razon_social': cliente_cianbox.get('razon_social', ''),
                    'email': cliente_cianbox.get('email', ''),
                    'rubro': '',
                    'ubicacion': f"{cliente_cianbox.get('localidad', '')}, {cliente_cianbox.get('provincia', '')}",
                    'forma_pago': '',
                    'marcas_preferidas': '',
                    'condicion_iva': cliente_cianbox.get('condicion_iva', ''),
                    'domicilio': cliente_cianbox.get('domicilio', ''),
                    'saldo_cianbox': cliente_cianbox.get('saldo', 0),
                    'id_cianbox': cliente_cianbox.get('id'),
                    'estado': 'cianbox',
                    'conversaciones': [],
                    'creado': datetime.utcnow(),
                    'actualizado': datetime.utcnow()
                }
            else:
                print(f'👤 Cliente no encontrado en Cianbox, creando nuevo...')
                cliente = {
                    'telefono': remitente,
                    'nombre': nombre,
                    'cuit': '',
                    'razon_social': '',
                    'email': '',
                    'rubro': '',
                    'ubicacion': '',
                    'forma_pago': '',
                    'marcas_preferidas': '',
                    'estado': 'nuevo',
                    'conversaciones': [],
                    'creado': datetime.utcnow(),
                    'actualizado': datetime.utcnow()
                }
            
            clientes.insert_one(cliente)
            cliente = clientes.find_one({'telefono': remitente})
        else:
            print(f'👤 Cliente existente: {cliente.get("nombre")}')
            
            # Si el cliente existe pero no tiene datos de Cianbox, intentar vincular
            if not cliente.get('id_cianbox'):
                cliente_cianbox = buscar_cliente_por_celular(remitente)
                if cliente_cianbox:
                    print(f'🔗 Vinculando cliente existente con Cianbox...')
                    clientes.update_one(
                        {'telefono': remitente},
                        {'$set': {
                            'cuit': cliente_cianbox.get('cuit', '') or cliente.get('cuit', ''),
                            'razon_social': cliente_cianbox.get('razon_social', '') or cliente.get('razon_social', ''),
                            'email': cliente_cianbox.get('email', '') or cliente.get('email', ''),
                            'ubicacion': f"{cliente_cianbox.get('localidad', '')}, {cliente_cianbox.get('provincia', '')}" or cliente.get('ubicacion', ''),
                            'condicion_iva': cliente_cianbox.get('condicion_iva', ''),
                            'domicilio': cliente_cianbox.get('domicilio', ''),
                            'saldo_cianbox': cliente_cianbox.get('saldo', 0),
                            'id_cianbox': cliente_cianbox.get('id'),
                            'estado': 'cianbox',
                            'actualizado': datetime.utcnow()
                        }}
                    )
                    cliente = clientes.find_one({'telefono': remitente})
        
        datos_extraidos = extraer_datos_cliente(texto, cliente)
        if datos_extraidos:
            print('📝 Datos del cliente actualizados')
        
        conversaciones = cliente.get('conversaciones', [])
        conversaciones.append({
            'rol': 'usuario',
            'contenido': texto,
            'fecha': datetime.utcnow()
        })
        
        print('🔄 Paso 2: Extrayendo producto con GPT...')
        producto_nombre = extraer_producto(texto, conversaciones)
        print(f'📦 Producto extraído: "{producto_nombre or "(ninguno)"}"')
        
        stock_info = None
        contexto = ''
        
        if producto_nombre:
            print('🔄 Paso 3: Consultando stock...')
            stock_info = buscar_inteligente(producto_nombre)
            print(f'📊 Stock info: {"encontrado" if stock_info.get("encontrado") else "no encontrado"}')
            
            if stock_info.get('encontrado'):
                if stock_info.get('multiple'):
                    opciones_texto = '\n'.join([
                        f'''{i+1}. {op['nombre']}
   - Código: {op['codigo']}
   - Marca: {op['marca']}
   - Stock: {op['stock']} unidades
   - Precio: USD {op['precio_usd'] or 'N/A'} / ARS ${op['precio_ars']:,.0f}''' if op['precio_ars'] else f'''{i+1}. {op['nombre']}
   - Código: {op['codigo']}
   - Marca: {op['marca']}
   - Stock: {op['stock']} unidades
   - Precio: USD {op['precio_usd'] or 'N/A'}'''
                        for i, op in enumerate(stock_info['opciones'])
                    ])
                    contexto = f'''
BÚSQUEDA: "{producto_nombre}"
ENCONTRÉ {stock_info['cantidad']} OPCIONES DISPONIBLES:

{opciones_texto}

Presentá estas opciones al cliente de forma clara y preguntá cuál le interesa.
'''
                elif stock_info.get('disponible'):
                    precio_ars = f"${stock_info['precio_ars']:,.0f}" if stock_info.get('precio_ars') else 'N/A'
                    contexto = f'''
PRODUCTO ENCONTRADO:
- Nombre: {stock_info['nombre']}
- Código: {stock_info['codigo']}
- Stock disponible: {stock_info['stock']} unidades
- Precio: USD {stock_info.get('precio_usd', 'N/A')} / ARS {precio_ars}
- Marca: {stock_info['marca']}
- Categoría: {stock_info.get('categoria', '')}

Informá disponibilidad y precio. Preguntá si quiere presupuesto formal.
'''
                else:
                    alternativas = buscar_alternativas(
                        stock_info.get('categoria', ''),
                        stock_info.get('marca', '')
                    )
                    
                    if alternativas:
                        alt_texto = '\n'.join([
                            f'''{i+1}. {alt['nombre']}
   - Código: {alt['codigo']}
   - Marca: {alt['marca']}
   - Stock: {alt['stock']} unidades
   - Precio: USD {alt['precio_usd'] or 'N/A'}'''
                            for i, alt in enumerate(alternativas[:5])
                        ])
                        contexto = f'''
PRODUCTO SIN STOCK: {stock_info['nombre']}

ALTERNATIVAS DISPONIBLES:
{alt_texto}

Ofrecé estas alternativas al cliente.
'''
                    else:
                        contexto = f'''
PRODUCTO SIN STOCK: {stock_info['nombre']}
NO HAY ALTERNATIVAS.

Informá que:
1. No hay stock en este momento
2. Vas a consultar con Compras
3. Lo mantenés al tanto apenas tengas novedades
'''
                        notificar_sin_stock(stock_info['nombre'], cliente, conversaciones)
            else:
                contexto = f'''
El cliente preguntó por "{producto_nombre}" pero NO se encontró en nuestro catálogo.
Respondé amablemente que no encontraste ese producto específico y preguntá si puede darte más detalles o si busca algo similar.
'''
        else:
            contexto = '''
El cliente envió un mensaje sin mencionar ningún producto específico.
Respondé de forma cordial y preguntá en qué podés ayudarlo. Somos GRUPO SER, empresa de seguridad electrónica.
'''
        
        print('🔄 Paso 4: Generando respuesta con OpenAI...')
        respuesta = generar_respuesta(texto, conversaciones, contexto, cliente)
        print(f'✅ Respuesta generada: {respuesta[:100]}...')
        
        conversaciones.append({
            'rol': 'asistente',
            'contenido': respuesta,
            'fecha': datetime.utcnow()
        })
        
        print('🔄 Paso 5: Guardando en MongoDB...')
        clientes.update_one(
            {'telefono': remitente},
            {
                '$set': {
                    'conversaciones': conversaciones,
                    'actualizado': datetime.utcnow(),
                    'cuit': cliente.get('cuit', ''),
                    'razon_social': cliente.get('razon_social', ''),
                    'email': cliente.get('email', ''),
                    'rubro': cliente.get('rubro', ''),
                    'ubicacion': cliente.get('ubicacion', ''),
                    'forma_pago': cliente.get('forma_pago', ''),
                    'marcas_preferidas': cliente.get('marcas_preferidas', '')
                }
            }
        )
        print('✅ Cliente guardado')
        
        print('🔄 Paso 6: Enviando mensaje por WhatsApp...')
        enviar_mensaje_whatsapp(remitente, respuesta)
        print(f'✅ Respuesta enviada a {remitente}')
        print(f'{"="*50}\n')
        
    except Exception as e:
        print(f'\n{"❌"*25}')
        print(f'❌ ERROR EN procesar_mensaje:')
        print(f'❌ Mensaje: {e}')
        import traceback
        traceback.print_exc()
        print(f'{"❌"*25}\n')
        
        try:
            enviar_mensaje_whatsapp(
                remitente,
                'Disculpá, tuve un problema técnico. ¿Podés intentar de nuevo en un momento?'
            )
        except:
            pass

# ============================================
# RUTA PRINCIPAL
# ============================================

@app.route('/')
def inicio():
    return '🤖 Ovidio Bot - Python - Online | Inteligencia Activa'

# ============================================
# INICIAR SERVIDOR
# ============================================

if __name__ == '__main__':
    conectar_mongodb()
    inicializar_cianbox()
    port = int(os.environ.get('PORT', 3000))
    print(f'🚀 Servidor Ovidio corriendo en puerto {port}')
    print(f'📊 Integración con seguridadrosario.com: ACTIVA')
    print(f'🧠 Extractor de productos: ACTIVO')
    print(f'📧 Notificaciones email: ACTIVAS')
    app.run(host='0.0.0.0', port=port, debug=False)
