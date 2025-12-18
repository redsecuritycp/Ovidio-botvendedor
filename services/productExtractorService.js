const axios = require('axios');

async function extractProduct(messageText, conversationHistory = []) {
  try {
    // Construir contexto de la conversación
    let conversationContext = '';
    if (conversationHistory.length > 0) {
      const lastMessages = conversationHistory.slice(-6);
      conversationContext = lastMessages.map(msg => 
        `${msg.role === 'user' ? 'Cliente' : 'Ovidio'}: ${msg.content}`
      ).join('\n');
    }

    const response = await axios.post(
      'https://api.openai.com/v1/chat/completions',
      {
        model: 'gpt-4o-mini',
        messages: [
          {
            role: 'system',
            content: `Extraés términos de búsqueda de productos de seguridad electrónica.

CONTEXTO DE LA CONVERSACIÓN:
${conversationContext || '(Primera interacción)'}

REGLAS:
1. Si mencionan producto directo: "cámara IP" → "cámara IP"
2. Si dan características después de que Ovidio preguntó:
   - "exterior, 2mp, dahua" (hablaban de cámaras) → "cámara dahua 2mp"
   - "4 canales, hikvision" (hablaban de DVR) → "dvr hikvision 4"
3. SIEMPRE incluí marca si la mencionan
4. SIEMPRE incluí características técnicas (2mp, 4mp, exterior, etc)
5. Saludos sin producto → ""

Respondé SOLO con los términos de búsqueda.`
          },
          {
            role: 'user',
            content: messageText
          }
        ],
        temperature: 0.3,
        max_tokens: 100
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
    
    // Limpiar respuestas vacías
    if (extractedProduct === '""' || extractedProduct === "''" || 
        extractedProduct === '(ninguno)' || extractedProduct === 'ninguno') {
      extractedProduct = '';
    }
    extractedProduct = extractedProduct.replace(/^["']|["']$/g, '');
    
    console.log(`🔍 Mensaje original: "${messageText}"`);
    console.log(`📦 Producto extraído: "${extractedProduct}"`);
    
    return extractedProduct;
  } catch (error) {
    console.error('❌ Error extrayendo producto:', error.message);
    return '';
  }
}

module.exports = { extractProduct };