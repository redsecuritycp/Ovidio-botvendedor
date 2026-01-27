import os
from flask import Flask, request, jsonify, send_from_directory
from pymongo import MongoClient, ASCENDING
from datetime import datetime, timedelta
import requests
import json
from openai import OpenAI
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.units import mm
import uuid
import glob
import threading
import time as time_module
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

try:
    from services.cianbox_service import buscar_cliente_por_celular, inicializar_cianbox, obtener_historial_pagos, obtener_saldo_cliente, obtener_productos
    CIANBOX_DISPONIBLE = True
except ImportError:
    CIANBOX_DISPONIBLE = False
    print('⚠️ Servicio Cianbox no disponible')

app = Flask(__name__)

cliente_mongo = None
db = None
cliente_openai = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))

# Crear carpeta para presupuestos en /tmp (persiste mejor en Replit)
PRESUPUESTOS_DIR = '/tmp/presupuestos'
if not os.path.exists(PRESUPUESTOS_DIR):
    os.makedirs(PRESUPUESTOS_DIR)
    print(f'📁 Carpeta presupuestos creada: {PRESUPUESTOS_DIR}')
else:
    print(f'📁 Carpeta presupuestos existe: {PRESUPUESTOS_DIR}')

DIAS_EXPIRACION = 15

def limpiar_pdfs_viejos():
    """Elimina PDFs con más de 15 días de antigüedad"""
    try:
        ahora = datetime.now()
        archivos = glob.glob(os.path.join(PRESUPUESTOS_DIR, '*.pdf'))
        eliminados = 0
        
        for archivo in archivos:
            fecha_creacion = datetime.fromtimestamp(os.path.getctime(archivo))
            dias_antiguedad = (ahora - fecha_creacion).days
            
            if dias_antiguedad > DIAS_EXPIRACION:
                os.remove(archivo)
                eliminados += 1
                print(f'🗑️ PDF eliminado por antigüedad: {archivo}')
        
        if eliminados > 0:
            print(f'🧹 Limpieza: {eliminados} PDFs eliminados')
    except Exception as e:
        print(f'❌ Error limpiando PDFs: {e}')

def conectar_mongodb():
    global cliente_mongo, db
    try:
        cliente_mongo = MongoClient(os.environ.get('MONGODB_URI'))
        db = cliente_mongo['ovidio_db']
        
        # Crear índice TTL para presupuestos (expiran a los 15 días)
        try:
            db['presupuestos'].create_index(
                'creado',
                expireAfterSeconds=DIAS_EXPIRACION * 24 * 60 * 60
            )
            print(f'✅ Índice TTL configurado: {DIAS_EXPIRACION} días')
        except Exception as e:
            # El índice ya existe
            print(f'ℹ️ Índice TTL ya existe')
        
        print('✅ MongoDB conectado')
        return db
    except Exception as e:
        print(f'❌ Error MongoDB: {e}')
        return None

# ============== SINCRONIZACIÓN CIANBOX ==============

def sincronizar_clientes_cianbox():
    """
    Descarga TODOS los clientes de Cianbox y los guarda en MongoDB.
    La API de Cianbox no filtra bien, así que guardamos todo localmente.
    """
    try:
        if db is None:
            print('❌ MongoDB no conectado, no se puede sincronizar')
            return False
        
        from services.cianbox_service import get_token, CIANBOX_BASE_URL
        import requests
        
        token = get_token()
        if not token:
            print('❌ No se pudo obtener token de Cianbox')
            return False
        
        print('🔄 Iniciando sincronización de clientes Cianbox...')
        
        todos_clientes = []
        pagina = 1
        limit = 100
        
        while True:
            response = requests.get(
                f'{CIANBOX_BASE_URL}/clientes',
                params={'access_token': token, 'limit': limit, 'page': pagina},
                timeout=30
            )
            
            if response.status_code != 200:
                print(f'❌ Error en página {pagina}: {response.status_code}')
                break
            
            data = response.json()
            if data.get('status') != 'ok':
                print(f'❌ Error en página {pagina}: {data.get("message")}')
                break
            
            clientes = data.get('body', [])
            if not clientes:
                break
            
            todos_clientes.extend(clientes)
            print(f'📥 Página {pagina}: {len(clientes)} clientes (total: {len(todos_clientes)})')
            
            pagina += 1
            
            # Seguridad: máximo 200 páginas
            if pagina > 200:
                print('⚠️ Límite de páginas alcanzado')
                break
        
        if not todos_clientes:
            print('⚠️ No se encontraron clientes en Cianbox')
            return False
        
        # Guardar en MongoDB
        coleccion = db['clientes_cianbox']
        
        # Limpiar colección anterior
        coleccion.delete_many({})
        
        # Insertar todos los clientes
        for cliente in todos_clientes:
            celular = cliente.get('celular', '') or ''
            celular_limpio = ''.join(filter(str.isdigit, celular))
            email = (cliente.get('email', '') or '').strip().lower()
            
            coleccion.insert_one({
                'cianbox_id': cliente.get('id'),
                'razon_social': cliente.get('razon'),
                'cuit': cliente.get('numero_documento'),
                'celular': celular,
                'celular_normalizado': celular_limpio,
                'email': email,
                'domicilio': cliente.get('domicilio'),
                'localidad': cliente.get('localidad'),
                'provincia': cliente.get('provincia'),
                'telefono': cliente.get('telefono'),
                'condicion_iva': cliente.get('condicion'),
                'tiene_cuenta_corriente': cliente.get('ctacte'),
                'saldo': cliente.get('saldo'),
                'descuento': cliente.get('descuento'),
                'listas_precio': cliente.get('listas_precio', [0]),
                'sincronizado': datetime.utcnow()
            })
        
        # Crear índices para búsqueda rápida
        coleccion.create_index('celular_normalizado')
        coleccion.create_index('email')
        coleccion.create_index('cuit')
        
        print(f'✅ Sincronización completada: {len(todos_clientes)} clientes guardados')
        return True
        
    except Exception as e:
        print(f'❌ Error en sincronización: {e}')
        import traceback
        traceback.print_exc()
        return False


def buscar_cliente_en_cache(celular=None, email=None, cuit=None):
    """
    Busca un cliente en el caché local de MongoDB (clientes_cianbox).
    Mucho más rápido y confiable que la API de Cianbox.
    """
    try:
        if db is None:
            return None
        
        coleccion = db['clientes_cianbox']
        cliente = None
        
        if celular:
            celular_limpio = ''.join(filter(str.isdigit, celular))
            if celular_limpio.startswith('549'):
                celular_limpio = celular_limpio[3:]
            elif celular_limpio.startswith('54'):
                celular_limpio = celular_limpio[2:]
            
            # Buscar por celular normalizado (coincidencia parcial)
            cliente = coleccion.find_one({
                '$or': [
                    {'celular_normalizado': celular_limpio},
                    {'celular_normalizado': {'$regex': f'{celular_limpio}$'}},
                ]
            })
        
        if not cliente and email:
            email_limpio = email.strip().lower()
            cliente = coleccion.find_one({'email': email_limpio})
        
        if not cliente and cuit:
            cuit_limpio = ''.join(filter(str.isdigit, cuit))
            cliente = coleccion.find_one({'cuit': cuit_limpio})
        
        if cliente:
            print(f'✅ Cliente encontrado en caché: {cliente.get("razon_social")}')
            return {
                'id': cliente.get('cianbox_id'),
                'razon_social': cliente.get('razon_social'),
                'condicion_iva': cliente.get('condicion_iva'),
                'cuit': cliente.get('cuit'),
                'domicilio': cliente.get('domicilio'),
                'localidad': cliente.get('localidad'),
                'provincia': cliente.get('provincia'),
                'telefono': cliente.get('telefono'),
                'celular': cliente.get('celular'),
                'email': cliente.get('email'),
                'tiene_cuenta_corriente': cliente.get('tiene_cuenta_corriente'),
                'saldo': cliente.get('saldo'),
                'descuento': cliente.get('descuento'),
                'listas_precio': cliente.get('listas_precio', [0])
            }
        
        return None
        
    except Exception as e:
        print(f'❌ Error buscando en caché: {e}')
        return None

# ============== CRON AUTOMÁTICO ==============

def cron_sincronizacion_cianbox():
    """
    Ejecuta sincronización de Cianbox cada 24 horas automáticamente.
    """
    while True:
        # Esperar 24 horas (86400 segundos)
        time_module.sleep(86400)
        print('⏰ Cron: Ejecutando sincronización diaria de Cianbox...')
        sincronizar_clientes_cianbox()


def cron_seguimientos_diarios():
    """
    Ejecuta seguimientos diarios: 7 días sin actividad y presupuestos por vencer.
    Se ejecuta todos los días a las 10:00 AM Argentina.
    """
    while True:
        # Calcular segundos hasta las 10:00 AM del día siguiente
        ahora = datetime.utcnow()
        # Argentina es UTC-3, así que 10:00 AR = 13:00 UTC
        proxima_ejecucion = ahora.replace(hour=13, minute=0, second=0, microsecond=0)
        if ahora.hour >= 13:
            proxima_ejecucion += timedelta(days=1)
        
        segundos_espera = (proxima_ejecucion - ahora).total_seconds()
        print(f'⏰ Próximo seguimiento diario en {segundos_espera/3600:.1f} horas')
        
        time_module.sleep(segundos_espera)
        
        print('⏰ Cron: Ejecutando seguimientos diarios...')
        ejecutar_seguimiento_7dias()
        ejecutar_recordatorio_presupuestos()


def cron_saludo_lunes():
    """
    Envía saludos los lunes entre 11:00 y 14:00 Argentina (horario random).
    """
    while True:
        ahora = datetime.utcnow()
        
        # Calcular próximo lunes
        dias_hasta_lunes = (7 - ahora.weekday()) % 7
        if dias_hasta_lunes == 0 and ahora.hour >= 17:  # Ya pasó el horario del lunes
            dias_hasta_lunes = 7
        
        # Horario random entre 11:00 y 14:00 Argentina (14:00-17:00 UTC)
        hora_random = random.randint(14, 16)
        minuto_random = random.randint(0, 59)
        
        proximo_lunes = ahora.replace(hour=hora_random, minute=minuto_random, second=0, microsecond=0)
        proximo_lunes += timedelta(days=dias_hasta_lunes)
        
        segundos_espera = (proximo_lunes - ahora).total_seconds()
        
        if segundos_espera > 0:
            print(f'⏰ Próximo saludo lunes en {segundos_espera/3600:.1f} horas (a las {hora_random-3}:{minuto_random:02d} AR)')
            time_module.sleep(segundos_espera)
        
        # Verificar que sea lunes
        if datetime.utcnow().weekday() == 0:
            print('⏰ Cron: Ejecutando saludo de lunes...')
            ejecutar_saludo_lunes()
        else:
            # Si no es lunes (por algún desfase), esperar al próximo
            time_module.sleep(3600)


