/**
 * useWebSocket — Sprint 32 Checkpoint 4 (TASK-92)
 *
 * Improvements over the original hook:
 *  - Exponential backoff: 1s → 2s → 4s → 8s → … → 30s cap
 *  - Exports `disconnected` (max retries exhausted) in addition to `connected`/`reconnecting`
 *  - Exports a manual `reconnect()` callback for the "Reconnect" button
 *  - Filter state is preserved across reconnects (stored in feedStore/alertStore, not in the WS)
 *  - Connection status is exposed as a typed `status` field for richer UI display
 */
import { useEffect, useRef, useState, useCallback } from 'react';
import { useFeedStore } from '../stores/feedStore';
import { useAlertStore } from '../stores/alertStore';
import type { Post } from '../stores/feedStore';
import type { AlertEvent } from '../stores/alertStore';

export type WsStatus = 'connected' | 'reconnecting' | 'disconnected';

const MAX_RETRIES = 10;
const BASE_DELAY_MS = 1000;
const MAX_DELAY_MS = 30_000;

function getBackoffDelay(retryCount: number): number {
  return Math.min(BASE_DELAY_MS * Math.pow(2, retryCount), MAX_DELAY_MS);
}

export function useWebSocket() {
  const [status, setStatus] = useState<WsStatus>('reconnecting');
  const wsRef = useRef<WebSocket | null>(null);
  const retriesRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Track whether the hook is still mounted to prevent state updates after unmount
  const mountedRef = useRef(true);

  const getWsUrl = useCallback((): string => {
    const isLocalhost =
      window.location.hostname === 'localhost' ||
      /^(\d+\.){3}\d+$/.test(window.location.hostname);
    const host = isLocalhost
      ? `${window.location.hostname}:8000`
      : window.location.host;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${host}/ws/feed`;
  }, []);

  const connect = useCallback(() => {
    if (!mountedRef.current) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    // Cancel any pending reconnect timer
    if (reconnectTimerRef.current !== null) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }

    const ws = new WebSocket(getWsUrl());
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      setStatus('connected');
      retriesRef.current = 0;
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'ping') return;

        // Route alert messages to alert store
        if (data.type === 'alert' && data.alert) {
          useAlertStore.getState().addIncomingAlert(data.alert as AlertEvent);
          return;
        }

        useFeedStore.getState().addPost(data as Post);
      } catch {
        // ignore malformed messages
      }
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      wsRef.current = null;

      if (retriesRef.current < MAX_RETRIES) {
        setStatus('reconnecting');
        const delay = getBackoffDelay(retriesRef.current);
        retriesRef.current += 1;
        reconnectTimerRef.current = setTimeout(connect, delay);
      } else {
        setStatus('disconnected');
      }
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [getWsUrl]);

  // Manual reconnect — resets retry counter so backoff restarts from 1s
  const reconnect = useCallback(() => {
    retriesRef.current = 0;
    setStatus('reconnecting');
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    connect();
  }, [connect]);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  return {
    /** True when the WebSocket is open and healthy */
    connected: status === 'connected',
    /** True while waiting between reconnect attempts */
    reconnecting: status === 'reconnecting',
    /** True when max retries have been exhausted (show "Reconnect" button) */
    disconnected: status === 'disconnected',
    /** Full connection status string for richer UI */
    status,
    /** Manually trigger a reconnect (resets backoff counter) */
    reconnect,
  };
}
