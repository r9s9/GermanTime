import { Icon } from "./Icon";

export function PageStub({
  title,
  subtitle,
  icon,
}: {
  title: string;
  subtitle: string;
  icon: string;
}) {
  return (
    <div>
      <h1 className="text-2xl font-semibold">{title}</h1>
      <div className="card mt-6 flex flex-col items-center gap-3 px-8 py-16 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-white/5 text-mute">
          <Icon name={icon} size={26} />
        </div>
        <p className="max-w-md text-sm text-mute">{subtitle}</p>
      </div>
    </div>
  );
}
