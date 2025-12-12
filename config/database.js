const mongoose = require('mongoose');

async function connectDB() {
  try {
    const mongoURI = process.env.MONGODB_URI;
    
    if (!mongoURI) {
      console.error('❌ MONGODB_URI no está configurado en Secrets');
      return;
    }

    await mongoose.connect(mongoURI, {
      serverSelectionTimeoutMS: 5000
    });

    console.log('✅ Conectado a MongoDB Atlas');
  } catch (error) {
    console.error('❌ Error conectando a MongoDB:', error.message);
    process.exit(1);
  }
}

module.exports = connectDB;