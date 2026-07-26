"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { orgs } from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";

export default function NewOrgPage() {
  const router = useRouter();
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const created = await orgs.create({ slug, name });
      router.push(`/orgs/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create org");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-md space-y-6">
      <h1 className="text-3xl font-bold">Create organization</h1>
      <Card>
        <CardHeader>
          <CardTitle>New org</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="slug">Slug</Label>
              <Input
                id="slug"
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                placeholder="acme-corp"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="name">Name</Label>
              <Input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Acme Corp"
                required
              />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" disabled={busy} className="w-full">
              {busy ? "Creating…" : "Create organization"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
