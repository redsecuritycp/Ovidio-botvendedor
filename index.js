require('dotenv').config();
const express = require('express');
const whatsappService = require('./services/whatsappService');
const aiService = require('./services/aiService');
const stockService = require('./services/stockService');
const productExtractor = require('./services/productExtractorService');
const Customer = require('./models/Customer');
const connectDB = require('./config/database');

const app = express();
app.use(express.json());

connectDB();

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
  const from = message.from;
  
  try {
    const messageText = message.text?.body;

    if (!messageText) return;

    console.log(`📩 Mensaje de ${from}: ${messageText}`);

    let customer = await Customer.findOne({ phone: from });
    
    if (!customer) {
      customer = new Customer({
        phone: from,
        name: value.contacts?.[0]?.profile?.name || 'Cliente',
        conversations: []
      });
    }

    customer.conversations.push({
      role: 'user',
      content: messageText,
      timestamp: new Date()
    });

    const productName = await productExtractor.extractProduct(messageText);

    let stockInfo = null;
    let context = '';

    if (productName && productName.length > 0) {
      console.log(`🛒 Buscando producto: "${productName}"`);
      stockInfo = await stockService.checkStock(productName);

      if (stockInfo) {
        if (stockInfo.disponible) {
          context = `
PRODUCTO ENCONTRADO:
- Nombre: ${stockInfo.nombre}
- Código: ${stockInfo.codigo}
- Stock disponible: ${stockInfo.stock} unidades
- Precio: USD ${stockInfo.precio_usd || 'N/A'} / ARS $${stockInfo.precio_ars ? Number(stockInfo.precio_ars).toLocaleString('es-AR') : 'N/A'}
- Marca: ${stockInfo.marca}
- Categoría: ${stockInfo.categoria}
${stockInfo.descripcion ? `- Descripción: ${stockInfo.descripcion}` : ''}

Informale al cliente sobre disponibilidad y precio. Preguntá si quiere presupuesto formal.
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

Ofrece estas alternativas al cliente de forma amable.
            `;
          } else {
            context = `
PRODUCTO SIN STOCK: ${stockInfo.nombre}
NO HAY ALTERNATIVAS DISPONIBLES.

Informá al cliente que:
1. No tenemos stock en este momento
2. Ya consultamos con el área de Compras
3. Lo contactaremos apenas tengamos novedades
            `;
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

    const conversationHistory = customer.conversations.slice(-10);
    const aiResponse = await aiService.generateResponse(conversationHistory, customer, context);

    customer.conversations.push({
      role: 'assistant',
      content: aiResponse,
      timestamp: new Date()
    });

    await customer.save();
    await whatsappService.sendMessage(from, aiResponse);

    console.log(`✅ Respuesta enviada a ${from}`);

  } catch (error) {
    console.error('❌ Error procesando mensaje:', error);
    
    try {
      await whatsappService.sendMessage(
        from,
        'Disculpá, tuve un problema técnico. ¿Podés intentar de nuevo en un momento?'
      );
    } catch (sendError) {
      console.error('❌ Error enviando mensaje de emergencia:', sendError);
    }
  }
}

app.get('/', (req, res) => {
  res.send('🤖 Ovidio Bot - Online | Inteligencia Activa');
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`🚀 Servidor Ovidio corriendo en puerto ${PORT}`);
  console.log(`📊 Integración con seguridadrosario.com: ACTIVA`);
  console.log(`🧠 Extractor de productos: ACTIVO`);
});