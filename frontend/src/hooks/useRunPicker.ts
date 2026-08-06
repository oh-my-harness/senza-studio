import { useCallback, useEffect, useRef, useState } from 'react';
import { useProjectStore } from '../store/projectStore';
import { api } from '../lib/api';
import type { StudioEvent } from '../types';

/** Decode a UUIDv7's leading 48 bits (big-endian ms since epoch) into a Date. */
export function uuidv7ToDate(uuid: string): Date | null {
  const hex = uuid.replace(/-/g, '').slice(0, 12);
  if (hex.length < 12) return null;
  const ms = parseInt(hex, 16);
  return Number.isFinite(ms) ? new Date(ms) : null;
}

export interface UseRunPickerResult {
  runIds: string[]; // most-recent-first
  loadingRunIds: boolean;
  selectedRunId: string | null; // null = "Live"
  selectRun: (id: string | null) => void;
  events: StudioEvent[];
  mode: 'live' | 'historical' | 'empty';
  loadingEvents: boolean;
  fetchError: string | null;
  refreshRunIds: () => void;
}

/**
 * Drives the Trace tab's run picker. Deliberately component-local state
 * (not projectStore) — nothing outside Trace needs it. When the selected
 * run is the currently-live run, aliases straight to projectStore's
 * liveEvents and skips the REST fetch entirely, so switching back to
 * "Live" mid-run just resumes showing whatever has been accumulating the
 * whole time.
 */
export function useRunPicker(projectId: string | undefined): UseRunPickerResult {
  const activeRunId = useProjectStore((s) => s.activeRunId);
  const liveEvents = useProjectStore((s) => s.liveEvents);

  const [runIds, setRunIds] = useState<string[]>([]);
  const [loadingRunIds, setLoadingRunIds] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [loadingEvents, setLoadingEvents] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [historicalEvents, setHistoricalEvents] = useState<StudioEvent[]>([]);
  const cacheRef = useRef<Map<string, StudioEvent[]>>(new Map());

  const refreshRunIds = useCallback(() => {
    if (!projectId) return;
    setLoadingRunIds(true);
    api
      .listRuns(projectId)
      .then((ids) => setRunIds([...ids].reverse())) // run-ids are UUIDv7 — lexicographic order is chronological
      .catch(() => setRunIds([]))
      .finally(() => setLoadingRunIds(false));
  }, [projectId]);

  useEffect(() => {
    refreshRunIds();
  }, [refreshRunIds]);

  // Pick up a freshly-started run in the picker without requiring a manual refresh.
  useEffect(() => {
    if (activeRunId) refreshRunIds();
  }, [activeRunId, refreshRunIds]);

  const selectRun = useCallback(
    (id: string | null) => {
      setSelectedRunId(id);
      setFetchError(null);
      if (id === null || id === activeRunId) return; // live — resolved by aliasing below
      const cached = cacheRef.current.get(id);
      if (cached) {
        setHistoricalEvents(cached);
        return;
      }
      if (!projectId) return;
      setLoadingEvents(true);
      api
        .getRunEvents(projectId, id)
        .then((events) => {
          cacheRef.current.set(id, events);
          setHistoricalEvents(events);
        })
        .catch((e) => setFetchError(e instanceof Error ? e.message : String(e)))
        .finally(() => setLoadingEvents(false));
    },
    [projectId, activeRunId],
  );

  const isLive = selectedRunId === null || selectedRunId === activeRunId;
  const events = isLive ? liveEvents : historicalEvents;
  const mode: UseRunPickerResult['mode'] = isLive ? (events.length ? 'live' : 'empty') : 'historical';

  return {
    runIds,
    loadingRunIds,
    selectedRunId,
    selectRun,
    events,
    mode,
    loadingEvents,
    fetchError,
    refreshRunIds,
  };
}
