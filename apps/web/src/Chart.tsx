import { useEffect, useRef } from "react";
import ApexCharts from "apexcharts";

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
    const options: ApexCharts.ApexOptions = {
      chart: {
        type: kind,
        height,
        background: "transparent",
        toolbar: { show: false },
        fontFamily: "IBM Plex Sans, Segoe UI, system-ui, sans-serif",
      },
      theme: { mode: "dark" },
      colors: ["#3dd68c", "#ff6b6b", "#f5c84c", "#7ab8ff", "#c084fc"],
      dataLabels: { enabled: false },
      stroke: { curve: "smooth", width: kind === "line" ? 2 : 0 },
      grid: { borderColor: "#2a3548" },
      legend: { labels: { colors: "#9aa8bc" } },
      xaxis: {
        categories: kind === "donut" ? undefined : categories,
        labels: { style: { colors: "#9aa8bc" } },
      },
      yaxis: { labels: { style: { colors: "#9aa8bc" } } },
      tooltip: { theme: "dark" },
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
