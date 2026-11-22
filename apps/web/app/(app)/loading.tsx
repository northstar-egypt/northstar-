/** Shared route loading composition. Evaluated by the frontend build and visual review. */
import { Skeleton } from "@/components/ui";

export default function Loading() {
  return <div aria-busy="true" className="flex flex-col gap-6"><Skeleton className="h-12 w-2/3" /><div className="grid grid-cols-2 gap-4 lg:grid-cols-4">{[0, 1, 2, 3].map((key) => <Skeleton key={key} className="h-28" />)}</div><Skeleton className="h-80" /></div>;
}
