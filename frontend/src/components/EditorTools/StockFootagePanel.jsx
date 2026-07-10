import { formatTime } from '../../utils/timeFormat';
import styles from './StockFootagePanel.module.css';

function StockFootageCard({ item, download, onSeek }) {
  const query = item.parameters?.search_query || '';
  const status = download?.status || 'idle';
  const isImage =
    (download?.mediaType || item.parameters?.media_type) === 'image';

  return (
    <div className={styles.card}>
      <div className={styles.cardHeader}>
        <span className={styles.query}>{query || 'Untitled clip'}</span>
        <span className={styles.mediaBadge}>
          {isImage ? 'Still image · max 3s' : 'Video clip · max 5s'}
        </span>
        <button
          type="button"
          className={styles.jumpButton}
          onClick={() => onSeek(Number(item.start) || 0)}
        >
          Jump to {formatTime(Number(item.start) || 0)}
        </button>
      </div>

      <div className={styles.preview}>
        {status === 'done' && download?.previewUrl ? (
          isImage ? (
            <img
              className={styles.video}
              src={download.previewUrl}
              alt={query || 'Stock still image'}
            />
          ) : (
            <video
              className={styles.video}
              src={download.previewUrl}
              controls
              preload="metadata"
            />
          )
        ) : (
          <div className={styles.placeholder}>
            {status === 'loading' && 'Downloading B-roll…'}
            {status === 'error' && (download?.error || 'Download failed')}
            {(status === 'idle' || status === 'pending') &&
              'Not downloaded yet'}
          </div>
        )}
      </div>

      <span className={styles.timecode}>
        Inserted at {formatTime(Number(item.start) || 0)} –{' '}
        {formatTime(Number(item.end) || 0)}
      </span>
    </div>
  );
}

export default function StockFootagePanel({
  items,
  downloads,
  planReady,
  isDownloading,
  error,
  onDownloadAll,
  onSaveToProject,
  onSeek,
  savedStockCount = 0,
}) {
  const hasItems = items.length > 0;
  const completedCount = items.filter(
    (item) => downloads[item.id]?.status === 'done'
  ).length;

  return (
    <section className={styles.panel}>
      <div className={styles.header}>
        <div>
          <h3>Stock Footage</h3>
          <p>
            Download B-roll — short video clips and still images — for the
            stock-footage suggestions in your editing plan, then preview where
            each will be inserted.
          </p>
        </div>
        <button
          type="button"
          className={styles.primaryButton}
          onClick={onDownloadAll}
          disabled={!planReady || !hasItems || isDownloading}
        >
          {isDownloading ? 'Downloading…' : 'Download Footage'}
        </button>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {!planReady ? (
        <p className={styles.empty}>
          Generate an editing plan first — stock-footage suggestions will appear
          here once planning is complete.
        </p>
      ) : !hasItems ? (
        <p className={styles.empty}>
          The current editing plan has no stock-footage suggestions.
        </p>
      ) : (
        <>
          {completedCount > 0 && (
            <div className={styles.saveActions}>
              <button
                type="button"
                className={styles.primaryButton}
                onClick={onSaveToProject}
                disabled={completedCount === 0}
              >
                Save {completedCount} clip{completedCount === 1 ? '' : 's'} to
                project
              </button>
              {savedStockCount > 0 && (
                <span className={styles.savedNote}>
                  {savedStockCount} clip{savedStockCount === 1 ? '' : 's'} saved ·
                  applied on render
                </span>
              )}
            </div>
          )}

          <div className={styles.list}>
            {items.map((item) => (
              <StockFootageCard
                key={item.id}
                item={item}
                download={downloads[item.id]}
                onSeek={onSeek}
              />
            ))}
          </div>
        </>
      )}
    </section>
  );
}
