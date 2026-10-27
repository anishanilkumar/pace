/** Progress as a row of index ticks: `lit` arc, `warn` gold, `over` arc-dim, the rest engraved. */
export function Ticks({ total, lit, warn = 0, over = 0, className = "" }: {
  total: number;
  lit: number;
  warn?: number;
  over?: number;
  className?: string;
}) {
  const ticks = [];
  for (let i = 0; i < total + over; i++) {
    const cls = i < lit ? (i >= total ? "lit over" : "lit") : i < lit + warn ? "warn" : "";
    ticks.push(<i key={i} className={cls} />);
  }
  return <div className={`ticks ${className}`} aria-hidden="true">{ticks}</div>;
}
