const axios = require('axios');

// Diccionario de corrección de marcas (errores comunes → marca correcta)
const MARCAS_CORRECCION = {
  // Dahua
  'dahau': 'dahua', 'daua': 'dahua', 'dahuaa': 'dahua', 'dahu': 'dahua',
  'dahuwa': 'dahua', 'dauha': 'dahua',
  // Hikvision
  'hikvisión': 'hikvision', 'hikvicion': 'hikvision', 'hik': 'hikvision',
  'hikvison': 'hikvision', 'hikivision': 'hikvision', 'hikvission': 'hikvision',
  'hivision': 'hikvision', 'hkvision': 'hikvision', 'hikvi': 'hikvision',
  // Ajax
  'ayax': 'ajax', 'ajaz': 'ajax', 'ajaks': 'ajax',
  // Imou
  'imuo': 'imou', 'imu': 'imou', 'imo': 'imou',
  // Ezviz
  'esbis': 'ezviz', 'ezvis': 'ezviz', 'esviz': 'ezviz', 'ezvs': 'ezviz',
  // DSC
  'dcs': 'dsc'
};

// Sinónimos de tipos de producto
const SINONIMOS_PRODUCTO = {
  // Cámaras
  'camara': ['camara', 'cámara', 'camera', 'cam', 'camra', 'cámra'],
  'bullet': ['bullet', 'tubo', 'cilindrica', 'cilíndrica', 'bala', 'tubular'],
  'domo': ['domo', 'dome', 'cupula', 'cúpula', 'redonda', 'techo'],
  'ptz': ['ptz', 'motorizada', 'robotica', 'robótica', 'movimiento'],
  // Grabadores
  'dvr': ['dvr', 'grabador', 'grabadora', 'videograbador', 'grabador de video'],
  'nvr': ['nvr', 'grabador ip', 'grabador de red'],
  // Otros
  'disco': ['disco', 'hdd', 'disco rigido', 'disco rígido', 'disco duro', 'rigido', 'rígido'],
  'alarma': ['alarma', 'panel', 'central'],
  'switch': ['switch', 'poe', 'switch poe'],
  'fuente': ['fuente', 'transformador', 'alimentador', 'power']
};

// Sinónimos de características
const SINONIMOS_CARACTERISTICAS = {
  'exterior': ['exterior', 'afuera', 'para afuera', 'outdoor', 'intemperie', 'externo', 'ip67', 'ip66'],
  'interior': ['interior', 'adentro', 'para adentro', 'indoor', 'interno'],
  'wifi': ['wifi', 'inalambrica', 'inalámbrica', 'wireless', 'sin cable'],
  'poe': ['poe', 'power over ethernet', 'alimentacion por cable'],
  'audio': ['audio', 'microfono', 'micrófono', 'sonido', 'con audio'],
  'color': ['color', 'full color', 'colorvu', 'color vu', 'vision color', 'color de noche']
};

// Patrones de resolución
const PATRONES_RESOLUCION = [
  { patron: /(\d+)\s*(?:mega|mp|megapixel|megapixeles|megas)/i, grupo: 1 },
  { patron: /(\d+)\s*k/i, multiplicador: (n) => n === '4' ? '8' : n === '2' ? '4' : n },
  { patron: /1080p?/i, valor: '2' },
  { patron: /2k/i, valor: '4' },
  { patron: /4k/i, valor: '8' },
  { patron: /full\s*hd/i, valor: '2' }
];

// Patrones de canales (para DVR/NVR)
const PATRONES_CANALES = [
  { patron: /(\d+)\s*(?:canales|ch|channels)/i, grupo: 1 },
  { patron: /(\d+)\s*(?:camaras|cámaras)/i, grupo: 1 }
];

/**
 * Normaliza y corrige el texto de búsqueda
 */
