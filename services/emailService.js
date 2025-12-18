const nodemailer = require('nodemailer');

const transporter = nodemailer.createTransport({
  service: 'gmail',
  auth: {
    user: process.env.EMAIL_USER,
    pass: process.env.EMAIL_PASS
  }
});

async function enviarEmail(asunto, html, destinatario = null) {
  try {
    const dest = destinatario || process.env.EMAIL_USER;
    
    await transporter.sendMail({
      from: process.env.EMAIL_USER,
      to: dest,
      subject: asunto,
      html: html
    });
    
    console.log(`📧 Email enviado: ${asunto}`);
    return true;
  } catch (error) {
    console.error('❌ Error enviando email:', error.message);
    return false;
  }
}

async function notificarNuevoPedido(customer, productos, totalUSD) {
  const asunto = `🛒 NUEVO PEDIDO - ${customer.razonSocial || customer.name || customer.phone}`;
  
  const html = `
    <h2>Nuevo Pedido</h2>
    <p><strong>Cliente:</strong> ${customer.razonSocial || customer.name || 'Sin nombre'}</p>
    <p><strong>CUIT:</strong> ${customer.cuit || 'No proporcionado'}</p>
    <p><strong>Teléfono:</strong> ${customer.phone}</p>
    <p><strong>Forma de pago:</strong> ${customer.formaPago || 'No especificada'}</p>
    <h3>Productos:</h3>
    <p>${productos}</p>
    <p><strong>Total estimado:</strong> $${totalUSD} USD</p>
  `;
  
  return await enviarEmail(asunto, html);
}

async function notificarSinStock(producto, customer) {
  const asunto = `⚠️ SIN STOCK - ${producto}`;
  
  const html = `
    <h2>Producto Sin Stock</h2>
    <p><strong>Producto:</strong> ${producto}</p>
    <p><strong>Cliente que lo pidió:</strong> ${customer.razonSocial || customer.name || customer.phone}</p>
    <p><strong>Teléfono:</strong> ${customer.phone}</p>
    <p><strong>CUIT:</strong> ${customer.cuit || 'No proporcionado'}</p>
    <p><em>Consultar disponibilidad y precio.</em></p>
  `;
  
  return await enviarEmail(asunto, html);
}

async function notificarNuevoCliente(customer) {
  const asunto = `👤 NUEVO CLIENTE - ${customer.razonSocial || customer.name || customer.phone}`;
  
  const html = `
    <h2>Nuevo Cliente Registrado</h2>
    <p><strong>Nombre:</strong> ${customer.name || 'No proporcionado'}</p>
    <p><strong>Razón Social:</strong> ${customer.razonSocial || 'No proporcionada'}</p>
    <p><strong>CUIT:</strong> ${customer.cuit || 'No proporcionado'}</p>
    <p><strong>Teléfono:</strong> ${customer.phone}</p>
    <p><strong>Rubro:</strong> ${customer.rubro || 'No especificado'}</p>
  `;
  
  return await enviarEmail(asunto, html);
}

module.exports = {
  enviarEmail,
  notificarNuevoPedido,
  notificarSinStock,
  notificarNuevoCliente
};