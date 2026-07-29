"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Plus, ListChecks } from "lucide-react";
import { tasks } from "@/lib/api-client";
import type { Task, TaskStatus } from "@/lib/task-types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const COLUMNS: { id: TaskStatus; label: string }[] = [
  { id: "todo", label: "To do" },
  { id: "in_progress", label: "In progress" },
  { id: "review", label: "In review" },
  { id: "done", label: "Done" },
  { id: "cancelled", label: "Cancelled" },
];

const PRIORITY_VARIANTS: Record<string, "default" | "secondary" | "destructive" | "warning" | "success"> = {
  urgent: "destructive",
  high: "warning",
  medium: "default",
  low: "secondary",
};

export default function TasksPage() {
  const [tasksList, setTasksList] = useState<Task[] | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newPriority, setNewPriority] = useState("medium");

  async function load() {
    try {
      const data = await tasks.list({ scope: "mine" });
      setTasksList(data);
    } catch {
      setTasksList([]);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function transition(id: string, to: TaskStatus) {
    await tasks.transition(id, to);
    await load();
  }

  async function createTask() {
    if (!newTitle.trim()) return;
    await tasks.create({ title: newTitle, priority: newPriority as any });
    setNewTitle("");
    setNewPriority("medium");
    setShowCreate(false);
    await load();
  }

  const byStatus = COLUMNS.reduce<Record<TaskStatus, Task[]>>(
    (acc, col) => {
      acc[col.id] = (tasksList || []).filter((t) => t.status === col.id);
      return acc;
    },
    { todo: [], in_progress: [], review: [], done: [], cancelled: [] },
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-3xl font-bold">
            <ListChecks className="h-6 w-6" />
            Tasks
          </h1>
          <p className="text-muted-foreground">
            Kanban view of tasks you own or are assigned to.
          </p>
        </div>
        <Button onClick={() => setShowCreate(!showCreate)}>
          <Plus className="mr-1 h-4 w-4" />
          New task
        </Button>
      </div>

      {showCreate && (
        <Card>
          <CardContent className="space-y-3 pt-6">
            <div className="space-y-2">
              <Label>Title</Label>
              <Input
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                placeholder="What needs to be done?"
              />
            </div>
            <div className="space-y-2">
              <Label>Priority</Label>
              <Select value={newPriority} onValueChange={setNewPriority}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="low">Low</SelectItem>
                  <SelectItem value="medium">Medium</SelectItem>
                  <SelectItem value="high">High</SelectItem>
                  <SelectItem value="urgent">Urgent</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex gap-2">
              <Button onClick={createTask}>Create</Button>
              <Button variant="ghost" onClick={() => setShowCreate(false)}>
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-5">
        {COLUMNS.map((col) => (
          <Card key={col.id}>
            <CardHeader>
              <CardTitle className="flex items-center justify-between text-sm">
                <span>{col.label}</span>
                <Badge variant="secondary">{byStatus[col.id].length}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {byStatus[col.id].length === 0 ? (
                <p className="text-xs text-muted-foreground">No tasks.</p>
              ) : (
                byStatus[col.id].map((t) => (
                  <div
                    key={t.id}
                    className="rounded-md border bg-card p-3 text-sm space-y-2"
                  >
                    <Link
                      href={`/tasks/${t.id}`}
                      className="block font-medium hover:underline"
                    >
                      {t.title}
                    </Link>
                    {t.description && (
                      <p className="line-clamp-2 text-xs text-muted-foreground">
                        {t.description}
                      </p>
                    )}
                    <div className="flex items-center justify-between">
                      <Badge variant={PRIORITY_VARIANTS[t.priority] || "default"}>
                        {t.priority}
                      </Badge>
                      <select
                        className="text-xs rounded border bg-background px-1 py-0.5"
                        value={t.status}
                        onChange={(e) =>
                          transition(t.id, e.target.value as TaskStatus)
                        }
                      >
                        {COLUMNS.map((c) => (
                          <option key={c.id} value={c.id}>
                            → {c.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}