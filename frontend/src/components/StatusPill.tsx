type StatusPillProps = {
  label: string;
  tone?: "ok" | "warn" | "error";
};

export default function StatusPill({ label, tone = "ok" }: StatusPillProps) {
  const color = tone === "error" ? "#ef4444" : tone === "warn" ? "#f59e0b" : "#10b981";
  return (
    <span className="status-pill">
      <span className="dot" style={{ background: color, boxShadow: `0 0 12px ${color}` }} />
      {label}
    </span>
  );
}
