/**
 * TRION Bridge Message Types
 * Protocol for Browser <-> Deno communication
 */

// Message directions
export type MessageDirection = 'request' | 'response' | 'event';

// Base message structure
export interface BridgeMessage {
  id: string;
  direction: MessageDirection;
  type: string;
  payload: unknown;
  timestamp: number;
}

// Request types (Browser -> Deno)
export type RequestType =
  | 'plugin:list'
  | 'plugin:enable'
  | 'plugin:disable'
  | 'plugin:get'
  | 'plugin:settings:get'
  | 'plugin:settings:set'
  | 'vault:read'
  | 'vault:write'
  | 'vault:list'
  | 'panel:create'
  | 'panel:update'
  | 'panel:close'
  | 'backend:event';

// Event types (Deno -> Browser)
export type EventType =
  | 'plugin:enabled'
  | 'plugin:disabled'
  | 'plugin:error'
  | 'panel:content'
  | 'notification'
  | 'sse:forward'
  | 'plugin:list';

// Request payloads
export interface PluginListRequest {
  type: 'plugin:list';
}

export interface PluginEnableRequest {
  type: 'plugin:enable';
  payload: { id: string };
}

export interface PluginDisableRequest {
  type: 'plugin:disable';
  payload: { id: string };
}

export interface VaultReadRequest {
  type: 'vault:read';
  payload: { path: string; pluginId: string };
}

export interface VaultWriteRequest {
  type: 'vault:write';
  payload: { path: string; data: unknown; pluginId: string };
}

export interface PanelCreateRequest {
  type: 'panel:create';
  payload: {
    pluginId: string;
    tabId: string;
    title: string;
    contentType: 'markdown' | 'text' | 'code';
    options?: {
      autoOpen?: boolean;
      content?: string;
    };
  };
}

export interface PanelUpdateRequest {
  type: 'panel:update';
  payload: {
    tabId: string;
    content: string;
    append?: boolean;
  };
}

export interface BackendEventRequest {
  type: 'backend:event';
  payload: {
    eventType: string;
    data: unknown;
  };
}

// Response structure
export interface BridgeResponse<T = unknown> {
  id: string;
  direction: 'response';
  type: string;
  success: boolean;
  data?: T;
  error?: string;
  timestamp: number;
}

// Event structure
export interface BridgeEvent<T = unknown> {
  id: string;
  direction: 'event';
  type: EventType;
  payload: T;
  timestamp: number;
}

// Helper to create messages
export function createRequest(type: RequestType, payload?: unknown): BridgeMessage {
  return {
    id: crypto.randomUUID(),
    direction: 'request',
    type,
    payload: payload ?? {},
    timestamp: Date.now()
  };
}

export function createResponse(requestId: string, type: string, success: boolean, data?: unknown, error?: string): BridgeResponse {
  return {
    id: requestId,
    direction: 'response',
    type,
    success,
    data,
    error,
    timestamp: Date.now()
  };
}

export function createEvent(type: EventType, payload: unknown): BridgeEvent {
  return {
    id: crypto.randomUUID(),
    direction: 'event',
    type,
    payload,
    timestamp: Date.now()
  };
}

console.log('[TRION] Message types loaded');
