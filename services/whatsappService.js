const axios = require("axios");

const WHATSAPP_API_URL = `https://graph.facebook.com/v21.0/${process.env.PHONE_NUMBER_ID}/messages`;

async function sendMessage(to, texto) {
  try {
    const response = await axios.post(
      WHATSAPP_API_URL,
      {
        messaging_product: "whatsapp",
        to: to,
        type: "text",
        text: { body: texto },
      },
      {
        headers: {
          Authorization: `Bearer ${process.env.WHATSAPP_TOKEN}`,
          "Content-Type": "application/json",
        },
      },
    );

    console.log("✅ Mensaje enviado:", response.data);
    return response.data;
  } catch (error) {
    console.error(
      "❌ Error enviando mensaje:",
      error.response?.data || error.message,
    );
    throw error;
  }
}

module.exports = { sendMessage };
