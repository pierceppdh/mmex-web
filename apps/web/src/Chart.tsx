import { useEffect, useRef } from "react";
import ApexCharts from "apexcharts";
import { readTheme, resolvedTheme } from "./theme";

type Series = { name: string; data: number[] };

type Props = {
  kind?: "bar" | "line" | "donut";
  categories?: string[];
  series?: Series[];
  labels?: string[];
  values?: number[];
  height?: number;
};

export function Chart({
  kind = "bar",
  categories = [],
  series = [],
  labels = [],
  values = [],
  height = 280,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const mode = resolvedTheme(readTheme());
    const muted = mode === "light" ? "#5b6b82" : "#9aa8bc";
    const line = mode === "light" ? "#d5dee9" : "#2a3548";
    const options: ApexCharts.ApexOptions = {
      chart: {
        type: kind,
        height,
        background: "transparent",
        toolbar: { show: false },
        fontFamily: "IBM Plex Sans, Segoe UI, system-ui, sans-serif",
      },
      theme: { mode },
      colors: mode === "light"
        ? ["#1b8f58", "#c62828", "#b45309", "#2563eb", "#7c3aed"]
        : ["#3dd68c", "#ff6b6b", "#f5c84c", "#7ab8ff", "#c084fc"],
      dataLabels: { enabled: false },
      stroke: { curve: "smooth", width: kind === "line" ? 2 : 0 },
      grid: { borderColor: line },
      legend: { labels: { colors: muted } },
      xaxis: {
        categories: kind === "donut" ? undefined : categories,
        labels: { style: { colors: muted } },
      },
      yaxis: { labels: { style: { colors: muted } } },
      tooltip: { theme: mode },
      series: kind === "donut" ? values : series,
      labels: kind === "donut" ? labels : undefined,
      plotOptions: {
        bar: { borderRadius: 4, columnWidth: "55%" },
        pie: { donut: { size: "62%" } },
      },
    };
    const chart = new ApexCharts(el, options);
    void chart.render();
    return () => {
      chart.destroy();
    };
  }, [kind, height, JSON.stringify(categories), JSON.stringify(series), JSON.stringify(labels), JSON.stringify(values)]);

  return <div ref={ref} className="chart" />;
}
