import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

const oidc = vi.hoisted(() => {
  const handlers = new Map<string, Set<(...args: unknown[]) => void>>();
  const events = {
    addUserLoaded: (callback: (...args: unknown[]) => void) => add("userLoaded", callback),
    removeUserLoaded: (callback: (...args: unknown[]) => void) => remove("userLoaded", callback),
    addAccessTokenExpired: (callback: (...args: unknown[]) => void) => add("expired", callback),
    removeAccessTokenExpired: (callback: (...args: unknown[]) => void) => remove("expired", callback),
    addUserUnloaded: (callback: (...args: unknown[]) => void) => add("unloaded", callback),
    removeUserUnloaded: (callback: (...args: unknown[]) => void) => remove("unloaded", callback),
    addUserSignedOut: (callback: (...args: unknown[]) => void) => add("signedOut", callback),
    removeUserSignedOut: (callback: (...args: unknown[]) => void) => remove("signedOut", callback),
    emit: (event: string, ...args: unknown[]) =>
      handlers.get(event)?.forEach((callback) => callback(...args)),
  };

  function add(event: string, callback: (...args: unknown[]) => void) {
    const callbacks = handlers.get(event) ?? new Set();
    callbacks.add(callback);
    handlers.set(event, callbacks);
  }

  function remove(event: string, callback: (...args: unknown[]) => void) {
    handlers.get(event)?.delete(callback);
  }

  return {
    events,
    user: {
      access_token: "oidc-access-token",
      expired: false,
      profile: { name: "Release User", sub: "release-user-sub" },
    },
    manager: {
      events,
      getUser: vi.fn(async () => oidc.user),
      signinSilent: vi.fn(),
      signinRedirect: vi.fn(),
      signinRedirectCallback: vi.fn(),
      signoutRedirect: vi.fn(),
    },
  };
});

vi.mock("oidc-client-ts", () => ({
  UserManager: class {
    constructor() {
      return oidc.manager;
    }
  },
  WebStorageStateStore: class {},
}));

beforeEach(() => {
  vi.stubEnv("VITE_DEMO_MODE", "false");
  vi.stubEnv("VITE_OIDC_AUTHORITY", "https://identity.test/");
  vi.stubEnv("VITE_OIDC_CLIENT_ID", "smart-ev-web");
  vi.resetModules();
  sessionStorage.clear();
  oidc.manager.getUser.mockResolvedValue(oidc.user);
  oidc.manager.signinRedirectCallback.mockResolvedValue(oidc.user);
});

afterEach(() => {
  window.history.replaceState({}, "", "/");
  vi.unstubAllEnvs();
});

test("completes the OIDC callback and installs the API bearer token", async () => {
  window.history.replaceState({}, "", "/auth/callback?code=authorization-code&state=state");
  const [{ default: AuthGate }, { api }] = await Promise.all([
    import("./AuthGate"),
    import("./api"),
  ]);
  const requestHeaders: Headers[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(new URL(String(input)).pathname).toBe("/vehicles");
      requestHeaders.push(new Headers(init?.headers));
      return new Response("[]", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );

  render(<AuthGate><p>Authenticated content</p></AuthGate>);
  await screen.findByText("Release User");
  await api.vehicles();

  expect(oidc.manager.signinRedirectCallback).toHaveBeenCalledOnce();
  expect(window.location.pathname).toBe("/");
  expect(requestHeaders[0].get("Authorization")).toBe("Bearer oidc-access-token");
});

test("removes OIDC callback parameters when sign-in processing fails", async () => {
  window.history.replaceState({}, "", "/auth/callback?code=one-time-code&state=callback-state");
  oidc.manager.signinRedirectCallback.mockRejectedValueOnce(new Error("callback failed"));
  const { default: AuthGate } = await import("./AuthGate");

  render(<AuthGate><p>Authenticated content</p></AuthGate>);

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Sign-in could not be completed. Please try again.",
  );
  expect(window.location.pathname).toBe("/");
  expect(window.location.search).toBe("");
});