function normalizarTexto(texto) {
  let normalizado = texto.toLowerCase()
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '') // Quitar tildes
    .replace(/[^\w\s]/g, ' ') // Quitar caracteres especiales
    .replace(/\s+/g, ' ') // Espacios múltiples a uno
    .trim();
  
  return normalizado;
}

/**
 * Detecta y corrige la marca
 */
function detectarMarca(texto) {
  const normalizado = normalizarTexto(texto);
  const palabras = normalizado.split(' ');
  
  // Buscar marca exacta o con corrección
  for (const palabra of palabras) {
    // Marca exacta
    const marcasValidas = ['dahua', 'hikvision', 'ajax', 'imou', 'ezviz', 'dsc', 'epcom', 'provision', 'honeywell'];
    if (marcasValidas.includes(palabra)) {
      return palabra;
    }
    
    // Corrección de errores
    if (MARCAS_CORRECCION[palabra]) {
      return MARCAS_CORRECCION[palabra];
    }
    
    // Similaridad (para errores no mapeados)
    for (const marca of marcasValidas) {
      if (calcularSimilaridad(palabra, marca) > 0.7) {
        return marca;
      }
    }
  }
  
  return null;
}

/**
 * Detecta el tipo de producto
 */
function detectarTipoProducto(texto) {
  const normalizado = normalizarTexto(texto);
  
  for (const [tipo, sinonimos] of Object.entries(SINONIMOS_PRODUCTO)) {
    for (const sinonimo of sinonimos) {
      if (normalizado.includes(sinonimo)) {
        return tipo;
      }
    }
  }
  
  return null;
}

/**
 * Detecta características (exterior, wifi, etc)
 */
function detectarCaracteristicas(texto) {
  const normalizado = normalizarTexto(texto);
  const caracteristicas = [];
  
  for (const [caracteristica, sinonimos] of Object.entries(SINONIMOS_CARACTERISTICAS)) {
    for (const sinonimo of sinonimos) {
      if (normalizado.includes(sinonimo)) {
        caracteristicas.push(caracteristica);
        break;
      }
    }
  }
  
  return caracteristicas;
}

/**
 * Detecta resolución en MP
 */
function detectarResolucion(texto) {
  const normalizado = normalizarTexto(texto);
  
  for (const { patron, grupo, multiplicador, valor } of PATRONES_RESOLUCION) {
    const match = normalizado.match(patron);
    if (match) {
      if (valor) return valor;
      if (grupo) {
        const num = match[grupo];
        return multiplicador ? multiplicador(num) : num;
      }
    }
  }
  
  return null;
}

/**
 * Detecta cantidad de canales (para DVR/NVR)
 */
function detectarCanales(texto) {
  const normalizado = normalizarTexto(texto);
  
  for (const { patron, grupo } of PATRONES_CANALES) {
    const match = normalizado.match(patron);
    if (match && grupo) {
      return match[grupo];
    }
  }
  
  return null;
}

/**
 * Calcula similaridad entre dos strings (Dice coefficient simplificado)
 */
function calcularSimilaridad(str1, str2) {
  if (str1 === str2) return 1;
  if (str1.length < 2 || str2.length < 2) return 0;
  
  const bigrams1 = new Set();
  for (let i = 0; i < str1.length - 1; i++) {
    bigrams1.add(str1.substring(i, i + 2));
  }
  
  let matches = 0;
  for (let i = 0; i < str2.length - 1; i++) {
    if (bigrams1.has(str2.substring(i, i + 2))) {
      matches++;
    }
  }
  
  return (2 * matches) / (str1.length + str2.length - 2);
}

/**
 * Busca productos con inteligencia
 */
