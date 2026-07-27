"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Activity, GitBranch, Pause, Play, RotateCcw, X } from "lucide-react";
import { processes } from "@/lib/api-client";
import type { ProcessRecord } from "@/lib/process-types";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatDate } from "@/lib/utils";

export default function ProcessesPage() {
  const [list, setList] = useState<ProcessRecord[] | null>(null);

  async function load() {
    try {
      const data = await processes.list();
      setList(data);
    } catch {
      setList([]);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function start(id: string) {
    await processes.start(id);
    await load();
  }
  async function cancel(id: string) {
    await processes.cancel(id);
    await load();
  }
  async function resume(id: string) {
    await processes.resume(id);
    await load();
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-3xl font-bold">
          <GitBranch className="h-6 w-6" />
          Workflows
        </h1>
        <p className="text-muted-foreground">
          Multi-step DAGs that chain agent invocations together.
        </p>
      </div>

      {list === null ? (
        <p className="text-muted-foreground">Loading…</p>
      ) : list.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            No workflows yet. Create one via the API to get started.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {list.map((p) => (
            <Card key={p.id}>
              <CardHeader>
                <div className="flex items-start justify-between">
                  <div>
                    <CardTitle className="flex items-center gap-2">
                      {p.name}
                      <StatusBadge status={p.status} />
                    </CardTitle>
                    <CardDescription>
                      {p.definition.steps.length} step{p.definition.steps.length === 1 ? "" : "s"}
                      {" · "}
                      {p.definition.edges.length} edge{p.definition.edges.length === 1 ? "" : "s"}
                      {" · "}
                      Created {formatDate(p.created_at)}
                    </CardDescription>
                  </div>
                  <div className="flex gap-1">
                    {p.status === "draft" && (
                      <Button size="sm" onClick={() => start(p.id)}>
                        <Play className="mr-1 h-3 w-3" />
                        Start
                      </Button>
                    )}
                    {(p.status === "paused" || p.status === "stuck") && (
                      <Button size="sm" variant="outline" onClick={() => resume(p.id)}>
                        <RotateCcw className="mr-1 h-3 w-3" />
                        Resume
                      </Button>
                    )}
                    {["queued", "running", "paused"].includes(p.status) && (
                      <Button size="sm" variant="destructive" onClick={() => cancel(p.id)}>
                        <X className="mr-1 h-3 w-3" />
                        Cancel
                      </Button>
                    )}
                    <Link href={`/processes/${p.id}`}>
                      <Button size="sm" variant="ghost">
                        Details
                      </Button>
                    </Link>
                  </div>
                </div>
              </CardHeader>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const variant: "default" | "success" | "warning" | "destructive" | "secondary" =
    status === "completed"
      ? "success"
      : status === "failed" || status === "cancelled"
        ? "destructive"
        : status === "paused" || status === "queued" || status === "retrying"
          ? "warning"
          : status === "running"
            ? "default"
            : "secondary";
  return <Badge variant={variant}>{status}</Badge>;
}
