"use client";
import { useEffect, useState } from "react";
import { audit } from "@/lib/api-client";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";
import type { AuditLogEntry } from "@/lib/types";

export default function AuditPage() {
  const [items, setItems] = useState<AuditLogEntry[]>([]);
  const [action, setAction] = useState("");
  const [actorId, setActorId] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      const params: { action?: string; actor_id?: string; take: number } = { take: 100 };
      if (action) params.action = action;
      if (actorId) params.actor_id = actorId;
      const r = await audit.list(params);
      setItems(r.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Load failed");
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Audit log</h1>
        <p className="text-muted-foreground">Append-only event stream.</p>
      </div>

      <Card>
        <CardContent className="space-y-4 p-4">
          <div className="grid grid-cols-3 gap-2">
            <div>
              <Label>Action</Label>
              <Input value={action} onChange={(e) => setAction(e.target.value)} placeholder="auth.login" />
            </div>
            <div>
              <Label>Actor ID</Label>
              <Input value={actorId} onChange={(e) => setActorId(e.target.value)} placeholder="user uuid" />
            </div>
            <div className="flex items-end">
              <Button onClick={load} className="w-full">
                Filter
              </Button>
            </div>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </CardContent>
      </Card>

      <div className="space-y-1">
        {items.map((it) => (
          <Card key={it.id}>
            <CardContent className="flex items-center justify-between p-3 text-sm">
              <div className="flex items-center gap-3">
                <Badge variant="outline">{it.action}</Badge>
                <span className="text-muted-foreground">
                  {it.actor_email_snapshot || it.actor_id || "—"}
                </span>
                {it.target_type && (
                  <span className="text-xs text-muted-foreground">
                    → {it.target_type}:{it.target_id}
                  </span>
                )}
              </div>
              <span className="text-xs text-muted-foreground">{formatDate(it.created_at)}</span>
            </CardContent>
          </Card>
        ))}
        {items.length === 0 && (
          <p className="text-sm text-muted-foreground">No events.</p>
        )}
      </div>
    </div>
  );
}
