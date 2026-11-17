/**
 * The 518 colours, straight from the site's own docs/assets/tokens.css
 * (a copy of _hub/design/tokens.css), never retyped: its two custom-property
 * blocks are read at build time and put into every page's <head>.
 *
 *   :root                          Neon     -> every page (the default)
 *   :root[data-theme="midnight"]   Midnight -> html[data-theme='light']
 *
 * Docusaurus' colour modes are "dark" (Neon, the default) and "light"
 * (Midnight); src/css/custom.css maps the tokens onto Infima's --ifm-*.
 * Only custom properties are taken -- the file's base shell (body,
 * button ...) is the site's, not the guide's.
 *
 * The site's Aldrich is declared here too: docs/assets/fonts is one of the
 * guide's static folders, and only this knows the baseUrl.
 */
const fs = require('fs');
const path = require('path');

const TOKENS = path.resolve(__dirname, '..', '..', 'docs', 'assets', 'tokens.css');

function block(css, selector) {
  const start = css.indexOf(selector + ' {');
  if (start < 0) throw new Error(`tokens.css: no "${selector} {" block`);
  const open = css.indexOf('{', start);
  const close = css.indexOf('}', open);
  const body = css.slice(open + 1, close).replace(/\/\*[\s\S]*?\*\//g, '');
  const props = body.split(';').map((p) => p.trim()).filter((p) => p.startsWith('--'));
  if (props.length < 10) throw new Error(`tokens.css: "${selector}" has too few tokens`);
  return props.join(';') + ';';
}

function tokensCss(baseUrl = '/') {
  const css = fs.readFileSync(TOKENS, 'utf8').replace(/\r\n/g, '\n');
  const neon = block(css, ':root');
  const midnight = block(css, ':root[data-theme="midnight"]');
  const font = '@font-face{font-family:"Aldrich Guide";' +
    `src:url("${baseUrl}Aldrich-Regular.ttf") format("truetype");font-display:swap}`;
  return `${font}:root{${neon}}html[data-theme='light']{${midnight}}`;
}

module.exports = function tokens518(context) {
  return {
    name: 'tokens518',
    getPathsToWatch() {
      return [TOKENS];
    },
    injectHtmlTags() {
      return {
        headTags: [{tagName: 'style', attributes: {id: 'tokens518'}, innerHTML: tokensCss(context.baseUrl)}],
      };
    },
  };
};
module.exports.tokensCss = tokensCss;
