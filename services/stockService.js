const smartSearch = require('./smartSearchService');

async function checkStock(searchTerm) {
  // Usar el buscador inteligente
  return await smartSearch.buscarInteligente(searchTerm);
}

async function buscarAlternativas(categoria, marca) {
  try {
    // Buscar productos similares en la misma categoría
    const resultado = await smartSearch.buscarInteligente(categoria);
    
    if (resultado.encontrado && resultado.multiple) {
      // Filtrar los que tengan stock
      return resultado.opciones.filter(p => p.disponible);
    }
    
    return [];
  } catch (error) {
    console.error('❌ Error buscando alternativas:', error.message);
    return [];
  }
}

module.exports = { checkStock, buscarAlternativas };