export function isDemoModeEnabled(value) {
  return ["1", "true", "yes", "on"].includes(String(value ?? "").trim().toLowerCase());
}

export function getLocalPostgresTarget(databaseUrl) {
  try {
    const parsed = new URL(databaseUrl);
    if (!["postgresql:", "postgres:"].includes(parsed.protocol)) return null;
    if (!["localhost", "127.0.0.1"].includes(parsed.hostname)) return null;
    return {
      host: parsed.hostname,
      port: Number(parsed.port || 5432),
    };
  } catch {
    return null;
  }
}
