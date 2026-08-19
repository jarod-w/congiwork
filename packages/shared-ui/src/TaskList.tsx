import type { Copy, TaskSummary } from './types';

interface Props {
  copy: Copy;
  tasks: TaskSummary[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
}

function groupLabel(copy: Copy, createdAt: string, now = Date.now()): string {
  const created = new Date(createdAt).getTime();
  if (now - created < 1000 * 60 * 60 * 12) return copy.today;
  return copy.earlier;
}

export function TaskList({ copy, tasks, activeId, onSelect, onNew }: Props) {
  const running = tasks.filter((t) =>
    ['created', 'planning', 'running', 'waiting_approval'].includes(t.status),
  );
  const rest = tasks.filter((t) => !running.includes(t));
  return (
    <div className="cw-tasklist">
      <div className="cw-brand">
        <div className="cw-wordmark">{copy.appName}</div>
        <p className="cw-tagline">{copy.tagline}</p>
      </div>
      <button type="button" className="cw-btn cw-btn-primary cw-btn-block" onClick={onNew}>
        {copy.newTask}
      </button>
      {tasks.length === 0 ? <p className="cw-muted">{copy.emptyTasks}</p> : null}
      {running.length > 0 ? (
        <section>
          <h2>{copy.inProgress}</h2>
          <ul>
            {running.map((task) => (
              <li key={task.id}>
                <button
                  type="button"
                  className={task.id === activeId ? 'cw-task is-active' : 'cw-task'}
                  onClick={() => onSelect(task.id)}
                >
                  <span>{task.title || copy.newTask}</span>
                  <small>{task.status}</small>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {rest.length > 0 ? (
        <section>
          <h2>{groupLabel(copy, rest[0].created_at)}</h2>
          <ul>
            {rest.map((task) => (
              <li key={task.id}>
                <button
                  type="button"
                  className={task.id === activeId ? 'cw-task is-active' : 'cw-task'}
                  onClick={() => onSelect(task.id)}
                >
                  <span>{task.title || copy.newTask}</span>
                  <small>{task.status}</small>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
