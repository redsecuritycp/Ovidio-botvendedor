const axios = require('axios');

const BASE_URL = 'https://seguridadrosario.com';
const USERNAME = 'pansapablo@gmail.com';
const PASSWORD = 'Red24365!';

let sessionCookie = null;

async function login() {
  try {
    console.log('🔐 Intentando login en seguridadrosario.com...');
    
    const response = await axios.post(`${BASE_URL}/api/auth/login`, {
      email: USERNAME,
      password: PASSWORD
    }, {
      headers: { 'Content-Type': 'application/json' }
    });
    
    sessionCookie = response.headers['set-cookie'];
    console.log('✅ Login exitoso');
    return true;
  } catch (error) {
    console.log('⚠️ Login directo falló, usando inventario simulado');
    return false;
  }
}

async function buscarProducto(nombreProducto) {
  try {
    console.log(`🔍 Buscando: ${nombreProducto}`);
    
    // Por ahora retornamos null para usar el inventario simulado
    // Después configuramos el scraping real
    return null;
    
  } catch (error) {
    console.error('❌ Error buscando producto:', error.message);
    return null;
  }
}

module.exports = {
  login,
  buscarProducto
};