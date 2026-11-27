/** Build valid persisted cut edits from detected Dota dead intervals. */
export function buildDeathCutEdits(intervals, padding, mediaAssetId) {
  const safePadding = Number.isFinite(padding) ? Math.max(0, padding) : 0;
  const edits = [];
  let skipped = 0;

  for (const interval of intervals) {
    const end = Number(Number(interval.end).toFixed(2));
    const start = Number(
      Math.min(Number(interval.start) + safePadding, end).toFixed(2)
    );
    if (end <= start) {
      skipped += 1;
      continue;
    }
    edits.push({
      type: 'cut',
      source: 'death_detection',
      start,
      end,
      enabled: true,
      media_asset_id: mediaAssetId,
      metadata: {
        duration: Number((end - start).toFixed(2)),
        kind: 'death',
        start_padding: safePadding,
      },
    });
  }

  return { edits, skipped };
}
