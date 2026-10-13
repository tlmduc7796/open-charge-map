export type AppMode = "driver" | "planner";

interface AppModeSwitchProps {
  active: AppMode;
  onChange: (mode: AppMode) => void;
}

export default function AppModeSwitch({ active, onChange }: AppModeSwitchProps) {
  return (
    <nav className="app-mode-switch" aria-label="Chế độ ứng dụng">
      <button
        type="button"
        className={active === "driver" ? "active" : ""}
        aria-current={active === "driver" ? "page" : undefined}
        onClick={() => onChange("driver")}
      >
        Tài xế
      </button>
      <button
        type="button"
        className={active === "planner" ? "active" : ""}
        aria-current={active === "planner" ? "page" : undefined}
        onClick={() => onChange("planner")}
      >
        Planner
      </button>
    </nav>
  );
}
