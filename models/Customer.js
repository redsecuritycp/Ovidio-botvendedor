const mongoose = require('mongoose');

const customerSchema = new mongoose.Schema({
  // Identificación
  phone: { type: String, required: true, unique: true },
  name: { type: String, default: '' },
  
  // Datos comerciales
  cuit: { type: String, default: '' },
  razonSocial: { type: String, default: '' },
  email: { type: String, default: '' },
  rubro: { type: String, default: '' },
  ubicacion: { type: String, default: '' },
  
  // Preferencias
  formaPago: { type: String, default: '' },
  marcasPreferidas: { type: String, default: '' },
  
  // Relación
  cumpleanos: { type: String, default: '' },
  notas: { type: String, default: '' },
  
  // Estado comercial
  estado: { 
    type: String, 
    enum: ['nuevo', 'contactado', 'cotizado', 'pendiente_datos', 'cerrado', 'perdido'],
    default: 'nuevo'
  },
  
  // Pedidos/Cotizaciones
  pedidos: [{
    fecha: { type: Date, default: Date.now },
    productos: [{ 
      nombre: String, 
      cantidad: Number, 
      precioUSD: Number,
      precioARS: Number
    }],
    totalUSD: Number,
    totalARS: Number,
    estado: { 
      type: String, 
      enum: ['cotizado', 'confirmado', 'facturado', 'entregado', 'cancelado'],
      default: 'cotizado'
    },
    notas: String
  }],
  
  // Conversaciones
  conversations: [{
    role: { type: String, enum: ['user', 'assistant'] },
    content: String,
    timestamp: { type: Date, default: Date.now }
  }],
  
  // Resumen inteligente (generado por IA)
  resumen: { type: String, default: '' },
  necesidades: { type: String, default: '' },
  proximaAccion: { type: String, default: '' },
  
  // Métricas
  totalCompras: { type: Number, default: 0 },
  ultimoContacto: { type: Date, default: Date.now },
  
  // Timestamps automáticos
  createdAt: { type: Date, default: Date.now },
  updatedAt: { type: Date, default: Date.now }
});

// Actualizar updatedAt en cada save
customerSchema.pre('save', function(next) {
  this.updatedAt = new Date();
  next();
});

module.exports = mongoose.model('Customer', customerSchema);