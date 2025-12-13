const nodemailer = require("nodemailer");

async function sendPurchaseRequestEmail(
  productName,
  customer,
  conversationHistory,
) {
  console.log(
    "📧 [DESHABILITADO] Email a Compras no se enviará hasta configurar credenciales Gmail",
  );
  console.log(`   Producto: ${productName}`);
  console.log(`   Cliente: ${customer.name} (${customer.phone})`);
  return false;

  // TODO: Configurar "App Password" de Gmail en Secrets
  // https://support.google.com/accounts/answer/185833
}

module.exports = {
  sendPurchaseRequestEmail,
};
