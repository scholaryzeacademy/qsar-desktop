export function SegmentedToggle({
  value,
  onChange,
  options,
  size = "sm",
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  size?: "sm" | "md";
}) {
  return (
    <div className="flex gap-[3px] rounded-lg bg-surface2 p-[3px]">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={`flex-1 rounded-md font-semibold transition ${
            size === "sm" ? "py-[7px] text-[12.5px]" : "py-2 text-[13px]"
          } ${
            value === o.value
              ? "bg-white text-brand-700 shadow-card"
              : "text-inkmut hover:text-ink"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
