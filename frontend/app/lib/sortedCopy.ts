export function sortedCopy<T>(items: readonly T[], compare?: (a: T, b: T) => number): T[] {
  if (typeof items.toSorted === "function") return items.toSorted(compare);
  const copy = Array.from(items);
  return copy.sort(compare);
}
