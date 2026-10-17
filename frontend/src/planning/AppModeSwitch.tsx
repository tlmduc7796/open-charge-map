// "planner" is no longer offered as a tab (see MODES) but PlannerView still exists on disk.
export type AppMode = "driver" | "planner" | "gap";

interface AppModeSwitchProps {
  active: AppMode;
  onChange: (mode: AppMode) => void;
}

const MODES: { id: AppMode; label: string }[] = [
  { id: "driver", label: "Tài xế" },
  { id: "gap", label: "Khoảng trống" },
];

export default function AppModeSwitch({ active, onChange }: AppModeSwitchProps) {
  return (
    <nav className="app-mode-switch" aria-label="Chế độ ứng dụng">
      {MODES.map((mode) => (
        <button
          key={mode.id}
          type="button"
          className={active === mode.id ? "active" : ""}
          aria-current={active === mode.id ? "page" : undefined}
          onClick={() => onChange(mode.id)}
        >
          {mode.label}
        </button>
      ))}
    </nav>
  );
}
