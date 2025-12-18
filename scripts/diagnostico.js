const axios = require('axios');
require('dotenv').config();

console.log('=== DIAGNÓSTICO OVIDIO ===\n');

// 1. Verificar variables de entorno
console.log('📋 VARIABLES DE ENTORNO:');
console.log('- OPENAI_API_KEY:', process.env.OPENAI_API_KEY ? '✅ Configurada' : '❌ FALTA');
console.log('- WHATSAPP_TOKEN:', process.env.WHATSAPP_TOKEN ? '✅ Configurada' : '❌ FALTA');
console.log('- PHONE_NUMBER_ID:', process.env.PHONE_NUMBER_ID ? '✅ Configurada' : '❌ FALTA');
console.log('- MONGODB_URI:', process.env.MONGODB_URI ? '✅ Configurada' : '❌ FALTA');
console.log('- API_BASE_URL:', process.env.API_BASE_URL ? '✅ Configurada' : '❌ FALTA');
console.log('- VERIFY_TOKEN:', process.env.VERIFY_TOKEN ? '✅ Configurada' : '❌ FALTA');

// 2. Probar OpenAI
async function testOpenAI() {
  console.log('\n🧠 PROBANDO OPENAI...');
  try {
    const response = await axios.post(
      'https://api.openai.com/v1/chat/completions',
      {
        model: 'gpt-4o-mini',
        messages: [{ role: 'user', content: 'Decí hola' }],
        max_tokens: 10
      },
      {
        headers: {
          'Authorization': `Bearer ${process.env.OPENAI_API_KEY}`,
          'Content-Type': 'application/json'
        },
        timeout: 10000
      }
    );
    console.log('✅ OpenAI funciona:', response.data.choices[0].message.content);
  } catch (error) {
    console.log('❌ OpenAI ERROR:', error.response?.data?.error?.message || error.message);
  }
}

// 3. Probar API de stock
async function testStockAPI() {
  console.log('\n📦 PROBANDO API DE STOCK...');
  const API_BASE = process.env.API_BASE_URL || 'https://seguridadrosario.com/IDSRBE/Productos/ConsProductos';
  console.log('URL:', API_BASE);
  
  try {
    const response = await axios.get(API_BASE, {
      params: {
        Producto: 'camara',
        CategoriaId: 0,
        MarcaId: 0,
        OrdenId: 2,
        SucursalId: 2,
        Oferta: false
      },
      timeout: 10000
    });
    console.log('✅ API Stock funciona. Productos encontrados:', response.data?.producto?.length || 0);
  } catch (error) {
    console.log('❌ API Stock ERROR:', error.message);
  }
}

// 4. Probar MongoDB
async function testMongoDB() {
  console.log('\n🗄️ PROBANDO MONGODB...');
  const mongoose = require('mongoose');
  try {
    await mongoose.connect(process.env.MONGODB_URI, { serverSelectionTimeoutMS: 5000 });
    console.log('✅ MongoDB conectado');
    await mongoose.disconnect();
  } catch (error) {
    console.log('❌ MongoDB ERROR:', error.message);
  }
}

// Ejecutar todo
async function runDiagnostics() {
  await testOpenAI();
  await testStockAPI();
  await testMongoDB();
  console.log('\n=== FIN DIAGNÓSTICO ===');
  process.exit(0);
}

runDiagnostics();









