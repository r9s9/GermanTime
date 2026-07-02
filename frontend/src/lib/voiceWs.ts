export type VoiceEvent =
  | { t: "ready"; conv_id: string }
  | { t: "vad"; state: "speech_start" | "speech_end" }
  | { t: "stt_partial"; text: string }
  | { t: "stt_final"; text: string; turn_id: string }
  | { t: "llm_delta"; text: string }
  | { t: "tts_begin"; turn_id: string; sr: number; chunk: number; text: string }
  | { t: "tts_end"; turn_id: string }
  | { t: "barge_in" }
  | { t: "turn_stats"; turn_id: string; latency: Record<string, number> }
  | { t: "pron_result"; turn_id: string; words: unknown[] }
  | { t: "error"; message: string };

export class VoiceSocket {
  private ws: WebSocket;

  constructor(convId: string, onEvent: (e: VoiceEvent) => void, onAudio: (data: ArrayBuffer) => void) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    this.ws = new WebSocket(`${proto}://${location.host}/ws/voice/${convId}`);
    this.ws.binaryType = "arraybuffer";
    this.ws.onmessage = (ev) => {
      if (typeof ev.data === "string") {
        onEvent(JSON.parse(ev.data) as VoiceEvent);
      } else {
        onAudio(ev.data as ArrayBuffer);
      }
    };
  }

  onOpen(cb: () => void) {
    this.ws.addEventListener("open", cb);
  }

  onClose(cb: (ev: CloseEvent) => void) {
    this.ws.addEventListener("close", cb);
  }

  sendPcm(frame: ArrayBuffer) {
    if (this.ws.readyState === WebSocket.OPEN) this.ws.send(frame);
  }

  sendControl(msg: object) {
    if (this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  close() {
    this.ws.close();
  }
}
