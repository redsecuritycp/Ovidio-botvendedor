const webScraperService = require('../services/webScraperService');

const inventarioSimulado = {
  'cámara Hikvision ColorVu 4MP': { stock: 15, precio: 'AR$ 45.000' },
  'alarma Ajax Hub 2': { stock: 0, alternativa: 'alarma Hikvision AXHub con 8 zonas inalámbricas' },
  'grabador NVR 8 canales': { stock: 8, precio: 'AR$ 120.000' },
  'disco WD Purple 2TB': { stock: 0, alternativa: null }
};

async function verificarStock(nombreProducto) {
  try {
    const productoWeb = await webScraperService.buscarProducto(nombreProducto);
    
    if (productoWeb) {
      return {
        hay_stock: productoWeb.disponible,
        alternativa: null,
        precio: `USD ${productoWeb.precio_usd} / ARS ${productoWeb.precio_ars}`,
        codigo: productoWeb.codigo
      };
    }
    
    console.log('⚠️ Usando inventario simulado');
    const producto = inventarioSimulado[nombreProducto];
    
    if (!producto) {
      return { hay_stock: false, alternativa: null, precio: null };
    }
    
    if (producto.stock > 0) {
      return { hay_stock: true, alternativa: null, precio: producto.precio };
    }
    
    return { hay_stock: false, alternativa: producto.alternativa || null, precio: null };
    
  } catch (error) {
    console.error('❌ Error stock:', error.message);
    return { hay_stock: false, alternativa: null, precio: null };
  }
}

module.exports = { verificarStock };