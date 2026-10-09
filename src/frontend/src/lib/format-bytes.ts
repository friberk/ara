const sizes = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 })
/** Decimal units match the model registries' published download sizes. */
export function modelBytes(bytes: number) { return bytes >= 1e9 ? `${sizes.format(bytes / 1e9)} GB` : bytes >= 1e6 ? `${sizes.format(bytes / 1e6)} MB` : bytes >= 1e3 ? `${sizes.format(bytes / 1e3)} KB` : `${bytes} B` }
