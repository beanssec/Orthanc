import { useCallback, useEffect, useRef, useState } from 'react';
import api from '../../services/api';
import { DashboardView } from './DashboardView';
import { DashboardGrid } from './DashboardGrid';
import { WidgetConfig } from './WidgetCard';
import '../../styles/dashboard-tabs.css';

// ── Types ──────────────────────────────────────────────────

interface DashboardTab {
  id: string;
  name: string;
  icon?: string;
  is_default: boolean;
  position: number;
  layout: WidgetConfig[];
}

// ── Add/Edit Tab Modal ─────────────────────────────────────

interface TabModalProps {
  initial?: { name: string; icon: string };
  title: string;
  onConfirm: (name: string, icon: string) => void;
  onCancel: () => void;
}

function TabModal({ initial, title, onConfirm, onCancel }: TabModalProps) {
  const [name, setName] = useState(initial?.name ?? '');
  const [icon, setIcon] = useState(initial?.icon ?? '📌');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (name.trim()) {
      onConfirm(name.trim(), icon.trim() || '📌');
    }
  };

  return (
    <div className="tab-modal-overlay" onClick={onCancel}>
      <div className="tab-modal" onClick={(e) => e.stopPropagation()}>
        <div className="tab-modal__title">{title}</div>
        <form onSubmit={handleSubmit} style={{ display: 'contents' }}>
          <div className="tab-modal__field">
            <label className="tab-modal__label">Icon (emoji)</label>
            <input
              className="tab-modal__input"
              value={icon}
              onChange={(e) => setIcon(e.target.value)}
              placeholder="📌"
              maxLength={4}
              style={{ width: '80px' }}
            />
          </div>
          <div className="tab-modal__field">
            <label className="tab-modal__label">Tab Name</label>
            <input
              className="tab-modal__input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My Tab"
              autoFocus
              maxLength={32}
            />
          </div>
          <div className="tab-modal__actions">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={onCancel}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-primary btn-sm"
              disabled={!name.trim()}
            >
              {initial ? 'Save' : 'Create'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Confirm Delete Modal ───────────────────────────────────

interface ConfirmDeleteProps {
  tabName: string;
  onConfirm: () => void;
  onCancel: () => void;
}

function ConfirmDelete({ tabName, onConfirm, onCancel }: ConfirmDeleteProps) {
  return (
    <div className="tab-modal-overlay" onClick={onCancel}>
      <div className="tab-modal" onClick={(e) => e.stopPropagation()}>
        <div className="tab-modal__title">Delete Tab</div>
        <div style={{ fontSize: '13px', color: 'var(--text-muted)', lineHeight: 1.5 }}>
          Delete <strong style={{ color: 'var(--text)' }}>{tabName}</strong>?
          This will remove all widgets on this tab. This cannot be undone.
        </div>
        <div className="tab-modal__actions">
          <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-sm"
            style={{ background: '#ef4444', color: '#fff', border: 'none' }}
            onClick={onConfirm}
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}

// ── DashboardTabs ──────────────────────────────────────────

export function DashboardTabs() {
  const [tabs, setTabs] = useState<DashboardTab[]>([]);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modal state
  const [showAddModal, setShowAddModal] = useState(false);
  const [editingTab, setEditingTab] = useState<DashboardTab | null>(null);
  const [deletingTab, setDeletingTab] = useState<DashboardTab | null>(null);

  // Context menu (right-click) state
  const [contextMenu, setContextMenu] = useState<{ tabId: string; x: number; y: number } | null>(null);
  const contextMenuRef = useRef<HTMLDivElement>(null);

  const fetchTabs = useCallback(async () => {
    try {
      const res = await api.get<DashboardTab[]>('/dashboard-tabs/');
      const tabList = res.data ?? [];
      setTabs(tabList);
      // Activate first tab or keep current if still valid
      if (tabList.length > 0) {
        setActiveTabId((prev) => {
          if (prev && tabList.some((t) => t.id === prev)) return prev;
          return tabList[0].id;
        });
      }
      setError(null);
    } catch (err) {
      // If the tabs endpoint doesn't exist yet, show Overview as a fallback
      if ((err as { response?: { status: number } })?.response?.status === 404) {
        setTabs([]);
        setActiveTabId(-1); // -1 = fallback Overview
      } else {
        setError(err instanceof Error ? err.message : 'Failed to load tabs');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTabs();
  }, [fetchTabs]);

  // Close context menu on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (contextMenuRef.current && !contextMenuRef.current.contains(e.target as Node)) {
        setContextMenu(null);
      }
    };
    if (contextMenu) {
      document.addEventListener('mousedown', handler);
    }
    return () => document.removeEventListener('mousedown', handler);
  }, [contextMenu]);

  // ── Tab actions ──────────────────────────────────────────

  const handleAddTab = async (name: string, icon: string) => {
    try {
      const res = await api.post<DashboardTab>('/dashboard-tabs/', {
        name,
        icon,
        layout: [],
      });
      const newTab = res.data;
      setTabs((prev) => [...prev, newTab]);
      setActiveTabId(newTab.id);
      setShowAddModal(false);
    } catch (err) {
      console.error('Failed to create tab', err);
    }
  };

  const handleEditTab = async (name: string, icon: string) => {
    if (!editingTab) return;
    try {
      const res = await api.put<DashboardTab>(`/dashboard-tabs/${editingTab.id}`, {
        name,
        icon,
        layout: editingTab.layout,
      });
      setTabs((prev) =>
        prev.map((t) => (t.id === editingTab.id ? { ...t, ...res.data } : t))
      );
      setEditingTab(null);
    } catch (err) {
      console.error('Failed to update tab', err);
    }
  };

  const handleDeleteTab = async () => {
    if (!deletingTab) return;
    try {
      await api.delete(`/dashboard-tabs/${deletingTab.id}`);
      const remaining = tabs.filter((t) => t.id !== deletingTab.id);
      setTabs(remaining);
      if (activeTabId === deletingTab.id) {
        setActiveTabId(remaining.length > 0 ? remaining[0].id : null);
      }
      setDeletingTab(null);
    } catch (err) {
      console.error('Failed to delete tab', err);
    }
  };

  const handleLayoutChange = useCallback((tabId: string, updatedWidgets: WidgetConfig[]) => {
    setTabs((prev) =>
      prev.map((t) => (t.id === tabId ? { ...t, layout: updatedWidgets } : t))
    );
  }, []);

  // ── Render ───────────────────────────────────────────────

  if (loading) {
    return (
      <div className="dashboard-tabs">
        <div className="dashboard-tabs__loading">
          <span>⟳</span> Loading tabs…
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="dashboard-tabs">
        <div className="dashboard-tabs__error">⚠ {error}</div>
      </div>
    );
  }

  // Fallback: if tabs endpoint doesn't exist, just render DashboardView
  if (tabs.length === 0 && activeTabId === -1) {
    return <DashboardView />;
  }

  const activeTab = tabs.find((t) => t.id === activeTabId) ?? tabs[0] ?? null;

  const renderTabContent = (tab: DashboardTab) => {
    // Only the "Overview" tab renders the full existing DashboardView
    if (tab.name === 'Overview') {
      return (
        <div className="tab-content tab-content--scrollable">
          <DashboardView />
        </div>
      );
    }

    // Other tabs use the grid layout
    return (
      <div className="tab-content tab-content--scrollable">
        <DashboardGrid
          tabId={tab.id}
          tabName={tab.name}
          widgets={tab.layout ?? []}
          onLayoutChange={(widgets) => handleLayoutChange(tab.id, widgets)}
        />
      </div>
    );
  };

  return (
    <div className="dashboard-tabs">
      {/* Tab Bar */}
      <div className="tab-bar">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={`tab-bar__tab${activeTabId === tab.id ? ' tab-bar__tab--active' : ''}`}
            onClick={() => setActiveTabId(tab.id)}
            onContextMenu={(e) => {
              if (!tab.is_default) {
                e.preventDefault();
                setContextMenu({ tabId: tab.id, x: e.clientX, y: e.clientY });
              }
            }}
          >
            {tab.icon && <span className="tab-bar__tab-icon">{tab.icon}</span>}
            <span className="tab-bar__tab-name">{tab.name}</span>
            {!tab.is_default && (
              <div className="tab-bar__tab-actions">
                <button
                  className="tab-bar__tab-action"
                  onClick={(e) => {
                    e.stopPropagation();
                    setEditingTab(tab);
                  }}
                  title="Edit tab"
                >
                  ✎
                </button>
                <button
                  className="tab-bar__tab-action tab-bar__tab-action--delete"
                  onClick={(e) => {
                    e.stopPropagation();
                    setDeletingTab(tab);
                  }}
                  title="Delete tab"
                >
                  ✕
                </button>
              </div>
            )}
          </button>
        ))}

        <button
          className="tab-bar__add"
          onClick={() => setShowAddModal(true)}
          title="Add new tab"
        >
          +
        </button>
      </div>

      {/* Context Menu */}
      {contextMenu && (
        <div
          ref={contextMenuRef}
          style={{
            position: 'fixed',
            top: contextMenu.y,
            left: contextMenu.x,
            background: 'var(--bg-surface)',
            border: '1px solid var(--border)',
            borderRadius: '6px',
            padding: '4px 0',
            zIndex: 999,
            minWidth: '120px',
            boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
          }}
        >
          {[contextMenu].map(({ tabId }) => {
            const tab = tabs.find((t) => t.id === tabId);
            if (!tab) return null;
            return (
              <div key={tabId}>
                <button
                  style={{
                    display: 'block',
                    width: '100%',
                    padding: '6px 12px',
                    background: 'none',
                    border: 'none',
                    color: 'var(--text)',
                    cursor: 'pointer',
                    textAlign: 'left',
                    fontSize: '12px',
                  }}
                  onClick={() => {
                    setEditingTab(tab);
                    setContextMenu(null);
                  }}
                >
                  ✎ Edit
                </button>
                <button
                  style={{
                    display: 'block',
                    width: '100%',
                    padding: '6px 12px',
                    background: 'none',
                    border: 'none',
                    color: '#ef4444',
                    cursor: 'pointer',
                    textAlign: 'left',
                    fontSize: '12px',
                  }}
                  onClick={() => {
                    setDeletingTab(tab);
                    setContextMenu(null);
                  }}
                >
                  ✕ Delete
                </button>
              </div>
            );
          })}
        </div>
      )}

      {/* Active Tab Content */}
      {activeTab && renderTabContent(activeTab)}

      {/* Modals */}
      {showAddModal && (
        <TabModal
          title="New Tab"
          onConfirm={handleAddTab}
          onCancel={() => setShowAddModal(false)}
        />
      )}
      {editingTab && (
        <TabModal
          title="Edit Tab"
          initial={{ name: editingTab.name, icon: editingTab.icon ?? '📌' }}
          onConfirm={handleEditTab}
          onCancel={() => setEditingTab(null)}
        />
      )}
      {deletingTab && (
        <ConfirmDelete
          tabName={deletingTab.name}
          onConfirm={handleDeleteTab}
          onCancel={() => setDeletingTab(null)}
        />
      )}
    </div>
  );
}
