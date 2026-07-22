import { HealthCheck } from "./health-check";

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-8 p-8">
      <div className="text-center">
        <h1 className="text-5xl font-bold tracking-tight">NorthStar</h1>
        <p className="mt-3 max-w-md text-balance text-slate-400">
          A national talent database and intelligence platform for Egyptian
          sports. Foundation stage.
        </p>
      </div>

      <HealthCheck />

      <div className="flex gap-4 text-sm text-slate-500">
        <a
          className="underline hover:text-slate-300"
          href="http://localhost:8000/docs"
          target="_blank"
          rel="noreferrer"
        >
          API docs
        </a>
        <a
          className="underline hover:text-slate-300"
          href="https://github.com"
          target="_blank"
          rel="noreferrer"
        >
          Repo
        </a>
      </div>
    </main>
  );
}
