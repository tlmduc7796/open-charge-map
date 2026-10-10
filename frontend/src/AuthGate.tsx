import { useEffect, useState, type ReactNode } from "react";
import { UserManager, WebStorageStateStore, type User } from "oidc-client-ts";

import { clearJourneySessionState, setAccessTokenProvider } from "./api";

const DEMO_MODE = import.meta.env.VITE_DEMO_MODE !== "false";
const authority = import.meta.env.VITE_OIDC_AUTHORITY ?? "";
const clientId = import.meta.env.VITE_OIDC_CLIENT_ID ?? "";
const scope = import.meta.env.VITE_OIDC_SCOPE ?? "openid profile email offline_access";
const configured = Boolean(authority && clientId);
const manager = configured ? new UserManager({
  authority,
  client_id: clientId,
  redirect_uri: `${window.location.origin}/auth/callback`,
  post_logout_redirect_uri: window.location.origin,
  response_type: "code",
  scope,
  automaticSilentRenew: true,
  userStore: new WebStorageStateStore({ store: window.sessionStorage }),
}) : null;

export default function AuthGate({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(DEMO_MODE || !configured);
  const [error, setError] = useState<string | null>(
    !DEMO_MODE && !configured
      ? "Release login is not configured. Set VITE_OIDC_AUTHORITY and VITE_OIDC_CLIENT_ID."
      : null,
  );

  useEffect(() => {
    if (DEMO_MODE) return;
    if (!manager) return;
    let active = true;
    const updateUser = (next: User) => {
      if (!active) return;
      const subject = typeof next.profile.sub === "string" ? next.profile.sub : "";
      const identity = subject ? `${authority}\n${subject}` : "";
      try {
        const previousIdentity = sessionStorage.getItem("smart-ev-authenticated-subject");
        if (previousIdentity !== identity) clearJourneySessionState();
        if (identity) sessionStorage.setItem("smart-ev-authenticated-subject", identity);
      } catch {
        clearJourneySessionState();
      }
      setUser(next);
      setError(null);
      setAccessTokenProvider(() => next.access_token);
    };
    const expireUser = () => {
      if (!active) return;
      setUser(null);
      setAccessTokenProvider(() => null);
      clearJourneySessionState();
      setError("Your sign-in expired. Please sign in again.");
    };
    const unloadUser = () => {
      if (!active) return;
      setUser(null);
      setAccessTokenProvider(() => null);
      clearJourneySessionState();
    };
    manager.events.addUserLoaded(updateUser);
    manager.events.addAccessTokenExpired(expireUser);
    manager.events.addUserUnloaded(unloadUser);
    manager.events.addUserSignedOut(unloadUser);
    const initialize = async () => {
      try {
        let current = window.location.pathname === "/auth/callback"
          ? await manager.signinRedirectCallback()
          : await manager.getUser();
        if (current?.expired) current = await manager.signinSilent();
        if (!active) return;
        if (window.location.pathname === "/auth/callback") window.history.replaceState({}, "", "/");
        if (current) updateUser(current);
        else {
          setAccessTokenProvider(() => null);
          clearJourneySessionState();
        }
      } catch {
        if (active) {
          if (window.location.pathname === "/auth/callback") {
            window.history.replaceState({}, "", "/");
          }
          clearJourneySessionState();
          setError("Sign-in could not be completed. Please try again.");
        }
      } finally {
        if (active) setReady(true);
      }
    };
    void initialize();
    return () => {
      active = false;
      manager.events.removeUserLoaded(updateUser);
      manager.events.removeAccessTokenExpired(expireUser);
      manager.events.removeUserUnloaded(unloadUser);
      manager.events.removeUserSignedOut(unloadUser);
      setAccessTokenProvider(null);
    };
  }, []);

  if (DEMO_MODE) return children;
  if (!ready) return <main className="auth-screen">Checking sign-in…</main>;
  if (error) return <main className="auth-screen">
    <p role="alert">{error}</p>
    {manager && <button onClick={() => void manager.signinRedirect()}>Sign in again</button>}
  </main>;
  if (!user?.access_token) return <main className="auth-screen">
    <h1>Smart EV Journey</h1><p>Sign in to plan and manage a journey.</p>
    <button onClick={() => void manager?.signinRedirect()}>Sign in</button>
  </main>;
  return <>
    <div className="auth-bar"><span>{user.profile.name ?? user.profile.email ?? "Signed in"}</span>
      <button onClick={() => {
        clearJourneySessionState();
        void manager?.signoutRedirect();
      }}>Sign out</button></div>
    {children}
  </>;
}
