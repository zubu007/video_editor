import { useEffect, useRef, useState } from 'react';
import { formatTime } from '../../utils/timeFormat';
import {
  NumberField,
  ZoomOptions,
  StockOptions,
  DiagramOptions,
  MIN_LENGTH,
} from '../Inspector/InspectorPanel';
import styles from './EditsPanel.module.css';

// Effect edit types that can be created manually and shown in the list.
// Cuts are intentionally excluded — they come from the Silence tool.
const EDIT_TYPES = [
  { type: 'zoom', label: 'Zoom' },
  { type: 'insert_stock_footage', label: 'Stock footage' },
  { type: 'diagram', label: 'Diagram' },
];

const TYPE_LABELS = {
  zoom: 'Zoom',
  insert_stock_footage: 'B-roll',
  diagram: 'Diagram',
};

const TYPE_BADGE_CLASSES = {
  zoom: 'zoomBadge',
  insert_stock_footage: 'stockBadge',
  diagram: 'diagramBadge',
};

// Short summary of an edit's key property, shown on the collapsed row.
function editSummary(edit) {
  const meta = edit.metadata || {};
  if (edit.type === 'zoom') {
    return `×${Number(meta.zoom_level) || 1.2}`;
  }
  if (edit.type === 'insert_stock_footage') {
    return meta.search_query?.trim() || 'no query yet';
  }
  if (edit.type === 'diagram') {
    return meta.title?.trim() || meta.diagram_type || 'diagram';
  }
  return '';
}

// Dropdown button that offers the manual edit types to add.
function AddEditMenu({ onAddEdit, disabled }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const handleClickAway = (event) => {
      if (ref.current && !ref.current.contains(event.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickAway);
    return () => document.removeEventListener('mousedown', handleClickAway);
  }, [open]);

  return (
    <div className={styles.addWrap} ref={ref}>
      <button
        type="button"
        className={styles.addButton}
        onClick={() => setOpen((value) => !value)}
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        + Add edit
      </button>
      {open && (
        <div className={styles.menu} role="menu">
          {EDIT_TYPES.map((entry) => (
            <button
              key={entry.type}
              type="button"
              className={styles.menuItem}
              role="menuitem"
              onClick={() => {
                onAddEdit(entry.type);
                setOpen(false);
              }}
            >
              {entry.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function EditRow({
  edit,
  expanded,
  sourceDuration,
  stockStatus,
  onToggleExpand,
  onUpdateOverlay,
  onDeleteOverlay,
  onRefetchStock,
  onSeek,
}) {
  const badgeClass = styles[TYPE_BADGE_CLASSES[edit.type]] || '';

  return (
    <div className={`${styles.row} ${expanded ? styles.rowExpanded : ''}`}>
      <div className={styles.summary}>
        <button
          type="button"
          className={styles.expandToggle}
          aria-label={expanded ? 'Collapse edit' : 'Expand edit'}
          aria-expanded={expanded}
          onClick={() => onToggleExpand(edit.id)}
        >
          {expanded ? '▾' : '▸'}
        </button>
        <span className={`${styles.badge} ${badgeClass}`}>
          {TYPE_LABELS[edit.type] || edit.type}
        </span>
        <span className={styles.summaryValue} title={editSummary(edit)}>
          {editSummary(edit)}
        </span>
        <span className={styles.timecode}>
          {formatTime(edit.start)} – {formatTime(edit.end)}
        </span>
        <label className={styles.enabledToggle}>
          <input
            type="checkbox"
            checked={edit.enabled !== false}
            onChange={(event) =>
              onUpdateOverlay(edit, { enabled: event.target.checked })
            }
          />
          On
        </label>
        <button
          type="button"
          className={styles.iconButton}
          title={`Jump to ${formatTime(edit.start)}`}
          onClick={() => onSeek(edit.start)}
        >
          Jump
        </button>
        <button
          type="button"
          className={styles.deleteButton}
          aria-label="Delete edit"
          title="Delete edit"
          onClick={() => onDeleteOverlay(edit)}
        >
          ×
        </button>
      </div>

      {expanded && (
        <div className={styles.details}>
          <div className={styles.timingFields}>
            <NumberField
              label="Start (s)"
              value={edit.start}
              min={0}
              max={edit.end - MIN_LENGTH}
              onCommit={(start) => onUpdateOverlay(edit, { start })}
            />
            <NumberField
              label="End (s)"
              value={edit.end}
              min={edit.start + MIN_LENGTH}
              max={sourceDuration}
              onCommit={(end) => onUpdateOverlay(edit, { end })}
            />
          </div>

          {edit.type === 'zoom' && (
            <ZoomOptions overlay={edit} onUpdateOverlay={onUpdateOverlay} />
          )}
          {edit.type === 'insert_stock_footage' && (
            <StockOptions
              overlay={edit}
              stockStatus={stockStatus}
              onRefetchStock={onRefetchStock}
            />
          )}
          {edit.type === 'diagram' && (
            <DiagramOptions overlay={edit} onUpdateOverlay={onUpdateOverlay} />
          )}
        </div>
      )}
    </div>
  );
}

/**
 * "Edits" tab: manually add effect edits (zoom / stock footage / diagram) and
 * review every persisted effect edit — accepted AI suggestions and
 * manually-added ones alike — in one editable list.
 */
export default function EditsPanel({
  edits,
  sourceDuration,
  stockRefetch,
  error,
  hasProject,
  onAddEdit,
  onUpdateOverlay,
  onDeleteOverlay,
  onRefetchStock,
  onSeek,
}) {
  const [expandedId, setExpandedId] = useState(null);

  const toggleExpand = (id) =>
    setExpandedId((current) => (current === id ? null : id));

  // Show edits in timeline order so the list matches the timeline lanes.
  const orderedEdits = [...edits].sort((a, b) => a.start - b.start);

  return (
    <section className={styles.panel}>
      <div className={styles.header}>
        <div>
          <h3>Edits</h3>
          <p>Add edits manually or tweak accepted suggestions in one place.</p>
        </div>
        <AddEditMenu onAddEdit={onAddEdit} disabled={!hasProject} />
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {orderedEdits.length === 0 ? (
        <p className={styles.empty}>
          No edits yet. Use “+ Add edit” to create one, or accept a suggestion
          from the Plan, Stock Footage, or Diagrams tabs.
        </p>
      ) : (
        <div className={styles.list}>
          {orderedEdits.map((edit) => (
            <EditRow
              key={edit.id}
              edit={edit}
              expanded={expandedId === edit.id}
              sourceDuration={sourceDuration}
              stockStatus={stockRefetch?.[edit.id]}
              onToggleExpand={toggleExpand}
              onUpdateOverlay={onUpdateOverlay}
              onDeleteOverlay={onDeleteOverlay}
              onRefetchStock={onRefetchStock}
              onSeek={onSeek}
            />
          ))}
        </div>
      )}
    </section>
  );
}
