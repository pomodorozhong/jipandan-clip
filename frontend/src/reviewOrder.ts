// Exploration for the "Likely keep" order. A fixed share of clips is placed at a
// random position instead of by score, so the review log also records decisions
// on clips the score ranks low. Picks are derived from the session and clip ID,
// so they stay the same across reloads and are not shown in the list.

export const EXPLORE_RATE = 0.05;

// FNV-1a followed by the MurmurHash3 finalizer, mapped to [0, 1). Without the
// finalizer, IDs that differ only in their last digit hash to nearby values, so
// neighbouring clips would be picked (and placed) together.
function unitHash(text: string): number {
  let hash = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  hash ^= hash >>> 16;
  hash = Math.imul(hash, 0x85ebca6b);
  hash ^= hash >>> 13;
  hash = Math.imul(hash, 0xc2b2ae35);
  hash ^= hash >>> 16;
  return (hash >>> 0) / 0x1_0000_0000;
}

export function isExploreClip(seed: string, clipId: string): boolean {
  return unitHash(`${seed}:explore:${clipId}`) < EXPLORE_RATE;
}

/**
 * Order clips for "Likely keep ↓": by score, with exploration picks inserted at
 * random ranks. Inserting by rank (not by a random score) keeps picks at about
 * 1 in 20 at every depth, even though real scores bunch up near the top.
 */
export function orderByLikelyKeep<T extends { clip_id: string; likely_keep: number | null }>(
  clips: T[], seed: string | null, explore: boolean, tieBreak: (a: T, b: T) => number,
): T[] {
  const byScore = (a: T, b: T) => (b.likely_keep ?? -1) - (a.likely_keep ?? -1) || tieBreak(a, b);
  if (!explore || !seed) return [...clips].sort(byScore);
  const picks = clips.filter((clip) => isExploreClip(seed, clip.clip_id));
  if (!picks.length) return [...clips].sort(byScore);
  const pickIds = new Set(picks.map((clip) => clip.clip_id));
  const ordered = clips.filter((clip) => !pickIds.has(clip.clip_id)).sort(byScore);
  // Each pick claims a random slot in the final list; regular clips fill the rest in score order.
  const total = ordered.length + picks.length;
  const slots = picks
    .map((clip) => ({ clip, slot: Math.floor(unitHash(`${seed}:position:${clip.clip_id}`) * total) }))
    .sort((a, b) => a.slot - b.slot || tieBreak(a.clip, b.clip));
  const merged: T[] = [];
  let next = 0;
  for (const { clip, slot } of slots) {
    while (merged.length < slot && next < ordered.length) merged.push(ordered[next++]);
    merged.push(clip);
  }
  return merged.concat(ordered.slice(next));
}
