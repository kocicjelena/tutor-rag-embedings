// eslint-disable-next-line @typescript-eslint/no-require-imports
const path = require('path')

module.exports = {
  turbopack: {
    root: path.join(__dirname, '..'),
  },
  async headers() {
    return [
      {
        source: '/sw.js',
        headers: [
          { key: 'Service-Worker-Allowed', value: '/' },
          { key: 'Cache-Control', value: 'no-cache' },
        ],
      },
    ];
  },
}
