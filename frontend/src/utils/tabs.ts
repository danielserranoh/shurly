// Tabs that switch views in place (`role="tablist"`, the `.tab` class). A click or the arrow keys open a
// tab (roving tabindex), Home and End jump to the ends; its panel shows with a fade. The hash can name the
// tab (`#context`; the default tab has none), so a reload or a shared link opens it. A tab row wider than
// the screen scrolls sideways, fading whichever edge hides tabs and keeping the active one in view.
//
// Markup: each tab a `<button role="tab" data-tab="key" aria-controls="panel-id">`, each panel
// `role="tabpanel"`, hidden unless it's the open one.

export interface TabsOptions {
  /** The tab shown when the hash names none: the first one by default. */
  defaultKey?: string;
  /** Keep the open tab in the address's hash. */
  hash?: boolean;
  /** Runs each time a tab opens, after its panel shows. */
  onSelect?: (key: string) => void;
}

export interface Tabs {
  select(key: string, opts?: { focus?: boolean }): void;
  current(): string;
}

export function initTabs(tablist: HTMLElement, opts: TabsOptions = {}): Tabs {
  const tabs = [...tablist.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
  const keys = tabs.map((t) => t.dataset.tab!);
  const fallback = opts.defaultKey ?? keys[0];
  let open = '';

  const fromHash = () => {
    const key = location.hash.slice(1).toLowerCase();
    return keys.includes(key) ? key : fallback;
  };

  function reveal(tab: HTMLElement, smooth: boolean) {
    const left = tab.offsetLeft - (tablist.clientWidth - tab.offsetWidth) / 2;
    tablist.scrollTo({ left: Math.max(0, left), behavior: smooth ? 'smooth' : 'auto' });
  }

  function fades() {
    const max = tablist.scrollWidth - tablist.clientWidth;
    tablist.style.setProperty('--fade-start', tablist.scrollLeft > 2 ? '2rem' : '0px');
    tablist.style.setProperty('--fade-end', tablist.scrollLeft < max - 2 ? '2.5rem' : '0px');
  }

  function select(key: string, { focus = false, syncHash = opts.hash ?? false, animate = true } = {}) {
    for (const tab of tabs) {
      const on = tab.dataset.tab === key;
      const panel = document.getElementById(tab.getAttribute('aria-controls')!)!;
      tab.setAttribute('aria-selected', String(on));
      tab.tabIndex = on ? 0 : -1;
      if (on && panel.hidden) {
        panel.hidden = false;
        if (animate) {
          panel.classList.remove('animate-fade-in');
          void panel.offsetWidth; // restart the animation
          panel.classList.add('animate-fade-in');
        }
      } else if (!on) {
        panel.hidden = true;
      }
    }
    const active = tabs[keys.indexOf(key)];
    if (focus) active.focus();
    reveal(active, animate);
    if (syncHash) {
      const hash = key === fallback ? '' : `#${key}`;
      if (location.hash !== hash) history.replaceState(history.state, '', `${location.pathname}${location.search}${hash}`);
    }
    if (key !== open) {
      open = key;
      opts.onSelect?.(key);
    }
  }

  tablist.addEventListener('click', (e) => {
    const tab = (e.target as HTMLElement).closest<HTMLButtonElement>('[role="tab"]');
    if (tab) select(tab.dataset.tab!);
  });
  tablist.addEventListener('keydown', (e) => {
    const index = tabs.indexOf(document.activeElement as HTMLButtonElement);
    if (index < 0) return;
    const target = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: tabs.length - 1 }[e.key];
    if (target === undefined) return;
    e.preventDefault();
    select(keys[(target + tabs.length) % tabs.length], { focus: true });
  });
  tablist.addEventListener('scroll', fades, { passive: true });
  window.addEventListener('resize', fades);
  if (opts.hash) window.addEventListener('hashchange', () => select(fromHash(), { syncHash: false }));

  select(opts.hash ? fromHash() : fallback, { syncHash: false, animate: false });
  fades();
  return { select: (key, o) => select(key, { focus: o?.focus ?? false }), current: () => open };
}
