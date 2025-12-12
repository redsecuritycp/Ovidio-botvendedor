const mongoose = require('mongoose');

const customerSchema = new mongoose.Schema({
  phone: {
    type: String,
    required: true,
    unique: true
  },
  name: {
    type: String,
    default: 'Cliente'
  },
  cuit: String,
  razonSocial: String,
  rubro: String,
  location: String,
  conversations: [{
    role: {
      type: String,
      enum: ['user', 'assistant']
    },
    content: String,
    timestamp: {
      type: Date,
      default: Date.now
    }
  }],
  createdAt: {
    type: Date,
    default: Date.now
  },
  updatedAt: {
    type: Date,
    default: Date.now
  }
});

customerSchema.pre('save', function(next) {
  this.updatedAt = Date.now();
  next();
});

module.exports = mongoose.model('Customer', customerSchema);