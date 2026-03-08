import React, { useCallback, useEffect, useRef, useState } from 'react';
import api from '../../services/api';

interface SnapshotMeta {
  date: string;
  source: string;
}

interface DateRange {
  earliest: string | null;
  latest: string | null;
  count: number;
}

interface FrontlineSliderProps {
  onDateChange: (geojson: any) => void;
  source?: string;
}

export function FrontlineSlider({ onDateChange, source = 'deepstate' }: FrontlineSliderProps) {
  const [dates, setDates] = useState<SnapshotMeta[]>([]);
  const [currentIndex, setCurrentIndex] = useState<number>(0);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const [dateRange, setDateRange] = useState<DateRange>({ earliest: null, latest: null, count: 0 });

  const playIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Fetch available dates and range on mount / source change
  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const [snapsRes, rangeRes] = await Promise.all([
          api.get<SnapshotMeta[]>(`/frontlines/snapshots?days=90`),
          api.get<DateRange>(`/frontlines/dates?source=${source}`),
        ]);
        if (cancelled) return;

        // Filter to current source, oldest → newest
        const filtered = snapsRes.data
          .filter((s) => s.source === source)
          .slice()
          .reverse();

        setDates(filtered);
        setDateRange(rangeRes.data);
        // Default to latest (last index)
        if (filtered.length > 0) {
          setCurrentIndex(filtered.length - 1);
        }
      } catch (err) {
        console.error('FrontlineSlider: failed to load dates', err);
      }
    };

    load();
    return () => { cancelled = true; };
  }, [source]);

  // Load GeoJSON whenever the selected index changes
  const loadDate = useCallback(
    async (index: number) => {
      if (dates.length === 0 || index < 0 || index >= dates.length) return;

      // Cancel any in-flight request
      if (abortRef.current) abortRef.current.abort();
      abortRef.current = new AbortController();

      const targetDate = dates[index].date;
      setLoading(true);
      try {
        const res = await api.get(`/frontlines/snapshots/${targetDate}?source=${source}`, {
          signal: abortRef.current.signal,
        });
        onDateChange(res.data);
      } catch (err: any) {
        if (err?.name !== 'CanceledError' && err?.code !== 'ERR_CANCELED') {
          console.error('FrontlineSlider: failed to load snapshot', err);
        }
      } finally {
        setLoading(false);
      }
    },
    [dates, source, onDateChange]
  );

  useEffect(() => {
    loadDate(currentIndex);
  }, [currentIndex, loadDate]);

  // Autoplay
  useEffect(() => {
    if (playing) {
      playIntervalRef.current = setInterval(() => {
        setCurrentIndex((prev) => {
          const next = prev + 1;
          if (next >= dates.length) {
            setPlaying(false);
            return prev;
          }
          return next;
        });
      }, 800);
    } else {
      if (playIntervalRef.current) {
        clearInterval(playIntervalRef.current);
        playIntervalRef.current = null;
      }
    }
    return () => {
      if (playIntervalRef.current) clearInterval(playIntervalRef.current);
    };
  }, [playing, dates.length]);

  if (dates.length === 0) return null;

  const currentDate = dates[currentIndex]?.date ?? '—';
  const displayPos = currentIndex + 1;

  const stepBack = () => {
    setPlaying(false);
    setCurrentIndex((prev) => Math.max(0, prev - 1));
  };

  const stepForward = () => {
    setPlaying(false);
    setCurrentIndex((prev) => Math.min(dates.length - 1, prev + 1));
  };

  const togglePlay = () => setPlaying((v) => !v);

  return (
    <div className="frontline-slider">
      <button
        className="frontline-slider__btn"
        onClick={stepBack}
        disabled={currentIndex === 0}
        title="Step back"
      >
        ◀
      </button>

      <button
        className={`frontline-slider__btn${playing ? ' frontline-slider__btn--active' : ''}`}
        onClick={togglePlay}
        title={playing ? 'Pause' : 'Play'}
      >
        {playing ? '⏸' : '⏵'}
      </button>

      <button
        className="frontline-slider__btn"
        onClick={stepForward}
        disabled={currentIndex >= dates.length - 1}
        title="Step forward"
      >
        ▶
      </button>

      <input
        className="frontline-slider__range"
        type="range"
        min={0}
        max={dates.length - 1}
        value={currentIndex}
        onChange={(e) => {
          setPlaying(false);
          setCurrentIndex(Number(e.target.value));
        }}
      />

      <span className="frontline-slider__date">
        {loading ? '…' : currentDate}
      </span>

      <span className="frontline-slider__count">
        {displayPos}/{dates.length}
      </span>
    </div>
  );
}
