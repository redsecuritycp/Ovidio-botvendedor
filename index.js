require('dotenv').config();
const express = require('express');
const whatsappService = require('./services/whatsappService');
const aiService = require('./services/aiService');
const stockService = require('./services/stockService');
const emailService = require('./services/emailService');
const Customer = require('./models/Customer');
const connectDB = require('./config/database');

const app = express();
app.use(express.json());

// Conectar a MongoDB
connectDB();

// Endpoint de verificación del webhook
app.get('/webhook', (req, res) => {
  const mode = req.query['hub.mode'];
  const token = req.query['hub.verify_token'];
  const challenge = req.query['hub.challenge'];

  if (mode === 'subscribe' && token === process.env.VERIFY_TOKEN) {
    console.log('✅ Webhook verificado');
    res.status(200).send(challenge);
  } else {
    res.sendStatus(403);
  }
});

// Endpoint para recibir mensajes
app.post('/webhook', async (req, res) => {
  try {
    const body = req.body;

    if (body.object === 'whatsapp_business_account') {
      const entry = body.entry?.[0];
      const changes = entry?.changes?.[0];
      const value = changes?.value;

      if (value?.messages) {
        const message = value.messages[0];
        await processMessage(message, value);
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
  try {
    const from = message.from;
    const messageText = message.text?.body;

    if (!messageText) return;

    console.log(`📩 Mensaje de ${from}: ${messageText}`);

    // Buscar o crear cliente
    let customer = await Customer.findOne({ phone: from });
    
    if (!customer) {
      customer = new Customer({
        phone: from,
        name: value.contacts?.[0]?.profile?.name || 'Cliente',
        conversations: []
      });
    }

    // Guardar mensaje del cliente
    customer.conversations.push({
      role: 'user',
      content: messageText,
      timestamp: new Date()
    });

    // Verificar stock REAL desde seguridadrosario.com
    const stockInfo = await stockService.checkStock(messageText);

    let context = '';
    if (stockInfo) {
      if (stockInfo.disponible) {
        // HAY STOCK
        context = `
PRODUCTO ENCONTRADO:
- Nombre: ${stockInfo.nombre}
- Código: ${stockInfo.codigo}
- Stock disponible: ${stockInfo.stock} unidades
- Precio: USD ${stockInfo.precio_usd} / ARS $${stockInfo.precio_ars.toLocaleString('es-AR')}
- Marca: ${stockInfo.marca}
- Categoría: ${stockInfo.categoria}
${stockInfo.descripcion ? `- Descripción: ${stockInfo.descripcion}` : ''}

Informale al cliente sobre disponibilidad y precio. Preguntá si quiere presupuesto formal.
        `;
      } else {
        // NO HAY STOCK - Buscar alternativas
        const alternativas = await stockService.buscarAlternativas(
          stockInfo.categoria,
          stockInfo.marca
        );

        if (alternativas.length > 0) {
          // HAY ALTERNATIVAS
          context = `
PRODUCTO SIN STOCK: ${stockInfo.nombre}

ALTERNATIVAS DISPONIBLES en ${stockInfo.categoria}:
${alternativas.map((alt, i) => `
${i + 1}. ${alt.nombre}
   - Código: ${alt.codigo}
   - Marca: ${alt.marca}
   - Stock: ${alt.stock} unidades
   - Precio: USD ${alt.precio_usd} / ARS $${alt.precio_ars.toLocaleString('es-AR')}
`).join('\n')}

Ofrece estas alternativas al cliente de forma amable.
          `;
        } else {
          // NO HAY ALTERNATIVAS
          context = `
PRODUCTO SIN STOCK: ${stockInfo.nombre}
NO HAY ALTERNATIVAS DISPONIBLES en esta categoría.

Informá al cliente que:
1. No tenemos stock en este momento
2. Ya consultamos con el área de Compras
3. Lo contactaremos apenas tengamos novedades

Sé empático y ofrecé ayuda con otros productos.
          `;

          // Enviar email a Compras
          try {
            await emailService.sendPurchaseRequestEmail(
              stockInfo.nombre,
              customer,
              customer.conversations
            );
            console.log('📧 Email enviado a Compras');
          } catch (emailError) {
            console.error('❌ Error enviando email:', emailError.message);
          }
        }
      }
    }

    // Generar respuesta con OpenAI
    const aiResponse = await aiService.generateResponse(
      customer.conversations,
      customer,
      context
    );

    // Guardar respuesta de Ovidio
    customer.conversations.push({
      role: 'assistant',
      content: aiResponse,
      timestamp: new Date()
    });

    await customer.save();

    // Enviar respuesta por WhatsApp
    await whatsappService.sendMessage(from, aiResponse);

    console.log(`✅ Respuesta enviada a ${from}`);
  } catch (error) {
    console.error('❌ Error procesando mensaje:', error);
    
    // Respuesta de emergencia
    try {
      await whatsappService.sendMessage(
        message.from,
        'Disculpá, tuve un problema técnico. ¿Podés intentar de nuevo en un momento?'
      );
    } catch (sendError) {
      console.error('❌ Error enviando mensaje de emergencia:', sendError);
    }
  }
}

app.get('/', (req, res) => {
  res.send('🤖 Ovidio Bot - Online | Stock Real Integrado');
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`🚀 Servidor Ovidio corriendo en puerto ${PORT}`);
  console.log(`📊 Integración con seguridadrosario.com: ACTIVA`);
});