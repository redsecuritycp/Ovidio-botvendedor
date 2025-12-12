const { MongoClient } = require('mongodb');

let client;
let db;

async function conectarDB() {
  if (db) return db;
  
  try {
    client = new MongoClient(process.env.MONGODB_URI);
    await client.connect();
    db = client.db('ovidio_db');
    console.log('✅ MongoDB conectado');
    return db;
  } catch (error) {
    console.error('❌ Error conectando MongoDB:', error.message);
    throw error;
  }
}

async function guardarCliente(datosCliente) {
  const database = await conectarDB();
  const clientes = database.collection('clientes');
  
  // Fecha actual en timezone de Argentina (UTC-3)
  const ahoraArgentina = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/Argentina/Buenos_Aires' }));
  
  const resultado = await clientes.updateOne(
    { whatsapp_id: datosCliente.whatsapp_id },
    { 
      $set: { 
        ...datosCliente, 
        ultima_interaccion: ahoraArgentina 
      },
      $setOnInsert: { 
        primera_interaccion: ahoraArgentina 
      }
    },
    { upsert: true }
  );
  
  return resultado;
}

async function obtenerCliente(whatsapp_id) {
  const database = await conectarDB();
  const clientes = database.collection('clientes');
  return await clientes.findOne({ whatsapp_id });
}

async function guardarConversacion(whatsapp_id, mensaje, respuesta) {
  const database = await conectarDB();
  const conversaciones = database.collection('conversaciones');
  
  // Fecha actual en timezone de Argentina (UTC-3)
  const ahoraArgentina = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/Argentina/Buenos_Aires' }));
  
  await conversaciones.insertOne({
    whatsapp_id,
    mensaje,
    respuesta,
    timestamp: ahoraArgentina
  });
}

async function obtenerHistorialCliente(whatsapp_id, limite = 10) {
  const database = await conectarDB();
  const conversaciones = database.collection('conversaciones');
  
  return await conversaciones
    .find({ whatsapp_id })
    .sort({ timestamp: -1 })
    .limit(limite)
    .toArray();
}

module.exports = {
  conectarDB,
  guardarCliente,
  obtenerCliente,
  guardarConversacion,
  obtenerHistorialCliente
};