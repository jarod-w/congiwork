interface Props {
  text: string;
}

export function MessageStream({ text }: Props) {
  if (!text) return null;
  return (
    <article className="cw-message">
      <pre>{text}</pre>
    </article>
  );
}