def cron_cumpleanos():
    """
    Verifica cumpleaños todos los días a las 9:00 AM Argentina.
    """
    while True:
        ahora = datetime.utcnow()
        # 9:00 Argentina = 12:00 UTC
        proxima_ejecucion = ahora.replace(hour=12, minute=0, second=0, microsecond=0)
        if ahora.hour >= 12:
            proxima_ejecucion += timedelta(days=1)
        
        segundos_espera = (proxima_ejecucion - ahora).total_seconds()
        print(f'⏰ Próximo chequeo de cumpleaños en {segundos_espera/3600:.1f} horas')
        
        time_module.sleep(segundos_espera)
        
        print('⏰ Cron: Verificando cumpleaños...')
        ejecutar_felicitaciones_cumpleanos()


def iniciar_cron_cumpleanos():
    """Inicia el cron de cumpleaños en un thread separado"""
    thread = threading.Thread(target=cron_cumpleanos, daemon=True)
    thread.start()
    print('✅ Cron de cumpleaños iniciado (9:00 AM)')


def iniciar_cron_sincronizacion():
    """Inicia el cron de sincronización Cianbox en un thread separado"""
    thread = threading.Thread(target=cron_sincronizacion_cianbox, daemon=True)
    thread.start()
    print('✅ Cron de sincronización Cianbox iniciado (cada 24hs)')


def iniciar_cron_seguimientos():
    """Inicia el cron de seguimientos diarios en un thread separado"""
    thread = threading.Thread(target=cron_seguimientos_diarios, daemon=True)
    thread.start()
    print('✅ Cron de seguimientos diarios iniciado (10:00 AM)')


def iniciar_cron_lunes():
    """Inicia el cron de saludo lunes en un thread separado"""
    thread = threading.Thread(target=cron_saludo_lunes, daemon=True)
    thread.start()
    print('✅ Cron de saludo lunes iniciado (11:00-14:00 AR)')


# ============== FUNCIONES DE EMAIL ==============

def enviar_email(destinatario, asunto, cuerpo_html):
    """Envía un email usando SMTP de Gmail"""
    try:
        email_user = os.environ.get('EMAIL_USER')
        email_pass = os.environ.get('EMAIL_PASS')
        
        if not email_user or not email_pass:
            print('⚠️ EMAIL_USER o EMAIL_PASS no configurados, saltando email')
            return False
        
        msg = MIMEMultipart('alternative')
        msg['Subject'] = asunto
        msg['From'] = email_user
        msg['To'] = destinatario
        
        parte_html = MIMEText(cuerpo_html, 'html')
        msg.attach(parte_html)
        
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(email_user, email_pass)
            server.sendmail(email_user, destinatario, msg.as_string())
        
        print(f'✅ Email enviado a {destinatario}')
        return True
        
    except Exception as e:
        print(f'❌ Error enviando email: {e}')
        return False

def notificar_vendedor_presupuesto(presupuesto):
    """Notifica al vendedor cuando se genera un presupuesto"""
    try:
        vendedor_email = os.environ.get('VENDEDOR_EMAIL')
        if not vendedor_email:
            print('⚠️ VENDEDOR_EMAIL no configurado')
            return False
        
        items_html = ""
        for item in presupuesto['items']:
            items_html += f"<tr><td>{item['nombre']}</td><td>{item['cantidad']}</td><td>USD {item['precio']}</td></tr>"
        
        cuerpo = f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <h2 style="color: #00BCD4;">📋 Nuevo Presupuesto #{presupuesto['numero']}</h2>
            
            <h3>Cliente:</h3>
            <p>
                <strong>Nombre:</strong> {presupuesto['nombre_cliente']}<br>
                <strong>Teléfono:</strong> {presupuesto['telefono']}<br>
            </p>
            
            <h3>Productos:</h3>
            <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse;">
                <tr style="background-color: #00BCD4; color: white;">
                    <th>Producto</th>
                    <th>Cantidad</th>
                    <th>Precio USD</th>
                </tr>
                {items_html}
            </table>
            
            <p style="font-size: 18px; margin-top: 20px;">
                <strong>Total: USD {presupuesto['subtotal']:.0f} + IVA</strong>
            </p>
            
            <p style="color: #666; margin-top: 30px;">
                Generado automáticamente por Ovidio Bot.
            </p>
        </body>
        </html>
        """
        
        return enviar_email(vendedor_email, f"📋 Presupuesto #{presupuesto['numero']} - {presupuesto['nombre_cliente']}", cuerpo)
        
    except Exception as e:
        print(f'❌ Error notificando vendedor: {e}')
        return False

def notificar_compras_sin_stock(producto, cliente_nombre, cliente_telefono, historial):
    """Notifica a compras cuando no hay stock de un producto"""
    try:
        compras_email = os.environ.get('EMAIL_TO_COMPRAS')
        if not compras_email:
            print('⚠️ COMPRAS_EMAIL no configurado')
            return False
        
        historial_html = ""
        for msg in historial[-10:]:
            rol = "Cliente" if msg.get('rol') == 'usuario' else "Ovidio"
            contenido = msg.get('contenido', '')[:200]
            color = "#333" if rol == "Cliente" else "#00BCD4"
            historial_html += f"<p><strong style='color:{color}'>{rol}:</strong> {contenido}</p>"
        
        cuerpo = f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <h2 style="color: #FF5722;">⚠️ Producto Sin Stock</h2>
            
            <h3>Producto Solicitado:</h3>
            <p style="font-size: 18px; background-color: #FFF3E0; padding: 10px; border-radius: 5px;">
                <strong>{producto}</strong>
            </p>
            
            <h3>Cliente:</h3>
            <p>
                <strong>Nombre:</strong> {cliente_nombre}<br>
                <strong>Teléfono:</strong> <a href="https://wa.me/{cliente_telefono}">{cliente_telefono}</a><br>
            </p>
            
            <h3>Conversación:</h3>
            <div style="background-color: #f5f5f5; padding: 15px; border-radius: 5px;">
                {historial_html if historial_html else '<p>Sin historial disponible</p>'}
            </div>
            
            <p style="color: #666; margin-top: 30px;">
                Por favor consultar precio y demora.<br>
                Generado automáticamente por Ovidio Bot.
            </p>
        </body>
        </html>
        """
        
        return enviar_email(compras_email, f"⚠️ Sin Stock: {producto} - {cliente_nombre}", cuerpo)
        
    except Exception as e:
        print(f'❌ Error notificando compras: {e}')
        return False

def extraer_datos_personales(texto, datos_actuales=None):
    """Extrae información personal/humana de la conversación para generar vínculo"""
    try:
        datos = datos_actuales or {}
        memoria = datos.get('memoria_conversaciones', [])
        
        respuesta = cliente_openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": """Analizá el mensaje y extraé información PERSONAL/HUMANA que sirva para generar vínculo con el cliente.

NO extraer datos comerciales (eso ya está en Cianbox).
SÍ extraer cosas personales que un vendedor recordaría:

- Salud: si menciona médico, enfermedad, dolor, accidente (propio o familia)
- Familia: si menciona hijos, esposa, padres, hermanos
- Planes: viajes, vacaciones, fin de semana
- Hobbies: pesca, fútbol, deportes, actividades
- Trabajo: proyectos en curso, obras, clientes suyos
- Estado de ánimo: si está apurado, estresado, contento
- Cualquier dato personal que sirva para preguntar después

Respondé SOLO con JSON:
{
    "evento": "descripción breve de lo que mencionó",
    "tipo": "salud|familia|planes|hobby|trabajo|otro",
    "seguimiento": "pregunta para hacer en próxima conversación"
}

Si no hay nada personal, respondé {}

