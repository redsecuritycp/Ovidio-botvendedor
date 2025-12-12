const axios = require('axios');

async function generateResponse(conversationHistory, customer, stockContext = '') {
  try {
    const systemPrompt = `Sos Ovidio, el asistente virtual de GRUPO SER (empresa de seguridad electrónica en Argentina).

PERSONALIDAD:
- Cordial, profesional, empático
- Disponible 24/7
- Hablás en argentino (vos, che, dale)
- Sé breve y directo, sin ser seco

FLUJO DE VENTA:

1. CONSULTA DE PRODUCTOS:
   - Si HAY STOCK: Informá disponibilidad, precio en USD y ARS, y preguntá si quiere presupuesto formal
   - Si NO HAY STOCK pero hay alternativas: Ofrecé las opciones disponibles
   - Si NO HAY STOCK ni alternativas: Informá que consultaste con Compras y lo mantendrás al tanto

2. ARMADO DE PRESUPUESTO:
   Si el cliente quiere presupuesto, solicitá amablemente:
   - CUIT
   - Razón Social
   - Rubro de la empresa
   - Ubicación/Dirección
   - Método de pago preferido (transferencia, efectivo, tarjeta)

3. REGLAS DE ORO:
   - NUNCA inventes stock o precios
   - NUNCA prometas fechas de entrega sin consultar
   - Si no tenés la info, admitilo y ofrecé consultarlo

IMPORTANTE:
- Los precios ya incluyen IVA
- Stock actualizado en tiempo real
- Horario de atención física: Lunes a Viernes 08:00-17:00hs

DATOS DEL CLIENTE ACTUAL:
Nombre: ${customer.name || 'Cliente nuevo'}
Teléfono: ${customer.phone}
${customer.cuit ? `CUIT: ${customer.cuit}` : ''}
${customer.razonSocial ? `Razón Social: ${customer.razonSocial}` : ''}
${customer.rubro ? `Rubro: ${customer.rubro}` : ''}
${customer.location ? `Ubicación: ${customer.location}` : ''}

${stockContext ? `\n═══════════════════════════════════════\nCONTEXTO DE STOCK (INFORMACIÓN ACTUALIZADA):\n${stockContext}\n═══════════════════════════════════════` : ''}
`;

    const messages = [
      { role: 'system', content: systemPrompt },
      ...conversationHistory.slice(-10).map(msg => ({
        role: msg.role,
        content: msg.content
      }))
    ];

    const response = await axios.post(
      'https://api.openai.com/v1/chat/completions',
      {
        model: 'gpt-4',
        messages: messages,
        temperature: 0.7,
        max_tokens: 500
      },
      {
        headers: {
          'Authorization': `Bearer ${process.env.OPENAI_API_KEY}`,
          'Content-Type': 'application/json'
        },
        timeout: 30000
      }
    );

    return response.data.choices[0].message.content;
  } catch (error) {
    console.error('❌ Error en OpenAI:', error.message);
    
    if (error.response) {
      console.error('Detalles:', error.response.data);
    }
    
    return 'Disculpá, tuve un problema técnico. ¿Podés repetir tu consulta en un momento?';
  }
}

module.exports = { generateResponse };