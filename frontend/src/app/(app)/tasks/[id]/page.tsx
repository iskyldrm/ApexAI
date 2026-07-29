"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { MessageSquare, ListChecks, Send } from "lucide-react";
import { tasks } from "@/lib/api-client";
import type { Task, TaskComment } from "@/lib/task-types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatDate } from "@/lib/utils";

export default function TaskDetailPage() {
  const params = useParams<{ id: string }>();
  const [task, setTask] = useState<Task | null>(null);
  const [comments, setComments] = useState<TaskComment[]>([]);
  const [newComment, setNewComment] = useState("");

  async function load() {
    if (!params?.id) return;
    try {
      const [t, c] = await Promise.all([
        tasks.get(params.id),
        tasks.comments(params.id),
      ]);
      setTask(t);
      setComments(c);
    } catch {
      setTask(null);
    }
  }

  useEffect(() => {
    load();
  }, [params?.id]);

  async function postComment() {
    if (!params?.id || !newComment.trim()) return;
    await tasks.addComment(params.id, newComment);
    setNewComment("");
    await load();
  }

  async function transition(to: string) {
    if (!params?.id) return;
    await tasks.transition(params.id, to);
    await load();
  }

  if (!task) {
    return <p className="text-muted-foreground">Loading…</p>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-3xl font-bold">
            <ListChecks className="h-6 w-6" />
            {task.title}
          </h1>
          <p className="text-muted-foreground">
            Created {formatDate(task.created_at)} · priority {task.priority}
          </p>
        </div>
        <Badge>{task.status}</Badge>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-4">
          {task.description && (
            <Card>
              <CardHeader>
                <CardTitle>Description</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="whitespace-pre-wrap text-sm">{task.description}</p>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <MessageSquare className="h-4 w-4" /> Comments ({comments.length})
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="space-y-2">
                <textarea
                  className="flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={newComment}
                  onChange={(e) => setNewComment(e.target.value)}
                  placeholder="Add a comment…"
                />
                <Button onClick={postComment} disabled={!newComment.trim()}>
                  <Send className="mr-2 h-4 w-4" />
                  Post
                </Button>
              </div>
              {comments.map((c) => (
                <div key={c.id} className="rounded-md border p-3 text-sm">
                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>{c.author_type}: {c.author_id?.slice(0, 8) ?? "anon"}</span>
                    <span>{formatDate(c.created_at)}</span>
                  </div>
                  <p className="mt-2 whitespace-pre-wrap">{c.body}</p>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Move to</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {["todo", "in_progress", "review", "done", "cancelled"].map(
                (s) => (
                  <Button
                    key={s}
                    variant={task.status === s ? "default" : "outline"}
                    size="sm"
                    className="w-full justify-start"
                    disabled={task.status === s}
                    onClick={() => transition(s)}
                  >
                    {s.replace("_", " ")}
                  </Button>
                ),
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Metadata</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1 text-xs">
              <p>
                <span className="text-muted-foreground">Source:</span>{" "}
                {task.source}
              </p>
              <p>
                <span className="text-muted-foreground">Status:</span>{" "}
                {task.status}
              </p>
              <p>
                <span className="text-muted-foreground">Priority:</span>{" "}
                {task.priority}
              </p>
              {task.due_at && (
                <p>
                  <span className="text-muted-foreground">Due:</span>{" "}
                  {formatDate(task.due_at)}
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}