Ejemplos:
- "estoy en el médico con mi viejo" → {"evento": "padre enfermo, en médico", "tipo": "familia", "seguimiento": "¿Cómo sigue tu viejo?"}
- "el finde me voy a pescar" → {"evento": "va a pescar el fin de semana", "tipo": "hobby", "seguimiento": "¿Pudiste ir a pescar?"}
- "estoy terminando una obra en funes" → {"evento": "obra en Funes en curso", "tipo": "trabajo", "seguimiento": "¿Cómo va la obra en Funes?"}"""
                },
                {"role": "user", "content": texto}
            ],
            temperature=0.1
        )
        
        contenido = respuesta.choices[0].message.content.strip()
        contenido = contenido.replace('```json', '').replace('```', '').strip()
        
        nuevo_evento = json.loads(contenido)
        
        if nuevo_evento and nuevo_evento.get('evento'):
            # Agregar timestamp
            nuevo_evento['fecha'] = datetime.utcnow().isoformat()
            
            # Agregar a la memoria (máximo 10 eventos)
            memoria.append(nuevo_evento)
            if len(memoria) > 10:
                memoria = memoria[-10:]
            
            datos['memoria_conversaciones'] = memoria
            print(f'📝 Evento personal guardado: {nuevo_evento["evento"]}')
        
        return datos
        
    except Exception as e:
        print(f'⚠️ Error extrayendo datos personales: {e}')
        return datos_actuales or {}

def actualizar_datos_cliente(telefono, datos_personales):
    """Actualiza los datos personales del cliente en MongoDB"""
    try:
        if db is None or not datos_personales:
            return
        
        db['clientes'].update_one(
            {'telefono': telefono},
            {'$set': {'datos_personales': datos_personales, 'actualizado': datetime.utcnow()}}
        )
        print(f'✅ Datos personales actualizados para {telefono}')
        
    except Exception as e:
        print(f'❌ Error actualizando datos cliente: {e}')

def formatear_contexto_cliente(cliente, datos_cianbox=None):
    """Formatea los datos del cliente para incluir en el prompt"""
    if not cliente and not datos_cianbox:
        return ""
    
    partes = []
    
    # Info de Cianbox (comercial)
    if datos_cianbox:
        if datos_cianbox.get('razon_social'):
            partes.append(f"Razón social: {datos_cianbox['razon_social']}")
        if datos_cianbox.get('localidad'):
            partes.append(f"Ubicación: {datos_cianbox['localidad']}")
        if datos_cianbox.get('descuento') and datos_cianbox['descuento'] > 0:
            partes.append(f"Descuento asignado: {datos_cianbox['descuento']}%")
    
    # Memoria de conversaciones (personal/humano)
    if cliente:
        datos = cliente.get('datos_personales', {})
        memoria = datos.get('memoria_conversaciones', [])
        
        if memoria:
            partes.append("\n=== MEMORIA PERSONAL (usá esto para generar vínculo) ===")
            for evento in memoria[-5:]:  # Últimos 5 eventos
                seguimiento = evento.get('seguimiento', '')
                partes.append(f"- {evento.get('evento', '')} → Podés preguntar: \"{seguimiento}\"")
            partes.append("===")
    
    # Agregar marcas preferidas
    info = {}
    if partes:
        info['texto'] = "\n".join(partes)
    
    if cliente and cliente.get('marcas_preferidas'):
        info['marcas'] = cliente.get('marcas_preferidas')
    
    # Agregar proveedores conocidos
    if cliente and cliente.get('proveedores_actuales'):
        info['proveedores'] = cliente.get('proveedores_actuales')
    
    # Agregar comportamiento de pago
    if cliente and cliente.get('cianbox_id'):
        comportamiento = obtener_comportamiento_pago(cliente)
        if comportamiento:
            info['comportamiento_pago'] = comportamiento
    
    # Si hay info, retornar dict. Si no, retornar string vacío para compatibilidad
    if info:
        return info
    
    return ""

# ============== FUNCIONES DE STOCK ==============

def buscar_en_api_productos(termino_busqueda):
    """Busca productos en Cianbox"""
    try:
        productos = obtener_productos(termino_busqueda, limite=5)
        
        if productos:
            # Convertir formato Cianbox al formato esperado
            resultado = []
            for p in productos:
                resultado.append({
                    'name': p.get('nombre', ''),
                    'nombre': p.get('nombre', ''),
                    'price': p.get('precio', 0),
                    'precio': p.get('precio', 0),
                    'stock': p.get('stock', 0),
                    'cantidad': p.get('stock', 0),
                    'sku': p.get('codigo', ''),
                    'codigo': p.get('codigo', ''),
                    'iva': p.get('iva', 21),
                    'description': p.get('descripcion', ''),
                    'descripcion': p.get('descripcion', ''),
                    'marca': p.get('marca', ''),
                    'categoria': p.get('categoria', '')
                })
            return resultado
        
        return []
        
    except Exception as e:
        print(f'❌ Error buscando productos: {e}')
        return []

def formatear_producto_para_respuesta(producto):
    """Formatea un producto para mostrar al cliente, incluyendo spec principal"""
    nombre = producto.get('name', producto.get('nombre', 'Producto'))
    precio = producto.get('price', producto.get('precio', 0))
    stock = producto.get('stock', producto.get('cantidad', 0))
    sku = producto.get('sku', producto.get('codigo', ''))
    iva = producto.get('iva', 21)
    descripcion = producto.get('description', producto.get('descripcion', ''))
    
    estado_stock = "✅ Disponible" if stock > 0 else "❌ Sin stock"
    
    # Extraer spec principal de la descripción
    spec_principal = ""
    if descripcion:
        # Buscar specs comunes
        specs_keywords = ['MP', 'megapixel', 'canales', 'CH', 'PoE', 'WiFi', 'inalámbrico', 
                         'IP67', 'IP66', 'infrarrojo', 'IR', 'varifocal', 'motorizado',
                         'TB', 'GB', 'zonas', 'detectores']
        desc_lower = descripcion.lower()
        for keyword in specs_keywords:
            if keyword.lower() in desc_lower:
                # Extraer contexto alrededor del keyword
                idx = desc_lower.find(keyword.lower())
                start = max(0, idx - 10)
                end = min(len(descripcion), idx + len(keyword) + 10)
                spec_principal = descripcion[start:end].strip()
                break
    
    return {
        'nombre': nombre,
        'precio': precio,
        'stock': stock,
        'sku': sku,
        'iva': iva,
        'estado': estado_stock,
        'spec': spec_principal,
        'texto': f"• {nombre}\n  USD {precio} + IVA | {estado_stock}"
    }

def buscar_alternativas_producto(producto_sin_stock, cantidad=3):
    """
    Busca productos alternativos cuando el solicitado no tiene stock.
    Usa GPT para identificar características clave y busca similares.
    """
    try:
        nombre = producto_sin_stock.get('name', producto_sin_stock.get('nombre', ''))
        
        # Extraer categoría/tipo del producto
        respuesta = cliente_openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": """Dado un producto de seguridad electrónica, extraé términos de búsqueda para encontrar alternativas similares.
                    
