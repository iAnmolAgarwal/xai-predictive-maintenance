import type { SocketLike } from '../client';

/**
 * A hand-driven stand-in for `WebSocket`. Tests open it, push frames through it
 * and assert on what the client sent back; nothing here simulates the protocol.
 */
export class FakeSocket implements SocketLike {
  readonly url: string;
  readonly sent: string[] = [];
  closed = false;
  onopen: ((event: unknown) => void) | null = null;
  onclose: ((event: unknown) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;

  constructor(url: string) {
    this.url = url;
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.closed = true;
    this.onclose?.({});
  }

  /** Simulate the server accepting the connection. */
  open(): void {
    this.onopen?.({});
  }

  /** Deliver one frame, exactly as the server would. */
  receive(frame: unknown): void {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }

  /** Deliver a raw payload, for the malformed-frame paths. */
  receiveRaw(data: unknown): void {
    this.onmessage?.({ data });
  }

  /** Simulate the server or the network dropping the socket. */
  drop(): void {
    this.onclose?.({});
  }
}

export function socketFactory(created: FakeSocket[]) {
  return (url: string): SocketLike => {
    const socket = new FakeSocket(url);
    created.push(socket);
    return socket;
  };
}
