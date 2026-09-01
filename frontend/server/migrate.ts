// Brings the Better Auth schema up to date, in-process, at startup.
//
// WHY NOT THE CLI. `npx auth@latest migrate` is the documented path and is what
// `npm run auth:migrate` still runs for local work. It is the wrong tool for a
// deploy for two reasons: in Render's BUILD step it may not reach a database
// whose `ipAllowList` is empty, and in the START command it would download a
// package over the network on every boot. `getMigrations` is the same code the
// CLI calls, so this is not a reimplementation - it is the CLI's engine without
// the CLI.
import { getMigrations } from "better-auth/db/migration";
import { auth } from "./auth.ts";

export async function applyMigrations(): Promise<void> {
  if (process.env.AUTH_SKIP_MIGRATIONS === "1") {
    console.log("[auth-web] AUTH_SKIP_MIGRATIONS=1, leaving the schema alone");
    return;
  }

  // `throwOnUnsafe` is left ON (the default). It refuses to add a required
  // column with no default to a table that already has rows - which is exactly
  // the change that cannot be applied without deciding what the existing rows
  // should say. Better a failed deploy than a half-migrated auth table.
  const { toBeCreated, toBeAdded, runMigrations } = await getMigrations(
    auth.options,
  );

  const created = toBeCreated.map((entry) => entry.table);
  const altered = toBeAdded.map((entry) => entry.table);

  if (created.length === 0 && altered.length === 0) {
    console.log("[auth-web] auth schema is current");
    return;
  }

  await runMigrations();
  if (created.length) console.log(`[auth-web] created tables: ${created.join(", ")}`);
  if (altered.length) console.log(`[auth-web] altered tables: ${altered.join(", ")}`);
}