Respondé SOLO con 2-3 palabras clave separadas por coma.
Ejemplos:
- "Cámara Domo IP Hikvision 2MP" → "cámara domo IP, 2MP"
- "DVR Hikvision 8 canales" → "DVR 8 canales"
- "Sensor de movimiento DSC" → "sensor movimiento, PIR"
"""
                },
                {"role": "user", "content": nombre}
            ],
            temperature=0.3,
            max_tokens=30
        )
        
        terminos = respuesta.choices[0].message.content.strip()
        
        # Buscar alternativas
        alternativas = []
        for termino in terminos.split(','):
            termino = termino.strip()
            if termino:
                resultados = buscar_en_api_productos(termino)
                for prod in resultados:
                    stock = prod.get('stock', prod.get('cantidad', 0))
                    if stock > 0:  # Solo productos CON stock
                        alternativas.append(prod)
                        if len(alternativas) >= cantidad:
                            break
            if len(alternativas) >= cantidad:
                break
        
        return alternativas[:cantidad]
        
    except Exception as e:
        print(f'❌ Error buscando alternativas: {e}')
        return []


def formatear_alternativas(alternativas):
    """Formatea las alternativas para mostrar al cliente"""
    if not alternativas:
        return ""
    
    texto = "\n\n📦 *Alternativas disponibles:*"
    for alt in alternativas:
        nombre = alt.get('name', alt.get('nombre', ''))
        precio = alt.get('price', alt.get('precio', 0))
        texto += f"\n• {nombre} - USD {precio} + IVA"
    
    return texto

def detectar_marca_preferida(texto):
    """
    Detecta si el cliente menciona una marca preferida en su mensaje.
    """
    marcas_conocidas = [
        'hikvision', 'dahua', 'dsc', 'ajax', 'paradox', 'honeywell', 
        'bosch', 'samsung', 'lg', 'tp-link', 'ubiquiti', 'mikrotik',
        'intelbras', 'provision', 'epcom', 'syscom', 'zkteco', 'anviz',
        'commax', 'fermax', 'cdvi', 'hid', 'suprema', 'axis'
    ]
    
    texto_lower = texto.lower()
    marcas_encontradas = []
    
    for marca in marcas_conocidas:
        if marca in texto_lower:
            marcas_encontradas.append(marca.capitalize())
    
    return marcas_encontradas


def actualizar_marcas_cliente(telefono, marcas):
    """
    Actualiza las marcas preferidas del cliente en MongoDB.
    """
    try:
        if db is None or not marcas:
            return
        
        db['clientes'].update_one(
            {'telefono': telefono},
            {
                '$addToSet': {'marcas_preferidas': {'$each': marcas}},
                '$set': {'actualizado': datetime.utcnow()}
            }
        )
        print(f'✅ Marcas actualizadas para {telefono}: {marcas}')
        
    except Exception as e:
        print(f'❌ Error actualizando marcas: {e}')


def obtener_marcas_cliente(cliente):
    """
    Obtiene las marcas preferidas del cliente.
    """
    if not cliente:
        return []
    return cliente.get('marcas_preferidas', [])

def detectar_proveedor_mencionado(texto):
    """
    Detecta si el cliente menciona un proveedor en su mensaje.
    """
    proveedores_conocidos = [
        'casa munro', 'munro', 'reba', 'newsan', 'garbarino', 'fravega', 
        'megatone', 'musimundo', 'coto', 'easy', 'sodimac', 'mercadolibre',
        'electronica gonzalez', 'casa piedra', 'seguridad ya', 'tecnoseguridad',
        'alarmas rosario', 'syscom', 'intcomex', 'ingram', 'licencias online'
    ]
    
    texto_lower = texto.lower()
    proveedores_encontrados = []
    
    for proveedor in proveedores_conocidos:
        if proveedor in texto_lower:
            proveedores_encontrados.append(proveedor.title())
    
    # También detectar menciones genéricas
    if 'otro proveedor' in texto_lower or 'les compro a' in texto_lower or 'compro en' in texto_lower:
        # Intentar extraer el nombre después de estas frases
        pass
    
    return proveedores_encontrados


def actualizar_proveedores_cliente(telefono, proveedores):
    """
    Actualiza los proveedores conocidos del cliente en MongoDB.
    """
    try:
        if db is None or not proveedores:
            return
        
        db['clientes'].update_one(
            {'telefono': telefono},
            {
                '$addToSet': {'proveedores_actuales': {'$each': proveedores}},
                '$set': {'actualizado': datetime.utcnow()}
            }
        )
        print(f'✅ Proveedores actualizados para {telefono}: {proveedores}')
        
    except Exception as e:
        print(f'❌ Error actualizando proveedores: {e}')


def detectar_preferencia_promos(texto):
    """
    Detecta si el cliente indica preferencia sobre recibir promos/capacitaciones.
    Retorna: 'si', 'no', o None si no menciona nada.
    """
    texto_lower = texto.lower()
    
    # Detectar aceptación
    aceptacion = ['si quiero', 'sí quiero', 'me interesa', 'dale', 'mandame', 'enviame', 
                  'quiero recibir', 'si a las promo', 'si a promo', 'acepto']
    for frase in aceptacion:
        if frase in texto_lower:
            return 'si'
    
    # Detectar rechazo
    rechazo = ['no quiero', 'no me interesa', 'no gracias', 'no mandes', 'no envies',
               'sin promo', 'no a las promo', 'no spam']
    for frase in rechazo:
        if frase in texto_lower:
            return 'no'
    
    return None


def actualizar_preferencia_promos(telefono, preferencia):
    """
    Actualiza la preferencia de promos del cliente.
    """
    try:
        if db is None or not preferencia:
            return
        
        db['clientes'].update_one(
            {'telefono': telefono},
            {
                '$set': {
                    'acepta_promos': preferencia == 'si',
                    'fecha_preferencia_promos': datetime.utcnow(),
                    'actualizado': datetime.utcnow()
                }
            }
        )
        print(f'✅ Preferencia promos para {telefono}: {preferencia}')
        
    except Exception as e:
        print(f'❌ Error actualizando preferencia promos: {e}')


def detectar_fecha_nacimiento(texto):
    """
    Detecta si el cliente menciona su fecha de nacimiento.
    """
    import re
    
    # Patrones comunes de fecha
    patrones = [
        r'nac[ií]\s*(?:el\s*)?(\d{1,2})[/-](\d{1,2})[/-]?(\d{2,4})?',  # nací el 15/03/1990
        r'cumplea[ñn]os\s*(?:es\s*)?(?:el\s*)?(\d{1,2})[/-](\d{1,2})',  # cumpleaños es el 15/03
        r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})',  # 15/03/1990
        r'(\d{1,2})\s*de\s*(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)',  # 15 de marzo
    ]
    
    meses = {
        'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4,
        'mayo': 5, 'junio': 6, 'julio': 7, 'agosto': 8,
        'septiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12
    }
    
    texto_lower = texto.lower()
    
    for patron in patrones:
        match = re.search(patron, texto_lower)
        if match:
            grupos = match.groups()
            try:
                if len(grupos) >= 2:
                    dia = int(grupos[0])
                    
                    # Si el segundo grupo es un mes en texto
                    if grupos[1] in meses:
                        mes = meses[grupos[1]]
                    else:
                        mes = int(grupos[1])
                    
                    if 1 <= dia <= 31 and 1 <= mes <= 12:
                        return {'dia': dia, 'mes': mes}
            except:
                continue
    
    return None


def actualizar_fecha_nacimiento(telefono, fecha):
    """
    Actualiza la fecha de nacimiento del cliente.
    """
    try:
        if db is None or not fecha:
            return
        
        db['clientes'].update_one(
            {'telefono': telefono},
            {
                '$set': {
                    'fecha_nacimiento_dia': fecha['dia'],
                    'fecha_nacimiento_mes': fecha['mes'],
                    'actualizado': datetime.utcnow()
                }
            }
        )
        print(f'✅ Fecha nacimiento para {telefono}: {fecha["dia"]}/{fecha["mes"]}')
        
    except Exception as e:
        print(f'❌ Error actualizando fecha nacimiento: {e}')


def obtener_comportamiento_pago(cliente):
    """
    Obtiene el comportamiento de pago del cliente desde Cianbox.
    """
    try:
        cianbox_id = cliente.get('cianbox_id') if cliente else None
        
        if not cianbox_id:
            return None
        
        historial = obtener_historial_pagos(cianbox_id)
        return historial
        
    except Exception as e:
        print(f'❌ Error obteniendo comportamiento de pago: {e}')
        return None


def ejecutar_felicitaciones_cumpleanos():
    """
    Busca clientes que cumplen años hoy y les envía felicitación.
    """
    try:
        if db is None:
            return
        
        hoy = datetime.utcnow()
        dia_hoy = hoy.day
        mes_hoy = hoy.month
        
        print(f'🎂 Buscando cumpleaños del día {dia_hoy}/{mes_hoy}...')
        
        clientes = db['clientes'].find({
            'fecha_nacimiento_dia': dia_hoy,
            'fecha_nacimiento_mes': mes_hoy,
            'felicitado_este_ano': {'$ne': hoy.year}
        })
        
        enviados = 0
        for cliente in clientes:
            telefono = cliente.get('telefono')
            nombre = cliente.get('nombre', 'Cliente')
            
            mensaje = f"🎂 ¡Feliz cumpleaños {nombre}! Desde GRUPO SER te deseamos un gran día. Como regalo, tenés 10% OFF en tu próxima compra. ¿Algo más?"
            
            resultado = enviar_mensaje_whatsapp(telefono, mensaje)
            
            if resultado:
                db['clientes'].update_one(
                    {'_id': cliente['_id']},
                    {'$set': {'felicitado_este_ano': hoy.year}}
                )
                enviados += 1
        
        print(f'✅ Felicitaciones de cumpleaños: {enviados} enviadas')
        
    except Exception as e:
        print(f'❌ Error en felicitaciones cumpleaños: {e}')

# ============== FUNCIONES DE PRESUPUESTO ==============

def obtener_presupuesto_pendiente(telefono):
    """Obtiene el presupuesto pendiente de confirmación del cliente"""
    try:
        if db is None:
            conectar_mongodb()
        
        presupuestos = db['presupuestos']
        presupuesto = presupuestos.find_one({
            'telefono': telefono,
            'estado': 'pendiente_confirmacion'
        }, sort=[('creado', -1)])
        
        return presupuesto
    except Exception as e:
        print(f'❌ Error obteniendo presupuesto pendiente: {e}')
        return None

def crear_presupuesto(telefono, nombre_cliente, items, validez_dias=15):
    """Crea un presupuesto y lo guarda en MongoDB"""
    try:
        if db is None:
            conectar_mongodb()
        
        presupuestos = db['presupuestos']
        
        # Cancelar presupuestos pendientes anteriores del mismo cliente
        presupuestos.update_many(
            {'telefono': telefono, 'estado': 'pendiente_confirmacion'},
            {'$set': {'estado': 'cancelado', 'actualizado': datetime.utcnow()}}
        )
        
        # Generar número de presupuesto
        ultimo = presupuestos.find_one(sort=[('numero', -1)])
        numero = (ultimo.get('numero', 0) + 1) if ultimo else 1
        
        # Calcular totales
        subtotal = sum(item['precio'] * item['cantidad'] for item in items)
        
        # Calcular IVA por item
        total_iva = 0
        for item in items:
            iva_porcentaje = item.get('iva', 21)
            iva_item = (item['precio'] * item['cantidad']) * (iva_porcentaje / 100)
            total_iva += iva_item
            item['iva_monto'] = iva_item
        
        total = subtotal + total_iva
        
        ahora = datetime.utcnow()
        
        presupuesto = {
            'numero': numero,
            'telefono': telefono,
            'nombre_cliente': nombre_cliente,
            'items': items,
            'subtotal': subtotal,
            'iva': total_iva,
            'total': total,
            'validez_dias': validez_dias,
            'estado': 'pendiente_confirmacion',
            'pdf_url': None,
            'creado': ahora,
            'actualizado': ahora
        }
        
        presupuestos.insert_one(presupuesto)
        print(f'✅ Presupuesto #{numero} creado para {nombre_cliente}')
        
        return presupuesto
        
    except Exception as e:
        print(f'❌ Error creando presupuesto: {e}')
        return None

def formatear_presupuesto_texto(presupuesto):
    """Formatea el presupuesto para mostrar en WhatsApp"""
    lineas = []
    lineas.append(f"📋 *PRESUPUESTO #{presupuesto['numero']}*")
    lineas.append(f"Cliente: {presupuesto['nombre_cliente']}")
    lineas.append(f"Fecha: {presupuesto['creado'].strftime('%d/%m/%Y')}")
    lineas.append(f"Válido por: {presupuesto['validez_dias']} días")
    lineas.append("")
    lineas.append("*Detalle:*")
    
    for item in presupuesto['items']:
        iva_porcentaje = item.get('iva', 21)
        lineas.append(f"• {item['nombre']}")
        lineas.append(f"  {item['cantidad']} x ${item['precio']:,.0f} = ${item['precio'] * item['cantidad']:,.0f}")
        lineas.append(f"  (IVA {iva_porcentaje}%: ${item.get('iva_monto', 0):,.0f})")
    
    lineas.append("")
    lineas.append(f"*Subtotal:* ${presupuesto['subtotal']:,.0f}")
    lineas.append(f"*IVA:* ${presupuesto['iva']:,.0f}")
    lineas.append(f"*TOTAL:* ${presupuesto['total']:,.0f}")
    
    return "\n".join(lineas)

def generar_pdf_presupuesto(presupuesto):
    """Genera el PDF del presupuesto con diseño profesional"""
    try:
        nombre_archivo = f"presupuesto_{presupuesto['numero']}.pdf"
        ruta_archivo = os.path.join(PRESUPUESTOS_DIR, nombre_archivo)
        
        doc = SimpleDocTemplate(ruta_archivo, pagesize=A4,
                                rightMargin=15*mm, leftMargin=15*mm,
                                topMargin=15*mm, bottomMargin=15*mm)
        
        elementos = []
        estilos = getSampleStyleSheet()
        
        # Colores de la marca
        CYAN_PRIMARIO = colors.HexColor('#00BCD4')
        CYAN_OSCURO = colors.HexColor('#0097A7')
        GRIS_OSCURO = colors.HexColor('#37474F')
        GRIS_CLARO = colors.HexColor('#F5F5F5')
        
        # Logo
        logo_path = os.path.join(os.path.dirname(__file__), 'logo.png')
        if os.path.exists(logo_path):
            from reportlab.platypus import Image
            logo = Image(logo_path, width=50*mm, height=25*mm)
            logo.hAlign = 'LEFT'
            elementos.append(logo)
            elementos.append(Spacer(1, 5*mm))
        
        # Línea separadora cyan
        from reportlab.platypus import HRFlowable
        elementos.append(HRFlowable(width="100%", thickness=2, color=CYAN_PRIMARIO, spaceAfter=10))
        
        # Título PRESUPUESTO
        estilo_titulo = ParagraphStyle(
            'TituloPres',
            parent=estilos['Heading1'],
            fontSize=22,
            textColor=GRIS_OSCURO,
            spaceAfter=5,
            fontName='Helvetica-Bold'
        )
        elementos.append(Paragraph(f"PRESUPUESTO N° {presupuesto['numero']}", estilo_titulo))
        
        # Fecha y validez en una línea
        estilo_fecha = ParagraphStyle(
            'Fecha',
            parent=estilos['Normal'],
            fontSize=10,
            textColor=colors.gray,
            spaceAfter=15
        )
        fecha_str = presupuesto['creado'].strftime('%d/%m/%Y')
        elementos.append(Paragraph(f"Fecha: {fecha_str}  |  Válido por: {presupuesto['validez_dias']} días", estilo_fecha))
        
        # Caja de datos del cliente
        estilo_cliente_titulo = ParagraphStyle(
            'ClienteTitulo',
            parent=estilos['Normal'],
            fontSize=11,
            textColor=CYAN_OSCURO,
            fontName='Helvetica-Bold',
            spaceAfter=3
        )
        estilo_cliente = ParagraphStyle(
            'ClienteDatos',
            parent=estilos['Normal'],
            fontSize=11,
            textColor=GRIS_OSCURO,
            spaceAfter=15
        )
        elementos.append(Paragraph("CLIENTE", estilo_cliente_titulo))
        elementos.append(Paragraph(f"{presupuesto['nombre_cliente']}", estilo_cliente))
        
        elementos.append(Spacer(1, 5*mm))
        
        # Tabla de productos con estilo moderno
        datos_tabla = [['Producto', 'Cant.', 'Precio Unit.', 'IVA', 'Subtotal']]
        
        for item in presupuesto['items']:
            iva_porcentaje = item.get('iva', 21)
            subtotal_item = item['precio'] * item['cantidad']
            datos_tabla.append([
                item['nombre'][:45],
                str(item['cantidad']),
                f"${item['precio']:,.0f}",
                f"{iva_porcentaje}%",
                f"${subtotal_item:,.0f}"
            ])
        
        tabla = Table(datos_tabla, colWidths=[85*mm, 15*mm, 28*mm, 15*mm, 28*mm])
        tabla.setStyle(TableStyle([
            # Encabezado
            ('BACKGROUND', (0, 0), (-1, 0), CYAN_PRIMARIO),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('TOPPADDING', (0, 0), (-1, 0), 12),
            
            # Filas de datos
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('TEXTCOLOR', (0, 1), (-1, -1), GRIS_OSCURO),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 10),
            ('TOPPADDING', (0, 1), (-1, -1), 10),
            
            # Alineación
            ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),
            
            # Bordes sutiles
            ('LINEBELOW', (0, 0), (-1, 0), 2, CYAN_OSCURO),
            ('LINEBELOW', (0, 1), (-1, -2), 0.5, colors.HexColor('#E0E0E0')),
            ('LINEBELOW', (0, -1), (-1, -1), 1, GRIS_OSCURO),
            
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        
        elementos.append(tabla)
        elementos.append(Spacer(1, 8*mm))
        
        # Caja de totales a la derecha
        estilo_total_label = ParagraphStyle(
            'TotalLabel',
            parent=estilos['Normal'],
            fontSize=10,
            textColor=colors.gray,
            alignment=2
        )
        estilo_total_valor = ParagraphStyle(
            'TotalValor',
            parent=estilos['Normal'],
            fontSize=11,
            textColor=GRIS_OSCURO,
            alignment=2,
            fontName='Helvetica-Bold'
        )
        estilo_total_final = ParagraphStyle(
            'TotalFinal',
            parent=estilos['Normal'],
            fontSize=16,
            textColor=CYAN_OSCURO,
            alignment=2,
            fontName='Helvetica-Bold',
            spaceBefore=5
        )
        
        elementos.append(Paragraph(f"Subtotal: ${presupuesto['subtotal']:,.0f}", estilo_total_label))
        elementos.append(Paragraph(f"IVA: ${presupuesto['iva']:,.0f}", estilo_total_label))
        elementos.append(Spacer(1, 2*mm))
        elementos.append(HRFlowable(width="40%", thickness=1, color=CYAN_PRIMARIO, hAlign='RIGHT'))
        elementos.append(Paragraph(f"TOTAL: ${presupuesto['total']:,.0f}", estilo_total_final))
        
        elementos.append(Spacer(1, 15*mm))
        
        # Nota al pie
        estilo_nota = ParagraphStyle(
            'Nota',
            parent=estilos['Normal'],
            fontSize=8,
            textColor=colors.gray,
            alignment=0
        )
        elementos.append(Paragraph("• Los precios unitarios están expresados sin IVA.", estilo_nota))
        elementos.append(Paragraph("• El porcentaje de IVA puede ser 10.5% o 21% según el producto.", estilo_nota))
        elementos.append(Paragraph("• Este presupuesto no constituye una factura.", estilo_nota))
        
        elementos.append(Spacer(1, 10*mm))
        
        # Pie con contacto
        elementos.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#E0E0E0')))
        estilo_pie = ParagraphStyle(
            'Pie',
            parent=estilos['Normal'],
            fontSize=9,
            textColor=CYAN_OSCURO,
            alignment=1,
            spaceBefore=10
        )
        elementos.append(Paragraph("GRUPO SER - Seguridad Electrónica | www.seguridadrosario.com", estilo_pie))
        
        doc.build(elementos)
        
        # Verificar que el archivo se creó
        if os.path.exists(ruta_archivo):
            tamanio = os.path.getsize(ruta_archivo)
            print(f'✅ PDF creado físicamente: {ruta_archivo} ({tamanio} bytes)')
        else:
            print(f'❌ ERROR: El archivo PDF no se creó en {ruta_archivo}')
            return None
        
        base_url = os.environ.get('REPLIT_URL', 'https://tu-replit-url.repl.co')
        url_pdf = f"{base_url}/presupuestos/{nombre_archivo}"
        
        if db is not None:
            db['presupuestos'].update_one(
                {'_id': presupuesto['_id']},
                {'$set': {'pdf_url': url_pdf, 'estado': 'enviado', 'actualizado': datetime.utcnow()}}
            )
        
        print(f'✅ PDF generado: {url_pdf}')
        return url_pdf
        
    except Exception as e:
        print(f'❌ Error generando PDF: {e}')
        import traceback
        traceback.print_exc()
        return None

@app.route('/presupuestos/<nombre_archivo>')
def servir_presupuesto(nombre_archivo):
    return send_from_directory(PRESUPUESTOS_DIR, nombre_archivo)

# ============== PROCESAMIENTO DE MENSAJES ==============

def detectar_confirmacion_presupuesto(texto):
    texto_lower = texto.lower().strip()
    confirmaciones = ['si', 'sí', 'dale', 'ok', 'confirmo', 'confirmado', 'acepto', 'va', 'listo', 'perfecto', 'de acuerdo']
    for confirmacion in confirmaciones:
        if texto_lower == confirmacion or texto_lower.startswith(confirmacion + ' ') or texto_lower.startswith(confirmacion + ','):
            return True
    return False

def detectar_intencion_compra(texto):
    texto_lower = texto.lower()
    palabras_clave = ['precio', 'costo', 'vale', 'cuanto', 'cuánto', 'stock', 'tienen', 'tenes', 'tenés', 
                      'disponible', 'presupuesto', 'cotizar', 'cotización', 'comprar', 'necesito', 
                      'busco', 'quiero', 'camara', 'cámara', 'dvr', 'nvr', 'alarma', 'sensor']
    for palabra in palabras_clave:
        if palabra in texto_lower:
            return True
    return False

def detectar_quiere_presupuesto(texto):
    """Detecta si el cliente quiere cerrar/confirmar un presupuesto"""
    texto_lower = texto.lower().strip()
    
    # Si menciona "presupuesto" explícitamente
    if 'presupuesto' in texto_lower:
        return True
    
    # Frases que indican "ya terminé de consultar"
    frases_fin = [
        'nada mas', 'nada más', 'no nada', 'no gracias', 'no gracais',
        'solo esto', 'solo eso', 'eso solo', 'es todo', 'era eso', 'eso era',
        'ya está', 'ya esta', 'listo', 'no por ahora', 'con eso', 
        'eso nomás', 'eso nomas', 'estoy bien', 'está bien', 'esta bien',
        'perfecto', 'bueno dale', 'dale listo', 'ok listo', 'ok eso',
        'no necesito más', 'no necesito mas', 'suficiente', 'con eso estoy',
        'nada por ahora', 'todo bien', 'eso sería todo', 'eso seria todo',
        'si eso', 'sí eso', 'solo esos', 'solo estos', 'nomas eso',
        'no mas', 'no más', 'ya no', 'eso nomás gracias', 'gracias eso',
        'si todo', 'sí todo', 'armalo', 'si armalo', 'dale armalo', 'si dale'
    ]
    
    for frase in frases_fin:
        if frase in texto_lower:
            return True
    
    # Respuestas cortas de cierre
    respuestas_cortas = ['no', 'nada', 'listo', 'dale', 'ok', 'bueno', 'perfecto', 'gracias']
    if texto_lower in respuestas_cortas:
        return True
    
    return False

def extraer_productos_del_mensaje(texto):
    try:
        respuesta = cliente_openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": """Extraé los productos mencionados en el mensaje.
                    Respondé SOLO con un JSON array de strings con términos de búsqueda.
                    Si no hay productos claros, respondé [].
                    Ejemplos: cámaras, DVR, NVR, sensores, alarmas, cables, fuentes."""
                },
                {"role": "user", "content": texto}
            ],
            temperature=0.1
        )
        
        contenido = respuesta.choices[0].message.content.strip()
        contenido = contenido.replace('```json', '').replace('```', '').strip()
        productos = json.loads(contenido)
        return productos if isinstance(productos, list) else []
        
    except Exception as e:
        print(f'❌ Error extrayendo productos: {e}')
        return []

def extraer_productos_de_historial(historial):
    """Extrae productos del historial para armar presupuesto"""
    try:
        if not historial:
            print('⚠️ Historial vacío')
            return []
        
        ultimos = historial[-12:] if len(historial) > 12 else historial
        texto_historial = "\n".join([f"{msg.get('rol', 'unknown')}: {msg.get('contenido', '')}" for msg in ultimos])
        
        print(f'📜 Historial para análisis:\n{texto_historial[:500]}...')
        
        respuesta = cliente_openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": """Analizá esta conversación de ventas y extraé los productos que el cliente quiere comprar.

