"use client";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { orgs, audit } from "@/lib/api-client";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export default function DashboardPage() {
  const { user } = useAuth();
  const [orgCount, setOrgCount] = useState<number | null>(null);
  const [recent, setRecent] = useState<number | null>(null);

  useEffect(() => {
    orgs
      .list()
      .then((o) => setOrgCount(o.length))
      .catch(() => setOrgCount(0));
    audit
      .list({ take: 5 })
      .then((r) => setRecent(r.items.length))
      .catch(() => setRecent(0));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Welcome back, {user?.full_name || user?.email}</h1>
        <p className="text-muted-foreground">Your ApexAI overview.</p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardDescription>Organizations</CardDescription>
            <CardTitle className="text-3xl">{orgCount ?? "—"}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">orgs you belong to</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Recent activity</CardDescription>
            <CardTitle className="text-3xl">{recent ?? "—"}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">audit events (last 5)</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Account</CardDescription>
            <CardTitle className="text-base">{user?.email}</CardTitle>
          </CardHeader>
          <CardContent>
            <Badge variant={user?.is_active ? "success" : "destructive"}>
              {user?.is_active ? "Active" : "Inactive"}
            </Badge>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
