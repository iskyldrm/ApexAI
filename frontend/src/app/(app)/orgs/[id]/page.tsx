"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { orgs, invitations } from "@/lib/api-client";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { Invitation, Membership, Org, Team } from "@/lib/types";

const ROLE_OPTIONS = [
  { value: "admin", label: "Admin" },
  { value: "manager", label: "Manager" },
  { value: "developer", label: "Developer" },
  { value: "viewer", label: "Viewer" },
  { value: "tech_support", label: "Tech Support" },
];

export default function OrgDetailPage() {
  const params = useParams<{ id: string }>();
  const orgId = params.id;
  const [org, setOrg] = useState<Org | null>(null);
  const [teams, setTeams] = useState<Team[]>([]);
  const [members, setMembers] = useState<Membership[]>([]);
  const [invitationsList, setInvitationsList] = useState<Invitation[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("developer");
  const [teamName, setTeamName] = useState("");
  const [teamSlug, setTeamSlug] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function loadAll() {
    try {
      const [o, t, m, inv] = await Promise.all([
        orgs.get(orgId),
        orgs.listTeams(orgId),
        orgs.listMembers(orgId),
        invitations.list(orgId),
      ]);
      setOrg(o);
      setTeams(t);
      setMembers(m);
      setInvitationsList(inv);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load org");
    }
  }

  useEffect(() => {
    loadAll();
  }, [orgId]);

  async function sendInvite(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await invitations.create(orgId, { email: inviteEmail, role: inviteRole });
      setInviteEmail("");
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invite failed");
    }
  }

  async function createTeam(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await orgs.createTeam(orgId, { slug: teamSlug, name: teamName });
      setTeamName("");
      setTeamSlug("");
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create team failed");
    }
  }

  async function revokeInvitation(id: string) {
    try {
      await invitations.revoke(orgId, id);
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Revoke failed");
    }
  }

  if (!org) return <p className="text-muted-foreground">Loading…</p>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">{org.name}</h1>
          <p className="text-muted-foreground">slug: {org.slug}</p>
        </div>
        <Badge variant={org.status === "active" ? "success" : "secondary"}>{org.status}</Badge>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <Tabs defaultValue="teams">
        <TabsList>
          <TabsTrigger value="teams">Teams</TabsTrigger>
          <TabsTrigger value="members">Members</TabsTrigger>
          <TabsTrigger value="invitations">Invitations</TabsTrigger>
        </TabsList>

        <TabsContent value="teams" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Create team</CardTitle>
            </CardHeader>
            <CardContent>
              <form onSubmit={createTeam} className="flex gap-2">
                <div className="flex-1">
                  <Label htmlFor="team-slug">Slug</Label>
                  <Input
                    id="team-slug"
                    value={teamSlug}
                    onChange={(e) => setTeamSlug(e.target.value)}
                    required
                  />
                </div>
                <div className="flex-1">
                  <Label htmlFor="team-name">Name</Label>
                  <Input
                    id="team-name"
                    value={teamName}
                    onChange={(e) => setTeamName(e.target.value)}
                    required
                  />
                </div>
                <div className="flex items-end">
                  <Button type="submit">Create</Button>
                </div>
              </form>
            </CardContent>
          </Card>

          <div className="grid gap-3 md:grid-cols-2">
            {teams.map((t) => (
              <Card key={t.id}>
                <CardHeader>
                  <CardTitle>{t.name}</CardTitle>
                  <CardDescription>slug: {t.slug}</CardDescription>
                </CardHeader>
              </Card>
            ))}
            {teams.length === 0 && (
              <p className="col-span-2 text-sm text-muted-foreground">No teams yet.</p>
            )}
          </div>
        </TabsContent>

        <TabsContent value="members" className="space-y-2">
          {members.map((m) => (
            <Card key={m.id}>
              <CardContent className="flex items-center justify-between p-4">
                <div>
                  <p className="font-medium">{m.email || m.user_id}</p>
                  <p className="text-sm text-muted-foreground">{m.full_name}</p>
                </div>
                <Badge>{m.role}</Badge>
              </CardContent>
            </Card>
          ))}
          {members.length === 0 && (
            <p className="text-sm text-muted-foreground">No members yet.</p>
          )}
        </TabsContent>

        <TabsContent value="invitations" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Invite member</CardTitle>
            </CardHeader>
            <CardContent>
              <form onSubmit={sendInvite} className="flex gap-2">
                <div className="flex-1">
                  <Label htmlFor="invite-email">Email</Label>
                  <Input
                    id="invite-email"
                    type="email"
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.target.value)}
                    required
                  />
                </div>
                <div className="w-40">
                  <Label>Role</Label>
                  <Select value={inviteRole} onValueChange={setInviteRole}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ROLE_OPTIONS.map((r) => (
                        <SelectItem key={r.value} value={r.value}>
                          {r.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex items-end">
                  <Button type="submit">Send invite</Button>
                </div>
              </form>
            </CardContent>
          </Card>

          <div className="space-y-2">
            {invitationsList.map((inv) => (
              <Card key={inv.id}>
                <CardContent className="flex items-center justify-between p-4">
                  <div>
                    <p className="font-medium">{inv.email}</p>
                    <p className="text-sm text-muted-foreground">
                      {inv.role} · expires {new Date(inv.expires_at).toLocaleDateString()}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant={inv.status === "pending" ? "warning" : "secondary"}>
                      {inv.status}
                    </Badge>
                    {inv.status === "pending" && (
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => revokeInvitation(inv.id)}
                      >
                        Revoke
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
            {invitationsList.length === 0 && (
              <p className="text-sm text-muted-foreground">No invitations yet.</p>
            )}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
