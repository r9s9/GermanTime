/** Schedules PCM16 chunks back-to-back for gapless playback. flush() gives
 * an instant (sub-frame) stop for barge-in — no custom worklet needed since
 * Web Audio's own precise start-time scheduling is enough for this.
 */
export class ChunkedPlayer {
  private ctx: AudioContext;
  private nextStartTime = 0;
  private sources: AudioBufferSourceNode[] = [];
  onPlaybackChange?: (playing: boolean) => void;

  constructor(ctx: AudioContext) {
    this.ctx = ctx;
  }

  enqueuePcm16(pcm16: ArrayBuffer, sampleRate: number) {
    const int16 = new Int16Array(pcm16);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768;

    const buffer = this.ctx.createBuffer(1, float32.length, sampleRate);
    buffer.copyToChannel(float32, 0);

    const source = this.ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(this.ctx.destination);

    const now = this.ctx.currentTime;
    const startAt = Math.max(now, this.nextStartTime);
    source.start(startAt);
    this.nextStartTime = startAt + buffer.duration;
    this.sources.push(source);
    this.onPlaybackChange?.(true);

    source.onended = () => {
      this.sources = this.sources.filter((s) => s !== source);
      if (this.sources.length === 0) this.onPlaybackChange?.(false);
    };
  }

  flush() {
    for (const s of this.sources) {
      try {
        s.onended = null;
        s.stop();
      } catch {
        /* already stopped */
      }
    }
    this.sources = [];
    this.nextStartTime = this.ctx.currentTime;
    this.onPlaybackChange?.(false);
  }

  get isPlaying() {
    return this.sources.length > 0;
  }
}
