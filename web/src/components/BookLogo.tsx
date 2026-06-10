/** Open-book mark that paints itself from the active theme's accent colours
 *  (cover = --gold-dim, pages = --gold-light, text = --gold-dim). Adapts to
 *  every theme automatically. */
export function BookLogo({ className = "w-8 h-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden="true" focusable="false">
      {/* cover */}
      <path d="M8 18 L32 21 L56 18 L54 44 L32 48 L10 44 Z" fill="var(--gold-dim)" />
      {/* pages */}
      <path d="M11 20 L31 22.5 L31 45.5 L13 42 Z" fill="var(--gold-light)" />
      <path d="M53 20 L33 22.5 L33 45.5 L51 42 Z" fill="var(--gold-light)" />
      {/* text lines */}
      <g fill="var(--gold-dim)" opacity="0.5">
        {[27, 31, 35, 39].map(y => <rect key={"l" + y} x="15" y={y} width="13" height="1.7" rx="0.85" />)}
        {[27, 31, 35, 39].map(y => <rect key={"r" + y} x="36" y={y} width="13" height="1.7" rx="0.85" />)}
      </g>
    </svg>
  );
}
