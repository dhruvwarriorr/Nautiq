"use client";
import { useSyncExternalStore } from "react";
import { browserZone } from "./ask.mjs";
// Optional per-device conveniences. Reads and writes never throw; pages render correctly without them.
const listeners = new Set<() => void>();
function subscribe(callback: () => void) {
  listeners.add(callback);
  window.addEventListener("storage", callback);
  return () => {
    listeners.delete(callback);
    window.removeEventListener("storage", callback);
  };
}
function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
export function useStored(key: string): string | null {
  return useSyncExternalStore(
    subscribe,
    () => read(key),
    () => null,
  );
}
export function setStored(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* storage unavailable */
  }
  listeners.forEach((l) => l());
}
export function useDeviceZone(): string {
  return useSyncExternalStore(
    () => () => {},
    browserZone,
    () => "UTC",
  );
}
export function useHydrated(): boolean {
  return useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
}
