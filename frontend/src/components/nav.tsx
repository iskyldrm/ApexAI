"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { LogOut, Settings, Key, Users, FileText, Activity, Plus } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { orgs } from "@/lib/api-client";
import type { Org } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: Activity },
  { href: "/orgs", label: "Organizations", icon: Users },
  { href: "/keys", label: "AI Keys", icon: Key },
  { href: "/audit", label: "Audit Log", icon: FileText },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Nav() {
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const [orgsList, setOrgsList] = useState<Org[]>([]);

  useEffect(() => {
    orgs.list().then(setOrgsList).catch(() => setOrgsList([]));
  }, []);

  return (
    <aside className="flex h-screen w-64 flex-col border-r bg-card">
      <div className="border-b p-4">
        <h1 className="text-xl font-bold">ApexAI</h1>
        <p className="text-xs text-muted-foreground">{user?.email}</p>
        {user?.is_platform_admin && (
          <span className="mt-1 inline-block rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary">
            Platform Admin
          </span>
        )}
      </div>

      <nav className="flex-1 space-y-1 p-2">
        {navItems.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className={cn(
              "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
              pathname === href
                ? "bg-accent text-accent-foreground"
                : "hover:bg-accent/50",
            )}
          >
            <Icon className="h-4 w-4" />
            {label}
          </Link>
        ))}
      </nav>

      {orgsList.length > 0 && (
        <div className="border-t p-3">
          <p className="mb-2 text-xs font-medium uppercase text-muted-foreground">
            Your orgs
          </p>
          <div className="space-y-1">
            {orgsList.map((o) => (
              <Link
                key={o.id}
                href={`/orgs/${o.id}`}
                className="block truncate rounded px-2 py-1 text-sm hover:bg-accent"
              >
                {o.name}
              </Link>
            ))}
          </div>
          <Link href="/orgs/new">
            <Button variant="ghost" size="sm" className="mt-2 w-full justify-start">
              <Plus className="mr-1 h-3 w-3" />
              New org
            </Button>
          </Link>
        </div>
      )}

      <div className="border-t p-3">
        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-start"
          onClick={() => logout()}
        >
          <LogOut className="mr-2 h-4 w-4" />
          Sign out
        </Button>
      </div>
    </aside>
  );
}
