const nodemailer = require('nodemailer');

async function sendPurchaseRequestEmail(productName, customer, conversationHistory) {
  try {
    // Verificar que tenemos las credenciales
    if (!process.env.EMAIL_USER || !process.env.EMAIL_PASS || !process.env.EMAIL_TO_COMPRAS) {
      console.log('⚠️ Credenciales de email no configuradas. Saltando envío.');
      return false;
    }

    // Configurar transporter
    const transporter = nodemailer.createTransport({
      service: 'gmail',
      auth: {
        user: process.env.EMAIL_USER,
        pass: process.env.EMAIL_PASS
      }
    });

    // Armar el contenido del email
    const conversacionTexto = conversationHistory
      .slice(-5)
      .map(msg => `${msg.role === 'user' ? 'Cliente' : 'Ovidio'}: ${msg.content}`)
      .join('\n\n');

    const mailOptions = {
      from: process.env.EMAIL_USER,
      to: process.env.EMAIL_TO_COMPRAS,
      subject: `🚨 Solicitud de Compra: ${productName}`,
      html: `
        <h2>Solicitud de Producto sin Stock</h2>
        
        <h3>Producto Solicitado:</h3>
        <p><strong>${productName}</strong></p>
        
        <h3>Datos del Cliente:</h3>
        <ul>
          <li><strong>Nombre:</strong> ${customer.name}</li>
          <li><strong>Teléfono:</strong> ${customer.phone}</li>
          ${customer.cuit ? `<li><strong>CUIT:</strong> ${customer.cuit}</li>` : ''}
          ${customer.location ? `<li><strong>Ubicación:</strong> ${customer.location}</li>` : ''}
        </ul>
        
        <h3>Últimos 5 mensajes de la conversación:</h3>
        <pre style="background: #f4f4f4; padding: 15px; border-radius: 5px;">${conversacionTexto}</pre>
        
        <hr>
        <p><em>Email generado automáticamente por Ovidio Bot</em></p>
      `
    };

    // Enviar email
    await transporter.sendMail(mailOptions);
    console.log(`📧 Email enviado a Compras: ${productName}`);
    return true;
  } catch (error) {
    console.error('❌ Error enviando email:', error.message);
    return false;
  }
}

module.exports = {
  sendPurchaseRequestEmail
};