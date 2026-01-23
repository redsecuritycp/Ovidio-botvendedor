import os
from flask import Flask, request, jsonify, send_from_directory
from pymongo import MongoClient
from datetime import datetime
from openai import OpenAI
import requests
import json
import re
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.units import mm
import uuid

app = Flask(__name__)

cliente_mongo = None
db = None
cliente_openai = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))

# Crear carpeta para presupuestos si no existe
PRESUPUESTOS_DIR = os.path.join(os.path.dirname(__file__), 'presupuestos')
if not os.path.exists(PRESUPUESTOS_DIR):
    os.makedirs(PRESUPUESTOS_DIR)

def conectar_mongodb():
    global cliente_mongo, db
    try:
        cliente_mongo = MongoClient(os.environ.get('MONGODB_URI'))
        db = cliente_mongo['ovidio_db']
        print('✅ MongoDB conectado')
        return db
    except Exception as e:
        print(f'❌ Error MongoDB: {e}')
        return None

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
        
        # Generar número de presupuesto
        ultimo = presupuestos.find_one(sort=[('numero', -1)])
        numero = (ultimo.get('numero', 0) + 1) if ultimo else 1
        
        # Calcular totales
        subtotal = sum(item['precio'] * item['cantidad'] for item in items)
        
        # Calcular IVA por item (puede variar entre 10.5% y 21%)
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
    lineas.append("")
    lineas.append("_Precios expresados sin IVA. El IVA puede ser 10.5% o 21% según el producto._")
    
    return "\n".join(lineas)

def generar_pdf_presupuesto(presupuesto):
    """Genera el PDF del presupuesto y devuelve la URL"""
    try:
        # Nombre único para el archivo
        nombre_archivo = f"presupuesto_{presupuesto['numero']}_{uuid.uuid4().hex[:8]}.pdf"
        ruta_archivo = os.path.join(PRESUPUESTOS_DIR, nombre_archivo)
        
        # Crear el PDF
        doc = SimpleDocTemplate(ruta_archivo, pagesize=A4,
                                rightMargin=20*mm, leftMargin=20*mm,
                                topMargin=20*mm, bottomMargin=20*mm)
        
        elementos = []
        estilos = getSampleStyleSheet()
        
        # Estilo personalizado para título
        estilo_titulo = ParagraphStyle(
            'Titulo',
            parent=estilos['Heading1'],
            fontSize=18,
            spaceAfter=30,
            alignment=1  # Centrado
        )
        
        estilo_subtitulo = ParagraphStyle(
            'Subtitulo',
            parent=estilos['Normal'],
            fontSize=12,
            spaceAfter=20
        )
        
        # Encabezado
        elementos.append(Paragraph("GRUPO SER", estilo_titulo))
        elementos.append(Paragraph("Seguridad Electrónica", estilos['Normal']))
        elementos.append(Spacer(1, 20))
        
        # Datos del presupuesto
        elementos.append(Paragraph(f"<b>PRESUPUESTO N° {presupuesto['numero']}</b>", estilo_subtitulo))
        elementos.append(Paragraph(f"Fecha: {presupuesto['creado'].strftime('%d/%m/%Y')}", estilos['Normal']))
        elementos.append(Paragraph(f"Cliente: {presupuesto['nombre_cliente']}", estilos['Normal']))
        elementos.append(Paragraph(f"Válido por: {presupuesto['validez_dias']} días", estilos['Normal']))
        elementos.append(Spacer(1, 20))
        
        # Tabla de items
        datos_tabla = [['Producto', 'Cant.', 'Precio Unit.', 'IVA', 'Subtotal']]
        
        for item in presupuesto['items']:
            iva_porcentaje = item.get('iva', 21)
            subtotal_item = item['precio'] * item['cantidad']
            datos_tabla.append([
                item['nombre'],
                str(item['cantidad']),
                f"${item['precio']:,.0f}",
                f"{iva_porcentaje}%",
                f"${subtotal_item:,.0f}"
            ])
        
        tabla = Table(datos_tabla, colWidths=[80*mm, 15*mm, 30*mm, 15*mm, 30*mm])
        tabla.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a365d')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f7fafc')),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e2e8f0')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        
        elementos.append(tabla)
        elementos.append(Spacer(1, 20))
        
        # Totales
        estilo_total = ParagraphStyle(
            'Total',
            parent=estilos['Normal'],
            fontSize=11,
            alignment=2  # Derecha
        )
        
        elementos.append(Paragraph(f"Subtotal: ${presupuesto['subtotal']:,.0f}", estilo_total))
        elementos.append(Paragraph(f"IVA: ${presupuesto['iva']:,.0f}", estilo_total))
        elementos.append(Spacer(1, 10))
        
        estilo_total_final = ParagraphStyle(
            'TotalFinal',
            parent=estilos['Normal'],
            fontSize=14,
            fontName='Helvetica-Bold',
            alignment=2
        )
        elementos.append(Paragraph(f"TOTAL: ${presupuesto['total']:,.0f}", estilo_total_final))
        
        elementos.append(Spacer(1, 30))
        
        # Nota sobre IVA
        estilo_nota = ParagraphStyle(
            'Nota',
            parent=estilos['Normal'],
            fontSize=8,
            textColor=colors.gray
        )
        elementos.append(Paragraph("Nota: Los precios unitarios están expresados sin IVA. El porcentaje de IVA puede variar según el producto (10.5% o 21%).", estilo_nota))
        
        # Generar PDF
        doc.build(elementos)
        
        # Construir URL pública
        base_url = os.environ.get('REPLIT_URL', 'https://tu-replit-url.repl.co')
        url_pdf = f"{base_url}/presupuestos/{nombre_archivo}"
        
        # Actualizar presupuesto con URL del PDF
        if db:
            db['presupuestos'].update_one(
                {'_id': presupuesto['_id']},
                {'$set': {'pdf_url': url_pdf, 'estado': 'enviado', 'actualizado': datetime.utcnow()}}
            )
        
        print(f'✅ PDF generado: {url_pdf}')
        return url_pdf
        
    except Exception as e:
        print(f'❌ Error generando PDF: {e}')
        return None

