"use client";
import { useEffect, useState } from "react";
import { settings } from "@/lib/api-client";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";

export default function SettingsPage() {
  const [key, setKey] = useState("ai.default_provider");
  const [scope, setScope] = useState<"user" | "team" | "org" | "platform">("user");
  const [scopeId, setScopeId] = useState("");
  const [value, setValue] = useState("");
  const [resolved, setResolved] = useState<{
    scope: string;
    value: unknown;
    updated_at: string;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function loadResolved() {
    try {
      const r = await settings.get(key, scopeId || undefined);
      setResolved({ scope: r.scope, value: r.value, updated_at: r.updated_at });
    } catch {
      setResolved(null);
    }
  }

  useEffect(() => {
    loadResolved();
  }, []);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const parsed = value.trim() ? JSON.parse(value) : null;
      await settings.set(key, {
        scope,
        scope_id: scopeId || undefined,
        value: parsed,
      });
      await loadResolved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    }
  }

  async function remove() {
    setError(null);
    try {
      await settings.delete(key, scope, scopeId || undefined);
      await loadResolved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Settings</h1>
        <p className="text-muted-foreground">Override chain: user → team → org → platform.</p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Set a setting</CardTitle>
            <CardDescription>Writes at the chosen scope.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={save} className="space-y-4">
              <div className="space-y-2">
                <Label>Key</Label>
                <Input value={key} onChange={(e) => setKey(e.target.value)} required />
              </div>
              <div className="space-y-2">
                <Label>Scope</Label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                  value={scope}
                  onChange={(e) => setScope(e.target.value as typeof scope)}
                >
                  <option value="user">user</option>
                  <option value="team">team</option>
                  <option value="org">org</option>
                  <option value="platform">platform</option>
                </select>
              </div>
              <div className="space-y-2">
                <Label>Scope ID (optional)</Label>
                <Input
                  value={scopeId}
                  onChange={(e) => setScopeId(e.target.value)}
                  placeholder="UUID"
                />
              </div>
              <div className="space-y-2">
                <Label>Value (JSON)</Label>
                <Input
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  placeholder='{"p": "openai"}'
                />
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <div className="flex gap-2">
                <Button type="submit">Save</Button>
                <Button type="button" variant="destructive" onClick={remove}>
                  Delete at this scope
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Resolved value</CardTitle>
            <CardDescription>From override chain for key &quot;{key}&quot;.</CardDescription>
          </CardHeader>
          <CardContent>
            {resolved ? (
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <Badge>{resolved.scope}</Badge>
                </div>
                <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">
                  {JSON.stringify(resolved.value, null, 2)}
                </pre>
                <p className="text-xs text-muted-foreground">
                  updated {formatDate(resolved.updated_at)}
                </p>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No value set at any scope.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
