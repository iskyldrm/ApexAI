"use client";
import { useEffect, useState } from "react";
import { keys } from "@/lib/api-client";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";
import type { ApiKey, Integration } from "@/lib/types";

const PROVIDERS = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "google", label: "Google" },
  { value: "ollama", label: "Ollama" },
  { value: "custom", label: "Custom" },
];

const INTEGRATION_TYPES = [
  { value: "github_pat", label: "GitHub PAT" },
  { value: "slack_token", label: "Slack Token" },
  { value: "jira_token", label: "Jira Token" },
  { value: "linear_token", label: "Linear Token" },
];

export default function KeysPage() {
  const [aiKeys, setAiKeys] = useState<ApiKey[]>([]);
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [error, setError] = useState<string | null>(null);

  // AI key form
  const [provider, setProvider] = useState("openai");
  const [label, setLabel] = useState("");
  const [value, setValue] = useState("");

  // Integration form
  const [intType, setIntType] = useState("github_pat");
  const [intLabel, setIntLabel] = useState("");
  const [intToken, setIntToken] = useState("");

  async function load() {
    try {
      const [a, i] = await Promise.all([keys.listAi(), keys.listIntegrations()]);
      setAiKeys(a);
      setIntegrations(i);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Load failed");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function createAiKey(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await keys.createAi({ provider, label, value });
      setLabel("");
      setValue("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    }
  }

  async function createIntegration(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await keys.createIntegration({
        integration_type: intType,
        label: intLabel,
        value: { token: intToken },
      });
      setIntLabel("");
      setIntToken("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    }
  }

  async function delAi(id: string) {
    if (!confirm("Delete this AI key?")) return;
    try {
      await keys.deleteAi(id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  }

  async function delInteg(id: string) {
    if (!confirm("Delete this integration?")) return;
    try {
      await keys.deleteIntegration(id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Credentials</h1>
        <p className="text-muted-foreground">AI provider keys and integrations (user-scoped).</p>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <Tabs defaultValue="ai">
        <TabsList>
          <TabsTrigger value="ai">AI Keys</TabsTrigger>
          <TabsTrigger value="integrations">Integrations</TabsTrigger>
        </TabsList>

        <TabsContent value="ai" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Add AI key</CardTitle>
              <CardDescription>Stored in HashiCorp Vault.</CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={createAiKey} className="grid grid-cols-4 gap-2">
                <div>
                  <Label>Provider</Label>
                  <Select value={provider} onValueChange={setProvider}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PROVIDERS.map((p) => (
                        <SelectItem key={p.value} value={p.value}>
                          {p.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>Label</Label>
                  <Input value={label} onChange={(e) => setLabel(e.target.value)} required />
                </div>
                <div className="col-span-2">
                  <Label>API key value</Label>
                  <Input
                    type="password"
                    value={value}
                    onChange={(e) => setValue(e.target.value)}
                    required
                  />
                </div>
                <div className="col-span-4">
                  <Button type="submit">Add AI key</Button>
                </div>
              </form>
            </CardContent>
          </Card>

          <div className="space-y-2">
            {aiKeys.map((k) => (
              <Card key={k.id}>
                <CardContent className="flex items-center justify-between p-4">
                  <div>
                    <p className="font-medium">{k.label}</p>
                    <p className="text-sm text-muted-foreground">
                      {k.provider} · created {formatDate(k.created_at)}
                      {k.last_used_at && ` · last used ${formatDate(k.last_used_at)}`}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant={k.is_active ? "success" : "secondary"}>
                      {k.is_active ? "active" : "inactive"}
                    </Badge>
                    <Button size="sm" variant="destructive" onClick={() => delAi(k.id)}>
                      Delete
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
            {aiKeys.length === 0 && (
              <p className="text-sm text-muted-foreground">No AI keys yet.</p>
            )}
          </div>
        </TabsContent>

        <TabsContent value="integrations" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Add integration</CardTitle>
            </CardHeader>
            <CardContent>
              <form onSubmit={createIntegration} className="grid grid-cols-3 gap-2">
                <div>
                  <Label>Type</Label>
                  <Select value={intType} onValueChange={setIntType}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {INTEGRATION_TYPES.map((p) => (
                        <SelectItem key={p.value} value={p.value}>
                          {p.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>Label</Label>
                  <Input value={intLabel} onChange={(e) => setIntLabel(e.target.value)} required />
                </div>
                <div>
                  <Label>Token</Label>
                  <Input
                    type="password"
                    value={intToken}
                    onChange={(e) => setIntToken(e.target.value)}
                    required
                  />
                </div>
                <div className="col-span-3">
                  <Button type="submit">Add integration</Button>
                </div>
              </form>
            </CardContent>
          </Card>

          <div className="space-y-2">
            {integrations.map((i) => (
              <Card key={i.id}>
                <CardContent className="flex items-center justify-between p-4">
                  <div>
                    <p className="font-medium">{i.label}</p>
                    <p className="text-sm text-muted-foreground">
                      {i.integration_type} · created {formatDate(i.created_at)}
                    </p>
                  </div>
                  <Button size="sm" variant="destructive" onClick={() => delInteg(i.id)}>
                    Delete
                  </Button>
                </CardContent>
              </Card>
            ))}
            {integrations.length === 0 && (
              <p className="text-sm text-muted-foreground">No integrations yet.</p>
            )}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
