"use client";

/** Recoverable route error, without exposing server details. Evaluated in design-review.mjs. */
import { ErrorState } from "@/components/ui";

export default function Error({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <ErrorState title="This screen could not load" onRetry={reset}>Reload the screen to see the latest available records.</ErrorState>;
}
