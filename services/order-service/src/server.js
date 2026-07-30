require('dotenv').config();
const app = require('./app');

const PORT = process.env.PORT || 3005;

app.listen(PORT, () => {
  console.log(`order-service running on port ${PORT}`);
});