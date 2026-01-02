import os
from flask import Flask, request, jsonify
from pymongo import MongoClient
from datetime import datetime
import requests

app = Flask(__name__)

cliente_mongo = None
db = None

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
        
        respuesta = f'¡Hola {nombre}! Soy Ovidio de GRUPO SER. ¿En qué puedo ayudarte hoy?'
        
        enviar_mensaje_whatsapp(remitente, respuesta)
        guardar_conversacion(remitente, nombre, texto, respuesta)
        
    except Exception as e:
        print(f'❌ Error procesando: {e}')

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
                    '$set': {'actualizado': ahora}
                }
            )
            print(f'👤 Cliente actualizado: {nombre}')
            
    except Exception as e:
        print(f'❌ Error guardando: {e}')

@app.route('/')
def inicio():
    return '🤖 Ovidio Bot - Python - Online'

if __name__ == '__main__':
    conectar_mongodb()
    port = int(os.environ.get('PORT', 3000))
    print(f'🚀 Servidor Ovidio corriendo en puerto {port}')
    app.run(host='0.0.0.0', port=port, debug=False)
