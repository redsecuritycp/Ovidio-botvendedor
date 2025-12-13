const axios = require('axios');

async function extractProduct(messageText) {
  try {
    const response = await axios.post(
      'https://api.openai.com/v1/chat/completions',
      {
        model: 'gpt-4o-mini',
        messages: [
          {
            role: 'system',
            content: `Sos un asistente que extrae nombres de productos de mensajes de clientes de una empresa de seguridad electrónica.

REGLAS:
- Extraé SOLO el nombre del producto (sin saludos, sin "necesito", sin verbos)
- Ejemplos:
  * "Hola, necesito una cámara IP" → "cámara IP"
  * "che querría una alarma Ajax" → "alarma Ajax"
  * "disco duro 2TB" → "disco duro 2TB"
  * "tienen DVR Hikvision?" → "DVR Hikvision"
  * "hola" → ""
  * "buenos días" → ""
  * "gracias" → ""
  * "ok perfecto" → ""
- Si NO hay producto en el mensaje, respondé con string vacío ""
- Respondé SOLO con el nombre del producto, nada más`
          },
          {
            role: 'user',
            content: messageText
          }
        ],
        temperature: 0.3,
        max_tokens: 50
      },
      {
        headers: {
          'Authorization': `Bearer ${process.env.OPENAI_API_KEY}`,
          'Content-Type': 'application/json'
        },
        timeout: 10000
      }
    );

    let extractedProduct = response.data.choices[0].message.content.trim();
    
    // Limpiar si GPT devuelve "" literalmente
    if (extractedProduct === '""' || extractedProduct === "''") {
      extractedProduct = '';
    }
    
    console.log(`🔍 Mensaje original: "${messageText}"`);
    console.log(`📦 Producto extraído: "${extractedProduct}"`);
    
    return extractedProduct;
  } catch (error) {
    console.error('❌ Error extrayendo producto:', error.message);
    return '';
  }
}

module.exports = { extractProduct };
