/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_DEMO_MODE?: "live" | "replay";
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