test.each([
  ["signed out", "signedOut"],
  ["unloaded", "unloaded"],
])("clears the API bearer token when the OIDC user is %s", async (_label, event) => {
  const [{ default: AuthGate }, { api }] = await Promise.all([
    import("./AuthGate"),
    import("./api"),
  ]);
  const requestHeaders: Headers[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    expect(new URL(String(input)).pathname).toBe("/vehicles");
    requestHeaders.push(new Headers(init?.headers));
    return new Response("[]", {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<AuthGate><p>Authenticated content</p></AuthGate>);
  await screen.findByText("Release User");

  sessionStorage.setItem("smart-ev-current-journey-id", "journey-previous-user");
  sessionStorage.setItem("journey-token:journey-previous-user", "previous-user-capability");
  sessionStorage.setItem("journey:pending-idempotency-key", "previous-user-key");

  await api.vehicles();
  expect(requestHeaders[0].get("Authorization")).toBe("Bearer oidc-access-token");

  act(() => oidc.events.emit(event));
  await api.vehicles();
  expect(requestHeaders[1].has("Authorization")).toBe(false);
  expect(sessionStorage.getItem("smart-ev-current-journey-id")).toBeNull();
  expect(sessionStorage.getItem("journey-token:journey-previous-user")).toBeNull();
  expect(sessionStorage.getItem("journey:pending-idempotency-key")).toBeNull();
});

test("clears bearer and journey capabilities when the access token expires", async () => {
  const [{ default: AuthGate }, { api }] = await Promise.all([
    import("./AuthGate"),
    import("./api"),
  ]);
  const requestHeaders: Headers[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(new URL(String(input)).pathname).toBe("/vehicles");
      requestHeaders.push(new Headers(init?.headers));
      return new Response("[]", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );

  render(<AuthGate><p>Authenticated content</p></AuthGate>);
  await screen.findByText("Release User");
  sessionStorage.setItem("smart-ev-current-journey-id", "journey-expired-user");
  sessionStorage.setItem("journey-token:journey-expired-user", "expired-user-capability");

  await api.vehicles();
  act(() => oidc.events.emit("expired"));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Your sign-in expired. Please sign in again.",
  );
  await api.vehicles();

  expect(requestHeaders[0].get("Authorization")).toBe("Bearer oidc-access-token");
  expect(requestHeaders[1].has("Authorization")).toBe(false);
  expect(sessionStorage.getItem("smart-ev-current-journey-id")).toBeNull();
  expect(sessionStorage.getItem("journey-token:journey-expired-user")).toBeNull();
});

test("clears journey capabilities immediately when sign-out starts", async () => {
  const { default: AuthGate } = await import("./AuthGate");
  render(<AuthGate><p>Authenticated content</p></AuthGate>);
  await screen.findByText("Release User");
  sessionStorage.setItem("smart-ev-current-journey-id", "journey-previous-user");
  sessionStorage.setItem("journey-token:journey-previous-user", "previous-user-capability");
  sessionStorage.setItem("journey:pending-idempotency-key", "previous-user-key");

  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
  });

  expect(oidc.manager.signoutRedirect).toHaveBeenCalledOnce();
  expect(sessionStorage.getItem("smart-ev-current-journey-id")).toBeNull();
  expect(sessionStorage.getItem("journey-token:journey-previous-user")).toBeNull();
  expect(sessionStorage.getItem("journey:pending-idempotency-key")).toBeNull();
});

test("clears a persisted journey when OIDC identity changes in the same tab", async () => {
  const { default: AuthGate } = await import("./AuthGate");
  render(<AuthGate><p>Authenticated content</p></AuthGate>);
  await screen.findByText("Release User");
  sessionStorage.setItem("smart-ev-current-journey-id", "journey-user-a");
  sessionStorage.setItem("journey-token:journey-user-a", "user-a-capability");

  act(() => oidc.events.emit("userLoaded", {
    ...oidc.user,
    profile: { ...oidc.user.profile, sub: "release-user-b" },
  }));

  expect(sessionStorage.getItem("smart-ev-current-journey-id")).toBeNull();
  expect(sessionStorage.getItem("journey-token:journey-user-a")).toBeNull();
  expect(sessionStorage.getItem("smart-ev-authenticated-subject")).toBe(
    "https://identity.test/\nrelease-user-b",
  );
});
