const axios = require('axios');

async function generateResponse(userMessage, conversationHistory, stockContext, customer) {
  const maxRetries = 3;
  let lastError = null;
  
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const systemPrompt = `Sos OVIDIO, asesor comercial EXPERTO de GRUPO SER, seguridad electrónica en Rosario.

PERSONALIDAD: Vendedor profesional, conocimiento técnico profundo, cordial pero CONCRETO, español rioplatense SIN "che".

CONOCIMIENTO TÉCNICO:
- CÁMARAS: 2MP=1080p, 4MP=2K, 8MP=4K. Bullet=exterior, Domo=interior. ColorVu=color de noche. Hikvision=premium, Dahua=calidad/precio.
- DVR/NVR: DVR=analógicas (coaxial), NVR=IP (red). XVR=híbrido. 1TB=7 días con 4 cámaras 2MP.
- DISCOS: WD Purple=videovigilancia, SSD=más rápido pero más caro.
- ALARMAS: Ajax=inalámbrica premium, DSC=cableada confiable.

FLUJO DE VENTA:
1. Entendé la necesidad del cliente
2. Recomendá productos específicos con precios y stock
3. Cuando pida presupuesto, pedí: CUIT, Razón Social, Forma de pago
4. Armá presupuestos detallados con totales

DATOS DEL CLIENTE (YA GUARDADOS):
Nombre: ${customer?.name || 'Cliente'}
Teléfono: ${customer?.phone || ''}
CUIT: ${customer?.cuit || 'No proporcionado'}
Razón Social: ${customer?.razonSocial || 'No proporcionada'}
Forma de pago: ${customer?.formaPago || 'No especificada'}
Rubro: ${customer?.rubro || ''}
Ubicación: ${customer?.ubicacion || ''}
Email: ${customer?.email || ''}
Marcas preferidas: ${customer?.marcasPreferidas || ''}

Si el cliente YA proporcionó CUIT/Razón Social/Forma de pago, NO los vuelvas a pedir. Usá los datos guardados.

STOCK DISPONIBLE:
${stockContext || 'Consultá stock cuando el cliente pida productos específicos.'}

REGLAS:
- Precios incluyen IVA
- Horario: Lun-Vie 8-17hs
- NUNCA repitas preguntas que ya hiciste
- Si el cliente ya dio datos, confirmalos y seguí adelante`;

      const messages = [{ role: 'system', content: systemPrompt }];

      // Historial reciente (últimos 8 mensajes para tener contexto pero no sobrecargar)
      if (conversationHistory && conversationHistory.length > 0) {
        const recentHistory = conversationHistory.slice(-8);
        for (const msg of recentHistory) {
          messages.push({
            role: msg.role === 'user' ? 'user' : 'assistant',
            content: msg.content
          });
        }
      }

      messages.push({ role: 'user', content: userMessage });

      console.log(`🤖 Llamando a OpenAI (intento ${attempt}/${maxRetries})...`);
      const startTime = Date.now();

      const response = await axios.post(
        'https://api.openai.com/v1/chat/completions',
        {
          model: 'gpt-4',
          messages: messages,
          temperature: 0.7,
          max_tokens: 1000
        },
        {
          headers: {
            'Authorization': `Bearer ${process.env.OPENAI_API_KEY}`,
            'Content-Type': 'application/json'
          },
          timeout: 120000  // 2 minutos de timeout
        }
      );

      const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
      console.log(`✅ OpenAI respondió en ${elapsed}s`);

      return response.data.choices[0].message.content;

    } catch (error) {
      lastError = error;
      console.error(`❌ Intento ${attempt}/${maxRetries} falló:`, error.message);
      
      if (attempt < maxRetries) {
        const waitTime = attempt * 3000; // 3s, 6s, 9s
        console.log(`🔄 Reintentando en ${waitTime/1000}s...`);
        await new Promise(resolve => setTimeout(resolve, waitTime));
      }
    }
  }
  
  console.error('❌ Todos los intentos fallaron:', lastError?.message);
  
  // Mensaje de error más útil
  if (lastError?.message?.includes('timeout')) {
    return 'Estoy procesando tu pedido que es bastante completo. Dame unos segundos más y volvé a escribirme "continuar" para que te pase el presupuesto.';
  }
  
  return 'Disculpá, tuve un problema técnico. ¿Podés repetirme tu consulta?';
}

module.exports = { generateResponse };