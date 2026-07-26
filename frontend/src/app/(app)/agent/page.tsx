"use client";
import { useEffect, useState } from "react";
import { Activity, Play, RefreshCw, Sparkles, Terminal } from "lucide-react";
import { agent } from "@/lib/api-client";
import type { AgentRole, AgentRun, ConverseResponse } from "@/lib/agent-types";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";

const ROLES: { value: AgentRole; label: string; description: string }[] = [
  { value: "ANL", label: "Analyst (ANL)", description: "Read-only project analysis" },
  { value: "DEV_BE", label: "Backend Dev (DEV_BE)", description: "Python / FastAPI / DB" },
  { value: "DEV_FE", label: "Frontend Dev (DEV_FE)", description: "React / Next.js / UI" },
  { value: "QA", label: "QA", description: "Build, lint, test" },
  { value: "MGR", label: "Manager (MGR)", description: "Orchestrate via sub-agents" },
  { value: "PM", label: "PM", description: "Specs, stories" },
  { value: "SUP", label: "Support (SUP)", description: "Read-only investigation" },
];

export default function AgentPage() {
  const [role, setRole] = useState<AgentRole>("ANL");
  const [prompt, setPrompt] = useState("Analyze the project structure and list the top 5 files.");
  const [workDir, setWorkDir] = useState("/Users/me/projects");
  const [maxSteps, setMaxSteps] = useState("20");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ConverseResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runs, setRuns] = useState<AgentRun[]>([]);

  async function loadRuns() {
    try {
      const r = await agent.listRuns();
      setRuns(r.items);
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    loadRuns();
  }, []);

  async function runAgent() {
    setError(null);
    setResult(null);
    setBusy(true);
    try {
      const r = await agent.converse({
        role,
        prompt,
        work_dir: workDir,
        max_steps: maxSteps ? Number(maxSteps) : undefined,
      });
      setResult(r);
      await loadRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Run failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Sparkles className="h-6 w-6 text-primary" />
        <div>
          <h1 className="text-3xl font-bold">Agent runtime</h1>
          <p className="text-muted-foreground">
            Run a role-based specialist against a project directory.
          </p>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>New run</CardTitle>
          <CardDescription>Choose a role and provide a prompt.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label>Role</Label>
              <Select value={role} onValueChange={(v) => setRole(v as AgentRole)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ROLES.map((r) => (
                    <SelectItem key={r.value} value={r.value}>
                      {r.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                {ROLES.find((r) => r.value === role)?.description}
              </p>
            </div>
            <div className="space-y-2">
              <Label>Work directory</Label>
              <Input
                value={workDir}
                onChange={(e) => setWorkDir(e.target.value)}
                placeholder="/abs/path/to/project"
              />
              <Label className="mt-2 block">Max steps</Label>
              <Input
                type="number"
                value={maxSteps}
                onChange={(e) => setMaxSteps(e.target.value)}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label>Prompt</Label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              className="flex min-h-[120px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={runAgent} disabled={busy || !prompt || !workDir}>
              {busy ? (
                <>
                  <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                  Running…
                </>
              ) : (
                <>
                  <Play className="mr-2 h-4 w-4" />
                  Run agent
                </>
              )}
            </Button>
            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>
        </CardContent>
      </Card>

      {result && (
        <Card>
          <CardHeader>
            <CardTitle>Result</CardTitle>
            <CardDescription>
              <span className="inline-flex items-center gap-2">
                <Badge variant={result.success ? "success" : "destructive"}>
                  {result.finish_reason}
                </Badge>
                <span>{result.steps} steps · {result.input_tokens}+{result.output_tokens} tokens · {result.duration_ms}ms</span>
              </span>
            </CardDescription>
          </CardHeader>
          <CardContent>
            <pre className="overflow-x-auto rounded-md bg-muted p-4 text-sm whitespace-pre-wrap">
              {result.summary}
            </pre>
            {result.error && (
              <p className="mt-2 text-sm text-destructive">{result.error}</p>
            )}
            {result.intentional_files.length > 0 && (
              <p className="mt-2 text-xs text-muted-foreground">
                Intentional files: {result.intentional_files.join(", ")}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Terminal className="h-4 w-4" /> Recent runs
          </CardTitle>
          <CardDescription>Last 20 runs across all your orgs.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-1">
          {runs.length === 0 ? (
            <p className="text-sm text-muted-foreground">No runs yet.</p>
          ) : (
            runs.map((r) => (
              <div
                key={r.id}
                className="flex items-center justify-between rounded-md border p-3 text-sm"
              >
                <div className="flex items-center gap-3">
                  <Activity className="h-4 w-4 text-muted-foreground" />
                  <span className="font-mono text-xs">{r.id.slice(0, 8)}</span>
                  <Badge variant="outline">{r.role}</Badge>
                  <Badge
                    variant={
                      r.status === "finished"
                        ? "success"
                        : r.status === "running"
                        ? "warning"
                        : "destructive"
                    }
                  >
                    {r.status}
                  </Badge>
                </div>
                <div className="text-xs text-muted-foreground">
                  {r.steps} steps · {r.input_tokens}+{r.output_tokens} tokens
                  {r.started_at && ` · ${formatDate(r.started_at)}`}
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}
