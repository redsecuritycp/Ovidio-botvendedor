// Mapa completo de códigos de área de Argentina
const CODIGOS_AREA_ARGENTINA = {
  // 2 dígitos
  '11': 'Buenos Aires (CABA y GBA)',
  
  // 3 dígitos - principales
  '221': 'La Plata',
  '223': 'Mar del Plata',
  '261': 'Mendoza',
  '291': 'Bahía Blanca',
  '299': 'Neuquén',
  '341': 'Rosario',
  '342': 'Santa Fe',
  '343': 'Paraná',
  '351': 'Córdoba',
  '358': 'Río Cuarto',
  '362': 'Resistencia',
  '364': 'Formosa',
  '370': 'Corrientes',
  '376': 'Posadas',
  '379': 'Goya',
  '381': 'San Miguel de Tucumán',
  '383': 'Santiago del Estero',
  '385': 'La Rioja',
  '387': 'Salta',
  '388': 'Jujuy',
  
  // 4 dígitos - secundarios
  '2202': 'Azul',
  '2221': 'Chascomús',
  '2244': 'Tandil',
  '2245': 'Balcarce',
  '2252': 'San Pedro',
  '2254': 'Pergamino',
  '2266': 'Junín',
  '2281': 'Necochea',
  '2284': 'San Nicolás',
  '2302': 'Zárate',
  '2320': 'Campana',
  '2323': 'San Antonio de Areco',
  '2392': 'Luján',
  '2395': 'Mercedes',
  '2396': 'Chivilcoy',
  '2901': 'Ushuaia',
  '2920': 'Río Gallegos',
  '2962': 'Puerto Madryn',
  '2966': 'Trelew',
  '3400': 'Cañada de Gómez',
  '3401': 'Venado Tuerto',
  '3402': 'Casilda',
  '3404': 'Rufino',
  '3405': 'Firmat',
  '3406': 'San Lorenzo',
  '3409': 'Reconquista',
  '3435': 'Rafaela',
  '3442': 'Villa Constitución',
  '3446': 'Esperanza',
  '3491': 'Ceres',
  '3496': 'San Cristóbal',
  '3521': 'Villa María',
  '3525': 'Villa Carlos Paz',
  '3532': 'Bell Ville',
  '3541': 'San Francisco',
  '3543': 'Villa Dolores',
  '3571': 'La Carlota',
  '3583': 'Laboulaye'
};

function extraerInfoWhatsApp(whatsapp_id) {
  const info = {
    whatsapp_id: whatsapp_id,
    numero_completo: whatsapp_id,
    pais_codigo: null,
    pais_nombre: null,
    area_codigo: null,
    numero_local: null,
    ciudad: null,
    es_argentina: false
  };
  
  // Detectar Argentina
  if (whatsapp_id.startsWith('549')) {
    info.pais_codigo = '54';
    info.pais_nombre = 'Argentina';
    info.es_argentina = true;
    
    // Quitar '54' y el '9' de celular
    const sinPrefijo = whatsapp_id.substring(3); // Quita '549'
    
    // Intentar parsear el código de área (puede ser 2, 3 o 4 dígitos)
    let codigoEncontrado = false;
    
    // Probar 4 dígitos primero
    if (sinPrefijo.length >= 10) {
      const codigo4 = sinPrefijo.substring(0, 4);
      if (CODIGOS_AREA_ARGENTINA[codigo4]) {
        info.area_codigo = codigo4;
        info.ciudad = CODIGOS_AREA_ARGENTINA[codigo4];
        info.numero_local = sinPrefijo.substring(4);
        codigoEncontrado = true;
      }
    }
    
    // Si no, probar 3 dígitos
    if (!codigoEncontrado && sinPrefijo.length >= 9) {
      const codigo3 = sinPrefijo.substring(0, 3);
      if (CODIGOS_AREA_ARGENTINA[codigo3]) {
        info.area_codigo = codigo3;
        info.ciudad = CODIGOS_AREA_ARGENTINA[codigo3];
        info.numero_local = sinPrefijo.substring(3);
        codigoEncontrado = true;
      }
    }
    
    // Si no, probar 2 dígitos
    if (!codigoEncontrado && sinPrefijo.length >= 8) {
      const codigo2 = sinPrefijo.substring(0, 2);
      if (CODIGOS_AREA_ARGENTINA[codigo2]) {
        info.area_codigo = codigo2;
        info.ciudad = CODIGOS_AREA_ARGENTINA[codigo2];
        info.numero_local = sinPrefijo.substring(2);
        codigoEncontrado = true;
      }
    }
    
    // Si no se encontró, dejar como está
    if (!codigoEncontrado) {
      console.log(`⚠️ Código de área no reconocido para: ${whatsapp_id}`);
    }
  }
  
  console.log('📱 Info extraída del WhatsApp ID:', info);
  return info;
}

module.exports = { extraerInfoWhatsApp };