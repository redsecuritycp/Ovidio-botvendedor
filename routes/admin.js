const express = require('express');
const router = express.Router();
const Customer = require('../models/Customer');

router.get('/clientes', async (req, res) => {
  try {
    const clientes = await Customer.find()
      .select('-conversations')
      .sort({ updatedAt: -1 })
      .limit(50);
    
    res.json({
      success: true,
      total: clientes.length,
      clientes: clientes.map(c => ({
        id: c._id,
        nombre: c.razonSocial || c.name || c.phone,
        phone: c.phone,
        cuit: c.cuit,
        estado: c.estado || 'nuevo',
        formaPago: c.formaPago,
        rubro: c.rubro,
        ultimoContacto: c.updatedAt
      }))
    });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

router.get('/stats', async (req, res) => {
  try {
    const hoy = new Date();
    hoy.setHours(0, 0, 0, 0);
    
    const totalClientes = await Customer.countDocuments();
    const clientesHoy = await Customer.countDocuments({ createdAt: { $gte: hoy } });
    const conPedidos = await Customer.countDocuments({ 'pedidos.0': { $exists: true } });
    const pendientes = await Customer.countDocuments({ estado: 'pendiente_datos' });
    
    res.json({
      success: true,
      stats: { totalClientes, clientesHoy, conPedidos, pendientes }
    });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

router.get('/buscar', async (req, res) => {
  try {
    const { q } = req.query;
    if (!q) return res.json({ success: true, clientes: [] });
    
    const clientes = await Customer.find({
      $or: [
        { name: { $regex: q, $options: 'i' } },
        { razonSocial: { $regex: q, $options: 'i' } },
        { cuit: { $regex: q, $options: 'i' } },
        { phone: { $regex: q, $options: 'i' } }
      ]
    }).select('-conversations').limit(20);
    
    res.json({ success: true, clientes });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

module.exports = router;