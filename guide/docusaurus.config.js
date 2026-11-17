// OscGoesPurrr's user guide, next to the website.
//
// Build it with tools/build_guide.py (no console windows; it copies the
// result into docs/guide/ and writes the stamp tests/test_guide_build.py
// checks). GitHub Pages serves /docs on the public main, so the guide's
// URL ends in /OscGoesPurrr/guide/.
//
// Everything here goes public with the next release. No analytics, no
// external fonts or CDNs: search is local (lunr, built into the pages),
// the font is the site's own Aldrich, the colours the site's tokens.css.

const fs = require('fs');
const path = require('path');
const {themes} = require('prism-react-renderer');

const REPO = 'https://github.com/Blise518B/OscGoesPurrr';
const DOWNLOAD = `${REPO}/releases/latest/download/OscGoesPurrr-Windows.exe`;
const APPIMAGE = `${REPO}/releases/latest/download/OscGoesPurrr-Linux-x86_64.AppImage`;
const SITE_ASSETS = path.resolve(__dirname, '..', 'docs', 'assets');

// The site's icon, inlined, so the guide carries no copy of it.
const ICON = 'data:image/svg+xml;base64,' +
  fs.readFileSync(path.join(SITE_ASSETS, 'ogp-icon.svg')).toString('base64');

/** @type {import('@docusaurus/types').Config} */
module.exports = {
  title: 'OscGoesPurrr',
  tagline: 'All your VRChat haptics, in one app.',
  favicon: ICON,
  url: 'https://blise518b.github.io',
  baseUrl: '/OscGoesPurrr/guide/',
  trailingSlash: true,
  organizationName: 'Blise518B',
  projectName: 'OscGoesPurrr',
  onBrokenLinks: 'throw',
  onBrokenAnchors: 'throw',
  markdown: {
    hooks: {onBrokenMarkdownLinks: 'throw', onBrokenMarkdownImages: 'throw'},
  },
  i18n: {defaultLocale: 'en', locales: ['en']},

  // Aldrich comes from the site's own fonts folder (with its OFL licence).
  // Every path in this config is relative to guide/: Docusaurus puts the
  // config into the pages' JavaScript, so an absolute one would publish
  // the folders of the PC the guide was built on.
  staticDirectories: ['static', '../docs/assets/fonts'],

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          routeBasePath: '/',
          sidebarPath: './sidebars.js',
          editUrl: `${REPO}/edit/main/guide/`,
          breadcrumbs: true,
        },
        blog: false,
        pages: false,
        theme: {customCss: './src/css/custom.css'},
        sitemap: {lastmod: null, changefreq: null, priority: null},
      }),
    ],
  ],

  plugins: ['./plugins/tokens518.js'],

  themes: [
    [
      '@easyops-cn/docusaurus-search-local',
      {
        hashed: true,
        indexBlog: false,
        indexPages: false,
        docsRouteBasePath: '/',
        language: ['en'],
        highlightSearchTermsOnTargetPage: true,
        explicitSearchResultPath: true,
        searchBarShortcutHint: false,
      },
    ],
  ],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      // Neon is the mode the guide opens in; the toggle is Neon / Midnight
      // (src/theme/ColorModeToggle). Docusaurus calls them dark / light.
      colorMode: {defaultMode: 'dark', disableSwitch: false, respectPrefersColorScheme: false},
      navbar: {
        title: 'OscGoesPurrr',
        logo: {alt: '', src: ICON, href: '/'},
        items: [
          // plain links: a 'doc' item counts as active on every page of its sidebar
          {to: '/getting-started/', label: 'Getting started', position: 'left'},
          {to: '/help/common-problems/', label: 'Common problems', position: 'left'},
          {href: 'pathname:///OscGoesPurrr/', label: 'Website', position: 'right', target: '_self'},
          {href: DOWNLOAD, label: 'Download', position: 'right'},
          {href: REPO, label: 'GitHub', position: 'right'},
        ],
      },
      footer: {
        style: 'dark',
        links: [
          {
            title: 'Guide',
            items: [
              {label: 'Getting started', to: '/getting-started/'},
              {label: 'Common problems', to: '/help/common-problems/'},
            ],
          },
          {
            title: 'Get it',
            items: [
              {label: 'Windows (.exe)', href: DOWNLOAD},
              {label: 'Linux (AppImage)', href: APPIMAGE},
              {label: 'Every release', href: `${REPO}/releases`},
            ],
          },
          {
            title: 'More',
            items: [
              {label: 'Website', href: 'pathname:///OscGoesPurrr/', target: '_self'},
              {label: 'GitHub', href: REPO},
            ],
          },
        ],
        copyright: 'OscGoesPurrr · MIT · made by <a class="footer__author" href="https://github.com/Blise518B">Blise518B</a>',
      },
      docs: {sidebar: {hideable: false, autoCollapseCategories: false}},
      tableOfContents: {minHeadingLevel: 2, maxHeadingLevel: 3},
      prism: {theme: themes.vsDark, darkTheme: themes.vsDark},
    }),
};
