// eslint-disable-next-line @typescript-eslint/no-require-imports
const path = require('path')

module.exports = {
  // Build a self-contained server into .next/standalone — the app plus only
  // the node_modules it actually imports, traced file by file.
  //
  // Why it matters for Docker: without it, running the built app needs the
  // whole node_modules tree (~500 MB here, most of it build tooling that is
  // never imported at runtime). With it, the runtime image copies three small
  // directories and needs no `npm install` at all. `npm run dev` and
  // `npm start` locally are unaffected.
  output: 'standalone',

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