IMPORTANTE: Buscá productos mencionados por el asistente con precios en CUALQUIER formato:
- "El kit AX Pro cuesta USD 85 + IVA"
- "El kit Ajax cuesta USD 105 + IVA (21%)"
- "La cámara tiene un costo de $5,000"
- "Tenemos el DVR a $15,000"

Respondé SOLO con un JSON array:
[{"nombre": "nombre del producto", "cantidad": 1, "precio": 85}]

REGLAS:
- Extraé el nombre del producto como aparece
- El precio es el número en USD o pesos (sin IVA, sin signos, sin puntos)
- Si el cliente pidió cantidad específica, usala. Si no, asumí 1
- Si hay varios productos mencionados, incluí TODOS
- Si no hay productos con precio, respondé []"""
                },
                {"role": "user", "content": texto_historial}
            ],
            temperature=0.1
        )
        
        contenido = respuesta.choices[0].message.content.strip()
        contenido = contenido.replace('```json', '').replace('```', '').strip()
        print(f'📦 GPT extrajo: {contenido}')
        
        productos = json.loads(contenido)
        
        if not productos:
            print('⚠️ GPT no encontró productos')
            return []
        
        # Completar datos faltantes
        productos_completos = []
        for prod in productos:
            precio = prod.get('precio', 0)
            
            # Si no tiene precio, buscar en API
            if precio == 0:
                resultados = buscar_en_api_productos(prod['nombre'])
                if resultados:
                    info = formatear_producto_para_respuesta(resultados[0])
                    precio = info['precio']
            
            if precio > 0:
                productos_completos.append({
                    'nombre': prod['nombre'],
                    'cantidad': prod.get('cantidad', 1),
                    'precio': precio,
                    'sku': prod.get('sku', 'N/A'),
                    'iva': prod.get('iva', 21)
                })
        
        print(f'✅ Productos finales: {productos_completos}')
        return productos_completos
        
    except Exception as e:
        print(f'❌ Error extrayendo productos del historial: {e}')
        import traceback
        traceback.print_exc()
        return []

def generar_respuesta_con_contexto(mensaje_usuario, historial, nombre_cliente, productos_encontrados=None, presupuesto_texto=None, info_cliente=None, cliente_mongo=None, es_verificado=True):
    try:
        contexto_productos = ""
        if productos_encontrados and len(productos_encontrados) > 0:
            contexto_productos = "\n\n=== PRODUCTOS ENCONTRADOS ===\n"
            for prod in productos_encontrados:
                info = formatear_producto_para_respuesta(prod)
                contexto_productos += f"- {info['nombre']}: USD {info['precio']} + IVA ({info['iva']}%)\n"
            contexto_productos += "===\n"
        
        contexto_presupuesto = ""
        if presupuesto_texto:
            contexto_presupuesto = f"\n\nPresupuesto generado:\n{presupuesto_texto}"
        
        historial_texto = ""
        if historial and len(historial) > 0:
            ultimos = historial[-6:] if len(historial) > 6 else historial
            for msg in ultimos:
                rol = "Cliente" if msg.get('rol') == 'usuario' else "Ovidio"
                historial_texto += f"{rol}: {msg.get('contenido', '')[:100]}\n"
        
        # Manejar info_cliente
        if isinstance(info_cliente, dict):
            contexto_cliente = info_cliente.get('texto', '')
            marcas_cliente = info_cliente.get('marcas', [])
            proveedores_cliente = info_cliente.get('proveedores', [])
            comportamiento = info_cliente.get('comportamiento_pago', {})
        else:
            contexto_cliente = info_cliente if info_cliente else ""
            marcas_cliente = []
            proveedores_cliente = []
            comportamiento = {}
        
        # Determinar tipo de saludo
        es_primera_vez = not historial or len(historial) == 0
        es_primer_mensaje_dia = True
        
        if historial and len(historial) > 0:
            ultimo_msg = historial[-1]
            fecha_ultimo = ultimo_msg.get('fecha')
            if fecha_ultimo:
                fecha_hoy = datetime.utcnow().date()
                if hasattr(fecha_ultimo, 'date'):
                    es_primer_mensaje_dia = fecha_ultimo.date() < fecha_hoy
                else:
                    es_primer_mensaje_dia = True
        
        # Instrucción de saludo según contexto
        if es_primera_vez:
            instruccion_saludo = f"""PRIMERA VEZ - PRESENTATE:
