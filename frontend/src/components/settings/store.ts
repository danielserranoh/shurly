// Shared state for the settings panels. The page loads the account once and each panel
// subscribes to what it needs; late subscribers get the last published value.

import type { User } from '@/utils/types';

export interface Channel<T> {
  set(value: T): void;
  subscribe(fn: (value: T) => void): void;
}

function channel<T>(): Channel<T> {
  const subscribers = new Set<(value: T) => void>();
  let last: { value: T } | null = null;
  return {
    set(value) {
      last = { value };
      subscribers.forEach((fn) => fn(value));
    },
    subscribe(fn) {
      subscribers.add(fn);
      if (last) fn(last.value);
    },
  };
}

/** The signed-in user (GET /api/v1/auth/me), published by the settings page. */
export const currentUser = channel<User>();

/** How many of the workspace's tags are custom (not predefined); null when unknown. */
export const customTagCount = channel<number | null>();
