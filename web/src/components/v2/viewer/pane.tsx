/** Khung ngăn dùng chung cho các cột ở tab パイプライン: mọi ngăn có cùng thanh tiêu đề (h-10) và cùng chiều cao dòng
 *  (h-9, kẻ dưới), nên đặt cạnh nhau thì tiêu đề và các dòng thẳng hàng. Nhãn cột của bảng nằm ngay trên thanh tiêu đề
 *  (không thêm dòng tiêu đề cột) để giữ nhịp dòng giống ngăn không có bảng. */
import { cn } from "@/lib/utils";

export function Pane({ className, children }: { className?: string; children: React.ReactNode }) {
  return <section className={cn("flex min-w-0 flex-col bg-card", className)}>{children}</section>;
}

export function PaneHeader({
  title,
  meta,
  children,
}: {
  title: React.ReactNode;
  meta?: React.ReactNode;
  /** Bên phải: nút thao tác, hoặc nhãn cột (`PaneCol`). */
  children?: React.ReactNode;
}) {
  return (
    <div className="flex h-10 shrink-0 items-center gap-2 border-b border-border px-5">
      <h2 className="truncate text-sm font-semibold">{title}</h2>
      {meta && <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{meta}</span>}
      <span className="flex-1" />
      {children}
    </div>
  );
}

/** Ô nhãn cột trên thanh tiêu đề / ô số trong dòng — cùng `width` để thẳng cột. */
export function PaneCol({ width, className, children }: { width: string; className?: string; children?: React.ReactNode }) {
  return <span className={cn("shrink-0 text-right tabular-nums", width, className)}>{children}</span>;
}

export function PaneRow({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div className={cn("flex min-h-9 items-center gap-2 border-b border-border/70 px-5 py-1.5 text-sm", className)}>
      {children}
    </div>
  );
}
