// The guide's left sidebar: grouped like the app's own sidebar, Getting
// started first, Help last. A category's page lists what's in it.

/** Category with a generated landing page at /<slug>/. */
function section(label, slug, description, items) {
  return {
    type: 'category',
    label,
    collapsed: true,
    link: {type: 'generated-index', slug: `/${slug}/`, title: label, description},
    items,
  };
}

/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
module.exports = {
  guide: [
    {
      type: 'category',
      label: 'Introduction',
      collapsed: false,
      items: ['intro', 'getting-started'],
    },
    section('Toys', 'toys',
      'Your Bluetooth toys: the overview on Home, every toy in detail on the Toys page, and what keeps them safe.',
      ['toys/home', 'toys/toys-page', 'toys/modes', 'toys/toy-server', 'toys/toy-safety']),
    section('Your avatar', 'avatar',
      "OGP in your avatar's menu, the parameters it sends back to your avatar, and SPS 3.",
      ['avatar/menu', 'avatar/connected-parameters', 'avatar/sps3']),
    section('Shockers', 'shockers',
      'PiShock and OpenShock over USB: the hub, the safety rules, what your avatar does to them, and ShockOSC avatars.',
      ['shockers/hub', 'shockers/safety', 'shockers/behaviours', 'shockers/shockosc']),
    section('Friends', 'friends',
      "Link with other OGP users over the internet: they drive your toys, shockers and avatar, you drive theirs. Or share a link for someone's browser.",
      ['friends/adding', 'friends/what-they-may-do', 'friends/driving', 'friends/groups-and-me',
        'friends/web-remote', 'friends/vrchat-accounts']),
    section('Avatar Remote', 'avatar-remote',
      "VRC Parameter Relay's board inside OGP: your avatar's parameters as buttons, sliders and toggles, for you and your friends.",
      ['avatar-remote/board', 'avatar-remote/menu-slots', 'avatar-remote/height', 'avatar-remote/friends']),
    section('Suits and trackers', 'suits',
      "bHaptics, OWO and SteamVR trackers with a motor, fed by your avatar's body contacts on one page.",
      ['suits/bhaptics', 'suits/owo', 'suits/trackers']),
    'psvr2',
    section('Records', 'records',
      'What happened, kept on your PC: Statistics and the Log.',
      ['records/statistics', 'records/log']),
    section('Settings and tools', 'settings',
      'What you use, Off while away, Ctrl+Z, how OGP looks, and the ways it explains itself.',
      ['settings/features', 'settings/away', 'settings/undo', 'settings/appearance',
        'settings/help-and-tour']),
    {
      type: 'category',
      label: 'Help',
      collapsed: false,
      items: ['help/common-problems', 'help/linux'],
    },
  ],
};