# ============== RUTA PARA SERVIR PDFs ==============

@app.route('/presupuestos/<nombre_archivo>')
def servir_presupuesto(nombre_archivo):
    """Sirve los archivos PDF de presupuestos"""
    return send_from_directory(PRESUPUESTOS_DIR, nombre_archivo)

# ============== PROCESAMIENTO DE MENSAJES ==============

def detectar_confirmacion_presupuesto(texto):
    """Detecta si el usuario está confirmando un presupuesto"""
    texto_lower = texto.lower().strip()
    confirmaciones = ['si', 'sí', 'dale', 'ok', 'confirmo', 'confirmado', 'acepto', 'va', 'listo', 'perfecto', 'de acuerdo']
    
    for confirmacion in confirmaciones:
        if confirmacion in texto_lower:
            return True
    return False

def detectar_intencion_compra(texto):
    """Detecta si el mensaje indica intención de compra/consulta de productos"""
    texto_lower = texto.lower()
    palabras_clave = ['precio', 'costo', 'vale', 'cuanto', 'cuánto', 'stock', 'tienen', 'tenes', 'tenés', 
                      'disponible', 'presupuesto', 'cotizar', 'cotización', 'comprar', 'necesito', 
                      'busco', 'quiero', 'camara', 'cámara', 'dvr', 'nvr', 'alarma', 'sensor']
    
    for palabra in palabras_clave:
        if palabra in texto_lower:
            return True
    return False

def extraer_productos_del_mensaje(texto):
    """Usa GPT para extraer productos mencionados en el mensaje"""
    try:
        respuesta = cliente_openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": """Sos un extractor de productos para una empresa de seguridad electrónica.
                    Extraé los productos mencionados en el mensaje del cliente.
                    Respondé SOLO con un JSON array de strings con los nombres/términos de búsqueda.
                    Si no hay productos claros, respondé con un array vacío [].
                    Ejemplos de productos: cámaras, DVR, NVR, sensores, alarmas, cables, fuentes, etc."""
                },
                {"role": "user", "content": texto}
            ],
            temperature=0.1
        )
        
        contenido = respuesta.choices[0].message.content.strip()
        # Limpiar posibles caracteres extra
        contenido = contenido.replace('```json', '').replace('```', '').strip()
        productos = json.loads(contenido)
        return productos if isinstance(productos, list) else []
        
    except Exception as e:
        print(f'❌ Error extrayendo productos: {e}')
        return []

def generar_respuesta_con_contexto(mensaje_usuario, historial, nombre_cliente, productos_encontrados=None, presupuesto_texto=None):
    """Genera respuesta usando GPT con contexto del cliente"""
    try:
        # Construir contexto de productos si hay
        contexto_productos = ""
        if productos_encontrados:
            contexto_productos = "\n\nProductos encontrados en stock:\n"
            for prod in productos_encontrados:
                info = formatear_producto_para_respuesta(prod)
                contexto_productos += f"{info['texto']}\n"
        
        contexto_presupuesto = ""
        if presupuesto_texto:
            contexto_presupuesto = f"\n\nPresupuesto generado:\n{presupuesto_texto}"
        
        mensajes_sistema = f"""Sos Ovidio, el asistente comercial de GRUPO SER, empresa de seguridad electrónica en Rosario, Argentina.

REGLAS DE COMPORTAMIENTO:
- Sé cordial, profesional y concreto
- NO uses regionalismos como "che", "boludo", etc.
- Recordá el historial del cliente para no repetir preguntas
- Si el cliente pregunta por productos, mostrá los resultados del stock
- Los precios SIEMPRE se muestran SIN IVA, aclarando el porcentaje de IVA (puede ser 10.5% o 21% según el producto)
- Si el cliente muestra intención de compra, ofrecé armar un presupuesto
- Cuando muestres un presupuesto, preguntá si lo confirma para enviarle el PDF

