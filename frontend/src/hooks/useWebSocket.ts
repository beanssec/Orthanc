import { useEffect, useRef, useState, useCallback } from 'react';
import { useFeedStore } from '../stores/feedStore';
import { useAlertStore } from '../stores/alertStore';
import type { Post } from '../stores/feedStore';
import type { AlertEvent } from '../stores/alertStore';

export function useWebSocket() {
  const [connected, setConnected] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const retriesRef = useRef(0);
  const maxRetries = 10;

  const getWsUrl = useCallback(() => {
    const host = window.location.hostname === 'localhost' || window.location.hostname.match(/^(\d+\.){3}\d+$/)
      ? `${window.location.hostname}:8000`
      : window.location.host;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${host}/ws/feed`;
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(getWsUrl());
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      setReconnecting(false);
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
      setConnected(false);
      wsRef.current = null;

      if (retriesRef.current < maxRetries) {
        setReconnecting(true);
        const delay = Math.min(1000 * Math.pow(2, retriesRef.current), 30000);
        retriesRef.current += 1;
        setTimeout(connect, delay);
      } else {
        setReconnecting(false);
      }
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [getWsUrl]);

  useEffect(() => {
    connect();
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  return { connected, reconnecting };
}