async function buscarInteligente(textoCliente) {
  console.log(`\n🧠 ========== BÚSQUEDA INTELIGENTE ==========`);
  console.log(`📝 Texto original: "${textoCliente}"`);
  
  // Analizar el texto del cliente
  const marca = detectarMarca(textoCliente);
  const tipo = detectarTipoProducto(textoCliente);
  const caracteristicas = detectarCaracteristicas(textoCliente);
  const resolucion = detectarResolucion(textoCliente);
  const canales = detectarCanales(textoCliente);
  
  console.log(`🏷️ Marca detectada: ${marca || 'ninguna'}`);
  console.log(`📦 Tipo producto: ${tipo || 'ninguno'}`);
  console.log(`⚙️ Características: ${caracteristicas.length > 0 ? caracteristicas.join(', ') : 'ninguna'}`);
  console.log(`📊 Resolución: ${resolucion ? resolucion + 'MP' : 'no especificada'}`);
  console.log(`📺 Canales: ${canales || 'no especificados'}`);
  
  // Estrategia de búsqueda
  let productos = [];
  let terminoBusqueda = '';
  
  // Prioridad 1: Buscar por marca (más específico)
  if (marca) {
    terminoBusqueda = marca;
    productos = await buscarEnAPI(marca);
    console.log(`🔍 Búsqueda por marca "${marca}": ${productos.length} resultados`);
  }
  
  // Prioridad 2: Si no hay marca, buscar por tipo
  if (productos.length === 0 && tipo) {
    terminoBusqueda = tipo;
    productos = await buscarEnAPI(tipo);
    console.log(`🔍 Búsqueda por tipo "${tipo}": ${productos.length} resultados`);
  }
  
  // Prioridad 3: Buscar por palabra clave principal
  if (productos.length === 0) {
    const palabras = normalizarTexto(textoCliente).split(' ')
      .filter(p => p.length > 3)
      .sort((a, b) => b.length - a.length);
    
    for (const palabra of palabras.slice(0, 3)) {
      productos = await buscarEnAPI(palabra);
      if (productos.length > 0) {
        terminoBusqueda = palabra;
        console.log(`🔍 Búsqueda por palabra "${palabra}": ${productos.length} resultados`);
        break;
      }
    }
  }
  
  if (productos.length === 0) {
    console.log(`❌ No se encontraron productos`);
    return { encontrado: false, busqueda: textoCliente };
  }
  
  // Filtrar resultados
  let filtrados = productos;
  
  // Filtrar por marca si hay muchos resultados
  if (marca && filtrados.length > 5) {
    const porMarca = filtrados.filter(p => 
      p.nombre.toLowerCase().includes(marca) ||
      (p.marca && p.marca.toLowerCase().includes(marca))
    );
    if (porMarca.length > 0) {
      filtrados = porMarca;
      console.log(`✂️ Filtrado por marca: ${filtrados.length} productos`);
    }
  }
  
  // Filtrar por resolución
  if (resolucion && filtrados.length > 1) {
    const porResolucion = filtrados.filter(p => {
      const nombre = p.nombre.toLowerCase();
      return nombre.includes(resolucion + 'mp') || 
             nombre.includes(resolucion + ' mp') ||
             nombre.includes(resolucion + 'megapixel') ||
             nombre.includes('de ' + resolucion + 'mp');
    });
    if (porResolucion.length > 0) {
      filtrados = porResolucion;
      console.log(`✂️ Filtrado por resolución ${resolucion}MP: ${filtrados.length} productos`);
    }
  }
  
  // Filtrar por tipo (bullet, domo, etc)
  if (tipo && ['bullet', 'domo', 'ptz'].includes(tipo) && filtrados.length > 1) {
    const porTipo = filtrados.filter(p => 
      p.nombre.toLowerCase().includes(tipo)
    );
    if (porTipo.length > 0) {
      filtrados = porTipo;
      console.log(`✂️ Filtrado por tipo ${tipo}: ${filtrados.length} productos`);
    }
  }
  
  // Filtrar por características (exterior, wifi, etc)
  for (const caract of caracteristicas) {
    if (filtrados.length > 1) {
      const porCaract = filtrados.filter(p => {
        const nombre = p.nombre.toLowerCase();
        if (caract === 'exterior') {
          return nombre.includes('ip67') || nombre.includes('ip66') || 
                 nombre.includes('exterior') || nombre.includes('outdoor') ||
                 nombre.includes('bullet'); // bullets suelen ser exterior
        }
        if (caract === 'wifi') {
          return nombre.includes('wifi') || nombre.includes('wireless');
        }
        if (caract === 'audio') {
          return nombre.includes('audio') || nombre.includes('c/audio');
        }
        if (caract === 'color') {
          return nombre.includes('color') || nombre.includes('colorvu');
        }
        return nombre.includes(caract);
      });
      if (porCaract.length > 0) {
        filtrados = porCaract;
        console.log(`✂️ Filtrado por ${caract}: ${filtrados.length} productos`);
      }
    }
  }
  
  // Filtrar por canales (DVR/NVR)
  if (canales && filtrados.length > 1) {
    const porCanales = filtrados.filter(p => 
      p.nombre.toLowerCase().includes(canales + ' canales') ||
      p.nombre.toLowerCase().includes(canales + 'ch') ||
      p.nombre.toLowerCase().includes(canales + ' ch')
    );
    if (porCanales.length > 0) {
      filtrados = porCanales;
      console.log(`✂️ Filtrado por ${canales} canales: ${filtrados.length} productos`);
    }
  }
  
  // Ordenar por disponibilidad (con stock primero)
  filtrados.sort((a, b) => (b.stock > 0 ? 1 : 0) - (a.stock > 0 ? 1 : 0));
  
  console.log(`✅ Resultado final: ${filtrados.length} productos`);
  console.log(`🧠 ==========================================\n`);
  
  // Devolver resultados
  if (filtrados.length > 1) {
    return {
      encontrado: true,
      multiple: true,
      cantidad: filtrados.length,
      busqueda: terminoBusqueda,
      interpretacion: {
        marca,
        tipo,
        resolucion: resolucion ? resolucion + 'MP' : null,
        caracteristicas,
        canales
      },
      opciones: filtrados.slice(0, 5).map(p => ({
        nombre: p.nombre,
        codigo: p.codigo,
        stock: p.stock,
        precio_usd: p.precio_usd,
        precio_ars: p.precio_ars,
        marca: p.marca,
        disponible: p.stock > 0
      }))
    };
  }
  
  const producto = filtrados[0];
  return {
    encontrado: true,
    multiple: false,
    nombre: producto.nombre,
    codigo: producto.codigo,
    stock: producto.stock,
    precio_usd: producto.precio_usd,
    precio_ars: producto.precio_ars,
    marca: producto.marca,
    categoria: producto.categoria,
    disponible: producto.stock > 0
  };
}

