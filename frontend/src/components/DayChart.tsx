import type { Day } from "../types";

const COL = 14;
const BAR = 9;
const H = 120;

/**
 * Hours per day for the month, drawn by hand in SVG: one column a day, the
 * even plan as a dashed gold line. Working days that met the plan are arc;
 * short ones arc at rest; time on a day off is slate. Days to come are a
 * low engraved slot, a day of leave a dashed outline up to the plan: a day
 * the plan doesn't ask for.
 *
 * The day numbers are HTML under the drawing, not SVG text: the drawing
 * scales with the width, and text inside it would fall under --t-min on a
 * phone and balloon on a desk.
 */
export function DayChart({ days, plan, today }: { days: Day[]; plan: number; today: string | null }) {
  const top = Math.max(plan * 1.6, ...days.map((d) => d.hours), 1);
  const y = (h: number) => H - (h / top) * H;
  const width = days.length * COL;
  return (
    <div>
      <svg className="chart" viewBox={`0 0 ${width} ${H}`} role="img"
        aria-label={`Hours per day; plan ${plan.toFixed(1)} hours a working day`}>
        {days.map((d, i) => {
          const x = i * COL + (COL - BAR) / 2;
          const isToday = d.date === today;
          let mark;
          if (d.hours > 0) {
            const cls = !d.working ? "bar bar-off" : isToday ? "bar bar-today" : d.hours >= plan * 0.95 ? "bar bar-met" : "bar";
            mark = <rect className={cls} x={x} y={y(d.hours)} width={BAR} height={H - y(d.hours)} />;
          } else if (d.leave) {
            mark = <rect className="slot-leave" x={x + 1} y={y(plan)} width={BAR - 2} height={H - y(plan) - 1} />;
          } else if (d.working) {
            mark = <rect className="slot" x={x} y={H - 3} width={BAR} height={3} />;
          }
          return (
            <g key={d.date}>
              <title>{`${d.date}: ${d.hours.toFixed(2)} h${d.leave ? " (leave)" : !d.working ? " (day off)" : ""}`}</title>
              {mark}
            </g>
          );
        })}
        {plan > 0 && <line className="plan" x1={0} x2={width} y1={y(plan)} y2={y(plan)} />}
      </svg>
      <div className="chart-axis" aria-hidden="true">
        {days.map((d, i) => {
          const n = Number(d.date.slice(8));
          const isToday = d.date === today;
          if (!(isToday || n === 1 || n % 7 === 1)) return null;
          // Today's label wins; a weekly mark right beside it would collide.
          if (!isToday && today && Math.abs(Number(today.slice(8)) - n) < 3) return null;
          return (
            <span key={d.date} className={isToday ? "axis-today" : ""} style={{ left: `${((i + 0.5) / days.length) * 100}%` }}>
              {n}
            </span>
          );
        })}
      </div>
    </div>
  );
}
