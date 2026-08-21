import type { Copy, TaskSummary } from './types';

interface Props {
  copy: Copy;
  tasks: TaskSummary[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  /** WS-1：历史任务搜索。宿主拿着它去请求 /tasks?q=，不在这里过滤 —— 列表可能没全在手上。 */
  search?: string;
  onSearch?: (value: string) => void;
}

function groupLabel(copy: Copy, createdAt: string, now = Date.now()): string {
  const created = new Date(createdAt).getTime();
  if (now - created < 1000 * 60 * 60 * 12) return copy.today;
  return copy.earlier;
}

export function TaskList({ copy, tasks, activeId, onSelect, onNew, search, onSearch }: Props) {
  const running = tasks.filter((t) =>
    ['created', 'planning', 'running', 'waiting_approval'].includes(t.status),
  );
  const rest = tasks.filter((t) => !running.includes(t));
  const searching = Boolean(search && search.trim());
  return (
    <div className="cw-tasklist">
      <div className="cw-brand">
        <div className="cw-wordmark">{copy.appName}</div>
        <p className="cw-tagline">{copy.tagline}</p>
      </div>
      <button type="button" className="cw-btn cw-btn-primary cw-btn-block" onClick={onNew}>
        {copy.newTask}
      </button>
      {onSearch ? (
        <div className="cw-search">
          <input
            type="search"
            className="cw-input"
            value={search ?? ''}
            placeholder={copy.searchTasks}
            aria-label={copy.searchTasks}
            onChange={(event) => onSearch(event.target.value)}
          />
        </div>
      ) : null}
      {tasks.length === 0 ? (
        <p className="cw-muted">{searching ? copy.noMatches : copy.emptyTasks}</p>
      ) : null}
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
          {/* 搜索时按时间分组是误导 —— 命中的是全部历史，不是「今天」。 */}
          <h2>{searching ? copy.searchResults : groupLabel(copy, rest[0].created_at)}</h2>
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
