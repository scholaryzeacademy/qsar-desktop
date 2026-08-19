export function tierClass(level?: string | null): string {
  switch (level) {
    case "high":
      return "bg-brand-500";
    case "med":
    case "medium":
      return "bg-amber";
    case "low":
      return "bg-clay";
    default:
      return "bg-slateout";
  }
}
