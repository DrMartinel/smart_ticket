"use client";

// A resource's metrics over a chosen window: its fixed queries and the PromQL a person writes, each
// answer with its link to Prometheus and a note when it was cut or refused (F17 §h.1).

import { useEffect, useState } from "react";
import { ExternalLink } from "lucide-react";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { queryRefusal, windowOf } from "@/lib/infra";
import type { MetricAnswerOut, MetricQueryIn, PromQLIn, SeriesOut } from "@/lib/types/generated";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { Panel } from "@/components/ui/panel";
import { LoadingState } from "@/components/ui/states";
import { Textarea } from "@/components/ui/textarea";

export type Unit = "percent" | "ms" | "per_second" | "number";

export interface MetricPreset {
  label: string;
  unit: Unit;
  query: Pick<MetricQueryIn, "metric" | "filters" | "function" | "function_seconds"> | { promql: string };
}

type Result = { answer: MetricAnswerOut } | { error: string };

const WINDOWS = [
  { hours: 1, label: "Last hour" },
  { hours: 6, label: "Last 6 hours" },
  { hours: 24, label: "Last 24 hours" },
];
// Labels every series carries, which say nothing about which one it is.
const COMMON_LABELS = new Set(["__name__", "project", "project_name"]);
// Series shown per answer before the rest are counted.
const SHOWN_SERIES = 8;
// Mirrors PromQLIn.promql's max_length in core-api (apps/infra/request_schema.py).
const PROMQL_MAX = 2000;

function formatted(value: number, unit: Unit): string {
  switch (unit) {
    case "percent":
      return `${(value * 100).toFixed(1)} %`;
    case "ms":
      return `${(value * 1000).toFixed(1)} ms`;
    case "per_second":
      return `${value.toFixed(2)}/s`;
    case "number":
      return Number.isInteger(value) ? String(value) : value.toPrecision(4);
  }
}

async function run(preset: MetricPreset, hours: number, projectId: string): Promise<Result> {
  const window = windowOf(hours);
  const scope = projectId ? { project_id: projectId } : {};
  try {
    const answer =
      "promql" in preset.query
        ? await api.post<MetricAnswerOut>("/api/infra/metrics/promql", { promql: preset.query.promql, ...window, ...scope } satisfies PromQLIn)
        : await api.post<MetricAnswerOut>("/api/infra/metrics/query", { ...preset.query, ...window, ...scope } satisfies MetricQueryIn);
    return { answer };
  } catch (err) {
    return { error: queryRefusal(err) ?? "Couldn't run the query." };
  }
}

export default function MetricsPanel({ presets, projectId }: { presets: MetricPreset[]; projectId: string }) {
  const [hours, setHours] = useState(WINDOWS[0].hours);
  const [results, setResults] = useState<Record<string, Result>>({});
  const [promql, setPromql] = useState("");
  const [own, setOwn] = useState<Result | null>(null);
  const [running, setRunning] = useState(false);
  const key = JSON.stringify(presets);

  useEffect(() => {
    const wanted: MetricPreset[] = JSON.parse(key);
    let current = true;
    setResults({});
    for (const preset of wanted) {
      void run(preset, hours, projectId).then((r) => {
        if (current) setResults((prev) => ({ ...prev, [preset.label]: r }));
      });
    }
    return () => {
      current = false;
    };
  }, [key, hours, projectId]);

  const runOwn = async () => {
    const text = promql.trim();
    if (!text) return;
    setRunning(true);
    setOwn(await run({ label: "PromQL", unit: "number", query: { promql: text } }, hours, projectId));
    setRunning(false);
  };

  return (
    <Panel
      title="Metrics"
      aside={
        <NativeSelect
          aria-label="Time window"
          value={hours}
          disabled={running}
          onChange={(e) => {
            setHours(Number(e.target.value));
            setOwn(null);
          }}
        >
          {WINDOWS.map((w) => (
            <option key={w.hours} value={w.hours}>
              {w.label}
            </option>
          ))}
        </NativeSelect>
      }
    >
      <div className="flex flex-col gap-4">
        {presets.map((p) => (
          <Answer key={p.label} label={p.label} unit={p.unit} result={results[p.label]} />
        ))}
        <form
          className="flex flex-col gap-2 border-t border-border pt-3"
          onSubmit={(e) => {
            e.preventDefault();
            void runOwn();
          }}
        >
          <label className="text-xs font-medium text-foreground/80" htmlFor="promql">
            PromQL over the same window, limited to this resource&apos;s project
          </label>
          <Textarea
            id="promql"
            value={promql}
            maxLength={PROMQL_MAX}
            rows={2}
            className="font-mono text-xs"
            placeholder='rate(cloud_volume_iops_total{volume_id="vol-db-01"}[5m])'
            onChange={(e) => setPromql(e.target.value)}
          />
          <div className="flex justify-end">
            <Button type="submit" size="sm" variant="outline" disabled={running || !promql.trim()}>
              Run
            </Button>
          </div>
          {own && <Answer label="Your query" unit="number" result={own} />}
        </form>
      </div>
    </Panel>
  );
}

function Answer({ label, unit, result }: { label: string; unit: Unit; result: Result | undefined }) {
  return (
    <section aria-label={label} className="flex flex-col gap-1.5 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-medium">{label}</h3>
        {result && "answer" in result && result.answer.link && (
          <a href={result.answer.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
            Open in Prometheus
            <ExternalLink className="size-3" aria-hidden />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        )}
      </div>
      {!result ? (
        <LoadingState rows={1} label={`Loading ${label}`} />
      ) : "error" in result ? (
        <p role="alert" className="text-warn">
          {result.error}
        </p>
      ) : result.answer.series.length === 0 ? (
        <p className="text-muted-foreground">No samples in this window.</p>
      ) : (
        <>
          <ul className="flex flex-col gap-1">
            {result.answer.series.slice(0, SHOWN_SERIES).map((s, i) => (
              <SeriesLine key={i} series={s} unit={unit} />
            ))}
          </ul>
          {result.answer.series.length > SHOWN_SERIES && (
            <p className="text-xs text-muted-foreground">
              And {result.answer.series.length - SHOWN_SERIES} more series; open the query to see them all.
            </p>
          )}
        </>
      )}
      {result && "answer" in result && result.answer.truncated && (
        <p className="text-xs text-warn">The answer was cut to the size limit, so some series are missing.</p>
      )}
    </section>
  );
}

function SeriesLine({ series, unit }: { series: SeriesOut; unit: Unit }) {
  const name = Object.entries(series.labels)
    .filter(([k]) => !COMMON_LABELS.has(k))
    .map(([k, v]) => `${k}=${v}`)
    .join(", ");
  const points = series.points.filter((p): p is [number, number] => p[1] !== null);
  if (points.length === 0) {
    return <li className="text-muted-foreground">{name || "series"}: no values in this window</li>;
  }
  const latest = points[points.length - 1];
  const peak = points.reduce((top, p) => (p[1] > top[1] ? p : top), points[0]);
  return (
    <li className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
      {name && <span className="font-mono text-xs text-muted-foreground">{name}</span>}
      <span>
        now <span className="num font-medium">{formatted(latest[1], unit)}</span>
      </span>
      <span>
        peak <span className="num font-medium">{formatted(peak[1], unit)}</span>{" "}
        <span className="text-xs text-muted-foreground">at {dateTime(new Date(peak[0] * 1000).toISOString())}</span>
      </span>
    </li>
  );
}
