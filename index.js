require('dotenv').config();
const express = require('express');
const whatsappService = require('./services/whatsappService');
const aiService = require('./services/aiService');
const stockService = require('./services/stockService');
const productExtractor = require('./services/productExtractorService');
const Customer = require('./models/Customer');
const connectDB = require('./config/database');
const adminRoutes = require('./routes/admin');
const emailService = require('./services/emailService');

// Control de mensajes procesados (evita duplicados)
const processedMessages = new Set();

// Función para extraer datos del cliente del mensaje
function extraerDatosCliente(mensaje, customer) {
  const texto = mensaje.toLowerCase();
  let datosActualizados = false;
  
  // Detectar CUIT (formatos: 20-30643404-8, 20306434048, 20 30643404 8)
  const cuitMatch = mensaje.match(/\b(\d{2})[-\s]?(\d{8})[-\s]?(\d{1})\b/);
  if (cuitMatch && !customer.cuit) {
    customer.cuit = `${cuitMatch[1]}-${cuitMatch[2]}-${cuitMatch[3]}`;
    console.log(`💼 CUIT guardado: ${customer.cuit}`);
    datosActualizados = true;
  }
  
  // Detectar Razón Social
  const razonPatterns = [
    /raz[oó]n\s*social[:\s]+([^,\n]+)/i,
    /empresa[:\s]+([^,\n]+)/i,
    /\b([A-Z][a-zA-Z\s]+(S\.?R\.?L\.?|S\.?A\.?|S\.?A\.?S\.?))\b/
  ];
  for (const pattern of razonPatterns) {
    const match = mensaje.match(pattern);
    if (match && !customer.razonSocial) {
      customer.razonSocial = match[1].trim();
      console.log(`🏢 Razón Social guardada: ${customer.razonSocial}`);
      datosActualizados = true;
      break;
    }
  }
  
  // Detectar forma de pago
  const pagoPatterns = [
    /forma\s*de\s*pago[:\s]+([^,\n]+)/i,
    /pago[:\s]+(efectivo|transferencia|cheque[s]?|contado|tarjeta)/i,
    /\b(ch(?:eque)?\.?\s*\d+[-,\s]+\d+(?:[-,\s]+\d+)*)/i,
    /(contado|efectivo|transferencia|tarjeta)/i
  ];
  for (const pattern of pagoPatterns) {
    const match = mensaje.match(pattern);
    if (match && !customer.formaPago) {
      customer.formaPago = match[1].trim();
      console.log(`💳 Forma de pago guardada: ${customer.formaPago}`);
      datosActualizados = true;
      break;
    }
  }
  
  // Detectar email
  const emailMatch = mensaje.match(/\b([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b/);
  if (emailMatch && !customer.email) {
    customer.email = emailMatch[1];
    console.log(`📧 Email guardado: ${customer.email}`);
    datosActualizados = true;
  }
  
  // Detectar rubro
  const rubroPatterns = [
    /(?:me\s+dedico\s+a|trabajo\s+(?:en|con)|soy|rubro)[:\s]+([^,\n]+)/i,
    /(instalador|integrador|electricista|técnico|comercio|mayorista|minorista)/i
  ];
  for (const pattern of rubroPatterns) {
    const match = mensaje.match(pattern);
    if (match && !customer.rubro) {
      customer.rubro = match[1].trim();
      console.log(`🔧 Rubro guardado: ${customer.rubro}`);
      datosActualizados = true;
      break;
    }
  }
  
  // Detectar ubicación/ciudad
  const ubicacionPatterns = [
    /(?:soy\s+de|estoy\s+en|ubicad[oa]\s+en|ciudad)[:\s]+([^,\n]+)/i,
    /(?:rosario|buenos aires|córdoba|mendoza|santa fe|tucumán)/i
  ];
  for (const pattern of ubicacionPatterns) {
    const match = mensaje.match(pattern);
    if (match && !customer.ubicacion) {
      customer.ubicacion = (match[1] || match[0]).trim();
      console.log(`📍 Ubicación guardada: ${customer.ubicacion}`);
      datosActualizados = true;
      break;
    }
  }
  
  // Detectar marcas preferidas
  const marcas = ['hikvision', 'dahua', 'ajax', 'dsc', 'imou', 'ezviz', 'honeywell', 'epcom'];
  const marcasEncontradas = marcas.filter(m => texto.includes(m));
  if (marcasEncontradas.length > 0 && !customer.marcasPreferidas) {
    customer.marcasPreferidas = marcasEncontradas.join(', ');
    console.log(`🏷️ Marcas preferidas: ${customer.marcasPreferidas}`);
    datosActualizados = true;
  }
  
  return datosActualizados;
}

const app = express();
app.use(express.json());

connectDB();

app.get('/webhook', (req, res) => {
  const mode = req.query['hub.mode'];
  const token = req.query['hub.verify_token'];
  const challenge = req.query['hub.challenge'];

  if (mode === 'subscribe' && token === process.env.WHATSAPP_VERIFY_TOKEN) {
    console.log('✅ Webhook verificado');
    res.status(200).send(challenge);
  } else {
    res.sendStatus(403);
  }
});

app.post('/webhook', async (req, res) => {
  try {
    const body = req.body;

    if (body.object === 'whatsapp_business_account') {
      const entry = body.entry?.[0];
      const changes = entry?.changes?.[0];
      const value = changes?.value;

      if (value?.messages) {
        const message = value.messages[0];
        const messageId = message.id;
        
        // CONTROL DE DUPLICADOS
        if (processedMessages.has(messageId)) {
          console.log(`⚠️ Mensaje ${messageId} ya procesado, ignorando duplicado`);
          return res.sendStatus(200);
        }
        processedMessages.add(messageId);
        setTimeout(() => processedMessages.delete(messageId), 300000);
        
        // Responder inmediatamente a Meta para evitar reintentos
        res.sendStatus(200);
        
        // Procesar el mensaje de forma asíncrona
        processMessage(message, value).catch(err => {
          console.error('Error procesando mensaje:', err);
        });
        return;
      }

      res.sendStatus(200);
    } else {
      res.sendStatus(404);
    }
  } catch (error) {
    console.error('❌ Error en webhook:', error);
    res.sendStatus(500);
  }
});

async function processMessage(message, value) {
  const from = message.from;
  
  try {
    const messageText = message.text?.body;

    if (!messageText) {
      console.log('⚠️ Mensaje sin texto, ignorando');
      return;
    }

    console.log(`\n${'='.repeat(50)}`);
    console.log(`📩 Mensaje de ${from}: ${messageText}`);
    console.log(`${'='.repeat(50)}`);

    // Paso 1: Buscar/crear cliente
    console.log('🔄 Paso 1: Buscando cliente en MongoDB...');
    let customer = await Customer.findOne({ phone: from });
    
    if (!customer) {
      console.log('👤 Cliente nuevo, creando...');
      customer = new Customer({
        phone: from,
        name: value.contacts?.[0]?.profile?.name || 'Cliente',
        conversations: []
      });
    } else {
      console.log('👤 Cliente existente:', customer.name);
    }

    // Extraer y guardar datos del cliente
    const datosExtraidos = extraerDatosCliente(messageText, customer);
    if (datosExtraidos) {
      console.log(`📝 Datos del cliente actualizados en MongoDB`);
    }

    customer.conversations.push({
      role: 'user',
      content: messageText,
      timestamp: new Date()
    });

    // Paso 2: Extraer producto
    console.log('🔄 Paso 2: Extrayendo producto con GPT...');
    // Extraer producto del mensaje CON CONTEXTO de conversación
    const conversationHistory = customer.conversations.slice(-10);
    const productName = await productExtractor.extractProduct(messageText, conversationHistory);
    console.log(`📦 Producto extraído: "${productName || '(ninguno)'}"`);

    let stockInfo = null;
    let context = '';

    // Paso 3: Buscar stock si hay producto
    if (productName && productName.length > 0) {
      console.log('🔄 Paso 3: Consultando stock...');
      stockInfo = await stockService.checkStock(productName);
      console.log('📊 Stock info:', stockInfo ? 'encontrado' : 'no encontrado');

      if (stockInfo) {
        if (stockInfo.multiple && stockInfo.opciones) {
          // Múltiples opciones encontradas
          context = `
BÚSQUEDA: "${productName}"
ENCONTRÉ ${stockInfo.opciones.length} OPCIONES DISPONIBLES:

${stockInfo.opciones.map((op, i) => `
${i + 1}. ${op.nombre}
   - Código: ${op.codigo}
   - Marca: ${op.marca}
   - Stock: ${op.stock} unidades
   - Precio: USD ${op.precio_usd || 'N/A'} / ARS $${op.precio_ars ? Number(op.precio_ars).toLocaleString('es-AR') : 'N/A'}
`).join('')}

Presentá estas opciones al cliente de forma clara y preguntá cuál le interesa.
    `;
        } else if (stockInfo.disponible) {
          context = `
PRODUCTO ENCONTRADO:
- Nombre: ${stockInfo.nombre}
- Código: ${stockInfo.codigo}
- Stock disponible: ${stockInfo.stock} unidades
- Precio: USD ${stockInfo.precio_usd || 'N/A'} / ARS $${stockInfo.precio_ars ? Number(stockInfo.precio_ars).toLocaleString('es-AR') : 'N/A'}
- Marca: ${stockInfo.marca}
- Categoría: ${stockInfo.categoria}

Informá disponibilidad y precio. Preguntá si quiere presupuesto formal.
    `;
        } else {
          const alternativas = await stockService.buscarAlternativas(
            stockInfo.categoria,
            stockInfo.marca
          );

          if (alternativas && alternativas.length > 0) {
            context = `
PRODUCTO SIN STOCK: ${stockInfo.nombre}

ALTERNATIVAS DISPONIBLES:
${alternativas.map((alt, i) => `
${i + 1}. ${alt.nombre}
   - Código: ${alt.codigo}
   - Marca: ${alt.marca}
   - Stock: ${alt.stock} unidades
   - Precio: USD ${alt.precio_usd || 'N/A'} / ARS $${alt.precio_ars ? Number(alt.precio_ars).toLocaleString('es-AR') : 'N/A'}
`).join('\n')}

Ofrecé estas alternativas al cliente.
      `;
          } else {
            context = `
PRODUCTO SIN STOCK: ${stockInfo.nombre}
NO HAY ALTERNATIVAS.

Informá que:
1. No hay stock en este momento
2. Vas a consultar con Compras
3. Lo mantenés al tanto apenas tengas novedades
      `;
            // Notificar por email que no hay stock
            emailService.notificarSinStock(stockInfo.nombre, customer).catch(err => {
              console.error('Error enviando email de sin stock:', err);
            });
          }
        }
      } else {
        context = `
El cliente preguntó por "${productName}" pero NO se encontró en nuestro catálogo.
Respondé amablemente que no encontraste ese producto específico y preguntá si puede darte más detalles o si busca algo similar.
        `;
      }
    } else {
      context = `
El cliente envió un mensaje sin mencionar ningún producto específico.
Respondé de forma cordial y preguntá en qué podés ayudarlo. Somos GRUPO SER, empresa de seguridad electrónica.
      `;
    }

    // Paso 4: Generar respuesta con OpenAI
    console.log('🔄 Paso 4: Generando respuesta con OpenAI...');
    const aiResponse = await aiService.generateResponse(messageText, conversationHistory, context, customer);
    console.log('✅ Respuesta generada:', aiResponse.substring(0, 100) + '...');

    customer.conversations.push({
      role: 'assistant',
      content: aiResponse,
      timestamp: new Date()
    });

    // Paso 5: Guardar en MongoDB
    console.log('🔄 Paso 5: Guardando en MongoDB...');
    await customer.save();
    console.log('✅ Cliente guardado');

    // Paso 6: Enviar mensaje
    console.log('🔄 Paso 6: Enviando mensaje por WhatsApp...');
    await whatsappService.sendMessage(from, aiResponse);
    console.log(`✅ Respuesta enviada a ${from}`);
    console.log(`${'='.repeat(50)}\n`);

  } catch (error) {
    console.error(`\n${'❌'.repeat(25)}`);
    console.error('❌ ERROR EN processMessage:');
    console.error('❌ Mensaje:', error.message);
    console.error('❌ Stack:', error.stack);
    console.error(`${'❌'.repeat(25)}\n`);
    
    try {
      await whatsappService.sendMessage(
        from,
        'Disculpá, tuve un problema técnico. ¿Podés intentar de nuevo en un momento?'
      );
    } catch (sendError) {
      console.error('❌ Error enviando mensaje de emergencia:', sendError.message);
    }
  }
}

app.get('/', (req, res) => {
  res.send('🤖 Ovidio Bot - Online | Inteligencia Activa');
});

// Rutas del panel admin
app.use('/admin/api', adminRoutes);

// Servir panel admin estático
app.use('/admin', express.static('public/admin'));

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`🚀 Servidor Ovidio corriendo en puerto ${PORT}`);
  console.log(`📊 Integración con seguridadrosario.com: ACTIVA`);
  console.log(`🧠 Extractor de productos: ACTIVO`);
});