// PostCSS config — auto-discovered by Vite at the frontend root.
//
// The single plugin here, postcss-custom-media, resolves the named
// `@custom-media --bp-*` tokens declared at the top of src/styles/global.css
// into concrete `@media (max-width: …)` rules at build time. This lets every
// breakpoint live in one definition block instead of scattered literals.
//
// Note: `@container` queries cannot read custom-media (the spec only resolves
// them inside `@media`), so the 480px `.app-row` container query in global.css
// stays a literal — see the cross-reference comment there.
//
// CommonJS (.cjs) because package.json sets "type": "module"; PostCSS loads
// its config via require(), so an ESM .js here would fail to load.
module.exports = {
  plugins: {
    "postcss-custom-media": {},
  },
};