"¡Hola {nombre_cliente}! Soy Ovidio, asesor comercial de GRUPO SER. ¿En qué puedo ayudarte?"
Esta presentación es UNA SOLA VEZ."""
        elif es_primer_mensaje_dia:
            instruccion_saludo = f"""NUEVO DÍA:
"¡Hola {nombre_cliente}! ¿En qué puedo ayudarte hoy?"
NO te presentes, ya te conoce."""
        else:
            instruccion_saludo = """MISMO DÍA - NO SALUDES:
Continuá la conversación directamente, sin saludar."""
        
        # Info de comportamiento de pago
        info_pago = ""
        if comportamiento and comportamiento.get('perfil'):
            perfil = comportamiento.get('perfil')
            if perfil == 'excelente':
                info_pago = "CLIENTE EXCELENTE PAGADOR - Podés ofrecer cuenta corriente."
            elif perfil == 'riesgoso':
                info_pago = "CLIENTE CON DEUDA - Solo contado o transferencia anticipada."
        
        mensajes_sistema = f"""Sos Ovidio, asesor comercial de GRUPO SER (seguridad electrónica, Rosario).

{instruccion_saludo}

REGLAS CRÍTICAS:
1. MÁXIMO 2 LÍNEAS de WhatsApp (50-80 caracteres por línea)
2. Precios SIEMPRE en USD + IVA (ej: "USD 85 + IVA")
3. NUNCA incluir links ni URLs
4. UNA sola característica por producto
5. NO usar "che", "boludo", ni regionalismos
6. Ser directo, cordial y profesional

CIERRE DE MENSAJE - MUY IMPORTANTE:
- SIEMPRE terminar preguntando si necesita algo más
- NUNCA ofrecer presupuesto directamente, esperar a que diga "no" o "nada más"
- VARIAR la frase de cierre para no parecer robot. Ejemplos:
  * "¿Algo más?"
  * "¿Necesitás algo más?"
  * "¿Te busco otra cosa?"
  * "¿Qué más te muestro?"
  * "¿Algo más que necesite?"
- NO repetir la misma frase de cierre en mensajes consecutivos

CONOCIMIENTO TÉCNICO - USALO SIEMPRE:
- CÁMARAS: 2MP=1080p, 4MP=2K, 8MP=4K. Bullet=exterior, Domo=interior/discreto. ColorVu=color de noche. Hikvision=premium, Dahua=calidad/precio, Ajax=inalámbrico premium.
- DVR/NVR: DVR=cámaras analógicas, NVR=cámaras IP. Canales: 4, 8, 16, 32. 1TB≈7 días con 4 cámaras 2MP.
- ALARMAS: Ajax=inalámbrica premium, DSC=cableada confiable, Paradox=buena relación precio/calidad.
- CABLES: UTP Cat5e=100m máx, Cat6=mejor calidad. Coaxil RG59=cámaras analógicas.

COMPORTAMIENTO INTELIGENTE:
1. SIN STOCK → Ofrecé alternativa similar: "Ese no tenemos, pero el [alternativa] tiene specs similares a USD X + IVA. ¿Te sirve?"
2. PREGUNTA TÉCNICA → Respondé con conocimiento: "El DVR de 8 canales graba hasta 4 cámaras 4K o 8 cámaras 1080p. ¿Algo más?"
3. COMPARACIÓN → Compará brevemente: "El Hikvision es premium, el Dahua es similar pero más económico. ¿Cuál preferís?"
4. COMPLEMENTOS → Sugerí accesorios relacionados: "Para esas cámaras te recomiendo fuente de 12V y baluns. ¿Los agregamos?"

ACCESORIOS COMUNES:
- Cámaras → Fuentes 12V, Baluns, Conectores BNC, Cable UTP/Coaxil, Cajas de paso
- DVR/NVR → Disco duro (1TB, 2TB, 4TB), Cable HDMI, Mouse
- Alarmas → Sirenas, Teclados adicionales, Sensores extra, Batería de respaldo
- Cercos eléctricos → Aisladores, Alambre, Sirena, Batería

{info_pago}

{f"MARCAS PREFERIDAS: {', '.join(marcas_cliente)}" if marcas_cliente else ""}
{f"PROVEEDORES ACTUALES: {', '.join(proveedores_cliente)}" if proveedores_cliente else ""}

