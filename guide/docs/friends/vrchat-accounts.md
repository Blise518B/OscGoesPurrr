---
title: VRChat accounts and your instance
sidebar_label: VRChat accounts, instance
description: Link each friend to their VRChat account, import friends from VRCX, and let only friends in your instance drive you.
---

# VRChat accounts and your instance

An OGP friend is a nickname they chose. Linking them to their VRChat account
says "this OGP friend is that VRChat person". Then OGP can show who's with you
in VRChat, and can let only those people drive you.

The link stays on your PC. It's never sent to the friend or anyone.

## Read VRChat's log

Under the friend list, **IN YOUR VRCHAT INSTANCE** has the switch **Read
VRChat's log** (off by default). With it on, OGP reads who's in your instance
from VRChat's own log file, while VRChat runs, and shows them as chips.

## Link a friend

Either:

- drag someone from **In your VRChat instance** onto a friend's row; or
- open the friend's panel and press **Link…** next to **VRCHAT ACCOUNT**. Pick
  from the people in your instance, or from your VRChat friends in VRCX.

Their VRChat name then shows under their nickname, smaller, with **in your
instance** while they are. **Unlink** on their panel undoes it.

One VRChat account belongs to one friend: linking it to another moves it. OGP
keeps the account's user id, so a new display name doesn't break the link.
Your People statistics use one name for a linked friend.

### Import from VRCX

**Import from VRCX**, in the picker, reads your VRChat friends from
[VRCX](https://github.com/vrcx-team/VRCX)'s database: only when you click,
read-only, never written to. Without VRCX installed, the button says so.

## Only friends in your instance

**Only friends in my instance** (under Read VRChat's log, off by default)
lets only friends who are in your VRChat instance right now drive you. It's
checked on your PC from your own log: your location never leaves your PC.

- Switching it on also switches on **Read VRChat's log**.
- A friend who isn't with you shows **not here** on their row, and everything
  they send is refused like Pause, and logged. If they leave mid-session,
  their drive drops to zero at once. Their panel says "Not here".
- An unlinked friend counts as not here: their row says **not here · link
  their VRChat account**.
- **Allow from anywhere**, in a friend's VRChat account box, lets that friend
  in from anywhere.
- The **web remote** is blocked while this is on (a browser can't be in your
  instance), unless its panel's **Allow the web remote anyway** is on.
- Your own Me row is never blocked.

:::warning
With **Read VRChat's log** switched off while this is on, nobody is seen in
your instance, so no friend can drive you. OGP says so under the switch.
:::
