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
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

try:
    from services.cianbox_service import buscar_cliente_por_celular, inicializar_cianbox
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
    
    if partes:
        return "\n".join(partes)
    
    return ""

# ============== FUNCIONES DE STOCK ==============

def buscar_en_api_productos(termino_busqueda):
    """Busca productos en la API de seguridadrosario.com"""
    try:
        api_base = os.environ.get('API_BASE_URL', 'https://seguridadrosario.com')
        url = f"{api_base}/api/products/search?q={termino_busqueda}"
        
        headers = {
            'Accept': 'application/json',
            'User-Agent': 'Ovidio-Bot/1.0'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            datos = response.json()
            productos = datos if isinstance(datos, list) else datos.get('products', datos.get('data', []))
            return productos[:5]
        else:
            print(f'⚠️ API respondió con status {response.status_code}')
            return []
            
    except Exception as e:
        print(f'❌ Error buscando en API: {e}')
        return []

def formatear_producto_para_respuesta(producto):
    """Formatea un producto para mostrar al cliente"""
    nombre = producto.get('name', producto.get('nombre', 'Producto'))
    precio = producto.get('price', producto.get('precio', 0))
    stock = producto.get('stock', producto.get('cantidad', 0))
    sku = producto.get('sku', producto.get('codigo', ''))
    iva = producto.get('iva', 21)
    
    estado_stock = "✅ Disponible" if stock > 0 else "❌ Sin stock"
    
    return {
        'nombre': nombre,
        'precio': precio,
        'stock': stock,
        'sku': sku,
        'iva': iva,
        'estado': estado_stock,
        'texto': f"• {nombre}\n  Precio: ${precio:,.0f} + IVA ({iva}%)\n  Stock: {estado_stock}\n  Código: {sku}"
    }

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

def generar_respuesta_con_contexto(mensaje_usuario, historial, nombre_cliente, productos_encontrados=None, presupuesto_texto=None, info_cliente=None):
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
        
        contexto_cliente = info_cliente if info_cliente else ""
        
        mensajes_sistema = f"""Sos Ovidio, asesor comercial de GRUPO SER (seguridad electrónica, Rosario).
Vendés SOLO a instaladores/empresas (B2B), no a consumidores finales.

REGLAS ESTRICTAS:
1. Respuestas de MÁXIMO 2 líneas de WhatsApp
2. Precios SIEMPRE en USD + IVA (ej: "USD 85 + IVA 21%")
3. NUNCA incluir links ni URLs
4. Si mostrás un producto, agregar UNA característica breve
5. Terminar variando entre: "¿Algo más?", "¿Necesitás algo más?", "¿Te interesa algo más?", "¿Qué más necesitás?"
6. NO usar "che", "boludo"
7. Ser cordial y MUY humano

MEMORIA PERSONAL - MUY IMPORTANTE:
Si tenés memoria de conversaciones anteriores (familia, salud, planes, trabajo), 
usala naturalmente para conectar. Ejemplos:
- Si sabés que su padre estaba enfermo: "¿Cómo sigue tu viejo?"
- Si sabés que fue a pescar: "¿Qué tal la pesca?"
- Si tenía una obra: "¿Cómo va esa obra?"
No fuerces la pregunta, pero si viene al caso, preguntá.

EJEMPLO DE RESPUESTA CON VÍNCULO:
"¡Hola! El DVR 8ch está USD 95 + IVA. ¿Cómo sigue tu viejo, todo bien?"

Cliente: {nombre_cliente}
{contexto_cliente}
Historial: {historial_texto if historial_texto else 'Primera conversación'}
{contexto_productos}
{contexto_presupuesto}"""

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
    """Busca cliente completo en Cianbox por teléfono"""
    if not CIANBOX_DISPONIBLE:
        print('⚠️ Cianbox no disponible')
        return None
    try:
        tel_limpio = telefono.replace('+', '').replace(' ', '').replace('-', '')
        if tel_limpio.startswith('549'):
            tel_limpio = tel_limpio[3:]
        elif tel_limpio.startswith('54'):
            tel_limpio = tel_limpio[2:]
        
        print(f'🔍 Buscando en Cianbox: {tel_limpio}')
        cliente = buscar_cliente_por_celular(tel_limpio)
        if cliente:
            print(f'✅ Cianbox encontró: {cliente.get("razon_social")}')
            return cliente
        print(f'⚠️ Cianbox: No se encontró cliente con celular {tel_limpio}')
        return None
    except Exception as e:
        print(f'❌ Error buscando en Cianbox: {e}')
        return None

def verificar_cliente_por_cuit_email(texto, telefono):
    """Intenta verificar cliente por CUIT o email mencionado en el mensaje"""
    try:
        if not CIANBOX_DISPONIBLE:
            return None
        
        # Buscar CUIT (11 dígitos)
        import re
        cuit_match = re.search(r'\b(\d{2}-?\d{8}-?\d{1})\b', texto)
        if cuit_match:
            cuit = cuit_match.group(1).replace('-', '')
            from services.cianbox_service import buscar_cliente_por_cuit
            cliente = buscar_cliente_por_cuit(cuit)
            if cliente:
                print(f'✅ Cliente verificado por CUIT: {cliente.get("razon_social")}')
                return cliente
        
        # Buscar email
        email_match = re.search(r'\b[\w.-]+@[\w.-]+\.\w+\b', texto)
        if email_match:
            email = email_match.group(0)
            from services.cianbox_service import buscar_cliente_por_email
            cliente = buscar_cliente_por_email(email)
            if cliente:
                print(f'✅ Cliente verificado por email: {cliente.get("razon_social")}')
                return cliente
        
        return None
        
    except Exception as e:
        print(f'❌ Error verificando cliente: {e}')
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
                
                for termino in terminos:
                    resultados = buscar_en_api_productos(termino)
                    print(f'🔍 "{termino}": {len(resultados)} resultados')
                    productos_encontrados.extend(resultados)
            
            # Extraer y guardar datos personales de la conversación
            datos_actuales = cliente.get('datos_personales', {}) if cliente else {}
            datos_personales = extraer_datos_personales(texto, datos_actuales)
            if datos_personales and datos_personales != datos_actuales:
                actualizar_datos_cliente(remitente, datos_personales)
            
            # Generar respuesta con contexto del cliente
            info_cliente = formatear_contexto_cliente(cliente, datos_cianbox if es_cliente_verificado else None)
            
            # Si NO es cliente verificado y pregunta por precios, pedir que se identifique
            if not es_cliente_verificado and detectar_intencion_compra(texto):
                respuesta = f"¡Hola {nombre}! Para pasarte precios necesito verificar tu cuenta. ¿Me pasás tu CUIT o el email con el que estás registrado?"
            else:
                respuesta = generar_respuesta_con_contexto(texto, historial, nombre, productos_encontrados, None, info_cliente)
        
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
                    '$set': {'actualizado': ahora, 'nombre': nombre}
                }
            )
            print(f'👤 Cliente actualizado: {nombre}')
            
    except Exception as e:
        print(f'❌ Error guardando: {e}')

@app.route('/')
def inicio():
    return '🤖 Ovidio Bot - GRUPO SER - Online'

@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'service': 'ovidio-bot'}), 200

if __name__ == '__main__':
    limpiar_pdfs_viejos()
    conectar_mongodb()
    if CIANBOX_DISPONIBLE:
        inicializar_cianbox()
    port = int(os.environ.get('PORT', 3000))
    print(f'🚀 Ovidio corriendo en puerto {port}')
    app.run(host='0.0.0.0', port=port, debug=False)
