import type { ReactNode } from 'react';

interface Props {
  sidebar: ReactNode;
  main: ReactNode;
  panel: ReactNode;
  panelOpen: boolean;
}

export function WorkspaceShell({ sidebar, main, panel, panelOpen }: Props) {
  return (
    <div className="cw-shell">
      <aside className="cw-sidebar">{sidebar}</aside>
      <section className="cw-main">{main}</section>
      {panelOpen ? <aside className="cw-panel">{panel}</aside> : null}
    </div>
  );
}
