require("dotenv").config();
const { MongoClient } = require('mongodb');
const whatsappInfoLogic = require('../logic/whatsappInfoLogic');

async function actualizarTodosLosClientes() {
  const client = new MongoClient(process.env.MONGODB_URI);
  
  try {
    await client.connect();
    const db = client.db('ovidio_db');
    const clientes = db.collection('clientes');
    
    // Buscar TODOS los clientes
    const todosLosClientes = await clientes.find({}).toArray();
    
    console.log(`📊 Encontrados ${todosLosClientes.length} clientes`);
    
    for (const cliente of todosLosClientes) {
      // Extraer info actualizada
      const infoActualizada = whatsappInfoLogic.extraerInfoWhatsApp(cliente.whatsapp_id);
      
      // Actualizar
      await clientes.updateOne(
        { whatsapp_id: cliente.whatsapp_id },
        { $set: infoActualizada }
      );
      
      console.log(`✅ Actualizado: ${cliente.whatsapp_id} → ${infoActualizada.ciudad || 'Sin ciudad'}`);
    }
    
    console.log('🎉 Todos los clientes actualizados');
    
  } finally {
    await client.close();
  }
}

actualizarTodosLosClientes();