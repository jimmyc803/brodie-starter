import "server-only";

import { AccessToken } from "livekit-server-sdk";

// Call passes for the client page. The room name carries the client id (client-<uuid>-<random>): the Brodie worker reads it
// (facetime/worker.py client_for_room) to load that client's assigned day and save the session to them.
// The caller joins as the bridge identity the worker binds to (facetime BRIDGE_IDENTITY). Keys never leave the server.
export const CALLER_IDENTITY = "chert-bridge";
export const CALLER_TRACK = "facetime-remote-video";
export const COACH_IDENTITY = "brodie-agent";

export function livekitConfigured(): boolean {
  return Boolean(process.env.LIVEKIT_URL && process.env.LIVEKIT_API_KEY && process.env.LIVEKIT_API_SECRET);
}

export function clientRoomName(clientId: string): string {
  return `client-${clientId}-${crypto.randomUUID().slice(0, 8)}`;
}

export async function mintCallPass(clientId: string): Promise<{ url: string; token: string; room: string }> {
  const room = clientRoomName(clientId);
  const at = new AccessToken(process.env.LIVEKIT_API_KEY, process.env.LIVEKIT_API_SECRET, {
    identity: CALLER_IDENTITY,
    name: "Client",
    ttl: 60 * 60, // one workout
  });
  at.addGrant({ roomJoin: true, room, canPublish: true, canSubscribe: true, canPublishData: true });
  return { url: process.env.LIVEKIT_URL as string, token: await at.toJwt(), room };
}
