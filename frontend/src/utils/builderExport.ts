import { EXPORT_SCHEMAS } from '../types/builder'
import type { BuilderExportEnvelope, ExportSchema } from '../types/builder'
import { saveBlob } from './saveBlob'

/**
 * A document leaving as a file, and a file arriving as a document.
 *
 * Both halves are small and both are pure, and they live together so that the
 * file this writes is by construction the file that reads: the suffix, the
 * envelope keys and the accepted `export` values are declared once.
 *
 * WHAT IS NOT CHECKED HERE, deliberately. `readExportFile` refuses a file on
 * exactly two grounds - the `export` field and the presence of a `document` -
 * because those are the two facts that decide whether the bytes are a builder
 * export at all. Everything inside `document` is the server's to judge:
 * `POST /import` parses it, upgrades a v1 to v2 (plan 15 D5) and answers a 422
 * in its own words if it cannot. A client that re-validated the document would
 * be the second opinion spec §6.1 forbids, and it would go stale the day C1
 * lands.
 */

/** What the server's `Content-Disposition` names the file, and what this side names it. */
export const EXPORT_FILE_SUFFIX = '.builder.json'

/** `<name>.builder.json`. The browser sanitises path separators itself. */
export function exportFilename(name: string): string {
  return `${name}${EXPORT_FILE_SUFFIX}`
}

/**
 * Write the envelope to disk through the one blob-URL path the app has.
 *
 * The bytes are this side's serialisation of the server's JSON rather than the
 * response body verbatim - two-space indented, so a file an author opens in an
 * editor is readable - and the name comes off the envelope rather than off
 * `Content-Disposition`, for the reason `BuilderApi.create` gives about
 * `Location`: the header is not CORS-safelisted and `CORS_EXPOSE_HEADERS` does
 * not name it, so cross-origin it reads as null with nothing raised.
 */
export function downloadExport(envelope: BuilderExportEnvelope): void {
  const blob = new Blob([JSON.stringify(envelope, null, 2)], { type: 'application/json' })
  saveBlob(blob, exportFilename(envelope.name))
}

/**
 * A file that is not a builder export, with a sentence naming which file and
 * why. Typed so a surface can tell "the file is wrong" (render inline, keep
 * the picker) from "the server refused it" (render inline, and the document
 * inside was the problem).
 */
export class ExportFileError extends Error {
  readonly name = 'ExportFileError'
}

const isExportSchema = (value: unknown): value is ExportSchema =>
  typeof value === 'string' && (EXPORT_SCHEMAS as readonly string[]).includes(value)

/**
 * The envelope out of a file's text, or an `ExportFileError`.
 *
 * `filename` is only for the sentence. Naming the file matters more than it
 * looks: an author who picked the wrong one of three similarly-named exports
 * needs to know which was refused, and "not a builder export" alone sends
 * them back to the picker guessing.
 *
 * `needs_credentials` is defaulted rather than required, and `name` falls back
 * to the filename. Neither is one of the two facts that make a file an export,
 * and an export written by hand or by an older build should still import;
 * the server re-derives both from the document anyway.
 */
export function parseExportEnvelope(text: string, filename: string): BuilderExportEnvelope {
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    throw new ExportFileError(`${filename} is not JSON, so it cannot be a builder export.`)
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new ExportFileError(`${filename} is not a builder export: it does not hold an object.`)
  }
  const raw = parsed as Record<string, unknown>
  if (!isExportSchema(raw.export)) {
    const found = typeof raw.export === 'string' ? `"${raw.export}"` : 'missing'
    throw new ExportFileError(
      `${filename} is not a builder export: its "export" field is ${found}, ` +
        `not one of ${EXPORT_SCHEMAS.join(', ')}.`,
    )
  }
  const document = raw.document
  if (document === null || typeof document !== 'object' || Array.isArray(document)) {
    throw new ExportFileError(`${filename} carries no "document" to import.`)
  }
  const needs = Array.isArray(raw.needs_credentials)
    ? raw.needs_credentials.filter((entry): entry is string => typeof entry === 'string')
    : []
  const name =
    typeof raw.name === 'string' && raw.name.trim().length > 0
      ? raw.name
      : filename.replace(/\.builder\.json$/i, '').replace(/\.json$/i, '')
  return {
    export: raw.export,
    exported_at: typeof raw.exported_at === 'string' ? raw.exported_at : '',
    name,
    source_version: typeof raw.source_version === 'number' ? raw.source_version : 0,
    needs_credentials: needs,
    document: document as Record<string, unknown>,
  }
}

/** The envelope out of a picked file. Rejects with an `ExportFileError` for a file that is not one. */
export async function readExportFile(file: File): Promise<BuilderExportEnvelope> {
  return parseExportEnvelope(await file.text(), file.name)
}
