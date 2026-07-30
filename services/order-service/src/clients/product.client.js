const axios = require('axios');

const PRODUCT_SERVICE_URL = process.env.PRODUCT_SERVICE_URL;

async function getProduct(productId) {
  const response = await axios.get(`${PRODUCT_SERVICE_URL}/products/${productId}`, {
    timeout: 3000,
  });
  return response.data;
}

async function decrementStock(productId, quantity) {
  const response = await axios.patch(
    `${PRODUCT_SERVICE_URL}/products/${productId}/decrement-stock`,
    { quantity },
    { timeout: 3000 }
  );
  return response.data;
}

module.exports = { getProduct, decrementStock };