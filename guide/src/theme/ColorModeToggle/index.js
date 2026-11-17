/**
 * The colour-mode toggle as every 518 app has it: Neon (the default) and
 * Midnight. Docusaurus calls them "dark" and "light"; both are dark, the
 * difference is the frame (_hub/design-518.md § 1). The label follows the
 * page's data-theme in CSS (custom.css), so it is right before React
 * hydrates too.
 */
import React from 'react';
import clsx from 'clsx';
import useIsBrowser from '@docusaurus/useIsBrowser';

export default function ColorModeToggle({className, value, onChange}) {
  const isBrowser = useIsBrowser();
  const next = value === 'light' ? 'dark' : 'light';
  return (
    <div className={clsx('modeToggle', className)}>
      <button
        type="button"
        className="modeToggle__button"
        disabled={!isBrowser}
        onClick={() => onChange(next)}
        title="Switch between Neon and Midnight"
        aria-label="Switch between Neon and Midnight">
        <span aria-hidden="true">◐</span>
        <span className="modeToggle__neon">Neon</span>
        <span className="modeToggle__midnight">Midnight</span>
      </button>
    </div>
  );
}