Cliente: {nombre_cliente}
Historial: {historial_texto if historial_texto else 'Primera conversación'}
{contexto_productos}
{contexto_presupuesto}
{f"Info adicional: {contexto_cliente}" if contexto_cliente else ""}"""

        respuesta = cliente_openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": mensajes_sistema},
                {"role": "user", "content": mensaje_usuario}
            ],
            temperature=0.7,
            max_tokens=150
        )
        
        return respuesta.choices[0].message.content
        
    except Exception as e:
        print(f'❌ Error generando respuesta: {e}')
        return f"Hola {nombre_cliente}, disculpá, tuve un inconveniente. ¿Podés repetirme tu consulta?"

# ============== WEBHOOK ==============

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

def obtener_cliente_cianbox(telefono):
    """
    Busca cliente primero en caché MongoDB, luego en API Cianbox si no encuentra.
    """
    if not CIANBOX_DISPONIBLE:
        return None
    
    try:
        # Primero buscar en caché local (mucho más rápido y confiable)
        cliente = buscar_cliente_en_cache(celular=telefono)
        if cliente:
            return cliente
        
        # Si no está en caché, buscar en API (por si es cliente nuevo)
        print(f'⚠️ Cliente no en caché, buscando en API Cianbox...')
        cliente = buscar_cliente_por_celular(telefono)
        return cliente
        
    except Exception as e:
        print(f'❌ Error obteniendo cliente Cianbox: {e}')
        return None

def verificar_cliente_por_cuit_email(texto, telefono):
    """
    Intenta verificar un cliente por CUIT o email mencionado en el mensaje.
    Busca primero en caché local, luego en API.
    """
    import re
    
    # Buscar CUIT en el texto (formato: XX-XXXXXXXX-X o solo números)
    cuit_pattern = r'\b(\d{2}[-]?\d{8}[-]?\d{1})\b'
    cuit_match = re.search(cuit_pattern, texto)
    
    # Buscar email en el texto
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    email_match = re.search(email_pattern, texto)
    
    if cuit_match:
        cuit = cuit_match.group(1)
        print(f'🔍 CUIT detectado en mensaje: {cuit}')
        
        # Buscar en caché primero
        cliente = buscar_cliente_en_cache(cuit=cuit)
        if cliente:
            return cliente
        
        # Si no está en caché, buscar en API
        from services.cianbox_service import buscar_cliente_por_cuit
        return buscar_cliente_por_cuit(cuit)
    
    if email_match:
        email = email_match.group(0)
        print(f'🔍 Email detectado en mensaje: {email}')
        
        # Buscar en caché primero
        cliente = buscar_cliente_en_cache(email=email)
        if cliente:
            return cliente
        
        # Si no está en caché, buscar en API
        from services.cianbox_service import buscar_cliente_por_email
        return buscar_cliente_por_email(email)
    
    return None

def vincular_cliente_cianbox(telefono, datos_cianbox):
    """Vincula el teléfono de WhatsApp con el cliente de Cianbox en MongoDB"""
    try:
        if db is None or not datos_cianbox:
            return
        
        db['clientes'].update_one(
            {'telefono': telefono},
            {
                '$set': {
                    'cianbox_id': datos_cianbox.get('id'),
                    'cianbox_verificado': True,
                    'nombre': datos_cianbox.get('razon_social') or datos_cianbox.get('nombre'),
                    'cuit': datos_cianbox.get('cuit', ''),
                    'email': datos_cianbox.get('email', ''),
                    'ubicacion': datos_cianbox.get('localidad', ''),
                    'actualizado': datetime.utcnow()
                }
            },
            upsert=True
        )
        print(f'✅ Cliente vinculado: WhatsApp {telefono} → Cianbox {datos_cianbox.get("razon_social")}')
        
    except Exception as e:
        print(f'❌ Error vinculando cliente: {e}')

def procesar_mensaje(remitente, texto, value):
    try:
        contactos = value.get('contacts', [{}])
        nombre_wa = contactos[0].get('profile', {}).get('name', 'Cliente') if contactos else 'Cliente'
        
        if db is None:
            conectar_mongodb()
        
        # Primero verificar si ya está vinculado en MongoDB
        cliente_mongo = db['clientes'].find_one({'telefono': remitente}) if db is not None else None
        
        if cliente_mongo and cliente_mongo.get('cianbox_verificado'):
            # Ya está verificado, usar datos guardados
            nombre = cliente_mongo.get('nombre') or nombre_wa
            es_cliente_verificado = True
            datos_cianbox = {'razon_social': nombre, 'localidad': cliente_mongo.get('ubicacion')}
            print(f'✅ Cliente ya vinculado en MongoDB: {nombre}')
        else:
            # Buscar en Cianbox por celular
            datos_cianbox = obtener_cliente_cianbox(remitente)
            
            if datos_cianbox:
                nombre = datos_cianbox.get('razon_social') or datos_cianbox.get('nombre') or nombre_wa
                es_cliente_verificado = True
                vincular_cliente_cianbox(remitente, datos_cianbox)
                print(f'✅ Cliente verificado en Cianbox: {nombre}')
            else:
                nombre = nombre_wa
                es_cliente_verificado = False
                print(f'⚠️ Cliente NO está en Cianbox: {nombre}')
            
            # Si no está verificado, intentar verificar por CUIT o email en el mensaje
            if not es_cliente_verificado:
                datos_cianbox = verificar_cliente_por_cuit_email(texto, remitente)
                if datos_cianbox:
                    nombre = datos_cianbox.get('razon_social') or datos_cianbox.get('nombre') or nombre_wa
                    es_cliente_verificado = True
                    vincular_cliente_cianbox(remitente, datos_cianbox)
                    print(f'✅ Cliente verificado y vinculado por CUIT/email: {nombre}')
        
        print(f'📝 Texto: {texto}')
        
        cliente = cliente_mongo  # Ya lo buscamos arriba
        historial = cliente.get('conversaciones', []) if cliente else []
        
        # Verificar presupuesto pendiente
        presupuesto_pendiente = obtener_presupuesto_pendiente(remitente)
        
        print(f'📋 Presupuesto pendiente: {presupuesto_pendiente is not None}')
        
        # CASO 1: Hay presupuesto pendiente y cliente confirma → generar PDF
        if presupuesto_pendiente and detectar_confirmacion_presupuesto(texto):
            print(f'🎯 Generando PDF para presupuesto #{presupuesto_pendiente.get("numero")}')
            url_pdf = generar_pdf_presupuesto(presupuesto_pendiente)
            if url_pdf:
                # Enviar PDF como archivo adjunto
                numero = presupuesto_pendiente.get('numero')
                nombre_archivo = f"presupuesto_{numero}.pdf"
                ruta_archivo = os.path.join(PRESUPUESTOS_DIR, nombre_archivo)
                
                resultado = enviar_documento_whatsapp(
                    remitente, 
                    ruta_archivo, 
                    f"Presupuesto_GRUPOSER_{numero}.pdf",
                    f"¡Listo {nombre}! 📄 Acá tenés tu presupuesto. ¿Algo más en que pueda ayudarte?"
                )
                
                if resultado:
                    guardar_conversacion(remitente, nombre, texto, f"[PDF enviado: Presupuesto #{numero}]")
                    return  # Ya enviamos el documento, no enviar mensaje de texto
                else:
                    respuesta = f"Disculpá {nombre}, hubo un error enviando el PDF. Lo revisamos y te lo enviamos."
            else:
                respuesta = f"Disculpá {nombre}, hubo un error generando el PDF. Lo revisamos y te lo enviamos."
        
        # CASO 2: Cliente quiere presupuesto o indica que terminó de consultar
        elif detectar_quiere_presupuesto(texto):
            print(f'🎯 Cliente quiere presupuesto / terminó de consultar')
            productos = extraer_productos_de_historial(historial)
            
            if productos and any(p['precio'] > 0 for p in productos):
                presupuesto = crear_presupuesto(remitente, nombre, productos)
                if presupuesto:
                    presupuesto_texto = formatear_presupuesto_texto(presupuesto)
                    respuesta = f"Perfecto {nombre}, te armo el presupuesto:\n\n{presupuesto_texto}\n\n¿Confirmás para enviarte el PDF?"
                    # Notificar al vendedor por email
                    notificar_vendedor_presupuesto(presupuesto)
                else:
                    respuesta = f"Disculpá {nombre}, no pude armar el presupuesto. ¿Podés decirme qué productos necesitás?"
            else:
                respuesta = f"Perfecto {nombre}. Si necesitás cotizar algo, avisame. ¡Estoy para ayudarte!"
        
        # CASO 3: Consulta normal
        else:
            productos_encontrados = []
            
            if detectar_intencion_compra(texto):
                print(f'🔍 Buscando productos...')
                terminos = extraer_productos_del_mensaje(texto)
                print(f'🔍 Términos: {terminos}')
                
                productos_sin_stock = []
                alternativas_encontradas = []
                
                for termino in terminos:
                    resultados = buscar_en_api_productos(termino)
                    print(f'🔍 "{termino}": {len(resultados)} resultados')
                    productos_encontrados.extend(resultados)
                    
                    # Detectar productos sin stock y buscar alternativas
                    for prod in resultados:
                        stock = prod.get('stock', prod.get('cantidad', 0))
                        if stock <= 0:
                            productos_sin_stock.append(prod)
                            # Buscar alternativas
                            alts = buscar_alternativas_producto(prod)
                            alternativas_encontradas.extend(alts)
                
                # Si hay productos sin stock, notificar a compras
                if productos_sin_stock and len(productos_sin_stock) > 0:
                    historial_conv = cliente.get('conversaciones', []) if cliente else []
                    for prod_sin_stock in productos_sin_stock:
                        nombre_prod = prod_sin_stock.get('name', prod_sin_stock.get('nombre', 'Producto'))
                        notificar_compras_sin_stock(nombre_prod, nombre, remitente, historial_conv)
                
                # Detectar marcas mencionadas
                marcas_detectadas = detectar_marca_preferida(texto)
                if marcas_detectadas:
                    actualizar_marcas_cliente(remitente, marcas_detectadas)
                
                # Detectar proveedores mencionados
                proveedores_detectados = detectar_proveedor_mencionado(texto)
                if proveedores_detectados:
                    actualizar_proveedores_cliente(remitente, proveedores_detectados)
                
                # Detectar preferencia de promos
                pref_promos = detectar_preferencia_promos(texto)
                if pref_promos:
                    actualizar_preferencia_promos(remitente, pref_promos)
                
                # Detectar fecha de nacimiento
                fecha_nac = detectar_fecha_nacimiento(texto)
                if fecha_nac:
                    actualizar_fecha_nacimiento(remitente, fecha_nac)
                
                # Agregar alternativas a productos encontrados
                if alternativas_encontradas:
                    productos_encontrados.extend(alternativas_encontradas)
            
            # Extraer y guardar datos personales de la conversación
            datos_actuales = cliente.get('datos_personales', {}) if cliente else {}
            datos_personales = extraer_datos_personales(texto, datos_actuales)
            if datos_personales and datos_personales != datos_actuales:
                actualizar_datos_cliente(remitente, datos_personales)
            
            # Generar respuesta con contexto del cliente
            info_cliente = formatear_contexto_cliente(cliente, datos_cianbox if es_cliente_verificado else None)
            
            # Si NO es cliente verificado, pedir CUIT (solo la primera vez)
            ya_pidio_cuit = False
            if cliente:
                ya_pidio_cuit = cliente.get('cuit_solicitado', False)
            
            if not es_cliente_verificado and not ya_pidio_cuit:
                # Marcar que ya pedimos CUIT
                if db is not None:
                    db['clientes'].update_one(
                        {'telefono': remitente},
                        {'$set': {'cuit_solicitado': True, 'actualizado': datetime.utcnow()}},
                        upsert=True
                    )
                respuesta = f"¡Hola {nombre}! Soy Ovidio de GRUPO SER. Para verificar tu cuenta y pasarte precios, ¿me pasás tu CUIT? Es solo por esta vez."
            else:
                respuesta = generar_respuesta_con_contexto(texto, historial, nombre, productos_encontrados, None, info_cliente, cliente, es_cliente_verificado)
        
        enviar_mensaje_whatsapp(remitente, respuesta)
        guardar_conversacion(remitente, nombre, texto, respuesta)
        
    except Exception as e:
        print(f'❌ Error procesando: {e}')
        import traceback
        traceback.print_exc()

def enviar_documento_whatsapp(destinatario, ruta_archivo, nombre_archivo, caption=""):
    """Envía un documento PDF por WhatsApp"""
    try:
        # Primero subir el archivo a Meta
        url_upload = f"https://graph.facebook.com/v21.0/{os.environ.get('PHONE_NUMBER_ID')}/media"
        
        headers = {
            'Authorization': f"Bearer {os.environ.get('WHATSAPP_TOKEN')}"
        }
        
        with open(ruta_archivo, 'rb') as f:
            files = {
                'file': (nombre_archivo, f, 'application/pdf'),
                'messaging_product': (None, 'whatsapp'),
                'type': (None, 'application/pdf')
            }
            response_upload = requests.post(url_upload, headers=headers, files=files)
        
        if response_upload.status_code != 200:
            print(f'❌ Error subiendo PDF: {response_upload.text}')
            return None
        
        media_id = response_upload.json().get('id')
        print(f'✅ PDF subido, media_id: {media_id}')
        
        # Ahora enviar el documento
        url_send = f"https://graph.facebook.com/v21.0/{os.environ.get('PHONE_NUMBER_ID')}/messages"
        
        payload = {
            'messaging_product': 'whatsapp',
            'to': destinatario,
            'type': 'document',
            'document': {
                'id': media_id,
                'filename': nombre_archivo,
                'caption': caption
            }
        }
        
        headers_send = {
            'Authorization': f"Bearer {os.environ.get('WHATSAPP_TOKEN')}",
            'Content-Type': 'application/json'
        }
        
        response = requests.post(url_send, headers=headers_send, json=payload)
        print(f'✅ Documento enviado a {destinatario}')
        return response.json()
    
    except Exception as e:
        print(f'❌ Error enviando documento: {e}')
        import traceback
        traceback.print_exc()
        return None

def enviar_mensaje_whatsapp(destinatario, texto):
    try:
        url = f"https://graph.facebook.com/v21.0/{os.environ.get('PHONE_NUMBER_ID')}/messages"
        
        headers = {
            'Authorization': f"Bearer {os.environ.get('WHATSAPP_TOKEN')}",
            'Content-Type': 'application/json'
        }
        
        payload = {
            'messaging_product': 'whatsapp',
            'to': destinatario,
            'type': 'text',
            'text': {'body': texto}
        }
        
        response = requests.post(url, headers=headers, json=payload)
        print(f'✅ Mensaje enviado a {destinatario}')
        return response.json()
    
    except Exception as e:
        print(f'❌ Error enviando mensaje: {e}')
        return None

def enviar_plantilla_whatsapp(destinatario, nombre_plantilla, parametros):
    """
    Envía un mensaje usando una plantilla pre-aprobada de WhatsApp.
    Necesario para mensajes después de 24hs sin interacción.
    
    Args:
        destinatario: Número de teléfono
        nombre_plantilla: Nombre de la plantilla en Meta (ej: 'seguimiento_7dias')
        parametros: Lista de strings para las variables {{1}}, {{2}}, etc.
    """
    try:
        url = f"https://graph.facebook.com/v21.0/{os.environ.get('PHONE_NUMBER_ID')}/messages"
        
        headers = {
            'Authorization': f"Bearer {os.environ.get('WHATSAPP_TOKEN')}",
            'Content-Type': 'application/json'
        }
        
        # Construir componentes con parámetros
        components = []
        if parametros and len(parametros) > 0:
            body_parameters = [{"type": "text", "text": str(p)} for p in parametros]
            components.append({
                "type": "body",
                "parameters": body_parameters
            })
        
        payload = {
            'messaging_product': 'whatsapp',
            'to': destinatario,
            'type': 'template',
            'template': {
                'name': nombre_plantilla,
                'language': {'code': 'es_AR'},
                'components': components
            }
        }
        
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            print(f'✅ Plantilla {nombre_plantilla} enviada a {destinatario}')
            return response.json()
        else:
            print(f'❌ Error enviando plantilla: {response.status_code} - {response.text}')
            return None
    
    except Exception as e:
        print(f'❌ Error enviando plantilla: {e}')
        return None


def obtener_tema_ultima_consulta(conversaciones):
    """
    Extrae el tema principal de la última consulta del cliente usando GPT.
    """
    try:
        if not conversaciones or len(conversaciones) == 0:
            return "tu consulta"
        
        # Tomar últimos mensajes del usuario
        mensajes_usuario = [c.get('contenido', '') for c in conversaciones[-10:] if c.get('rol') == 'usuario']
        
        if not mensajes_usuario:
            return "tu consulta"
        
        texto = " | ".join(mensajes_usuario[-5:])
        
        respuesta = cliente_openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Extraé el tema principal de consulta en máximo 5 palabras. Ejemplos: 'cámaras para la obra', 'alarma para el local', 'DVR 8 canales'. Si no hay tema claro, respondé 'tu consulta'."
                },
                {"role": "user", "content": texto}
            ],
            temperature=0.3,
            max_tokens=20
        )
        
        tema = respuesta.choices[0].message.content.strip()
        return tema if tema else "tu consulta"
        
    except Exception as e:
        print(f'❌ Error extrayendo tema: {e}')
        return "tu consulta"


def obtener_mensaje_personal_lunes(cliente):
    """
    Genera un mensaje personalizado para el saludo del lunes basado en la memoria del cliente.
    """
    try:
        datos_personales = cliente.get('datos_personales', {})
        memoria = datos_personales.get('memoria_conversaciones', [])
        
        contexto = ""
        
        if datos_personales:
            if datos_personales.get('familia'):
                contexto += f"Familia: {datos_personales.get('familia')}. "
            if datos_personales.get('hobbies'):
                contexto += f"Hobbies: {datos_personales.get('hobbies')}. "
            if datos_personales.get('salud'):
                contexto += f"Salud: {datos_personales.get('salud')}. "
            if datos_personales.get('planes'):
                contexto += f"Planes: {datos_personales.get('planes')}. "
        
        if memoria and len(memoria) > 0:
            ultimos = memoria[-3:]
            for m in ultimos:
                contexto += f"{m.get('evento', '')}. "
        
        if not contexto.strip():
            return "¿Cómo estuvo el finde?"
        
        respuesta = cliente_openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": """Generá UNA pregunta corta y cálida para un cliente basándote en lo que sabés de él.
                    
