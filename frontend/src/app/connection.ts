import { useSyncExternalStore } from "react";
let connected = typeof navigator === "undefined" || navigator.onLine;
const listeners = new Set<() => void>();
export function setConnected(value: boolean) {
  // A cached/service-worker response must never restore write permission while
  // the browser itself is offline.
  value = value && (typeof navigator === "undefined" || navigator.onLine);
  if (connected !== value) {
    connected = value;
    listeners.forEach((fn) => fn());
  }
}
export function useConnection() {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    () => connected,
  );
}

if (typeof window !== "undefined") {
  const offline = () => setConnected(false);
  window.addEventListener("offline", offline);
  if (import.meta.hot)
    import.meta.hot.dispose(() =>
      window.removeEventListener("offline", offline),
    );
}
