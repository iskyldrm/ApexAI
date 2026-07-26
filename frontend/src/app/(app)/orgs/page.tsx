"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { orgs } from "@/lib/api-client";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Plus } from "lucide-react";
import type { Org } from "@/lib/types";

export default function OrgsPage() {
  const [list, setList] = useState<Org[] | null>(null);

  useEffect(() => {
    orgs.list().then(setList).catch(() => setList([]));
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Organizations</h1>
          <p className="text-muted-foreground">All orgs you belong to.</p>
        </div>
        <Link href="/orgs/new">
          <Button>
            <Plus className="mr-2 h-4 w-4" /> New org
          </Button>
        </Link>
      </div>

      {list === null ? (
        <p className="text-muted-foreground">Loading…</p>
      ) : list.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            You&apos;re not a member of any organization yet.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {list.map((o) => (
            <Link key={o.id} href={`/orgs/${o.id}`}>
              <Card className="transition-colors hover:bg-accent/50">
                <CardHeader>
                  <CardTitle>{o.name}</CardTitle>
                  <CardDescription>slug: {o.slug}</CardDescription>
                </CardHeader>
                <CardContent>
                  <Badge variant={o.status === "active" ? "success" : "secondary"}>
                    {o.status}
                  </Badge>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