Ejemplos:
- Si mencionó pesca → "¿Cómo te fue en la pesca?"
- Si tiene mamá enferma → "¿Cómo sigue tu mamá?"
- Si iba a viajar → "¿Qué tal el viaje?"
- Si no hay nada específico → "¿Cómo estuvo el finde?"

Máximo 8 palabras. Solo la pregunta, sin "Hola" ni introducción."""
                },
                {"role": "user", "content": f"Contexto del cliente: {contexto}"}
            ],
            temperature=0.7,
            max_tokens=30
        )
        
        mensaje = respuesta.choices[0].message.content.strip()
        return mensaje if mensaje else "¿Cómo estuvo el finde?"
        
    except Exception as e:
        print(f'❌ Error generando mensaje personal: {e}')
        return "¿Cómo estuvo el finde?"


def ejecutar_seguimiento_7dias():
    """
    Busca clientes que no interactuaron en 7 días y les envía seguimiento.
    """
    try:
        if db is None:
            return
        
        print('🔍 Buscando clientes para seguimiento 7 días...')
        
        hace_7_dias = datetime.utcnow() - timedelta(days=7)
        hace_8_dias = datetime.utcnow() - timedelta(days=8)
        
        # Clientes con última actividad entre 7 y 8 días (para no repetir)
        clientes = db['clientes'].find({
            'actualizado': {'$gte': hace_8_dias, '$lte': hace_7_dias},
            'seguimiento_enviado': {'$ne': True}
        })
        
        enviados = 0
        for cliente in clientes:
            telefono = cliente.get('telefono')
            nombre = cliente.get('nombre', 'Cliente')
            conversaciones = cliente.get('conversaciones', [])
            
            tema = obtener_tema_ultima_consulta(conversaciones)
            
            # Enviar plantilla
            resultado = enviar_plantilla_whatsapp(telefono, 'seguimiento_7dias', [nombre, tema])
            
            if resultado:
                # Marcar como enviado
                db['clientes'].update_one(
                    {'_id': cliente['_id']},
                    {'$set': {'seguimiento_enviado': True, 'fecha_seguimiento': datetime.utcnow()}}
                )
                enviados += 1
        
        print(f'✅ Seguimiento 7 días: {enviados} mensajes enviados')
        
    except Exception as e:
        print(f'❌ Error en seguimiento 7 días: {e}')


def ejecutar_saludo_lunes():
    """
    Envía saludo personalizado los lunes a clientes activos.
    """
    try:
        if db is None:
            return
        
        print('🔍 Preparando saludos de lunes...')
        
        # Clientes con actividad en últimos 30 días
        hace_30_dias = datetime.utcnow() - timedelta(days=30)
        
        clientes = db['clientes'].find({
            'actualizado': {'$gte': hace_30_dias},
            'cianbox_verificado': True  # Solo clientes verificados
        })
        
        enviados = 0
        for cliente in clientes:
            telefono = cliente.get('telefono')
            nombre = cliente.get('nombre', 'Cliente')
            
            mensaje_personal = obtener_mensaje_personal_lunes(cliente)
            
            # Enviar plantilla
            resultado = enviar_plantilla_whatsapp(telefono, 'saludo_lunes', [nombre, mensaje_personal])
            
            if resultado:
                enviados += 1
        
        print(f'✅ Saludo lunes: {enviados} mensajes enviados')
        
    except Exception as e:
        print(f'❌ Error en saludo lunes: {e}')


def ejecutar_recordatorio_presupuestos():
    """
    Envía recordatorio de presupuestos que vencen en 3 días.
    """
    try:
        if db is None:
            return
        
        print('🔍 Buscando presupuestos por vencer...')
        
        # Presupuestos que vencen en 3 días
        ahora = datetime.utcnow()
        
        presupuestos = db['presupuestos'].find({
            'estado': {'$in': ['pendiente_confirmacion', 'enviado']},
            'recordatorio_enviado': {'$ne': True}
        })
        
        enviados = 0
        for pres in presupuestos:
            fecha_creacion = pres.get('creado')
            validez = pres.get('validez_dias', 15)
            fecha_vencimiento = fecha_creacion + timedelta(days=validez)
            dias_restantes = (fecha_vencimiento - ahora).days
            
            # Enviar recordatorio si vence en 3 días o menos
            if 0 < dias_restantes <= 3:
                telefono = pres.get('telefono')
                nombre = pres.get('nombre_cliente', 'Cliente')
                numero = pres.get('numero')
                
                resultado = enviar_plantilla_whatsapp(
                    telefono, 
                    'recordatorio_presupuesto', 
                    [nombre, str(numero), str(dias_restantes)]
                )
                
                if resultado:
                    db['presupuestos'].update_one(
                        {'_id': pres['_id']},
                        {'$set': {'recordatorio_enviado': True}}
                    )
                    enviados += 1
        
        print(f'✅ Recordatorio presupuestos: {enviados} mensajes enviados')
        
    except Exception as e:
        print(f'❌ Error en recordatorio presupuestos: {e}')

def guardar_conversacion(telefono, nombre, mensaje, respuesta):
    try:
        if db is None:
            conectar_mongodb()
        
        ahora = datetime.utcnow()
        clientes = db['clientes']
        cliente = clientes.find_one({'telefono': telefono})
        
        if not cliente:
            clientes.insert_one({
                'telefono': telefono,
                'nombre': nombre,
                'cuit': '',
                'email': '',
                'rubro': '',
                'ubicacion': '',
                'estado': 'nuevo',
                'cianbox_id': None,
                'cianbox_verificado': False,
                'conversaciones': [
                    {'rol': 'usuario', 'contenido': mensaje, 'fecha': ahora},
                    {'rol': 'asistente', 'contenido': respuesta, 'fecha': ahora}
                ],
                'creado': ahora,
                'actualizado': ahora
            })
            print(f'👤 Cliente nuevo: {nombre}')
        else:
            # Solo actualizar nombre si NO está verificado en Cianbox
            update_fields = {'actualizado': ahora}
            if not cliente.get('cianbox_verificado'):
                update_fields['nombre'] = nombre
            
            clientes.update_one(
                {'telefono': telefono},
                {
                    '$push': {
                        'conversaciones': {
                            '$each': [
                                {'rol': 'usuario', 'contenido': mensaje, 'fecha': ahora},
                                {'rol': 'asistente', 'contenido': respuesta, 'fecha': ahora}
                            ]
                        }
                    },
                    '$set': update_fields
                }
            )
            print(f'👤 Cliente actualizado: {cliente.get("nombre", nombre)}')
            
    except Exception as e:
        print(f'❌ Error guardando: {e}')

@app.route('/')
def inicio():
    return '🤖 Ovidio Bot - GRUPO SER - Online'

@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'service': 'ovidio-bot'}), 200

@app.route('/sync-cianbox', methods=['POST'])
def sync_cianbox_endpoint():
    """Endpoint para disparar sincronización manual de Cianbox"""
    resultado = sincronizar_clientes_cianbox()
    if resultado:
        return jsonify({'status': 'ok', 'message': 'Sincronización completada'}), 200
    else:
        return jsonify({'status': 'error', 'message': 'Error en sincronización'}), 500

@app.route('/sync-cianbox-status')
def sync_status():
    """Ver estado de la última sincronización"""
    try:
        if db is None:
            return jsonify({'status': 'error', 'message': 'MongoDB no conectado'}), 500
        
        coleccion = db['clientes_cianbox']
        count = coleccion.count_documents({})
        ultimo = coleccion.find_one(sort=[('sincronizado', -1)])
        
        return jsonify({
            'status': 'ok',
            'total_clientes': count,
            'ultima_sincronizacion': ultimo.get('sincronizado').isoformat() if ultimo else None
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    limpiar_pdfs_viejos()
    conectar_mongodb()
    if CIANBOX_DISPONIBLE:
        inicializar_cianbox()
        # Sincronizar clientes de Cianbox al arrancar (si el caché está vacío)
        if db is not None:
            cache_count = db['clientes_cianbox'].count_documents({})
            if cache_count == 0:
                print('📥 Caché vacío, sincronizando clientes de Cianbox...')
                sincronizar_clientes_cianbox()
            else:
                print(f'📦 Caché con {cache_count} clientes de Cianbox')
            # Iniciar todos los crons
            iniciar_cron_sincronizacion()
            iniciar_cron_seguimientos()
            iniciar_cron_lunes()
            iniciar_cron_cumpleanos()
    port = int(os.environ.get('PORT', 3000))
    print(f'🚀 Ovidio corriendo en puerto {port}')
    app.run(host='0.0.0.0', port=port, debug=False)