DATOS DEL CLIENTE:
- Nombre: {nombre_cliente}

HISTORIAL RECIENTE:
{historial[-5:] if historial else 'Primera conversación'}
{contexto_productos}
{contexto_presupuesto}"""

        respuesta = cliente_openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": mensajes_sistema},
                {"role": "user", "content": mensaje_usuario}
            ],
            temperature=0.7,
            max_tokens=500
        )
        
        return respuesta.choices[0].message.content
        
    except Exception as e:
        print(f'❌ Error generando respuesta: {e}')
        return f"¡Hola {nombre_cliente}! Disculpá, estoy teniendo un inconveniente técnico. ¿Podés repetirme tu consulta?"

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

def procesar_mensaje(remitente, texto, value):
    try:
        contactos = value.get('contacts', [{}])
        nombre = contactos[0].get('profile', {}).get('name', 'Cliente') if contactos else 'Cliente'
        
        print(f'👤 Cliente: {nombre}')
        
        # Obtener historial del cliente
        if db is None:
            conectar_mongodb()
        
        cliente = db['clientes'].find_one({'telefono': remitente}) if db else None
        historial = cliente.get('conversaciones', []) if cliente else []
        
        # Verificar si hay presupuesto pendiente de confirmación
        presupuesto_pendiente = obtener_presupuesto_pendiente(remitente)
        
        if presupuesto_pendiente and detectar_confirmacion_presupuesto(texto):
            # El cliente confirmó el presupuesto, generar PDF
            url_pdf = generar_pdf_presupuesto(presupuesto_pendiente)
            if url_pdf:
                respuesta = f"¡Perfecto {nombre}! 📄 Aquí tenés tu presupuesto en PDF:\n\n{url_pdf}\n\nPodés descargarlo o compartirlo. ¿Hay algo más en lo que pueda ayudarte?"
            else:
                respuesta = f"Disculpá {nombre}, hubo un problema al generar el PDF. Nuestro equipo lo revisará y te lo enviamos a la brevedad."
        else:
            # Flujo normal
            productos_encontrados = []
            presupuesto_texto = None
            
            # Detectar si es consulta de productos
            if detectar_intencion_compra(texto):
                terminos = extraer_productos_del_mensaje(texto)
                
                for termino in terminos:
                    resultados = buscar_en_api_productos(termino)
                    productos_encontrados.extend(resultados)
                
                # Si encontramos productos y parece querer comprar, crear presupuesto
                if productos_encontrados and any(p in texto.lower() for p in ['presupuesto', 'cotizar', 'comprar', 'quiero']):
                    items_presupuesto = []
                    for prod in productos_encontrados[:3]:  # Máximo 3 productos
                        info = formatear_producto_para_respuesta(prod)
                        items_presupuesto.append({
                            'nombre': info['nombre'],
                            'precio': info['precio'],
                            'cantidad': 1,
                            'sku': info['sku'],
                            'iva': info['iva']
                        })
                    
                    if items_presupuesto:
                        presupuesto = crear_presupuesto(remitente, nombre, items_presupuesto)
                        if presupuesto:
                            presupuesto_texto = formatear_presupuesto_texto(presupuesto)
            
            # Generar respuesta con contexto
            respuesta = generar_respuesta_con_contexto(
                texto, 
                historial, 
                nombre, 
                productos_encontrados,
                presupuesto_texto
            )
            
            # Si se generó presupuesto, agregar pregunta de confirmación
            if presupuesto_texto:
                respuesta += f"\n\n{presupuesto_texto}\n\n¿Confirmás este presupuesto? Si decís que sí, te envío el PDF para que lo tengas. 📄"
        
        enviar_mensaje_whatsapp(remitente, respuesta)
        guardar_conversacion(remitente, nombre, texto, respuesta)
        
    except Exception as e:
        print(f'❌ Error procesando: {e}')
        import traceback
        traceback.print_exc()

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
                'razon_social': '',
                'email': '',
                'rubro': '',
                'ubicacion': '',
                'forma_pago': '',
                'marcas_preferidas': '',
                'estado': 'nuevo',
                'conversaciones': [
                    {'rol': 'usuario', 'contenido': mensaje, 'fecha': ahora},
                    {'rol': 'asistente', 'contenido': respuesta, 'fecha': ahora}
                ],
                'creado': ahora,
                'actualizado': ahora
            })
            print(f'👤 Cliente nuevo creado: {nombre}')
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
    conectar_mongodb()
    port = int(os.environ.get('PORT', 3000))
    print(f'🚀 Servidor Ovidio corriendo en puerto {port}')
    app.run(host='0.0.0.0', port=port, debug=False)
