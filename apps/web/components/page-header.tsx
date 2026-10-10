export function PageHeader({
  title,
  description,
  actions,
  badges,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  badges?: React.ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="space-y-1.5">
        <h1 className="text-[26px] leading-tight">{title}</h1>
        {description && <p className="max-w-2xl text-muted-foreground">{description}</p>}
        {badges && <div className="flex flex-wrap gap-1.5 pt-1">{badges}</div>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}

export function SectionTitle({ children, aside }: { children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
      <h2 className="text-[15px]">{children}</h2>
      {aside}
    </div>
  );
}
