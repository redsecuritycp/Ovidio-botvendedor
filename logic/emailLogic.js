const nodemailer = require('nodemailer');

async function enviarEmailCompras(data) {
  try {
    const transporter = nodemailer.createTransport({
      host: process.env.EMAIL_HOST,
      port: process.env.EMAIL_PORT,
      secure: false, // true para 465, false para otros puertos
      auth: {
        user: process.env.EMAIL_USER,
        pass: process.env.EMAIL_PASS
      }
    });

    const mailOptions = {
      from: process.env.EMAIL_USER,
      to: process.env.EMAIL_TO_COMPRAS,
      subject: `⚠️ OVIDIO - Solicitud de Stock Urgente`,
      html: `
        <div style="font-family: Arial, sans-serif; padding: 20px; background: #f5f5f5;">
          <div style="background: white; padding: 20px; border-radius: 8px;">
            <h2 style="color: #00a6e0;">🤖 Solicitud Automática de Stock</h2>
            
            <p><strong>Cliente WhatsApp:</strong> ${data.cliente}</p>
            <p><strong>Producto solicitado:</strong> ${data.producto}</p>
            
            <div style="background: #f9f9f9; padding: 15px; border-left: 4px solid #00a6e0; margin: 20px 0;">
              <p><strong>Consulta original del cliente:</strong></p>
              <p style="font-style: italic;">"${data.consulta}"</p>
            </div>

            <p style="color: #666; font-size: 12px; margin-top: 30px;">
              <em>Generado automáticamente por Ovidio Bot - GRUPO SER</em>
            </p>
          </div>
        </div>
      `
    };

    const info = await transporter.sendMail(mailOptions);
    console.log('📧 Email enviado a Compras:', info.messageId);
    return info;

  } catch (error) {
    console.error('❌ Error enviando email:', error.message);
    throw error;
  }
}

module.exports = { enviarEmailCompras };