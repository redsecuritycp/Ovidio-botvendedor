const axios = require('axios');

// API de tu web (desde Secrets)
const API_BASE = process.env.API_BASE_URL;
const API_USER = process.env.API_USERNAME;
const API_PASS = process.env.API_PASSWORD;

// Caché en memoria (1 hora)
let cache = {
  data: null,
  timestamp: null,
  ttl: 60 * 60 * 1000 // 1 hora en ms
};

/**
 * Consulta la API real de seguridadrosario.com
 */
async function fetchProductos(searchTerm = '') {
  try {
    console.log(`🔍 Consultando API: "${searchTerm}"`);
    
    const response = await axios.get(API_BASE, {
      params: {
        Producto: searchTerm,
        CategoriaId: 0,
        MarcaId: 0,
        OrdenId: 2,
        SucursalId: 2,
        Oferta: false
      },
      timeout: 10000
    });

    if (response.data && response.data.producto) {
      console.log(`✅ ${response.data.producto.length} productos encontrados`);
      return response.data.producto;
    }

    return [];
  } catch (error) {
    console.error('❌ Error consultando API:', error.message);
    return [];
  }
}

/**
 * Busca productos con caché
 */
async function buscarProductos(searchTerm) {
  const now = Date.now();
  if (cache.data && cache.timestamp && (now - cache.timestamp) < cache.ttl && !searchTerm) {
    console.log('📦 Usando caché de productos');
    return cache.data;
  }

  const productos = await fetchProductos(searchTerm);
  
  if (!searchTerm) {
    cache.data = productos;
    cache.timestamp = now;
  }

  return productos;
}

/**
 * Verifica stock de un producto específico
 */
async function checkStock(productName) {
  try {
    const productos = await buscarProductos(productName);
    
    if (productos.length === 0) {
      console.log(`❌ Producto "${productName}" no encontrado`);
      return null;
    }

    const coincidencia = productos.find(p => 
      p.producto.toLowerCase().includes(productName.toLowerCase())
    ) || productos[0];

    return {
      encontrado: true,
      nombre: coincidencia.producto,
      codigo: coincidencia.codigoInterno,
      descripcion: coincidencia.descripcion || 'Sin descripción disponible',
      stock: coincidencia.disponible,
      disponible: coincidencia.disponible > 0,
      precio_usd: coincidencia.precioUSD,
      precio_ars: coincidencia.precioARS,
      marca: coincidencia.marca,
      categoria: coincidencia.categoria,
      imagen: coincidencia.imagenes && coincidencia.imagenes.length > 0 
        ? coincidencia.imagenes[0] 
        : null
    };
  } catch (error) {
    console.error('❌ Error verificando stock:', error.message);
    return null;
  }
}

/**
 * Busca alternativas a un producto sin stock
 */
async function buscarAlternativas(categoria, marca = null) {
  try {
    console.log(`🔄 Buscando alternativas en categoría: ${categoria}`);
    
    const productos = await buscarProductos('');
    
    let alternativas = productos.filter(p => 
      p.categoria === categoria && 
      p.disponible > 0
    );

    if (marca) {
      const mismaMarca = alternativas.filter(p => p.marca === marca);
      if (mismaMarca.length > 0) {
        alternativas = mismaMarca;
      }
    }

    return alternativas.slice(0, 3).map(p => ({
      nombre: p.producto,
      codigo: p.codigoInterno,
      precio_usd: p.precioUSD,
      precio_ars: p.precioARS,
      stock: p.disponible,
      marca: p.marca
    }));
  } catch (error) {
    console.error('❌ Error buscando alternativas:', error.message);
    return [];
  }
}

function clearCache() {
  cache.data = null;
  cache.timestamp = null;
  console.log('🗑️ Caché limpiado');
}

module.exports = {
  buscarProductos,
  checkStock,
  buscarAlternativas,
  clearCache
};