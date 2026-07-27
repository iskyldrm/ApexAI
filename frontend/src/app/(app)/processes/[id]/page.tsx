"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Activity, Clock, GitBranch } from "lucide-react";
import { processes } from "@/lib/api-client";
import type { ProcessEvent, ProcessRecord } from "@/lib/process-types";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";

export default function ProcessDetailPage() {
  const params = useParams<{ id: string }>();
  const [process, setProcess] = useState<ProcessRecord | null>(null);
  const [events, setEvents] = useState<ProcessEvent[]>([]);

  async function load() {
    if (!params?.id) return;
    try {
      const [p, ev] = await Promise.all([
        processes.get(params.id),
        processes.events(params.id),
      ]);
      setProcess(p);
      setEvents(ev);
    } catch {
      setProcess(null);
    }
  }

  useEffect(() => {
    load();
  }, [params?.id]);

  if (!process) {
    return <p className="text-muted-foreground">Loading…</p>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">{process.name}</h1>
          <p className="text-muted-foreground">
            {process.steps.length} steps · Created {formatDate(process.created_at)}
          </p>
        </div>
        <Badge>{process.status}</Badge>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <GitBranch className="h-4 w-4" /> Steps
            </CardTitle>
            <CardDescription>Execution order with status.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {process.steps.map((s) => (
              <div
                key={s.id}
                className="flex items-center justify-between rounded-md border p-3 text-sm"
              >
                <div>
                  <p className="font-medium">
                    {s.step_name} <span className="text-muted-foreground">({s.role})</span>
                  </p>
                  {s.error && (
                    <p className="text-xs text-destructive">{s.error}</p>
                  )}
                  {s.agent_run_id && (
                    <p className="text-xs text-muted-foreground">
                      run: {s.agent_run_id.slice(0, 8)}…
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground">
                    {s.attempt}/{s.max_attempts}
                  </span>
                  <Badge
                    variant={
                      s.status === "completed"
                        ? "success"
                        : s.status === "failed" || s.status === "cancelled"
                          ? "destructive"
                          : s.status === "paused" || s.status === "queued" || s.status === "retrying"
                            ? "warning"
                            : s.status === "running"
                              ? "default"
                              : "secondary"
                    }
                  >
                    {s.status}
                  </Badge>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="h-4 w-4" /> Event log
            </CardTitle>
            <CardDescription>Append-only history (event-sourced).</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="max-h-96 space-y-1 overflow-y-auto">
              {events.length === 0 ? (
                <p className="text-sm text-muted-foreground">No events.</p>
              ) : (
                events.map((e) => (
                  <div
                    key={e.id}
                    className="rounded-md border-l-2 border-primary/40 bg-muted/30 px-3 py-1.5 text-xs"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono">{e.event_type}</span>
                      <span className="text-muted-foreground">
                        <Clock className="mr-1 inline h-3 w-3" />
                        {formatDate(e.created_at)}
                      </span>
                    </div>
                    {e.actor_id && (
                      <p className="text-muted-foreground">by {e.actor_id}</p>
                    )}
                  </div>
                ))
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
