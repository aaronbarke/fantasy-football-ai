"use client";

import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { WeeklyStat } from "@/lib/types";

export default function StatChart({ stats }: { stats: WeeklyStat[] }) {
  const data = [...stats]
    .sort((a, b) => a.season - b.season || a.week - b.week)
    .slice(-8)
    .map((s) => ({
      week: `W${s.week}`,
      points: s.fantasy_points_ppr ?? 0,
    }));

  if (data.length === 0)
    return <p className="text-sm text-gray-400">No stat history available.</p>;

  return (
    <ResponsiveContainer width="100%" height={180}>
      <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
        <XAxis dataKey="week" fontSize={12} tickLine={false} />
        <YAxis fontSize={12} tickLine={false} axisLine={false} />
        <Tooltip
          formatter={(value) => [`${Number(value).toFixed(1)} pts`, "PPR"]}
        />
        <Line
          type="monotone"
          dataKey="points"
          stroke="#16a34a"
          strokeWidth={2}
          dot={{ r: 3 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
