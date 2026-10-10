/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_GOONG_MAPTILES_KEY: string;
  readonly VITE_DEMO_MODE: string;
  readonly VITE_OIDC_AUTHORITY: string;
  readonly VITE_OIDC_CLIENT_ID: string;
  readonly VITE_OIDC_SCOPE: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