/**
 * Función auxiliar para buscar en la API
 */
async function buscarEnAPI(termino) {
  try {
    const API_BASE = process.env.API_BASE_URL;
    
    if (!API_BASE) {
      console.error('❌ API_BASE_URL no configurada');
      return [];
    }
    
    const response = await axios.get(API_BASE, {
      params: {
        Producto: termino,
        CategoriaId: 0,
        MarcaId: 0,
        OrdenId: 2,
        SucursalId: 2,
        Oferta: false
      },
      timeout: 10000
    });
    
    if (response.data && response.data.producto) {
      return response.data.producto.map(p => ({
        nombre: p.producto || '',
        codigo: p.codigoInterno || '',
        stock: parseInt(p.disponible || 0),
        precio_usd: parseFloat(p.precioUSD || 0),
        precio_ars: parseFloat(p.precioARS || 0),
        marca: p.marca || '',
        categoria: p.categoria || '',
        descripcion: p.descripcion || ''
      }));
    }
    
    return [];
  } catch (error) {
    console.error(`❌ Error buscando "${termino}":`, error.message);
    return [];
  }
}

module.exports = { 
  buscarInteligente,
  detectarMarca,
  detectarTipoProducto,
  detectarResolucion,
  detectarCaracteristicas,
  normalizarTexto
};
